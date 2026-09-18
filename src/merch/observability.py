from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from merch.config import Settings

_configured = False


def configure_observability(settings: Settings, app: Any | None = None) -> None:
    global _configured
    if settings.otel_exporter_endpoint and not _configured:
        provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.service_name}))
        exporter = OTLPSpanExporter(
            endpoint=f"{settings.otel_exporter_endpoint.rstrip('/')}/v1/traces"
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        _configured = True
    if app is not None and settings.otel_exporter_endpoint:
        FastAPIInstrumentor.instrument_app(app)
