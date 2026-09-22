"""CORE-0012: the three properties the telemetry seam is allowed to have.

Off by default, never fatal, and a pure side effect. Nothing here opens a
socket: the transport is the recording one in `conftest.py`, and the tests that
break the SDK do it at the seam this module owns.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from jeve import telemetry
from jeve.config import Settings
from tests.conftest import FAKE_DSN, SENTRY_ENV, Captured, capture_telemetry

# -- off by default --------------------------------------------------------


def test_no_dsn_means_no_telemetry_and_no_sdk() -> None:
    """A clean clone runs offline with nothing to configure."""

    assert telemetry.init("sim", settings=Settings()) is False
    assert telemetry.enabled() is False
    assert telemetry.current() is None
    with telemetry.span("sim.tick", {"sim.tick_seq": 1}, root=True) as span:
        span.set({"sim.decisions": 3})
        # None is what tells `jev_policy` there is no parent to hand across.
        assert span.parent is None
    telemetry.count("jeve.probe")
    telemetry.log("info", "nothing listens")
    telemetry.capture(RuntimeError("nobody hears this"))

    # The whole runtime imports without `sentry_sdk` ever loading — the API
    # module binds at import, the daemon at `main()`, the gateway per call.
    env = {k: v for k, v in os.environ.items() if k not in SENTRY_ENV}
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, jeve.telemetry, jeve.llm.gateway, jeve.sim.daemon, "
            "jeve.api.app; loaded = sorted(m for m in sys.modules if 'sentry' in m); "
            "assert not loaded, loaded",
        ],
        env=env,
        check=True,
        timeout=60,
    )


def test_the_dsn_is_the_only_switch() -> None:
    """One way to say it. No DSN and nothing reports; a DSN and it does."""

    assert telemetry.init("sim", settings=Settings()) is False
    telemetry.reset()
    capture_telemetry("sim")
    assert telemetry.enabled() is True


def test_the_service_dsn_wins_over_the_shared_one() -> None:
    """`api` and `sim` are one Fly app with one secret set; the name picks."""

    import sentry_sdk

    api = "https://aaa@o1.ingest.sentry.io/1"
    shared = "https://bbb@o1.ingest.sentry.io/2"
    both = Settings(sentry_dsn_api=api, sentry_dsn=shared)

    assert telemetry.init("api", settings=both, transport=_discarding())
    assert sentry_sdk.get_client().dsn == api
    telemetry.reset()

    assert telemetry.init("sim", settings=both, transport=_discarding())
    assert sentry_sdk.get_client().dsn == shared
    telemetry.reset()

    # The other service's DSN is not a fallback: that would report the API's
    # 5xx into the daemon's project.
    assert telemetry.init("api", settings=Settings(sentry_dsn_sim=api)) is False


def test_a_later_init_is_a_no_op(sentry: Captured) -> None:
    """First call wins: the API module's import-time call and a fixture coexist,
    and `soak.run_world` may run the daemon twice in one process."""

    assert telemetry.init("api", settings=Settings()) is True
    assert telemetry.enabled() is True


def test_unreadable_settings_disable_telemetry_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bad env var is a broken deployment, not a broken tick."""

    monkeypatch.setenv("SENTRY_DSN", FAKE_DSN)
    monkeypatch.setenv("JEVE_RUN_CAP_USD", "not-a-number")
    assert telemetry.init("sim") is False
    assert "telemetry disabled: ValueError" in capsys.readouterr().err
    assert telemetry.enabled() is False


# -- the shape that reaches the transport ----------------------------------


def test_a_root_is_a_root_and_a_bare_span_is_nothing(sentry: Captured) -> None:
    """Nothing becomes a trace by accident.

    The stream hub polls every half second and the gateway thread runs where
    no span is active: a `db` or `http.client` span there must vanish, not
    start a trace of its own. `root=True` is the one way to begin.
    """

    with telemetry.span("db"):
        pass
    assert sentry.spans_named("db") == []

    with telemetry.span("sim.tick", {"sim.tick_seq": 7}, root=True) as tick:
        tick.set({"sim.decisions": 3})
        with telemetry.span("db", {"sentry.op": "db"}):
            pass

    (root,) = sentry.spans_named("sim.tick")
    assert root["is_segment"] is True
    assert "parent_span_id" not in root
    assert root["attributes"]["sim.tick_seq"] == 7
    assert root["attributes"]["sim.decisions"] == 3
    assert root["attributes"]["service"] == "sim"

    (child,) = sentry.spans_named("db")
    assert child["parent_span_id"] == root["span_id"]
    assert child["trace_id"] == root["trace_id"]


