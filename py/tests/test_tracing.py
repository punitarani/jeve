"""LLM-0009: the three properties the tracing seam is allowed to have.

Off by default, never fatal, and a pure side effect. Nothing here opens a
socket or imports `braintrust`; the sink is the one in `conftest.py`.
"""

from __future__ import annotations

import threading

import pytest

from jeve import tracing
from jeve.config import Settings
from tests.conftest import ExplodingSink, RecordingSink

# -- off by default --------------------------------------------------------


def test_no_key_means_no_tracing_and_no_sdk() -> None:
    """A clean clone runs offline with nothing to configure."""

    assert tracing.enabled() is False
    with tracing.span("jev.decide", type="llm", input={"a": 1}) as span:
        span.log(output="anything")
        # `""` is what tells a caller there is no parent to hand across a
        # thread — `jev_policy` turns it back into None.
        assert span.export() == ""


def test_the_key_is_the_only_switch() -> None:
    """One way to say it. Unset the key and nothing traces; set it and it does.

    A separate on/off flag would be a second way to say the same thing, and
    would let the two disagree.
    """

    assert tracing.configure(settings=Settings()) is False
    tracing.reset()
    assert tracing.configure(settings=Settings(braintrust_api_key="sk-test"))
    tracing.reset()


def test_unreadable_settings_disable_tracing_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad env var is a broken deployment, not a broken tick."""

    monkeypatch.setenv("BRAINTRUST_API_KEY", "sk-test")
    monkeypatch.setenv("JEVE_RUN_CAP_USD", "not-a-number")
    assert tracing.configure() is False


# -- the shape that reaches the sink --------------------------------------


def test_fields_and_nesting_reach_the_sink(spans: RecordingSink) -> None:
    with tracing.span("decide.batch", type="task", metadata={"mode": "record"}) as top:
        top.log(metadata={"live_calls": 1})
        with tracing.span("jev.decide", type="llm", input={"state": "x"}) as call:
            call.log(output={"urgent": 0.9}, metrics={"tokens": 12})

    batch = spans.only("decide.batch")
    assert batch.type == "task"
    # `log` merges into a dict that is already there rather than replacing it.
    assert batch.fields["metadata"] == {"mode": "record", "live_calls": 1}

    inner = spans.only("jev.decide")
    assert inner.type == "llm"
    assert inner.fields["input"] == {"state": "x"}
    assert inner.fields["metrics"] == {"tokens": 12}
    assert [child.name for child in batch.children] == ["jev.decide"]


def test_an_exported_handle_parents_a_span_that_is_not_nested(
    spans: RecordingSink,
) -> None:
    """What crossing `JevPolicy._Bridge` looks like: the parent is passed.

    Contextvars do not survive `run_coroutine_threadsafe`, so the batch span
    would otherwise be invisible to the gateway and every call would land at
    the root of its own trace.
    """

    with tracing.span("decide.batch", type="task") as batch:
        handle = batch.export()
    assert handle

    with tracing.span("jev.decide", type="llm", parent=handle):
        pass

    assert [child.name for child in spans.only("decide.batch").children] == [
        "jev.decide"
    ]


def test_a_failure_in_the_body_is_recorded_and_re_raised(
    spans: RecordingSink,
) -> None:
    """A dead model is the daemon's business (SIM-0002), not the tracer's."""

    with pytest.raises(ZeroDivisionError):
        with tracing.span("jev.decide", type="llm"):
            raise ZeroDivisionError("boom")

    assert spans.only("jev.decide").error == "ZeroDivisionError: boom"


def test_flush_reaches_the_sink(spans: RecordingSink) -> None:
    tracing.flush()
    assert spans.flushes == 1


# -- never fatal -----------------------------------------------------------


def test_a_broken_sink_disables_tracing_instead_of_failing_the_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The rule `gateway._log_discrepancy` was written for, applied here.

    An unwritable ops dir once killed a decision call on Fly. Telemetry gets
    one warning and then gets out of the way.
    """

    tracing.configure(sink=ExplodingSink())
    with tracing.span("jev.decide", type="llm") as span:
        span.log(output="the call still returns this")
    assert "tracing disabled" in capsys.readouterr().err

    # Latched off: the second span is silent, and tracing is done for good.
    with tracing.span("jev.decide", type="llm"):
        pass
    assert capsys.readouterr().err == ""
    assert tracing.enabled() is False
    tracing.reset()


