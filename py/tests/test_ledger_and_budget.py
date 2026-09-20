"""The ceiling is the one thing that must not be wrong.

These run without a network. Every rule in LLM-0004 has a test that fails when
the rule is removed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jeve.config import Settings
from jeve.errors import BudgetExceededError
from jeve.llm.budget import BudgetGuard
from jeve.llm.ledger import SpendLedger


def _ledger(tmp_path: Path) -> SpendLedger:
    return SpendLedger(tmp_path / "ledger.jsonl", checkpoint=tmp_path / "spend.json")


def _guard(tmp_path: Path, ledger: SpendLedger) -> BudgetGuard:
    return BudgetGuard(Settings(ops_dir=tmp_path), ledger)


def test_empty_ledger_reads_as_zero(tmp_path: Path) -> None:
    assert _ledger(tmp_path).read().effective_usd == 0.0


def test_settled_costs_accumulate(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 0.25, estimated=False, model="m", outcome="ok")
    ledger.reserve("b", 1.0, purpose="gate", model="m")
    ledger.settle("b", 0.5, estimated=False, model="m", outcome="ok")

    spend = ledger.read()
    assert spend.settled_usd == pytest.approx(0.75)
    assert spend.reserved_usd == 0.0
    assert spend.calls == 2


def test_unsettled_reservation_still_counts(tmp_path: Path) -> None:
    """A crashed process must over-count, never under-count."""

    ledger = _ledger(tmp_path)
    ledger.reserve("orphan", 2.0, purpose="gate", model="m")
    assert ledger.read().effective_usd == pytest.approx(2.0)


def test_release_gives_a_reservation_back(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.reserve("rejected", 2.0, purpose="gate", model="m")
    ledger.release("rejected", reason="http-401-unbilled")
    assert ledger.read().effective_usd == 0.0


def test_spend_survives_a_new_ledger_object(tmp_path: Path) -> None:
    """State lives on disk, so a restart cannot hand budget back."""

    first = _ledger(tmp_path)
    first.reserve("a", 1.0, purpose="gate", model="m")
    first.settle("a", 3.5, estimated=False, model="m", outcome="ok")

    assert _ledger(tmp_path).read().effective_usd == pytest.approx(3.5)


def test_torn_final_line_does_not_lose_earlier_spend(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 4.0, estimated=False, model="m", outcome="ok")
    with open(ledger.path, "a") as handle:
        handle.write('{"kind": "settle", "id": "torn", "amount_')

    assert ledger.read().settled_usd == pytest.approx(4.0)


def test_checkpoint_tracks_the_ledger(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 0.75, estimated=True, model="m", outcome="ok")

    payload = json.loads((tmp_path / "spend.json").read_text())
    assert payload["effective_usd"] == pytest.approx(0.75)
    assert payload["estimated_calls"] == 1


def test_explore_is_refused_at_twelve_dollars(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 12.01, estimated=False, model="m", outcome="ok")
    guard = _guard(tmp_path, ledger)

    with pytest.raises(BudgetExceededError, match="exploratory"):
        guard.authorise("x", worst_case_usd=0.01, purpose="explore", model="m")

    # Gate work continues.
    guard.authorise("y", worst_case_usd=0.01, purpose="gate", model="m")


def test_everything_is_refused_at_sixteen(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 16.0, estimated=False, model="m", outcome="ok")
    guard = _guard(tmp_path, ledger)

    assert guard.state().should_halt is True
    with pytest.raises(BudgetExceededError, match="halt"):
        guard.authorise("x", worst_case_usd=0.01, purpose="gate", model="m")


def test_a_call_that_would_breach_twenty_is_refused_before_it_is_issued(
    tmp_path: Path,
) -> None:
    """The reservation is what makes $20 a real ceiling under concurrency."""

    ledger = _ledger(tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 11.0, estimated=False, model="m", outcome="ok")
    guard = _guard(tmp_path, ledger)

    with pytest.raises(BudgetExceededError, match="hard ceiling"):
        guard.authorise("big", worst_case_usd=9.5, purpose="gate", model="m")


def test_concurrent_reservations_cannot_sail_past_the_ceiling(tmp_path: Path) -> None:
    """In-flight calls count, so a burst cannot outrun the ladder.

    Without reservations, sixteen concurrent calls would all be authorised
    against $0 of settled spend and the ceiling would only notice afterwards.
    """

    ledger = _ledger(tmp_path)
    guard = _guard(tmp_path, ledger)
    for index in range(16):
        guard.authorise(f"c{index}", worst_case_usd=1.0, purpose="gate", model="m")

    # Nothing has settled; the ladder is enforced on reservations alone.
    assert ledger.read().settled_usd == 0.0
    with pytest.raises(BudgetExceededError, match="halt"):
        guard.authorise("one-too-many", worst_case_usd=0.01, purpose="gate", model="m")


def test_no_single_call_can_jump_the_hard_ceiling(tmp_path: Path) -> None:
    """The $20 rung is checked against the projection, not just the balance."""

    ledger = _ledger(tmp_path)
    # Settled below the halt rung, so the ladder's earlier rungs stay open.
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 15.0, estimated=False, model="m", outcome="ok")
    guard = _guard(tmp_path, ledger)

    with pytest.raises(BudgetExceededError, match="hard ceiling"):
        guard.authorise("whale", worst_case_usd=6.0, purpose="gate", model="m")


def test_first_remote_reading_becomes_the_baseline(tmp_path: Path) -> None:
    """`/key` reports lifetime spend for the credential; only the delta is ours."""

    ledger = _ledger(tmp_path)
    guard = _guard(tmp_path, ledger)
    guard.apply_remote(31.40)

    spend = ledger.read()
    assert spend.baseline_usd == pytest.approx(31.40)
    assert spend.effective_usd == 0.0


def test_remote_is_authoritative_when_it_is_higher(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    guard = _guard(tmp_path, ledger)
    guard.apply_remote(10.0)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 1.0, estimated=False, model="m", outcome="ok")

    _, divergence = guard.apply_remote(12.0)

    assert divergence is not None and divergence > 0.10
    assert ledger.read().effective_usd == pytest.approx(2.0)


def test_a_lagging_remote_cannot_hand_budget_back(tmp_path: Path) -> None:
    """Taking 'trust the remote' literally would refund spend we already made."""

    ledger = _ledger(tmp_path)
    guard = _guard(tmp_path, ledger)
    guard.apply_remote(10.0)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 5.0, estimated=False, model="m", outcome="ok")

    guard.apply_remote(10.0)  # the meter has not caught up

    assert ledger.read().effective_usd == pytest.approx(5.0)


def test_remote_recheck_is_due_after_fifteen_minutes(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    guard = _guard(tmp_path, ledger)
    guard.apply_remote(1.0)
    guard.apply_remote(1.0)

    checked_at = ledger.read().remote_checked_at
    assert checked_at is not None
    assert guard.needs_remote_check(now=checked_at + 60) is False
    assert guard.needs_remote_check(now=checked_at + 15 * 60 + 1) is True


def test_an_entry_after_a_torn_line_is_not_welded_to_it(tmp_path: Path) -> None:
    """A killed process leaves half a line. Appending straight onto it turns
    the *next* real entry into garbage too, and that one was real money."""

    ledger = _ledger(tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 0.25, estimated=False, model="m", outcome="ok")
    with open(ledger.path, "a") as handle:
        handle.write('{"kind": "settle", "id": "torn", "amount_')

    ledger.reserve("b", 1.0, purpose="gate", model="m")
    ledger.settle("b", 0.50, estimated=False, model="m", outcome="ok")

    assert ledger.read().settled_usd == pytest.approx(0.75)
    assert _ledger(tmp_path).read().settled_usd == pytest.approx(0.75)


def test_two_ledger_objects_on_one_file_agree(tmp_path: Path) -> None:
    """The sim and a script share the file. Each remembers only how far it has
    read, so each must see what the other wrote since."""

    sim, script = _ledger(tmp_path), _ledger(tmp_path)
    sim.reserve("s1", 1.0, purpose="gate", model="m")
    assert script.read().reserved_usd == pytest.approx(1.0)

    script.reserve("x1", 2.0, purpose="gate", model="m")
    script.settle("x1", 0.1, estimated=False, model="m", outcome="ok")
    sim.settle("s1", 0.2, estimated=False, model="m", outcome="ok")

    for view in (sim.read(), script.read(), _ledger(tmp_path).read()):
        assert view.settled_usd == pytest.approx(0.3)
        assert view.reserved_usd == 0.0
        assert view.calls == 2


def test_reading_does_not_rescan_the_file(tmp_path: Path) -> None:
    """Quadratic reads were minutes of blocked event loop at tonight's volume.
    Asserted on bytes read, not on a stopwatch."""

    ledger = _ledger(tmp_path)
    for index in range(200):
        ledger.reserve(f"c{index}", 0.001, purpose="gate", model="m")
        ledger.settle(f"c{index}", 0.0001, estimated=False, model="m", outcome="ok")

    before = ledger._offset
    ledger.reserve("last", 0.001, purpose="gate", model="m")
    grew_by = ledger._offset - before

    assert before > 20_000
    assert grew_by < 300
    assert ledger.read().calls == 200


def test_a_replaced_ledger_file_is_read_from_the_top(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 0.9, estimated=False, model="m", outcome="ok")
    assert ledger.read().settled_usd == pytest.approx(0.9)

    ledger.path.unlink()
    assert ledger.read().settled_usd == 0.0
    ledger.reserve("b", 1.0, purpose="gate", model="m")
    ledger.settle("b", 0.1, estimated=False, model="m", outcome="ok")
    assert ledger.read().settled_usd == pytest.approx(0.1)
