"""Optional OpenTelemetry tracing of agent runs.

No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set (e.g. a local Arize
Phoenix instance at http://localhost:6006/v1/traces).
"""

import os


def setup_telemetry() -> None:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return

    from openinference.instrumentation.smolagents import SmolagentsInstrumentor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    SmolagentsInstrumentor().instrument(tracer_provider=provider)