def test_an_explicit_parent_crosses_a_thread(sentry: Captured) -> None:
    """What crossing `JevPolicy._Bridge` looks like: the parent is passed.

    The thread is started before any span exists, so the SDK's threading
    integration cannot hand the span over implicitly and the handle is the
    only way across — as it is for the gateway's loop thread, which is born
    inside the first tick and lives for the rest of the process.
    """

    handles: queue.Queue[telemetry.Parent | None] = queue.Queue()

    def gateway_thread() -> None:
        with telemetry.span("jev.decide", parent=handles.get()):
            with telemetry.span("http.client"):
                pass

    worker = threading.Thread(target=gateway_thread)
    worker.start()
    with telemetry.span("sim.tick", root=True) as tick:
        handles.put(telemetry.current())
        assert tick.parent is not None
        worker.join(timeout=10)

    (root,) = sentry.spans_named("sim.tick")
    (decide,) = sentry.spans_named("jev.decide")
    (http,) = sentry.spans_named("http.client")
    assert decide["parent_span_id"] == root["span_id"]
    assert decide["trace_id"] == root["trace_id"]
    # And the explicit parent is the *active* span on that thread, so what the
    # SDK's httpx integration opens underneath nests without being told.
    assert http["parent_span_id"] == decide["span_id"]


def test_a_failure_in_the_body_is_recorded_and_re_raised(sentry: Captured) -> None:
    """A dead model is the daemon's business (SIM-0002), not the tracer's."""

    with pytest.raises(ZeroDivisionError):
        with telemetry.span("sim.tick", root=True):
            raise ZeroDivisionError("boom")

    (tick,) = sentry.spans_named("sim.tick")
    assert tick["status"] == "error"


def test_attributes_are_primitives_and_none_is_dropped(sentry: Captured) -> None:
    """The SDK takes `str | int | float | bool`; the daemon has paths and Nones."""

    with telemetry.span(
        "sim.tick", {"sim.error": None, "sim.cassette": Path("golden")}, root=True
    ):
        pass

    (tick,) = sentry.spans_named("sim.tick")
    assert "sim.error" not in tick["attributes"]
    assert tick["attributes"]["sim.cassette"] == "golden"


def test_metrics_logs_and_errors_reach_the_transport(sentry: Captured) -> None:
    telemetry.count("jeve.sim.status", 1, attributes={"status": "running"})
    telemetry.gauge("jeve.sim.tick.lag", 0.25, unit="second")
    telemetry.distribution("jeve.sim.tick.duration", 1.5, unit="second")
    telemetry.log("warning", "waiting on the model", attributes={"sim.failures": 2})
    telemetry.capture(ValueError("the cafe caught fire"), tags={"sim.exit_code": 4})

    (status,) = sentry.metrics_named("jeve.sim.status")
    assert (status["type"], status["value"]) == ("counter", 1.0)
    assert status["attributes"]["status"] == "running"
    assert status["attributes"]["service"] == "sim"
    (lag,) = sentry.metrics_named("jeve.sim.tick.lag")
    assert (lag["type"], lag["value"], lag["unit"]) == ("gauge", 0.25, "second")
    (duration,) = sentry.metrics_named("jeve.sim.tick.duration")
    assert (duration["type"], duration["value"]) == ("distribution", 1.5)

    (line,) = sentry.logs()
    assert (line["level"], line["body"]) == ("warn", "waiting on the model")
    assert line["attributes"]["sim.failures"] == 2

    (event,) = sentry.events()
    assert event["exception"]["values"][0]["type"] == "ValueError"
    assert event["tags"]["sim.exit_code"] == "4"
    assert event["tags"]["service"] == "sim"


def test_status_tags_every_later_error(sentry: Captured) -> None:
    """`sim.status` on a halt's issue says what the daemon was doing."""

    telemetry.status("sim.status", "waiting_on_model")
    telemetry.capture(RuntimeError("then this"))

    (event,) = sentry.events()
    assert event["tags"]["sim.status"] == "waiting_on_model"


def test_flush_and_reset_leave_the_sdk_disabled(sentry: Captured) -> None:
    import sentry_sdk

    telemetry.flush()
    assert sentry_sdk.get_client().is_active()
    telemetry.reset()
    assert not sentry_sdk.get_client().is_active()
    assert telemetry.enabled() is False


# -- never fatal -----------------------------------------------------------


def test_a_broken_sdk_disables_telemetry_instead_of_failing_the_call(
    sentry: Captured,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The rule `gateway._log_discrepancy` was written for, applied here.

    An unwritable ops dir once killed a decision call on Fly. Telemetry gets
    one warning and then gets out of the way.
    """

    import sentry_sdk

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("sentry is having a moment")

    monkeypatch.setattr(sentry_sdk.traces, "start_span", boom)
    ran = False
    with telemetry.span("sim.tick", root=True) as span:
        span.set({"sim.decisions": 1})
        ran = True
    assert ran
    assert "telemetry disabled: RuntimeError" in capsys.readouterr().err

    # Latched off: the SDK is unbound, and everything after is silent.
    assert telemetry.enabled() is False
    assert not sentry_sdk.get_client().is_active()
    telemetry.count("jeve.probe")
    with telemetry.span("sim.tick", root=True):
        pass
    assert capsys.readouterr().err == ""


def test_a_failure_only_on_flush_still_latches_off(
    sentry: Captured,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sentry_sdk

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("flush exploded")

    monkeypatch.setattr(sentry_sdk, "flush", boom)
    telemetry.flush()
    assert "telemetry disabled" in capsys.readouterr().err
    assert telemetry.enabled() is False


def _discarding() -> object:
    """A transport that keeps nothing. For tests about binding, not payloads."""

    from sentry_sdk.transport import Transport

    class Discarding(Transport):
        def capture_envelope(self, envelope: object) -> None:
            return None

    return Discarding()
