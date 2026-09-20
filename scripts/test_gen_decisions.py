#!/usr/bin/env python3
"""Tests for the decision generator.

Each one breaks a record the way a real edit would and asserts the specific
complaint. A check nobody has watched fail is a check that might not work.

    python3 scripts/test_gen_decisions.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path  # noqa: F401

_spec = importlib.util.spec_from_file_location(
    "gen_decisions", Path(__file__).parent / "gen-decisions.py"
)
assert _spec and _spec.loader
gen = importlib.util.module_from_spec(_spec)
sys.modules["gen_decisions"] = gen
_spec.loader.exec_module(gen)


def record(**overrides: object) -> str:
    meta: dict[str, object] = {
        "id": "CORE-0001",
        "title": "A decision",
        "status": "accepted",
        "date": "2026-09-20",
        "deciders": ["punitarani"],
        "scope": [],
        "tags": ["x"],
        "supersedes": [],
        "superseded-by": None,
        "relates-to": [],
        "confirmation": None,
    }
    meta.update(overrides)
    body = (
        "\n# CORE-0001 — A decision\n\n"
        "## Context and Problem Statement\n\nSomething forced a choice.\n\n"
        "## Considered Options\n\n- One\n- Two\n\n"
        "## Decision Outcome\n\nWe took the first one, for a reason that\n"
        "spans two lines.\n\n### Consequences\n\n- Good: it works.\n"
    )
    return gen.render_front_matter(meta) + body


class FrontMatter(unittest.TestCase):
    def test_round_trips(self) -> None:
        meta, body = gen.parse_front_matter(record(), "t.md")
        self.assertEqual(meta["id"], "CORE-0001")
        self.assertIsNone(meta["superseded-by"])
        self.assertEqual(meta["deciders"], ["punitarani"])
        self.assertIn("## Decision Outcome", body)

    def test_unquoted_glob_is_rejected_with_advice(self) -> None:
        """`[**/x]` is a YAML alias, not a list. Catch it here, not in CI."""

        text = record().replace("scope: []", "scope: [**/decisions/*.md]")
        with self.assertRaises(gen.RecordError) as caught:
            gen.parse_front_matter(text, "t.md")
        self.assertIn("Globs must be quoted", str(caught.exception))

    def test_missing_front_matter_is_named(self) -> None:
        with self.assertRaises(gen.RecordError):
            gen.parse_front_matter("# Just a heading\n", "t.md")

    def test_unclosed_front_matter_is_named(self) -> None:
        with self.assertRaises(gen.RecordError):
            gen.parse_front_matter("---\nid: CORE-0001\n", "t.md")

    def test_summary_is_the_paragraph_not_the_line(self) -> None:
        rec = gen.Record(
            path=gen.DECISIONS / "core" / "t.md",
            meta={},
            body=record().split("---", 2)[2],
        )
        self.assertEqual(
            rec.summary, "We took the first one, for a reason that spans two lines."
        )


class Validation(unittest.TestCase):
    def test_bad_id_shape(self) -> None:
        meta, _ = gen.parse_front_matter(record(id="core-1"), "t.md")
        self.assertTrue(any("'id'" in p for p in gen.validate_meta(meta, "t.md")))

    def test_unknown_status(self) -> None:
        meta, _ = gen.parse_front_matter(record(status="maybe"), "t.md")
        self.assertTrue(any("'status'" in p for p in gen.validate_meta(meta, "t.md")))

    def test_unknown_key_is_rejected(self) -> None:
        text = record().replace("tags:", 'flavour: ["x"]\ntags:')
        meta, _ = gen.parse_front_matter(text, "t.md")
        self.assertTrue(any("unknown key" in p for p in gen.validate_meta(meta, "t.md")))

    def test_missing_key_is_reported(self) -> None:
        text = "\n".join(
            line for line in record().splitlines() if not line.startswith("tags:")
        )
        meta, _ = gen.parse_front_matter(text, "t.md")
        self.assertTrue(any("missing required" in p for p in gen.validate_meta(meta, "t.md")))

    def test_schema_matches_the_field_spec(self) -> None:
        schema = gen.json_schema()
        self.assertEqual(set(schema["properties"]), set(gen.FIELDS))
        self.assertIn("superseded-by", schema["required"])


class Globs(unittest.TestCase):
    FILES = [
        "py/src/jeve/llm/gateway.py",
        "py/src/jeve/llm/decisions/LLM-0001-x.md",
        "decisions/core/CORE-0001-x.md",
    ]

    def test_a_glob_matching_real_code_passes(self) -> None:
        self.assertTrue(gen.glob_matches("py/src/jeve/llm/**", self.FILES))

    def test_drift_is_caught(self) -> None:
        self.assertFalse(gen.glob_matches("py/src/jeve/world/**", self.FILES))

    def test_records_do_not_satisfy_their_own_area_glob(self) -> None:
        """The loophole that would make the drift check vacuous.

        Two records in `py/src/jeve/world/decisions/` would otherwise match
        `py/src/jeve/world/**` by matching each other, and a package with no
        code would pass.
        """

        files = ["py/src/jeve/world/decisions/WORLD-0001-x.md"]
        self.assertFalse(gen.glob_matches("py/src/jeve/world/**", files))

    def test_a_glob_about_decisions_still_matches_them(self) -> None:
        self.assertTrue(gen.glob_matches("**/decisions/*.md", self.FILES))


class Graph(unittest.TestCase):
    def _records(self, *metas: dict[str, object]) -> list[gen.Record]:
        out = []
        for meta in metas:
            text = record(**meta)
            parsed, body = gen.parse_front_matter(text, "t.md")
            name = f"{parsed['id']}-x.md"
            out.append(
                gen.Record(
                    path=gen.DECISIONS / "core" / name, meta=parsed, body=body
                )
            )
        return out

    def test_dangling_reference_is_caught(self) -> None:
        records = self._records({"id": "CORE-0001", "relates-to": ["CORE-0099"]})
        self.assertTrue(
            any("unknown id CORE-0099" in p for p in gen.check_records(records))
        )

    def test_supersede_must_be_symmetric(self) -> None:
        records = self._records(
            {"id": "CORE-0001", "status": "superseded", "superseded-by": "CORE-0002"},
            {"id": "CORE-0002"},  # does not list CORE-0001 in supersedes
        )
        problems = gen.check_records(records)
        self.assertTrue(any("does not list it in supersedes" in p for p in problems))

    def test_a_symmetric_pair_is_accepted(self) -> None:
        records = self._records(
            {"id": "CORE-0001", "status": "superseded", "superseded-by": "CORE-0002"},
            {"id": "CORE-0002", "supersedes": ["CORE-0001"]},
        )
        self.assertEqual(
            [p for p in gen.check_records(records) if "supersede" in p], []
        )

    def test_superseded_by_forces_the_status(self) -> None:
        records = self._records(
            {"id": "CORE-0001", "superseded-by": "CORE-0002"},
            {"id": "CORE-0002", "supersedes": ["CORE-0001"]},
        )
        self.assertTrue(
            any("expected 'superseded'" in p for p in gen.check_records(records))
        )

    def test_duplicate_ids_are_caught(self) -> None:
        records = self._records({"id": "CORE-0001"}, {"id": "CORE-0001"})
        self.assertTrue(any("also used by" in p for p in gen.check_records(records)))

    def test_a_gap_in_numbering_is_caught(self) -> None:
        """A gap means a record was deleted, which is never allowed."""

        records = self._records({"id": "CORE-0001"}, {"id": "CORE-0003"})
        self.assertTrue(any("contiguous" in p for p in gen.check_records(records)))

    def test_next_id_continues_the_sequence(self) -> None:
        records = self._records({"id": "CORE-0001"}, {"id": "CORE-0002"})
        self.assertEqual(gen.next_id(records, "CORE"), "CORE-0003")
        self.assertEqual(gen.next_id(records, "WORLD"), "WORLD-0001")


class Rules(unittest.TestCase):
    def test_only_accepted_records_with_scope_get_a_rule(self) -> None:
        def make(status: str, scope: list[str]) -> gen.Record:
            meta, body = gen.parse_front_matter(
                record(status=status, scope=scope), "t.md"
            )
            return gen.Record(
                path=gen.DECISIONS / "core" / "t.md", meta=meta, body=body
            )

        targets = gen.rule_targets(
            [
                make("accepted", ["py/**"]),
                make("proposed", ["py/**"]),
                make("superseded", ["py/**"]),
                make("accepted", []),
            ]
        )
        self.assertEqual(len(targets), 1)

    def test_the_rule_carries_retrieval_vocabulary(self) -> None:
        meta, body = gen.parse_front_matter(record(scope=["py/**"]), "t.md")
        text = gen.render_rule(
            gen.Record(path=gen.DECISIONS / "core" / "t.md", meta=meta, body=body)
        )
        self.assertIn("globs: py/**", text)
        self.assertIn("alwaysApply: false", text)
        for phrase in ("why", "what was decided", "changed"):
            self.assertIn(phrase, text)


class RealRepo(unittest.TestCase):
    def test_the_committed_records_are_valid(self) -> None:
        records, problems = gen.load_records()
        self.assertEqual(problems + gen.check_records(records), [])
        self.assertGreater(len(records), 0)

    def test_generated_artifacts_are_current(self) -> None:
        records, _ = gen.load_records()
        self.assertEqual(gen.generate(records, write=False), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
