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

"""
The opentelemetry.util.http.asgi package provides an ASGI middleware that can
be used on any ASGI framework (such as Django-channels / Quart) to track
requests timing through OpenTelemetry.
"""

import typing
import urllib
from functools import wraps
from typing import Tuple

from asgiref.compatibility import guarantee_single_callable

from opentelemetry import context, propagators, trace
from opentelemetry.instrumentation.utils import http_status_to_status_code
from opentelemetry.trace.propagation.textmap import DictGetter
from opentelemetry.trace.status import Status, StatusCode
from opentelemetry.util.http.asgi.version import __version__  # noqa


class CarrierGetter(DictGetter):
    def get(
        self, carrier: dict, key: str
    ) -> typing.Optional[typing.List[str]]:
        """Getter implementation to retrieve a HTTP header value from the ASGI
        scope.

        Args:
            carrier: ASGI scope object
            key: header name in scope
        Returns:
            A list with a single string with the header value if it exists,
                else None.
        """
        headers = carrier.get("headers")
        decoded = [
            _value.decode("utf8")
            for (_key, _value) in headers
            if _key.decode("utf8") == key
        ]
        if not decoded:
            return None
        return decoded


carrier_getter = CarrierGetter()


def collect_request_attributes(scope):
    """Collects HTTP request attributes from the ASGI scope and returns a
    dictionary to be used as span creation attributes."""
    server_host, port, http_url = get_host_port_url_tuple(scope)
    query_string = scope.get("query_string")
    if query_string and http_url:
        if isinstance(query_string, bytes):
            query_string = query_string.decode("utf8")
        http_url = http_url + ("?" + urllib.parse.unquote(query_string))

    result = {
        "http.scheme": scope.get("scheme"),
        "http.host": server_host,
        "net.host.port": port,
        "http.flavor": scope.get("http_version"),
        "http.target": scope.get("path"),
        "http.url": http_url,
    }
    http_method = scope.get("method")
    if http_method:
        result["http.method"] = http_method

    http_host_value_list = carrier_getter.get(scope, "host")
    if http_host_value_list:
        result["http.server_name"] = ",".join(http_host_value_list)
    http_user_agent = carrier_getter.get(scope, "user-agent")
    if http_user_agent:
        result["http.user_agent"] = http_user_agent[0]

    if "client" in scope and scope["client"] is not None:
        result["net.peer.ip"] = scope.get("client")[0]
        result["net.peer.port"] = scope.get("client")[1]

    # remove None values
    result = {k: v for k, v in result.items() if v is not None}

    return result


def get_host_port_url_tuple(scope):
    """Returns (host, port, full_url) tuple.
    """
    server = scope.get("server") or ["0.0.0.0", 80]
    port = server[1]
    server_host = server[0] + (":" + str(port) if port != 80 else "")
    full_path = scope.get("root_path", "") + scope.get("path", "")
    http_url = scope.get("scheme", "http") + "://" + server_host + full_path
    return server_host, port, http_url


def set_status_code(span, status_code):
    """Adds HTTP response attributes to span using the status_code argument."""
    if not span.is_recording():
        return
    try:
        status_code = int(status_code)
    except ValueError:
        span.set_status(
            Status(
                StatusCode.ERROR,
                "Non-integer HTTP status: " + repr(status_code),
            )
        )
    else:
        span.set_attribute("http.status_code", status_code)
        span.set_status(Status(http_status_to_status_code(status_code)))


def get_default_span_details(scope: dict) -> Tuple[str, dict]:
    """Default implementation for span_details_callback

    Args:
        scope: the asgi scope dictionary

    Returns:
        a tuple of the span, and any attributes to attach to the
        span.
    """
    method_or_path = scope.get("method") or scope.get("path")

    return method_or_path, {}


class OpenTelemetryMiddleware:
    """The ASGI application middleware.

    This class is an ASGI middleware that starts and annotates spans for any
    requests it is invoked with.

    Args:
        app: The ASGI application callable to forward requests to.
        span_details_callback: Callback which should return a string
            and a tuple, representing the desired span name and a
            dictionary with any additional span attributes to set.
            Optional: Defaults to get_default_span_details.
    """

    def __init__(self, app, excluded_urls=None, span_details_callback=None):
        self.app = guarantee_single_callable(app)
        self.tracer = trace.get_tracer(__name__, __version__)
        self.span_details_callback = (
            span_details_callback or get_default_span_details
        )
        self.excluded_urls = excluded_urls

    async def __call__(self, scope, receive, send):
        """The ASGI application

        Args:
            scope: A ASGI environment.
            receive: An awaitable callable yielding dictionaries
            send: An awaitable callable taking a single dictionary as argument.
        """
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        _, _, url = get_host_port_url_tuple(scope)
        if self.excluded_urls and self.excluded_urls.url_disabled(url):
            return await self.app(scope, receive, send)

        token = context.attach(propagators.extract(carrier_getter, scope))
        span_name, additional_attributes = self.span_details_callback(scope)

        try:
            with self.tracer.start_as_current_span(
                span_name + " asgi", kind=trace.SpanKind.SERVER,
            ) as span:
                if span.is_recording():
                    attributes = collect_request_attributes(scope)
                    attributes.update(additional_attributes)
                    for key, value in attributes.items():
                        span.set_attribute(key, value)

                @wraps(receive)
                async def wrapped_receive():
                    with self.tracer.start_as_current_span(
                        span_name + " asgi." + scope["type"] + ".receive"
                    ) as receive_span:
                        message = await receive()
                        if receive_span.is_recording():
                            if message["type"] == "websocket.receive":
                                set_status_code(receive_span, 200)
                            receive_span.set_attribute("type", message["type"])
                    return message

                @wraps(send)
                async def wrapped_send(message):
                    with self.tracer.start_as_current_span(
                        span_name + " asgi." + scope["type"] + ".send"
                    ) as send_span:
                        if send_span.is_recording():
                            if message["type"] == "http.response.start":
                                status_code = message["status"]
                                set_status_code(send_span, status_code)
                            elif message["type"] == "websocket.send":
                                set_status_code(send_span, 200)
                            send_span.set_attribute("type", message["type"])
                        await send(message)

                await self.app(scope, wrapped_receive, wrapped_send)
        finally:
            context.detach(token)