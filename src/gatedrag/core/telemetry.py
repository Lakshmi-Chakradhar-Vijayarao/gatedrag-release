"""OpenTelemetry tracing. Spans are no-ops unless GATEDRAG_OTEL is set:
  GATEDRAG_OTEL=console   print spans to stdout
  GATEDRAG_OTEL=otlp      export over OTLP (needs opentelemetry-exporter-otlp; endpoint via OTEL_* env vars)
"""

from __future__ import annotations

import os

from opentelemetry import trace

_configured = False


def configure_tracing(service_name: str = "gatedrag") -> None:
    global _configured
    mode = os.environ.get("GATEDRAG_OTEL", "").lower()
    if _configured or not mode:
        return
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if mode == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # optional

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True


def tracer():
    return trace.get_tracer("gatedrag")
