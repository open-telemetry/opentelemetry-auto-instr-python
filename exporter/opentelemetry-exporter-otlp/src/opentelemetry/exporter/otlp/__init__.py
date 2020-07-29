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
This library allows to export tracing data to an OTLP collector.

Usage
-----

The **OTLP Span Exporter** allows to export `OpenTelemetry`_ traces to the
`OTLP`_ collector.


.. _OTLP: https://github.com/open-telemetry/opentelemetry-collector/
.. _OpenTelemetry: https://github.com/open-telemetry/opentelemetry-python/

.. code:: python

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchExportSpanProcessor

    # Resource can be required for some backends, e.g. Jaeger
    # If resource wouldn't be set - traces wouldn't appears in Jaeger
    resource = Resource(labels=labels={
        "service.name": "service"
    })

    trace.set_tracer_provider(TracerProvider(resource=resource)))
    tracer = trace.get_tracer(__name__)

    otlp_exporter = OTLPSpanExporter(endpoint="localhost:55678")

    span_processor = BatchExportSpanProcessor(otlp_exporter)

    trace.get_tracer_provider().add_span_processor(span_processor)

    with tracer.start_as_current_span("foo"):
        print("Hello world!")

API
---
"""
