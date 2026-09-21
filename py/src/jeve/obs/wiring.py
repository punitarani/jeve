"""Build the providers, or build nothing.

Three rules, each with an incident behind it.

`start()` never raises. A telemetry misconfiguration must not crash-loop a
process: the spend checkpoint and the discrepancy log both had to be made
best-effort after a `PermissionError` took the sim down on boot, and an
exporter is no more entitled to stop the world than a log file is.

`start()` is idempotent. `tests/test_daemon.py` calls `daemon.main()` dozens of
times in one process.

`start()` does not touch the OpenTelemetry globals. `set_tracer_provider` and
its siblings are `Once()`-guarded — calling them would make start/shutdown a
one-shot per process and the no-op path untestable. We hold the providers and
hand out the tracer, meter and emitter ourselves. Trace-to-log correlation
still works: a log record reads the active span off the *context* API, which is
provider-independent.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from jeve.config import Settings, load_settings

if TYPE_CHECKING:
    from opentelemetry._logs import Logger as LogEmitter
    from opentelemetry.metrics import Meter
    from opentelemetry.trace import Tracer

# A gauge whose value lives somewhere else (a SQL row, a ledger cache) and is
# read when the metric reader collects.
GaugeCallback = Callable[[], float | None]

_LOCK = threading.Lock()
_LIVE: Live | None = None
_GENERATION = 0
_GAUGES: list[tuple[str, str, str, GaugeCallback]] = []


@dataclass(frozen=True, slots=True)
class Live:
    """The handles a started telemetry stack hands out.

    `generation` lets the instrument cache in `meters` notice a restart: a test
    that starts, shuts down and starts again must not keep the dead meter's
    instruments.
    """

    tracer: Tracer
    meter: Meter
    emitter: LogEmitter
    generation: int
    flush: tuple[Callable[[int], Any], ...]
    stop: tuple[Callable[[], Any], ...]


def live() -> Live | None:
    """The running stack, or None when telemetry is off."""

    return _LIVE


def _base_url(domain: str) -> str:
    """`api.axiom.co` -> `https://api.axiom.co`.

    A scheme is allowed through untouched so a local OTLP collector can stand
    in for Axiom during verification — see `scripts/obs_probe.py`.
    """

    return domain.rstrip("/") if "://" in domain else f"https://{domain.rstrip('/')}"


def _resource(service: str, settings: Settings) -> Any:
    from opentelemetry.sdk.resources import Resource

    machine = os.environ.get("FLY_MACHINE_ID")
    attributes: dict[str, str] = {
        "service.name": settings.otel_service or service,
        "service.version": "0.1.0",
        "service.instance.id": machine or f"{socket.gethostname()}:{os.getpid()}",
        "deployment.environment.name": (
            "production" if os.environ.get("FLY_APP_NAME") else "local"
        ),
    }
    if region := os.environ.get("FLY_REGION"):
        attributes["cloud.region"] = region
        attributes["cloud.provider"] = "fly.io"
    # Resource.create merges OTEL_RESOURCE_ATTRIBUTES, so an operator can tag a
    # run without a code change.
    return Resource.create(attributes)


def start(
    service: str,
    *,
    settings: Settings | None = None,
    span_exporter: Any | None = None,
    metric_reader: Any | None = None,
    log_exporter: Any | None = None,
) -> None:
    """Bring telemetry up, or return having done nothing.

    The SDK imports live *inside* this function, after the token check, so a
    process with no `AXIOM_TOKEN` never loads `opentelemetry.sdk`, the OTLP
    exporter, `requests` or `protobuf`. That is what makes the off state free
    rather than merely quiet.

    The three exporter arguments exist for tests, which inject in-memory sinks
    and so never open a socket.
    """

    global _LIVE, _GENERATION

    with _LOCK:
        if _LIVE is not None:
            return
        try:
            cfg = settings if settings is not None else load_settings()
            injected = span_exporter or metric_reader or log_exporter
            if not cfg.axiom_token and not injected:
                return
            _LIVE = _build(
                service,
                cfg,
                span_exporter=span_exporter,
                metric_reader=metric_reader,
                log_exporter=log_exporter,
                generation=_GENERATION + 1,
            )
            _GENERATION += 1
        except Exception as error:  # telemetry is never worth a process
            print(
                f"telemetry disabled: {type(error).__name__}: {error}",
                file=sys.stderr,
                flush=True,
            )
            _LIVE = None


def _build(
    service: str,
    cfg: Settings,
    *,
    span_exporter: Any | None,
    metric_reader: Any | None,
    log_exporter: Any | None,
    generation: int,
) -> Live:
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    # Without a root handler, stdlib logging's lastResort prints WARNING+ to
    # stderr — an unreachable Axiom would otherwise fill `fly logs` every few
    # seconds. ERROR still surfaces a bad token, which is the failure an
    # operator needs to see.
    logging.getLogger("opentelemetry").setLevel(logging.ERROR)

    resource = _resource(service, cfg)
    base = _base_url(cfg.axiom_domain)
    auth = {"Authorization": f"Bearer {cfg.axiom_token}"}
    timeout = cfg.otel_timeout_s

    tracing = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(cfg.otel_sample_ratio)),
    )
    if span_exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        span_exporter = OTLPSpanExporter(
            endpoint=f"{base}/v1/traces",
            headers={**auth, "X-Axiom-Dataset": cfg.axiom_dataset},
            timeout=timeout,
        )
    tracing.add_span_processor(BatchSpanProcessor(span_exporter))

    if metric_reader is None:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        # Metrics route to a different dataset, through a different header, and
        # the endpoint speaks protobuf only — so a single shared
        # OTEL_EXPORTER_OTLP_HEADERS could never configure both signals.
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(
                endpoint=f"{base}/v1/metrics",
                headers={**auth, "X-Axiom-Metrics-Dataset": cfg.axiom_metrics_dataset},
                timeout=timeout,
            ),
            export_interval_millis=cfg.otel_metric_interval_s * 1000,
        )
    metering = MeterProvider(resource=resource, metric_readers=[metric_reader])

    logs = LoggerProvider(resource=resource)
    if log_exporter is None:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )

        log_exporter = OTLPLogExporter(
            endpoint=f"{base}/v1/logs",
            headers={**auth, "X-Axiom-Dataset": cfg.axiom_dataset},
            timeout=timeout,
        )
    logs.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

    state = Live(
        tracer=tracing.get_tracer("jeve"),
        meter=metering.get_meter("jeve"),
        emitter=logs.get_logger("jeve"),
        generation=generation,
        flush=(tracing.force_flush, metering.force_flush, logs.force_flush),
        stop=(tracing.shutdown, metering.shutdown, logs.shutdown),
    )
    for name, unit, description, callback in _GAUGES:
        _create_gauge(state, name, unit, description, callback)
    return state


def _create_gauge(
    state: Live, name: str, unit: str, description: str, callback: GaugeCallback
) -> None:
    from opentelemetry.metrics import CallbackOptions, Observation

    def observe(_options: CallbackOptions) -> Iterable[Observation]:
        try:
            value = callback()
        except Exception:
            # A gap in the series is itself the signal, and an exception
            # raised on the exporter's collection thread helps nobody.
            return ()
        return () if value is None else (Observation(value),)

    state.meter.create_observable_gauge(
        name, callbacks=[observe], unit=unit, description=description
    )


def register_gauge(
    name: str, unit: str, description: str, callback: GaugeCallback
) -> None:
    """Publish a value that lives somewhere else, read at collection time.

    Registering before `start()` is fine — the gauge is queued and created when
    the meter exists. The callback runs on the metric reader's thread, so it
    must not block: read a cache, never a socket or a database.
    """

    with _LOCK:
        _GAUGES.append((name, unit, description, callback))
        if _LIVE is not None:
            try:
                _create_gauge(_LIVE, name, unit, description, callback)
            except Exception:
                pass


def shutdown() -> None:
    """Flush what is buffered, then stop. Bounded, and never raises.

    Called from the API's lifespan and from the daemon's `finally`, so it runs
    on every exit path including the deliberate halts. Each provider gets its
    own try/except: one wedged exporter must not strand the other two.
    """

    global _LIVE

    with _LOCK:
        state, _LIVE = _LIVE, None
    if state is None:
        return
    for flush in state.flush:
        try:
            flush(3_000)  # force_flush(timeout_millis)
        except Exception:
            pass
    for stop in state.stop:
        try:
            stop()
        except Exception:
            pass
