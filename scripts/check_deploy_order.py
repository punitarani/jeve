#!/usr/bin/env python3
"""The web app must deploy after the backend, never before it (OPS-0003).

A browser validates `/state` against the zod schema compiled into the static
export at build time (WEB-0005), and contracts flow backend to web (CORE-0011):
a new required field exists in the API first and the page learns to expect it
second. Ship the page first and it demands a field the running API does not
send yet. That is not hypothetical — `health.tracing` did exactly this, and the
window was up to nineteen minutes wide.

On a pull request both deploy jobs skip, so CI never *observes* the ordering.
This is the only thing that can prove it before a push to main reaches
production, which is why it is a confirmation rather than a comment.

Reachability, not a literal `needs` list: a rearrangement that still orders the
two correctly keeps passing. Stdlib only, like `check_fly_config.py` — the
`decisions` job has no third-party Python.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# `deploy-web` must run after every one of these.
REQUIRED_AFTER = ("deploy-backend", "python")

JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
NEEDS = re.compile(r"^    needs:\s*(.+?)\s*$")


def job_graph(text: str) -> dict[str, list[str]]:
    """Every job under `jobs:`, mapped to the jobs it names in `needs:`.

    The workflow is machine-written with two-space indentation, so a job is a
    four-space-indented key and its `needs:` is six spaces in. Anything else is
    not a job we can reason about, and a job with no `needs:` maps to [].
    """

    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == "jobs:")
    except StopIteration:
        raise SystemExit(f"{WORKFLOW}: no `jobs:` block — cannot check ordering")

    graph: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith(" "):
            break  # a new top-level key: out of `jobs:`
        if match := JOB.match(line):
            current = match.group(1)
            graph.setdefault(current, [])
            continue
        if current and (match := NEEDS.match(line)):
            raw = match.group(1).strip().strip("[]")
            graph[current] = [n.strip().strip("\"'") for n in raw.split(",") if n.strip()]
    return graph


def runs_after(graph: dict[str, list[str]], job: str, earlier: str) -> bool:
    """Is `earlier` reachable from `job` by following `needs`?"""

    seen: set[str] = set()
    stack = list(graph.get(job, []))
    while stack:
        name = stack.pop()
        if name == earlier:
            return True
        if name in seen:
            continue
        seen.add(name)
        stack.extend(graph.get(name, []))
    return False


def main(argv: list[str] | None = None) -> int:
    path = Path(argv[0]) if argv else WORKFLOW
    graph = job_graph(path.read_text())

    missing = [name for name in ("deploy-web", *REQUIRED_AFTER) if name not in graph]
    if missing:
        # Renamed or removed rather than reordered. Either way this check is no
        # longer checking what it claims to, so it fails instead of passing.
        print(f"::error::{path}: no such job(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    broken = [name for name in REQUIRED_AFTER if not runs_after(graph, "deploy-web", name)]
    if broken:
        for name in broken:
            print(
                f"::error::deploy-web does not run after {name} (OPS-0003). "
                f"Its needs are {graph['deploy-web']}.",
                file=sys.stderr,
            )
        return 1

    print(f"deploy-web runs after {' and '.join(REQUIRED_AFTER)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
