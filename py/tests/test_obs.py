"""Telemetry must cost nothing when it is off, and be honest when it is on.

OBS-0001 makes one promise that is load-bearing everywhere else: with no
`AXIOM_TOKEN`, the OpenTelemetry SDK is never imported, no thread starts and no
socket opens. `make check` has to pass on a clean clone with no network and no
key, and CI never sets a token — so these tests are the reason that promise is
true rather than merely intended.

The tests that exercise the *on* path inject in-memory exporters, so the whole
module runs offline.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from jeve import obs
from jeve.config import Settings
from jeve.obs import meters, wiring


@pytest.fixture(autouse=True)
def _telemetry_is_off_between_tests() -> Iterator[None]:
    """Because `start()` is idempotent, a leaked stack would hide a failure."""

    wiring.shutdown()
    wiring._GAUGES.clear()
    yield
    wiring.shutdown()
    wiring._GAUGES.clear()


def _on(**exporters: Any) -> Settings:
    return Settings(axiom_token="test-token", **exporters)


# --- the off path -----------------------------------------------------------


def test_nothing_starts_without_a_token() -> None:
    before = set(threading.enumerate())

    obs.start("jeve-test", settings=Settings())
    assert obs.live() is None

    with obs.span("sim.tick", {"jeve.sim_time": 900}) as tick:
        tick.set({"jeve.events": 3})
    obs.logger("jeve.test").info("a line")
    meters.TICKS.add(1, {"outcome": "ok"})
    obs.shutdown()

    assert set(threading.enumerate()) == before


def test_no_socket_is_opened_when_telemetry_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The strongest form of the promise: a socket here would raise.

    Deliberately touches no database — Postgres is a socket too, and the point
    is to catch *telemetry* opening one.
    """

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("telemetry opened a socket with no token set")

    monkeypatch.setattr(socket, "socket", explode)

    obs.start("jeve-test", settings=Settings())
    with obs.span("sim.tick"):
        obs.logger("jeve.test").warn("still nothing")
    meters.LLM_COST.add(0.01, {"model": "m"})
    obs.shutdown()


def test_the_sdk_is_not_even_imported_without_a_token() -> None:
    """In a subprocess: an earlier test that started telemetry would have left
    the SDK in this process's `sys.modules` and made the assertion vacuous."""

    probe = (
        "import sys, jeve.obs, jeve.api.app, jeve.sim.daemon;"
        "heavy = ('opentelemetry.sdk', 'opentelemetry.exporter',"
        " 'requests', 'google.protobuf');"
        "loaded = sorted(m for m in sys.modules"
        " if m.startswith(heavy));"
        "assert not loaded, loaded;"
        "print('clean')"
    )
    env = {**os.environ, "AXIOM_TOKEN": ""}
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "clean" in done.stdout


def test_start_is_idempotent_and_never_raises() -> None:
    """A daemon restarted in-process, and a garbage sample ratio.

    `tests/test_daemon.py` calls `daemon.main()` dozens of times in one
    process; a second `start()` must be a no-op rather than a second exporter.
    """

    obs.shutdown()  # before any start
    obs.start("jeve-test", settings=_on())
    first = obs.live()
    assert first is not None
    obs.start("jeve-test", settings=_on())
    assert obs.live() is first
    obs.shutdown()
    obs.shutdown()  # twice


