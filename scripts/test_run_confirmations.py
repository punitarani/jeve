#!/usr/bin/env python3
"""Unit tests for scripts/run-confirmations.py (OPS-0002).

Runs in the `decisions` CI job, which has neither uv nor pnpm nor a database,
so every command these tests execute is a shell builtin. Stdlib only.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "run_confirmations", ROOT / "scripts" / "run-confirmations.py"
)
assert spec is not None and spec.loader is not None
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


def index_with(*records: dict) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for record in records:
        handle.write(json.dumps(record) + "\n")
    handle.close()
    return Path(handle.name)


class Rewrite(unittest.TestCase):
    """Only a bare pytest invocation is turned into a collection."""

    def test_a_plain_pytest_command_is_collected(self) -> None:
        self.assertEqual(
            rc.rewrite("cd py && uv run pytest tests/test_api.py", "collect"),
            "cd py && uv run pytest tests/test_api.py --collect-only",
        )

    def test_flags_survive_the_rewrite(self) -> None:
        # CORE-0011 selects one test by name. `-k` matching nothing exits 5,
        # so a stale selector still fails under --collect-only.
        self.assertEqual(
            rc.rewrite("cd py && uv run pytest tests/test_api.py -k contract", "collect"),
            "cd py && uv run pytest tests/test_api.py -k contract --collect-only",
        )

    def test_several_paths_survive_the_rewrite(self) -> None:
        command = "cd py && uv run pytest tests/test_world.py tests/test_soak.py"
        self.assertEqual(rc.rewrite(command, "collect"), command + " --collect-only")

    def test_a_chained_command_is_left_alone(self) -> None:
        # CORE-0006 is ruff *and* mypy. Appending a pytest flag to the end
        # would hand it to mypy, which is a different command entirely.
        command = "cd py && uv run ruff check . && uv run mypy"
        self.assertEqual(rc.rewrite(command, "collect"), command)

    def test_a_build_that_ends_in_a_test_is_left_alone(self) -> None:
        command = "cd apps/web && pnpm exec next build && test -d out"
        self.assertEqual(rc.rewrite(command, "collect"), command)

    def test_a_non_pytest_command_is_left_alone(self) -> None:
        for command in (
            "python3 scripts/gen-decisions.py --check",
            "python3 scripts/check_fly_config.py",
            "npx nx show projects",
            "pnpm --filter @jeve/web exec tsc --noEmit",
        ):
            self.assertEqual(rc.rewrite(command, "collect"), command)

    def test_run_mode_rewrites_nothing(self) -> None:
        command = "cd py && uv run pytest tests/test_api.py"
        self.assertEqual(rc.rewrite(command, "run"), command)


class Load(unittest.TestCase):
    def test_one_command_named_by_two_records_runs_once(self) -> None:
        index = index_with(
            {"id": "LLM-0005", "confirmation": "true"},
            {"id": "LLM-0006", "confirmation": "true"},
        )
        self.assertEqual(rc.load(index), [("LLM-0005,LLM-0006", "true")])

    def test_records_without_a_confirmation_are_skipped(self) -> None:
        index = index_with(
            {"id": "CORE-0002", "confirmation": None},
            {"id": "CORE-0003"},
            {"id": "CORE-0004", "confirmation": "true"},
        )
        self.assertEqual(rc.load(index), [("CORE-0004", "true")])

    def test_first_seen_order_is_kept(self) -> None:
        index = index_with(
            {"id": "B-0001", "confirmation": "echo second"},
            {"id": "A-0001", "confirmation": "echo first"},
        )
        self.assertEqual(
            [command for _, command in rc.load(index)], ["echo second", "echo first"]
        )


class Main(unittest.TestCase):
    def test_all_passing_exits_zero(self) -> None:
        index = index_with({"id": "X-0001", "confirmation": "true"})
        self.assertEqual(rc.main(["--index", str(index)]), 0)

    def test_one_failure_fails_the_run(self) -> None:
        index = index_with(
            {"id": "X-0001", "confirmation": "true"},
            {"id": "X-0002", "confirmation": "false"},
        )
        self.assertEqual(rc.main(["--index", str(index)]), 1)

    def test_a_later_command_still_runs_after_a_failure(self) -> None:
        # One bad record must not hide the state of every record after it.
        marker = Path(tempfile.mkdtemp()) / "ran"
        index = index_with(
            {"id": "X-0001", "confirmation": "exit 7"},
            {"id": "X-0002", "confirmation": "touch {}".format(marker)},
        )
        self.assertEqual(rc.main(["--index", str(index)]), 1)
        self.assertTrue(marker.exists())

    def test_list_executes_nothing(self) -> None:
        marker = Path(tempfile.mkdtemp()) / "ran"
        index = index_with(
            {"id": "X-0001", "confirmation": "touch {}".format(marker)}
        )
        self.assertEqual(rc.main(["--index", str(index), "--list"]), 0)
        self.assertFalse(marker.exists())


class TheRealIndex(unittest.TestCase):
    def test_every_confirmation_in_the_repo_is_one_of_the_two_shapes(self) -> None:
        """A new confirmation shape should be a deliberate choice.

        Either it is a plain pytest run the suite already covers, or it is a
        command CI executes verbatim. Anything that looks like pytest but is
        not matched here would be executed in full in the python job, which is
        correct but slow — this test is where that gets noticed.
        """

        for ids, command in rc.load(rc.INDEX):
            collected = rc.rewrite(command, "collect")
            if "pytest" in command and collected == command:
                self.assertIn(
                    "&&",
                    command.replace("cd py && uv run pytest", "", 1),
                    "{}: pytest confirmation not collected and not chained: {}".format(
                        ids, command
                    ),
                )

    def test_no_confirmation_runs_the_whole_suite_again(self) -> None:
        """CI has already run the suite once, in parallel (OPS-0002).

        WEB-0006's `make check` ran all of it a second time, serially: fifteen
        of the python job's twenty-four minutes. It never names pytest, so the
        test above let it through.
        """

        for ids, command in rc.load(rc.INDEX):
            for wrapper in ("make check", "make test", "py:test", "-t test"):
                self.assertNotIn(
                    wrapper,
                    command,
                    "{}: `{}` re-runs the whole suite: {}".format(ids, wrapper, command),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
