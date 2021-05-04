# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
from unittest.mock import patch

import fastapi
from fastapi.testclient import TestClient

import opentelemetry.instrumentation.fastapi as otel_fastapi
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry.test.test_base import TestBase
from opentelemetry.util.http import get_excluded_urls, ExcludeList


class TestFastAPIManualInstrumentation(TestBase):
    def _create_app(self):
        app = self._create_fastapi_app()
        self._instrumentor.instrument_app(app)
        return app

    def _create_app_explicit_excluded_urls(self):
        app = self._create_fastapi_app()
        to_exclude = "/user/123,/foobar"
        excluded_urls = [
            excluded_url.strip() for excluded_url in to_exclude.split(",")
        ]
        self._instrumentor.instrument_app(
            app, excluded_urls=ExcludeList(excluded_urls)
        )
        return app

    def setUp(self):
        super().setUp()
        self.env_patch = patch.dict(
            "os.environ",
            {"OTEL_PYTHON_FASTAPI_EXCLUDED_URLS": "/exclude/123,healthzz"},
        )
        self.env_patch.start()
        self.exclude_patch = patch(
            "opentelemetry.instrumentation.fastapi._excluded_urls_from_env",
            get_excluded_urls("FASTAPI"),
        )
        self.exclude_patch.start()
        self._instrumentor = otel_fastapi.FastAPIInstrumentor()
        self._app = self._create_app()
        self._client = TestClient(self._app)

    def tearDown(self):
        super().tearDown()
        self.env_patch.stop()
        self.exclude_patch.stop()

    def test_basic_fastapi_call(self):
        self._client.get("/foobar")
        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 3)
        for span in spans:
            self.assertIn("/foobar", span.name)

    def test_fastapi_route_attribute_added(self):
        """Ensure that fastapi routes are used as the span name."""
        self._client.get("/user/123")
        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 3)
        for span in spans:
            self.assertIn("/user/{username}", span.name)
        self.assertEqual(
            spans[-1].attributes[SpanAttributes.HTTP_ROUTE], "/user/{username}"
        )
        # ensure that at least one attribute that is populated by
        # the asgi instrumentation is successfully feeding though.
        self.assertEqual(
            spans[-1].attributes[SpanAttributes.HTTP_FLAVOR], "1.1"
        )

    def test_fastapi_excluded_urls(self):
        """Ensure that given fastapi routes are excluded."""
        self._client.get("/exclude/123")
        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 0)
        self._client.get("/healthzz")
        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 0)

    def test_fastapi_excluded_urls_not_env(self):
        """Ensure that given fastapi routes are excluded when passed explicitly (not in the environment)"""
        app = self._create_app_explicit_excluded_urls()
        client = TestClient(app)
        client.get("/user/123")
        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 0)
        client.get("/foobar")
        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 0)

    @staticmethod
    def _create_fastapi_app():
        app = fastapi.FastAPI()

        @app.get("/foobar")
        async def _():
            return {"message": "hello world"}

        @app.get("/user/{username}")
        async def _(username: str):
            return {"message": username}

        @app.get("/exclude/{param}")
        async def _(param: str):
            return {"message": param}

        @app.get("/healthzz")
        async def _():
            return {"message": "ok"}

        return app


class TestAutoInstrumentation(TestFastAPIManualInstrumentation):
    """Test the auto-instrumented variant

    Extending the manual instrumentation as most test cases apply
    to both.
    """

    def _create_app(self):
        # instrumentation is handled by the instrument call
        resource = Resource.create({"key1": "value1", "key2": "value2"})
        result = self.create_tracer_provider(resource=resource)
        tracer_provider, exporter = result
        self.memory_exporter = exporter

        self._instrumentor.instrument(tracer_provider=tracer_provider)
        return self._create_fastapi_app()

    def _create_app_explicit_excluded_urls(self):
        resource = Resource.create({"key1": "value1", "key2": "value2"})
        tracer_provider, exporter = self.create_tracer_provider(
            resource=resource
        )
        self.memory_exporter = exporter

        to_exclude = "/user/123,/foobar"
        excluded_urls = [
            excluded_url.strip() for excluded_url in to_exclude.split(",")
        ]
        self._instrumentor.uninstrument()  # Disable previous instrumentation (setUp)
        self._instrumentor.instrument(
            tracer_provider=tracer_provider,
            excluded_urls=ExcludeList(excluded_urls),
        )
        return self._create_fastapi_app()

    def test_request(self):
        self._client.get("/foobar")
        spans = self.memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 3)
        for span in spans:
            self.assertEqual(span.resource.attributes["key1"], "value1")
            self.assertEqual(span.resource.attributes["key2"], "value2")

    def tearDown(self):
        self._instrumentor.uninstrument()
        super().tearDown()


class TestAutoInstrumentationLogic(unittest.TestCase):
    def test_instrumentation(self):
        """Verify that instrumentation methods are instrumenting and
        removing as expected.
        """
        instrumentor = otel_fastapi.FastAPIInstrumentor()
        original = fastapi.FastAPI
        instrumentor.instrument()
        try:
            instrumented = fastapi.FastAPI
            self.assertIsNot(original, instrumented)
        finally:
            instrumentor.uninstrument()

        should_be_original = fastapi.FastAPI
        self.assertIs(original, should_be_original)
