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

from os import environ
from re import compile as re_compile
from re import search

from starlette import applications
from starlette.routing import Match

from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.starlette.version import __version__  # noqa


class _ExcludeList:
    """Class to exclude certain paths (given as a list of regexes) from tracing requests"""

    def __init__(self, excluded_urls):
        self._excluded_urls = excluded_urls
        if self._excluded_urls:
            self._regex = re_compile("|".join(excluded_urls))

    def url_disabled(self, url: str) -> bool:
        return bool(self._excluded_urls and search(self._regex, url))


def _get_excluded_urls():
    excluded_urls = environ.get("OTEL_PYTHON_STARLETTE_EXCLUDED_URLS", [])

    if excluded_urls:
        excluded_urls = [
            excluded_url.strip() for excluded_url in excluded_urls.split(",")
        ]

    return _ExcludeList(excluded_urls)


_excluded_urls = _get_excluded_urls()


class StarletteInstrumentor(BaseInstrumentor):
    """An instrumentor for starlette

    See `BaseInstrumentor`
    """

    _original_starlette = None

    @staticmethod
    def instrument_app(app: applications.Starlette):
        """Instrument an uninstrumented Starlette application.
        """
        if not getattr(app, "is_instrumented_by_opentelemetry", False):
            app.add_middleware(
                OpenTelemetryMiddleware,
                excluded_urls=_excluded_urls,
                span_details_callback=_get_route_details,
            )
            app.is_instrumented_by_opentelemetry = True

    def _instrument(self, **kwargs):
        self._original_starlette = applications.Starlette
        applications.Starlette = _InstrumentedStarlette

    def _uninstrument(self, **kwargs):
        applications.Starlette = self._original_starlette


class _InstrumentedStarlette(applications.Starlette):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_middleware(
            OpenTelemetryMiddleware,
            excluded_urls=_excluded_urls,
            span_details_callback=_get_route_details,
        )


def _get_route_details(scope):
    """Callback to retrieve the starlette route being served.

    TODO: there is currently no way to retrieve http.route from
    a starlette application from scope.

    See: https://github.com/encode/starlette/pull/804
    """
    app = scope["app"]
    route = None
    for starlette_route in app.routes:
        match, _ = starlette_route.matches(scope)
        if match == Match.FULL:
            route = starlette_route.path
            break
        if match == Match.PARTIAL:
            route = starlette_route.path
    # method only exists for http, if websocket
    # leave it blank.
    span_name = route or scope.get("method", "")
    attributes = {}
    if route:
        attributes["http.route"] = route
    return span_name, attributes
