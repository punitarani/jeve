#!/usr/bin/env python3
"""Run every decision record's `confirmation` command, once each (OPS-0002).

A `confirmation` that nobody runs is a comment. This is what stops them
becoming aspirational.

Most of them are pytest subsets of a suite the same CI job has already run in
full, so re-executing them was fifteen minutes of running the same tests a
second time. In `--pytest collect` mode those commands are run with
`--collect-only` instead: the suite run is the execution, and collection is
what proves the record still names tests that exist and are selected. A record
pointing at a deleted file, a renamed test or a `-k` that now matches nothing
still fails, because pytest exits non-zero for all three.

Everything that is not a plain pytest invocation — ruff and mypy, tsc, the
Next build, the generator check, the fly config parse — runs verbatim. Those
are the confirmations that actually verify something the suite does not.

Stdlib only, and 3.9-compatible: this runs on whatever `python3` the runner
has, in a job that may not have set up a toolchain yet.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "decisions" / "index.jsonl"

# A confirmation that is nothing but `cd py && uv run pytest <paths and flags>`.
# The character class stops the rewrite the moment a command chains, pipes,
# redirects or substitutes — appending a flag to the end of `a && b` would
# silently pass it to `b`, which is a different command entirely.
PYTEST = re.compile(r"^cd py && uv run pytest(?: [^&|;<>`$()]+)?$")

# OPS-0004: a confirmation never re-runs the suite. `make check` is lint, types
# and the whole suite; in collect mode the job has already run all three, and
# running them again single-process is what took the python job past its
# budget. Stripped only in collect mode — locally `make check` means itself.
MAKE_CHECK = re.compile(r"^make check(?: && )?")


def load(index: Path):
    """Commands in first-seen order, each with the ids that ask for it."""

    seen = {}
    order = []
    with index.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            command = record.get("confirmation")
            if not command:
                continue
            if command not in seen:
                seen[command] = []
                order.append(command)
            seen[command].append(record["id"])
    return [(",".join(seen[command]), command) for command in order]


def rewrite(command: str, pytest_mode: str) -> str:
    """`--collect-only` for plain pytest commands, `make check` dropped from
    the front of any other, and everything else verbatim (OPS-0004).

    No extra `-q`: pytest's own `addopts` already carries one, and a second
    collapses the output to a bare count. One `-q` lists the node ids, which
    is the evidence worth having in the log.
    """

    if pytest_mode == "run":
        return command
    if PYTEST.match(command):
        return command + " --collect-only"
    if MAKE_CHECK.match(command):
        # What is left is whatever the record asks for beyond the suite; a
        # confirmation that is only `make check` has nothing left to prove.
        return MAKE_CHECK.sub("", command) or "true"
    return command


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pytest",
        choices=("run", "collect"),
        default="run",
        help="'collect' verifies pytest confirmations by collection (CI, where "
        "the suite has already run); 'run' executes them (the default, local)",
    )
    parser.add_argument(
        "--list", action="store_true", help="print what would run, execute nothing"
    )
    parser.add_argument("--index", type=Path, default=INDEX)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    commands = [(ids, rewrite(c, args.pytest)) for ids, c in load(args.index)]

    if args.list:
        for ids, command in commands:
            print("{}\t{}".format(ids, command))
        return 0

    grouped = bool(os.environ.get("GITHUB_ACTIONS"))
    failed = []
    for ids, command in commands:
        if grouped:
            print("::group::{}: {}".format(ids, command))
        else:
            print("--- {}: {}".format(ids, command))
        # Flush before spawning: the child writes to the same file descriptor,
        # and an unflushed group header lands after the output it opens.
        sys.stdout.flush()
        if subprocess.call(["bash", "-c", command], cwd=str(args.root)) != 0:
            failed.append((ids, command))
        if grouped:
            print("::endgroup::")
        sys.stdout.flush()

    for ids, command in failed:
        print("::error::{} confirmation failed: {}".format(ids, command))
    print(
        "{} of {} confirmations passed".format(
            len(commands) - len(failed), len(commands)
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
