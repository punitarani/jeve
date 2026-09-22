"""`make soak`, as a test: three weeks, and it is still a world.

Nothing ran past eight days until the audit did, and over thirty the world
wound down. This is the horizon that would have caught it (WORLD-0005).
`make soak` keeps the full thirty-five days; at 225 staff the suite runs
twenty-one, both arms, which is past the second payday, the first close and
the first written-off bill, in half the time.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from jeve import db
from jeve.sim import soak

pytestmark = pytest.mark.timeout(900)


def test_three_weeks_on_rules_hold_every_invariant(tmp_path: Path) -> None:
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {db.dsn()}: {error}")

    report = tmp_path / "soak.md"
    code = soak.main(
        ["--days", "21", "--counterfactual", "--report", str(report), "--database",
         "jeve_soak_test"]
    )  # fmt: skip
    text = report.read_text()
    assert code == 0, text
    assert "**PASS**" in text and "**NO**" not in text
    assert "Invoice amounts constant across arms:** yes" in text
    assert "Cash differs across arms:** yes" in text