def test_a_bad_configuration_turns_telemetry_off_rather_than_down(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The rule the spend checkpoint learned the hard way: never take the
    process with you."""

    obs.start("jeve-test", settings=_on(otel_sample_ratio=2.0))
    assert obs.live() is None
    assert "telemetry disabled" in capsys.readouterr().err


# --- the on path, offline ---------------------------------------------------


def _started() -> Any:
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    spans = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    obs.start(
        "jeve-test",
        settings=_on(),
        span_exporter=spans,
        metric_reader=reader,
    )
    return spans, reader


def test_spans_are_recorded_when_telemetry_is_on() -> None:
    spans, _ = _started()

    attrs: obs.Attrs = {"jeve.sim_time": 5400, "jeve.sim_label": "d1 Mon 01:30"}
    with obs.span("sim.tick", attrs):
        pass
    obs.shutdown()

    recorded = spans.get_finished_spans()
    assert [s.name for s in recorded] == ["sim.tick"]
    attributes = recorded[0].attributes or {}
    assert attributes["jeve.sim_time"] == 5400
    assert attributes["jeve.sim_label"] == "d1 Mon 01:30"


def test_a_span_is_stamped_with_wall_time_never_sim_time() -> None:
    """CORE-0003's guard, stated as an assertion.

    Sim time is an integer count of sim-seconds from a seeded epoch — order
    1e6. A wall-clock nanosecond timestamp is order 1e18. If sim time ever
    leaked into a timestamp field this is what would catch it.
    """

    spans, _ = _started()
    with obs.span("sim.tick", {"jeve.sim_time": 900}):
        pass
    obs.shutdown()

    span = spans.get_finished_spans()[0]
    assert span.start_time is not None and span.start_time > 1_700_000_000_000_000_000


def test_a_failed_block_is_an_error_span() -> None:
    from opentelemetry.trace import StatusCode

    spans, _ = _started()
    with pytest.raises(ValueError), obs.span("sim.tick"):
        raise ValueError("the model said no")
    obs.shutdown()

    span = spans.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert (span.attributes or {})["error.type"] == "ValueError"


def test_the_metric_inventory_is_stable() -> None:
    """A rename is a broken dashboard. Make it a broken test instead."""

    _, reader = _started()
    for instrument in meters.ALL:
        if isinstance(instrument, meters.Histogram):
            instrument.record(1.0)
        elif isinstance(instrument, meters.Counter | meters.UpDown):
            instrument.add(1)

    data = reader.get_metrics_data()
    seen = {
        (metric.name, metric.unit)
        for resource in (data.resource_metrics if data else ())
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    obs.shutdown()

    assert seen == {(i.name, i.unit) for i in meters.ALL}


def test_log_lines_keep_their_stream_and_their_bytes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The runbook guarantee: stdout gets the message and nothing else.

    Structured fields exist for Axiom; a `fly logs` reader must see exactly the
    sentence they saw before this change.
    """

    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

    records = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    obs.start("jeve-test", settings=_on(), log_exporter=records)

    log = obs.logger("jeve.sim")
    log.info("the model is back after 3 failed attempt(s)", {"jeve.failures": 3})
    log.warn("waiting on the upstream budget: retrying in 900s", {"jeve.delay_s": 900})
    obs.shutdown()

    captured = capsys.readouterr()
    assert captured.out == "the model is back after 3 failed attempt(s)\n"
    assert captured.err == "waiting on the upstream budget: retrying in 900s\n"
    # The fields went to Axiom, not to the terminal.
    assert "jeve.failures" not in captured.out

    emitted = records.get_finished_logs()
    bodies = [r.log_record.body for r in emitted]
    assert bodies == [
        "the model is back after 3 failed attempt(s)",
        "waiting on the upstream budget: retrying in 900s",
    ]
    first = emitted[0].log_record.attributes or {}
    assert first["jeve.scope"] == "jeve.sim"
    assert first["jeve.failures"] == 3


def test_a_dead_exporter_never_takes_the_process_down() -> None:
    """Axiom being unreachable is weather, not a halt."""

    from opentelemetry.sdk.trace.export import SpanExporter

    class Broken(SpanExporter):
        def export(self, spans: Any) -> Any:
            raise RuntimeError("axiom is unreachable")

        def shutdown(self) -> None:
            raise RuntimeError("still unreachable")

    obs.start("jeve-test", settings=_on(), span_exporter=Broken())
    with obs.span("sim.tick"):
        pass
    obs.shutdown()  # must return, not raise


def test_a_gauge_reads_its_value_at_collection_time() -> None:
    """Gauges publish something that lives elsewhere — a SQL row, a cache."""

    age = [12.0]
    obs.register_gauge("jeve.test.age", "s", "seconds", lambda: age[0])
    _, reader = _started()

    age[0] = 41.0
    data = reader.get_metrics_data()
    points = [
        point.value
        for resource in (data.resource_metrics if data else ())
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "jeve.test.age"
        for point in metric.data.data_points
    ]
    obs.shutdown()
    assert points == [41.0]


def test_a_gauge_that_raises_leaves_a_gap_not_a_crash() -> None:
    """A dead database must cost its own series, not the whole collection."""

    def broken() -> float:
        raise RuntimeError("the database is gone")

    obs.register_gauge("jeve.test.broken", "s", "seconds", broken)
    obs.register_gauge("jeve.test.fine", "s", "seconds", lambda: 7.0)
    _, reader = _started()

    data = reader.get_metrics_data()
    reported = {
        metric.name: [point.value for point in metric.data.data_points]
        for resource in (data.resource_metrics if data else ())
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    obs.shutdown()

    assert reported.get("jeve.test.fine") == [7.0]
    assert reported.get("jeve.test.broken", []) == []