def test_a_sink_that_fails_only_on_log_still_lets_the_body_finish(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class HalfBroken(RecordingSink):
        def flush(self) -> None:
            raise RuntimeError("flush exploded")

    tracing.configure(sink=HalfBroken())
    tracing.flush()
    assert "tracing disabled" in capsys.readouterr().err
    assert tracing.enabled() is False
    tracing.reset()


# -- which project the spans are told to land in --------------------------


def _init_logger_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Capture `init_logger`'s kwargs. Constructing the sink opens no socket."""

    import braintrust

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(braintrust, "init_logger", lambda **kw: calls.append(kw))
    return calls


def test_an_id_is_sent_alone_so_the_sdk_looks_it_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never both. Both is the branch that skips validation.

    `braintrust._compute_logger_metadata` branches on which argument is None.
    An id alone is resolved with `get_project_id`, so a stale or foreign one
    fails at login. Sent *alongside* a name it takes a third branch that
    trusts the id verbatim, never calls the API, and leaves every row to be
    rejected server-side and dropped on a background thread where nothing we
    write can see it.
    """

    calls = _init_logger_calls(monkeypatch)
    tracing._BraintrustSink(project_id="7f1ad66e-c91d", api_key="sk-test")

    assert calls == [{"project_id": "7f1ad66e-c91d", "api_key": "sk-test"}]
    assert "project" not in calls[0]


def test_no_id_sends_the_name_alone_so_the_sdk_creates_or_resolves_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key on its own is enough to trace; spans land in `jeve`."""

    calls = _init_logger_calls(monkeypatch)
    tracing._BraintrustSink(project_id=None, api_key="sk-test")

    assert calls == [{"project": "jeve", "api_key": "sk-test"}]
    assert "project_id" not in calls[0]


# -- against the real SDK, offline ----------------------------------------


def test_the_real_sdk_produces_the_span_shape_we_meant() -> None:
    """The contract with a dependency we do not own.

    Spans here are hand-built — there is no LLM SDK to wrap, because the
    gateway posts raw httpx (LLM-0009). That makes `start_span`'s keywords, the
    `llm` type and `metrics.estimated_cost` an API we are coupled to without a
    wrapper to absorb a change. This runs the real braintrust logger against
    its own in-memory backend, so an upgrade that moves any of them fails here
    rather than in production. No socket is opened.

    The shape is the whole trace: a tick, a batch under it by ambient context,
    and a call under the batch from another thread by exported handle — the
    `JevPolicy._Bridge` hop. The root carries an input and an output, because a
    root without them is exactly the empty trace this shape replaced.
    """

    from braintrust import logger as bt
    from braintrust.test_helpers import init_test_logger, simulate_login

    simulate_login()
    init_test_logger("jeve-span-shape")
    with bt._internal_with_memory_background_logger() as memory:

        def gateway_thread(handle: str) -> None:
            # The memory backend is thread-local; production's is not.
            bt._state._override_bg_logger.logger = memory
            try:
                with tracing.span("jev.decide", type="llm", parent=handle) as call:
                    call.log(
                        output={"urgent": 0.9},
                        metrics={"tokens": 430, "estimated_cost": 1.68e-05},
                    )
            finally:
                bt._state._override_bg_logger.logger = None

        tracing.reset()
        assert tracing.configure(settings=Settings(braintrust_api_key=bt.TEST_API_KEY))
        with tracing.span(
            "sim.tick", type="task", input={"label": "d0 Mon 09:00"}
        ) as tick_span:
            with tracing.span(
                "decide cafe.purchase",
                type="task",
                input=[{"person_id": "p1", "facts": {"queue_length": 2}}],
            ) as batch:
                worker = threading.Thread(target=gateway_thread, args=(batch.export(),))
                worker.start()
                worker.join()
                batch.log(output=[{"person_id": "p1", "settled_by": "live"}])
            # Logged last, as `Engine.tick` does once the tick has committed.
            tick_span.log(output={"decisions": 1})
        rows = memory.pop()

    by_name = {row["span_attributes"]["name"]: row for row in rows}
    tick, batch, decide = (
        by_name["sim.tick"],
        by_name["decide cafe.purchase"],
        by_name["jev.decide"],
    )
    assert tick["span_attributes"]["type"] == "task"
    assert not tick["span_parents"]
    assert tick["input"] == {"label": "d0 Mon 09:00"}
    assert tick["output"] == {"decisions": 1}

    assert batch["span_parents"] == [tick["span_id"]]
    assert batch["input"] == [{"person_id": "p1", "facts": {"queue_length": 2}}]
    assert batch["output"] == [{"person_id": "p1", "settled_by": "live"}]

    assert decide["span_attributes"]["type"] == "llm"
    assert decide["span_parents"] == [batch["span_id"]]
    assert decide["output"] == {"urgent": 0.9}
    # The field Braintrust prefers over its own registry estimate — the point
    # of logging it at all, since the registry has never heard of jev.
    assert decide["metrics"]["estimated_cost"] == 1.68e-05
    assert {row["root_span_id"] for row in rows} == {tick["root_span_id"]}
