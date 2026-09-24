"""The ceiling is the one thing that must not be wrong.

The ledger is a Postgres table (LLM-0007): these need the Compose database and
skip without it. Every rule in LLM-0004 still has a test that fails when the
rule is removed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from psycopg import Connection
from psycopg.rows import DictRow

from jeve.config import Settings
from jeve.errors import BudgetExceededError
from jeve.llm.budget import BudgetGuard
from jeve.llm.ledger import SpendLedger

pytestmark = pytest.mark.timeout(60)


def _ledger(spend_table: Connection[DictRow], tmp_path: Path) -> SpendLedger:
    ledger = SpendLedger(checkpoint=tmp_path / "spend.json")
    assert spend_table  # the fixture migrated and emptied the table
    return ledger


def _guard(tmp_path: Path, ledger: SpendLedger) -> BudgetGuard:
    return BudgetGuard(Settings(ops_dir=tmp_path), ledger)


def test_empty_ledger_reads_as_zero(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    assert _ledger(spend_table, tmp_path).read().effective_usd == 0.0


def test_settled_costs_accumulate(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    ledger = _ledger(spend_table, tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 0.25, estimated=False, model="m", outcome="ok")
    ledger.reserve("b", 1.0, purpose="gate", model="m")
    ledger.settle("b", 0.5, estimated=False, model="m", outcome="ok")

    spend = ledger.read()
    assert spend.settled_usd == pytest.approx(0.75)
    assert spend.reserved_usd == 0.0
    assert spend.calls == 2


def test_unsettled_reservation_still_counts(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """A crashed process must over-count, never under-count."""

    ledger = _ledger(spend_table, tmp_path)
    ledger.reserve("orphan", 2.0, purpose="gate", model="m")
    assert ledger.read().effective_usd == pytest.approx(2.0)


def test_release_gives_a_reservation_back(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    ledger = _ledger(spend_table, tmp_path)
    ledger.reserve("rejected", 2.0, purpose="gate", model="m")
    ledger.release("rejected", reason="http-401-unbilled")
    assert ledger.read().effective_usd == 0.0


def test_spend_survives_a_new_ledger_object(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """State lives in Postgres, so a restart cannot hand budget back."""

    first = _ledger(spend_table, tmp_path)
    first.reserve("a", 1.0, purpose="gate", model="m")
    first.settle("a", 3.5, estimated=False, model="m", outcome="ok")
    first.close()

    assert _ledger(spend_table, tmp_path).read().effective_usd == pytest.approx(3.5)


def test_entries_are_durable_without_the_caller_committing(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """Money spent by a tick that is then rolled back is still spent.

    The ledger writes on its own autocommit connection for exactly this
    reason: a reservation folded into the tick's transaction would un-record
    real money when the tick failed.
    """

    ledger = _ledger(spend_table, tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 4.0, estimated=False, model="m", outcome="ok")
    # No commit() call exists on SpendLedger — if one were needed, this read
    # on a second object would see nothing.
    assert _ledger(spend_table, tmp_path).read().settled_usd == pytest.approx(4.0)


def test_checkpoint_tracks_the_ledger(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    ledger = _ledger(spend_table, tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 0.75, estimated=True, model="m", outcome="ok")

    payload = json.loads((tmp_path / "spend.json").read_text())
    assert payload["effective_usd"] == pytest.approx(0.75)
    assert payload["estimated_calls"] == 1


def test_an_unwritable_checkpoint_is_not_fatal(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """The checkpoint mirrors the table; the table is truth. An unwritable
    fs — the sim image runs as uid 1001 under a root-owned /app — killed the
    daemon on boot once; a mirror must never break accounting."""

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    ledger = SpendLedger(checkpoint=blocker / "spend.json")

    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 0.5, estimated=False, model="m", outcome="ok")

    assert ledger.read().settled_usd == pytest.approx(0.5)


def test_explore_is_refused_at_twelve_dollars(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    ledger = _ledger(spend_table, tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 12.01, estimated=False, model="m", outcome="ok")
    guard = _guard(tmp_path, ledger)

    with pytest.raises(BudgetExceededError, match="exploratory"):
        guard.authorise("x", worst_case_usd=0.01, purpose="explore", model="m")

    # Gate work continues.
    guard.authorise("y", worst_case_usd=0.01, purpose="gate", model="m")


def test_everything_is_refused_at_sixteen(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    ledger = _ledger(spend_table, tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 16.0, estimated=False, model="m", outcome="ok")
    guard = _guard(tmp_path, ledger)

    assert guard.state().should_halt is True
    with pytest.raises(BudgetExceededError, match="halt"):
        guard.authorise("x", worst_case_usd=0.01, purpose="gate", model="m")


def test_a_call_that_would_breach_twenty_is_refused_before_it_is_issued(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """The reservation is what makes $20 a real ceiling under concurrency."""

    ledger = _ledger(spend_table, tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 11.0, estimated=False, model="m", outcome="ok")
    guard = _guard(tmp_path, ledger)

    with pytest.raises(BudgetExceededError, match="hard ceiling"):
        guard.authorise("big", worst_case_usd=9.5, purpose="gate", model="m")


def test_concurrent_reservations_cannot_sail_past_the_ceiling(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """In-flight calls count, so a burst cannot outrun the ladder.

    Without reservations, sixteen concurrent calls would all be authorised
    against $0 of settled spend and the ceiling would only notice afterwards.
    """

    ledger = _ledger(spend_table, tmp_path)
    guard = _guard(tmp_path, ledger)
    for index in range(16):
        guard.authorise(f"c{index}", worst_case_usd=1.0, purpose="gate", model="m")

    # Nothing has settled; the ladder is enforced on reservations alone.
    assert ledger.read().settled_usd == 0.0
    with pytest.raises(BudgetExceededError, match="halt"):
        guard.authorise("one-too-many", worst_case_usd=0.01, purpose="gate", model="m")


def test_two_processes_cannot_authorise_past_the_ceiling_together(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """Check-then-reserve is one serialised transaction (LLM-0007).

    Each guard sees the world through its own ledger object and its own
    connection — the daemon and the API, or two daemons racing. The second
    authorise must observe the first's reservation, not a pre-reserve
    snapshot.
    """

    sim = _ledger(spend_table, tmp_path)
    api = _ledger(spend_table, tmp_path)
    sim_guard = _guard(tmp_path, sim)
    api_guard = _guard(tmp_path, api)

    sim_guard.authorise("a", worst_case_usd=16.5, purpose="gate", model="m")
    with pytest.raises(BudgetExceededError, match="halt"):
        api_guard.authorise("b", worst_case_usd=1.0, purpose="gate", model="m")


def test_no_single_call_can_jump_the_hard_ceiling(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """The $20 rung is checked against the projection, not just the balance."""

    ledger = _ledger(spend_table, tmp_path)
    # Settled below the halt rung, so the ladder's earlier rungs stay open.
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 15.0, estimated=False, model="m", outcome="ok")
    guard = _guard(tmp_path, ledger)

    with pytest.raises(BudgetExceededError, match="hard ceiling"):
        guard.authorise("whale", worst_case_usd=6.0, purpose="gate", model="m")


def test_first_remote_reading_becomes_the_baseline(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """`/key` reports lifetime spend for the credential; only the delta is ours."""

    ledger = _ledger(spend_table, tmp_path)
    guard = _guard(tmp_path, ledger)
    guard.apply_remote(31.40)

    spend = ledger.read()
    assert spend.baseline_usd == pytest.approx(31.40)
    assert spend.effective_usd == 0.0


def test_remote_is_authoritative_when_it_is_higher(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    ledger = _ledger(spend_table, tmp_path)
    guard = _guard(tmp_path, ledger)
    guard.apply_remote(10.0)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 1.0, estimated=False, model="m", outcome="ok")

    _, divergence = guard.apply_remote(12.0)

    assert divergence is not None and divergence > 0.10
    assert ledger.read().effective_usd == pytest.approx(2.0)


def test_a_lagging_remote_cannot_hand_budget_back(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """Taking 'trust the remote' literally would refund spend we already made."""

    ledger = _ledger(spend_table, tmp_path)
    guard = _guard(tmp_path, ledger)
    guard.apply_remote(10.0)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 5.0, estimated=False, model="m", outcome="ok")

    guard.apply_remote(10.0)  # the meter has not caught up

    assert ledger.read().effective_usd == pytest.approx(5.0)


def test_remote_recheck_is_due_after_fifteen_minutes(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    ledger = _ledger(spend_table, tmp_path)
    guard = _guard(tmp_path, ledger)
    guard.apply_remote(1.0)
    guard.apply_remote(1.0)

    checked_at = ledger.read().remote_checked_at
    assert checked_at is not None
    assert guard.needs_remote_check(now=checked_at + 60) is False
    assert guard.needs_remote_check(now=checked_at + 15 * 60 + 1) is True


def test_two_ledger_objects_on_one_table_agree(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """The sim and the API share the table — each sees what the other wrote."""

    sim, api = _ledger(spend_table, tmp_path), _ledger(spend_table, tmp_path)
    sim.reserve("s1", 1.0, purpose="gate", model="m")
    assert api.read().reserved_usd == pytest.approx(1.0)

    api.reserve("x1", 2.0, purpose="gate", model="m")
    api.settle("x1", 0.1, estimated=False, model="m", outcome="ok")
    sim.settle("s1", 0.2, estimated=False, model="m", outcome="ok")

    for view in (sim.read(), api.read(), _ledger(spend_table, tmp_path).read()):
        assert view.settled_usd == pytest.approx(0.3)
        assert view.reserved_usd == 0.0
        assert view.calls == 2


# -- the running total (LLM-0010) -------------------------------------------


def test_read_is_the_totals_row_not_the_ledger(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """A spend check reads one row; it does not fold the ledger.

    The fold cost 80% of the production database's time at 86k rows and grew
    with every call. If this test fails because `read()` recomputes from
    `spend_entries`, the fold is back.
    """

    ledger = _ledger(spend_table, tmp_path)
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 0.5, estimated=False, model="m", outcome="ok")

    spend_table.execute("UPDATE spend_totals SET settled_usd = 99.0")
    spend_table.commit()

    assert ledger.read().settled_usd == pytest.approx(99.0)


def test_totals_agree_with_the_ledger_after_a_mixed_history(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """Every kind of entry moves the total exactly as the fold would."""

    ledger = _ledger(spend_table, tmp_path)
    guard = _guard(tmp_path, ledger)
    guard.apply_remote(3.0)  # baseline
    ledger.reserve("a", 1.0, purpose="gate", model="m")
    ledger.settle("a", 0.25, estimated=False, model="m", outcome="ok")
    ledger.reserve("b", 2.0, purpose="gate", model="m")
    ledger.settle("b", 0.75, estimated=True, model="m", outcome="ok")
    ledger.reserve("c", 1.5, purpose="gate", model="m")
    ledger.release("c", reason="http-401-unbilled")
    ledger.reserve("orphan", 4.0, purpose="gate", model="m")
    guard.apply_remote(3.5)  # remote

    running = ledger.read()
    folded = ledger.rebuild()

    assert running.settled_usd == pytest.approx(1.0)
    assert running.reserved_usd == pytest.approx(4.0)
    assert running.calls == 2
    assert running.estimated_calls == 1
    assert running.baseline_usd == pytest.approx(3.0)
    assert running.remote_usd == pytest.approx(3.5)
    assert running.remote_checked_at is not None
    for field in (
        "settled_usd",
        "reserved_usd",
        "calls",
        "estimated_calls",
        "baseline_usd",
        "remote_usd",
        "remote_checked_at",
    ):
        assert getattr(running, field) == pytest.approx(getattr(folded, field))


def test_a_new_ledger_reconciles_a_stale_total(
    spend_table: Connection[DictRow], tmp_path: Path
) -> None:
    """Rows the total has not seen are folded in when a ledger opens.

    During a deploy the old daemon keeps appending after the migration seeded
    the total; the new daemon's first open must not start from a stale row.
    """

    writer = _ledger(spend_table, tmp_path)
    writer.reserve("a", 1.0, purpose="gate", model="m")
    writer.settle("a", 2.0, estimated=False, model="m", outcome="ok")
    writer.reserve("open", 0.5, purpose="gate", model="m")
    writer.close()

    spend_table.execute(
        "UPDATE spend_totals SET as_of_seq = 0, settled_usd = 0, reserved_usd = 0, "
        "calls = 0"
    )
    spend_table.commit()

    spend = _ledger(spend_table, tmp_path).read()
    assert spend.settled_usd == pytest.approx(2.0)
    assert spend.reserved_usd == pytest.approx(0.5)
    assert spend.calls == 1
