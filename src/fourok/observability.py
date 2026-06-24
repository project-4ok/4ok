from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

DEFAULT_SERVICE_NAME = "fourok"
DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"

_CONFIGURED = False
_LOGGER_PROVIDER: LoggerProvider | None = None
_COUNTERS = {}
_HISTOGRAMS = {}

SafeAttributeValue = str | bool | int | float


@dataclass(frozen=True)
class ObservabilityConfig:
    service_name: str
    endpoint: str
    exporter: str


def configure_observability(
    *,
    service_name: str = DEFAULT_SERVICE_NAME,
    endpoint: str = DEFAULT_OTLP_ENDPOINT,
) -> ObservabilityConfig:
    global _CONFIGURED, _LOGGER_PROVIDER

    if _CONFIGURED:
        return ObservabilityConfig(
            service_name=service_name,
            endpoint=endpoint,
            exporter=_exporter_name(endpoint),
        )

    resource = Resource.create({"service.name": service_name})
    trace_provider = TracerProvider(resource=resource)
    if endpoint == "console":
        trace_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
        log_exporter = ConsoleLogRecordExporter(out=sys.stderr)
        metric_exporter = ConsoleMetricExporter(out=sys.stderr)
    else:
        trace_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=_signal_endpoint(endpoint, "traces")))
        )
        log_exporter = OTLPLogExporter(endpoint=_signal_endpoint(endpoint, "logs"))
        metric_exporter = OTLPMetricExporter(endpoint=_signal_endpoint(endpoint, "metrics"))

    trace.set_tracer_provider(trace_provider)
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(metric_exporter, export_interval_millis=5000)
        ],
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)
    logging.getLogger().addHandler(LoggingHandler(logger_provider=logger_provider))
    _LOGGER_PROVIDER = logger_provider

    LoggingInstrumentor().instrument(set_logging_format=False)
    SQLAlchemyInstrumentor().instrument()
    _CONFIGURED = True
    return ObservabilityConfig(
        service_name=service_name,
        endpoint=endpoint,
        exporter=_exporter_name(endpoint),
    )


def configure_observability_from_env() -> ObservabilityConfig | None:
    if os.environ.get("FOUR_OK_OBSERVABILITY_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return None
    return configure_observability(
        service_name=os.environ.get("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME),
        endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT),
    )


def emit_observability_smoke(
    *,
    service_name: str = "fourok-local-smoke",
    endpoint: str = DEFAULT_OTLP_ENDPOINT,
) -> dict[str, object]:
    config = configure_observability(service_name=service_name, endpoint=endpoint)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("fourok.observability_smoke") as span:
        span.set_attribute("fourok.signal", "safe-smoke")
        span.set_attribute("fourok.sensitive_payload_exported", False)
        logging.getLogger(__name__).info(
            "fourok observability smoke",
            extra={"fourok_signal": "safe-smoke"},
        )

    trace.get_tracer_provider().force_flush()
    if _LOGGER_PROVIDER is not None:
        _LOGGER_PROVIDER.force_flush()

    return {
        "status": "ok",
        "service_name": config.service_name,
        "exporter": config.exporter,
        "sensitive_payload_exported": False,
    }


def record_counter(
    name: str,
    value: int | float = 1,
    attributes: dict[str, object] | None = None,
) -> None:
    counter = _COUNTERS.get(name)
    if counter is None:
        counter = metrics.get_meter(__name__).create_counter(name)
        _COUNTERS[name] = counter
    counter.add(value, attributes or {})


def record_histogram(
    name: str,
    value: int | float,
    attributes: dict[str, object] | None = None,
) -> None:
    histogram = _HISTOGRAMS.get(name)
    if histogram is None:
        histogram = metrics.get_meter(__name__).create_histogram(name)
        _HISTOGRAMS[name] = histogram
    histogram.record(value, attributes or {})


@contextmanager
def critical_span(
    name: str,
    *,
    attributes: Mapping[str, SafeAttributeValue] | None = None,
    status_attribute: str | None = None,
) -> Iterator[object]:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(name) as span:
        set_safe_span_attributes(span, attributes or {})
        try:
            yield span
        except Exception as exc:
            if status_attribute:
                span.set_attribute(status_attribute, "failed")
            span.set_attribute("fourok.error.class", type(exc).__name__)
            raise


def set_safe_span_attributes(
    span: object,
    attributes: Mapping[str, SafeAttributeValue],
) -> None:
    for key, value in attributes.items():
        span.set_attribute(key, value)


def _signal_endpoint(endpoint: str, signal: str) -> str:
    if endpoint == "console":
        return endpoint
    parsed = urlparse(endpoint)
    if parsed.path.endswith(f"/v1/{signal}"):
        return endpoint
    return endpoint.rstrip("/") + f"/v1/{signal}"


def _exporter_name(endpoint: str) -> str:
    if endpoint == "console":
        return "console"
    return "otlp-http"
