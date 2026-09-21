#!/usr/bin/env python3
"""Validate decision records and regenerate everything derived from them.

Markdown is canonical. `decisions/INDEX.md`, `decisions/index.jsonl`,
`decisions/schema.json` and the generated block in `AGENTS.md` are outputs
and are never hand-edited — CI regenerates them and fails if the tree is
dirty.

Stdlib only, on purpose. The upstream ADR tools are archived or unmaintained,
and a hundred lines we own beats a dependency we cannot fix at 3am.

    gen-decisions.py                 regenerate
    gen-decisions.py --check         validate and diff, writing nothing
    gen-decisions.py --next CORE     print the next free id for a prefix
    gen-decisions.py --new CORE "…"  scaffold a record from the template
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "decisions"
INDEX_MD = DECISIONS / "INDEX.md"
INDEX_JSONL = DECISIONS / "index.jsonl"
SCHEMA_JSON = DECISIONS / "schema.json"
TEMPLATE = DECISIONS / "adr-template.md"
AGENTS_MD = ROOT / "AGENTS.md"

ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,7}-\d{4}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("proposed", "accepted", "rejected", "deprecated", "superseded")
MAX_BODY_LINES = 60

# MADR 4.0 minimal. Consequences is an H3 under Decision Outcome, not an H2.
REQUIRED_HEADINGS = (
    "## Context and Problem Statement",
    "## Considered Options",
    "## Decision Outcome",
)

# One spec, two uses: emitted as schema.json for other tools, and enforced by
# the validator below. Keeping them separate is how they drift apart.
FIELDS: dict[str, dict[str, Any]] = {
    "id": {"type": "string", "pattern": ID_PATTERN.pattern, "required": True},
    "title": {"type": "string", "minLength": 1, "required": True},
    "status": {"type": "string", "enum": list(STATUSES), "required": True},
    "date": {"type": "string", "pattern": DATE_PATTERN.pattern, "required": True},
    "deciders": {"type": "array", "items": "string", "required": True},
    "scope": {"type": "array", "items": "string", "required": True},
    "tags": {"type": "array", "items": "string", "required": True},
    "supersedes": {"type": "array", "items": "string", "required": True},
    "superseded-by": {"type": ["string", "null"], "required": True},
    "relates-to": {"type": "array", "items": "string", "required": True},
    "confirmation": {"type": ["string", "null"], "required": True},
}


class RecordError(Exception):
    """A specific problem with a specific file."""


@dataclass
class Record:
    path: Path
    meta: dict[str, Any]
    body: str
    problems: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return str(self.meta.get("id", "?"))

    @property
    def prefix(self) -> str:
        return self.id.split("-")[0]

    @property
    def rel(self) -> str:
        return self.path.relative_to(ROOT).as_posix()

    @property
    def summary(self) -> str:
        """The opening paragraph of Decision Outcome.

        Not the first sentence — that splits on `Next.js` and `ops/spend.json`.
        Not the first line either, since prose is hard-wrapped and a line ends
        mid-clause. The paragraph is the unit the template asks authors to
        write: one statement that stands on its own.
        """

        lines = self.body.splitlines()
        for index, line in enumerate(lines):
            if line.strip() != "## Decision Outcome":
                continue
            collected: list[str] = []
            for candidate in lines[index + 1 :]:
                text = candidate.strip()
                if not text:
                    if collected:
                        break
                    continue
                if text.startswith("#"):
                    break
                collected.append(text)
            return " ".join(collected)
        return ""


# --------------------------------------------------------------------------
# Front matter
# --------------------------------------------------------------------------


def parse_front_matter(text: str, source: str) -> tuple[dict[str, Any], str]:
    """Parse the `---` block.

    Values are JSON, which keeps the parser to a few lines and sidesteps a real
    YAML trap: an unquoted `[**/x]` is an *alias*, not a list of globs, and
    every YAML reader rejects it. Bare words and bare dates are accepted so the
    file still reads like ordinary MADR front matter.
    """

    if not text.startswith("---\n"):
        raise RecordError(f"{source}: no front matter (must start with '---')")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise RecordError(f"{source}: front matter is not closed with '---'")

    meta: dict[str, Any] = {}
    for offset, raw in enumerate(text[4:end].splitlines(), start=2):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line != line.lstrip():
            raise RecordError(
                f"{source}:{offset}: indented line; nested mappings are not "
                f"supported — use a JSON value on one line"
            )
        if ":" not in line:
            raise RecordError(f"{source}:{offset}: expected 'key: value'")
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key in meta:
            raise RecordError(f"{source}:{offset}: duplicate key {key!r}")
        meta[key] = _parse_value(value, source, offset)
    return meta, text[end + 5 :]


def _parse_value(value: str, source: str, line: int) -> Any:
    if value == "":
        raise RecordError(f"{source}:{line}: empty value; use null or []")
    if value in {"null", "~"}:
        return None
    if value in {"true", "false"}:
        return value == "true"
    if value[0] in "[{\"'" or value[0].isdigit() or value[0] == "-":
        if DATE_PATTERN.match(value):
            return value
        try:
            return json.loads(value.replace("'", '"'))
        except json.JSONDecodeError as error:
            raise RecordError(
                f"{source}:{line}: value is not valid JSON ({error.msg}). "
                f'Globs must be quoted: ["a/**"], not [a/**].'
            ) from None
    return value


def render_front_matter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key in FIELDS:
        value = meta[key]
        if value is None:
            rendered = "null"
        elif isinstance(value, str):
            rendered = value if key == "date" else json.dumps(value)
        else:
            rendered = json.dumps(value)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def json_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name, spec in FIELDS.items():
        prop: dict[str, Any] = {"type": spec["type"]}
        for extra in ("pattern", "enum", "minLength"):
            if extra in spec:
                prop[extra] = spec[extra]
        if spec["type"] == "array":
            prop["items"] = {"type": spec["items"]}
        properties[name] = prop
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/punitarani/jeve/decisions/schema.json",
        "title": "jeve decision record front matter",
        "description": (
            "Generated by scripts/gen-decisions.py from a single field spec. "
            "Do not edit; edit the spec."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [n for n, s in FIELDS.items() if s["required"]],
        "properties": properties,
    }


def validate_meta(meta: dict[str, Any], source: str) -> list[str]:
    problems: list[str] = []
    for name, spec in FIELDS.items():
        if name not in meta:
            problems.append(f"{source}: missing required key {name!r}")
            continue
        value = meta[name]
        types = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        if not _type_ok(value, types):
            problems.append(
                f"{source}: {name!r} should be {'|'.join(types)}, "
                f"got {type(value).__name__}"
            )
            continue
        if value is None:
            continue
        if spec["type"] == "array":
            if not all(isinstance(item, str) for item in value):
                problems.append(f"{source}: {name!r} must contain only strings")
        elif isinstance(value, str):
            if "pattern" in spec and not re.match(spec["pattern"], value):
                problems.append(
                    f"{source}: {name!r} is {value!r}, " f"expected /{spec['pattern']}/"
                )
            if "enum" in spec and value not in spec["enum"]:
                problems.append(
                    f"{source}: {name!r} is {value!r}, "
                    f"one of {', '.join(spec['enum'])}"
                )
            if "minLength" in spec and len(value) < spec["minLength"]:
                problems.append(f"{source}: {name!r} is empty")
    for name in meta:
        if name not in FIELDS:
            problems.append(f"{source}: unknown key {name!r}")
    return problems


def _type_ok(value: Any, types: list[str]) -> bool:
    for name in types:
        if name == "null" and value is None:
            return True
        if name == "string" and isinstance(value, str):
            return True
        if name == "array" and isinstance(value, list):
            return True
    return False


def tracked_files() -> list[str]:
    """Files git knows about, committed or not.

    `git ls-files` alone would fail a brand-new record's own scope before it is
    staged, which turns an ordinary edit into a CI failure.
    """

    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def glob_matches(pattern: str, files: list[str]) -> bool:
    """Does this scope glob match a real file?

    Decision records are excluded from counting unless the glob is about them.
    Otherwise two records sitting in `py/src/jeve/llm/decisions/` would satisfy
    a `py/src/jeve/llm/**` scope by matching each other, and the check that is
    supposed to catch a restructure would pass on an empty package.
    """

    about_decisions = "decisions" in pattern
    for name in files:
        parts = Path(name).parts
        if not about_decisions and "decisions" in parts:
            continue
        if Path(name).full_match(pattern):
            return True
    return False


def record_paths() -> list[Path]:
    """Every record file.

    Records currently live in `decisions/core/` for both cross-cutting and
    area-specific decisions. Once code structure exists, area records should
    move next to their code (e.g., `py/src/jeve/llm/decisions/`).
    """

    found = set(DECISIONS.glob("**/*.md")) | set(ROOT.glob("**/decisions/*.md"))
    return sorted(path for path in found if not _excluded(path))


# Tool directories that legitimately contain a folder called `decisions` —
# `.claude/skills/decisions/SKILL.md` is a skill, not a record.
_SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__"}


def _excluded(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts[:-1]
    return any(part.startswith(".") or part in _SKIP_DIRS for part in parts)


def load_records() -> tuple[list[Record], list[str]]:
    problems: list[str] = []
    records: list[Record] = []
    for path in record_paths():
        if any(part in {".git", "node_modules", ".venv"} for part in path.parts):
            continue
        if path.name in {"INDEX.md", "adr-template.md"}:
            continue
        source = path.relative_to(ROOT).as_posix()
        try:
            meta, body = parse_front_matter(path.read_text(), source)
        except RecordError as error:
            problems.append(str(error))
            continue
        record = Record(path=path, meta=meta, body=body)
        record.problems = validate_meta(meta, source)
        records.append(record)
        problems.extend(record.problems)
    return records, problems


def check_records(records: list[Record]) -> list[str]:
    problems: list[str] = []
    files = tracked_files()
    by_id: dict[str, Record] = {}

    for record in records:
        if record.problems:
            continue
        source = record.rel

        if record.id in by_id:
            problems.append(
                f"{source}: id {record.id} is also used by {by_id[record.id].rel}"
            )
        by_id[record.id] = record

        if not record.path.name.startswith(f"{record.id}-"):
            problems.append(
                f"{source}: filename must start with {record.id}- "
                f"(<PREFIX>-NNNN-kebab-title.md)"
            )

        # CORE lives at decisions/core/; area records live next to their code.
        folder = record.path.parent
        if record.prefix == "CORE":
            if folder != DECISIONS / "core":
                problems.append(f"{source}: CORE records belong in decisions/core/")
        # Area records can live in decisions/core/ temporarily or next to their code
        # Both locations are accepted during migration

        for heading in REQUIRED_HEADINGS:
            if heading not in record.body:
                problems.append(f"{source}: missing section '{heading}'")

        body_lines = len([ln for ln in record.body.splitlines() if ln.strip()])
        if body_lines > MAX_BODY_LINES:
            problems.append(
                f"{source}: {body_lines} non-blank body lines, limit is "
                f"{MAX_BODY_LINES} — a record should fit on one screen"
            )

        for pattern in record.meta["scope"]:
            if not glob_matches(pattern, files):
                problems.append(
                    f"{source}: scope glob {pattern!r} matches no file. "
                    f"Either the code moved or the glob is wrong."
                )

    # Cross-references, once every id is known.
    for record in records:
        if record.problems:
            continue
        source = record.rel
        for key in ("supersedes", "relates-to"):
            for ref in record.meta[key]:
                if ref not in by_id:
                    problems.append(f"{source}: {key} points at unknown id {ref}")
        superseded_by = record.meta["superseded-by"]
        if superseded_by is not None:
            if superseded_by not in by_id:
                problems.append(
                    f"{source}: superseded-by points at unknown id {superseded_by}"
                )
            elif record.id not in by_id[superseded_by].meta["supersedes"]:
                problems.append(
                    f"{source}: says it is superseded by {superseded_by}, but "
                    f"{superseded_by} does not list it in supersedes"
                )
            if record.meta["status"] != "superseded":
                problems.append(
                    f"{source}: has superseded-by but status is "
                    f"{record.meta['status']!r}, expected 'superseded'"
                )
        for ref in record.meta["supersedes"]:
            if ref in by_id and by_id[ref].meta["superseded-by"] != record.id:
                problems.append(
                    f"{source}: supersedes {ref}, but {ref} does not point back"
                )

    # Numbering is contiguous per prefix, so a gap means a lost record.
    numbers: dict[str, list[int]] = {}
    for record in records:
        if not record.problems:
            numbers.setdefault(record.prefix, []).append(int(record.id.split("-")[1]))
    for prefix, values in numbers.items():
        expected = list(range(1, len(values) + 1))
        if sorted(values) != expected:
            problems.append(
                f"{prefix}: ids are {sorted(values)}, expected {expected} — "
                f"numbering must be contiguous from 0001"
            )

    return problems


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


def render_index(records: list[Record]) -> str:
    rows = [
        "<!-- GENERATED by scripts/gen-decisions.py. Do not edit. -->",
        "",
        "# Decision index",
        "",
        "One row per decision record. Read this first, then open only the",
        "records whose scope covers what you are about to change.",
        "",
        "| ID | Status | Scope | Title | Summary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in sorted(records, key=lambda r: r.id):
        scope = "<br>".join(f"`{glob}`" for glob in record.meta["scope"]) or "—"
        link = f"[{record.id}]({_relative_link(record)})"
        title = str(record.meta["title"]).replace("|", "\\|")
        summary = record.summary.replace("|", "\\|")
        rows.append(
            f"| {link} | {record.meta['status']} | {scope} | {title} | {summary} |"
        )
    rows.append("")
    return "\n".join(rows)


def _relative_link(record: Record) -> str:
    import os.path

    return os.path.relpath(record.path, DECISIONS).replace("\\", "/")


def render_jsonl(records: list[Record]) -> str:
    lines = []
    for record in sorted(records, key=lambda r: r.id):
        payload = dict(record.meta)
        payload["path"] = record.rel
        payload["summary"] = record.summary
        lines.append(json.dumps(payload, sort_keys=True))
    return "\n".join(lines) + ("\n" if lines else "")


def render_agents_md_section(record: Record) -> str:
    """Render a decision record as an AGENTS.md section.

    Format is agent-agnostic markdown without tool-specific frontmatter.
    """

    tags = ", ".join(record.meta["tags"])
    scope = (
        ", ".join(f"`{glob}`" for glob in record.meta["scope"])
        if record.meta["scope"]
        else "None"
    )
    return (
        f"### {record.id}: {record.meta['title']}\n\n"
        f"**Status**: {record.meta['status']} ({record.meta['date']})  \n"
        f"**Scope**: {scope}  \n"
        f"**Tags**: {tags}\n\n"
        f"{record.summary}\n\n"
        f"This decision is immutable. To change it, write a new record and set "
        f"`superseded-by` on this one — do not edit its substance.\n\n"
        f"---\n\n"
    )


def agents_md_targets(records: list[Record]) -> dict[Path, str]:
    """Generate decision records section for AGENTS.md.

    Only accepted records with a real scope are included.
    A superseded or proposed decision that still had a section would keep
    pulling agents toward a choice that is no longer in force.
    """

    targets: dict[Path, str] = {}
    sections = []
    for record in sorted(records, key=lambda r: r.id):
        if record.meta["status"] != "accepted" or not record.meta["scope"]:
            continue
        sections.append(render_agents_md_section(record))

    if sections:
        decision_section = (
            "<!-- GENERATED by scripts/gen-decisions.py. Do not edit this section. -->\n\n"
            "## Decision Records\n\n"
            "Architecture decisions are recorded as immutable MADR 4.0 records. "
            "This section is auto-generated from the canonical records in `decisions/`. "
            "Consult `decisions/INDEX.md` for the full index and links to detailed records.\n\n"
        ) + "".join(sections)
        targets[AGENTS_MD] = decision_section

    return targets


def generate(records: list[Record], *, write: bool) -> list[str]:
    """Returns the paths whose content would change."""

    wanted: dict[Path, str] = {
        INDEX_MD: render_index(records),
        INDEX_JSONL: render_jsonl(records),
        SCHEMA_JSON: json.dumps(json_schema(), indent=2, sort_keys=True) + "\n",
    }
    # Cursor rules are deprecated in favor of agent-agnostic AGENTS.md
    # wanted.update(rule_targets(records))
    wanted.update(agents_md_targets(records))

    changed = []

    for path, content in sorted(wanted.items()):
        if path == AGENTS_MD:
            # Special handling for AGENTS.md: merge decision section with existing content
            current = path.read_text() if path.exists() else ""
            if (
                "<!-- GENERATED by scripts/gen-decisions.py. Do not edit this section. -->"
                in current
            ):
                # Replace existing decision section
                lines = current.split("\n")
                gen_start = lines.index(
                    "<!-- GENERATED by scripts/gen-decisions.py. Do not edit this section. -->"
                )
                # Find the end of the generated section (look for next major section or end of file)
                gen_end = len(lines)
                for i in range(gen_start + 1, len(lines)):
                    if lines[i].startswith("# ") and i > gen_start + 5:
                        gen_end = i
                        break
                merged = (
                    "\n".join(lines[:gen_start])
                    + "\n"
                    + content
                    + "\n".join(lines[gen_end:])
                )
                if merged != current:
                    changed.append(path.relative_to(ROOT).as_posix())
                if write:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(merged)
            else:
                # Append decision section to end of file
                merged = current.rstrip() + "\n\n" + content if current else content
                if merged != current:
                    changed.append(path.relative_to(ROOT).as_posix())
                if write:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(merged)
        else:
            current = path.read_text() if path.exists() else None
            if current != content:
                changed.append(path.relative_to(ROOT).as_posix())
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
    return sorted(set(changed))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def next_id(records: list[Record], prefix: str) -> str:
    used = [
        int(r.id.split("-")[1])
        for r in records
        if r.prefix == prefix and ID_PATTERN.match(r.id)
    ]
    return f"{prefix}-{max(used, default=0) + 1:04d}"


def scaffold(records: list[Record], prefix: str, title: str) -> Path:
    if not TEMPLATE.exists():
        raise SystemExit(f"template missing: {TEMPLATE}")
    from datetime import date

    new_id = next_id(records, prefix)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    # CORE records go in decisions/core/, others go next to their code
    # For now, we put everything in decisions/core/ until the code structure exists
    folder = DECISIONS / "core"
    path = folder / f"{new_id}-{slug}.md"
    if path.exists():
        raise SystemExit(f"already exists: {path}")
    text = TEMPLATE.read_text()
    meta, body = parse_front_matter(text, str(TEMPLATE))
    meta.update({"id": new_id, "title": title, "date": date.today().isoformat()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_front_matter(meta) + body)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate, write nothing")
    parser.add_argument("--next", metavar="PREFIX", help="print the next free id")
    parser.add_argument("--new", nargs=2, metavar=("PREFIX", "TITLE"))
    args = parser.parse_args()

    records, problems = load_records()

    if args.next:
        print(next_id(records, args.next.upper()))
        return 0

    if args.new:
        if problems:
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
        print(scaffold(records, args.new[0].upper(), args.new[1]))
        return 0

    problems += check_records(records)
    if problems:
        print(f"{len(problems)} problem(s) in {len(records)} record(s):\n")
        for problem in problems:
            print(f"  {problem}")
        return 1

    changed = generate(records, write=not args.check)
    if args.check:
        if changed:
            print("generated artifacts are stale; run scripts/gen-decisions.py:\n")
            for path in changed:
                print(f"  {path}")
            return 1
        print(f"ok — {len(records)} records, artifacts up to date")
        return 0

    print(f"ok — {len(records)} records")
    if changed:
        for path in changed:
            print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
