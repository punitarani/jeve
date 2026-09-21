"""LLM-0008: the three properties the tracing seam is allowed to have.

Off by default, never fatal, and a pure side effect. Nothing here opens a
socket or imports `braintrust`; the sink is the one in `conftest.py`.
"""

from __future__ import annotations

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


def test_a_key_is_not_enough_if_tracing_is_switched_off() -> None:
    """`JEVE_TRACING=off` kills telemetry without rotating a secret."""

    settings = Settings(braintrust_api_key="sk-test", tracing_enabled=False)
    assert tracing.configure(settings=settings) is False


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


# -- against the real SDK, offline ----------------------------------------


def test_the_real_sdk_produces_the_span_shape_we_meant() -> None:
    """The contract with a dependency we do not own.

    Spans here are hand-built — there is no LLM SDK to wrap, because the
    gateway posts raw httpx (LLM-0008). That makes `start_span`'s keywords, the
    `llm` type and `metrics.estimated_cost` an API we are coupled to without a
    wrapper to absorb a change. This runs the real braintrust logger against
    its own in-memory backend, so an upgrade that moves any of them fails here
    rather than in production. No socket is opened.
    """

    from braintrust import logger as bt
    from braintrust.test_helpers import init_test_logger, simulate_login

    simulate_login()
    init_test_logger("jeve-span-shape")
    with bt._internal_with_memory_background_logger() as memory:
        tracing.reset()
        assert tracing.configure(
            settings=Settings(
                braintrust_api_key=bt.TEST_API_KEY,
                braintrust_project="jeve-span-shape",
            )
        )
        with tracing.span("decide.batch", type="task", metadata={"mode": "record"}):
            with tracing.span("jev.decide", type="llm", input={"state": "x"}) as call:
                call.log(
                    output={"urgent": 0.9},
                    metrics={"tokens": 430, "estimated_cost": 1.68e-05},
                )
        rows = memory.pop()

    batch, decide = rows
    assert batch["span_attributes"]["name"] == "decide.batch"
    assert batch["span_attributes"]["type"] == "task"
    assert not batch["span_parents"]

    assert decide["span_attributes"]["type"] == "llm"
    assert decide["span_parents"] == [batch["span_id"]]
    assert decide["input"] == {"state": "x"}
    assert decide["output"] == {"urgent": 0.9}
    # The field Braintrust prefers over its own registry estimate — the point
    # of logging it at all, since the registry has never heard of jev.
    assert decide["metrics"]["estimated_cost"] == 1.68e-05
