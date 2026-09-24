"""`make evals`: run arms over seeds, measure them, judge them, report.

    uv run python scripts/evals.py run --arm jev --seed 20260920 --days 7
    uv run python scripts/evals.py measure --arms rules,jev --seeds dev
    uv run python scripts/evals.py report  --arms rules,jev,jev-tier1

`run` spends money for a Jev arm (hit-or-call against every cassette already
recorded); `measure` and `report` never do. The judge has its own subcommands
(`judge-validate`, `judge`) because it is the one part that calls a model on
purpose, and it says what it will cost before it does.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import psycopg
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from jeve import db
from jeve.config import find_repo_root
from jeve.core.seed import derive_rng
from jeve.evals import judge, report, runner, transcripts
from jeve.evals.arms import DEV_SEEDS, HELD_OUT_SEEDS

JUDGE_DATABASE = "jeve_evals_judge"
"""Where verdicts are cached and the judge's spend is metered: one ledger for
every judging call this harness makes, whatever worlds it reads."""


def _seeds(text: str) -> list[int]:
    if text == "dev":
        return list(DEV_SEEDS)
    if text == "held-out":
        return list(HELD_OUT_SEEDS)
    if text == "all":
        return [*DEV_SEEDS, *HELD_OUT_SEEDS]
    return [int(s) for s in text.split(",") if s.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make evals", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one arm on one seed")
    run.add_argument("--arm", required=True)
    run.add_argument("--seed", type=int, required=True)
    run.add_argument("--days", type=int, default=7)
    run.add_argument("--calls", choices=("record", "replay"), default="record")

    measure = sub.add_parser("measure", help="measure worlds that have run")
    measure.add_argument("--arms", required=True)
    measure.add_argument("--seeds", default="dev")

    validate = sub.add_parser(
        "judge-validate", help="can the judge see planted defects?"
    )
    validate.add_argument("--worlds", required=True, help="arm:seed,arm:seed")
    validate.add_argument("--per-defect", type=int, default=12)
    validate.add_argument("--live", action="store_true")
    validate.add_argument(
        "--retest", action="store_true", help="judge again under another seed"
    )

    versus = sub.add_parser("judge", help="arm against arm, episode against episode")
    versus.add_argument("--a", required=True)
    versus.add_argument("--b", required=True)
    versus.add_argument("--seeds", default="dev")
    versus.add_argument("--per-seed", type=int, default=12)
    versus.add_argument("--live", action="store_true")

    sweep = sub.add_parser("sweep", help="run, measure and report arms x seeds")
    sweep.add_argument("--arms", required=True)
    sweep.add_argument("--seeds", default="dev")
    sweep.add_argument("--days", type=int, default=7)
    sweep.add_argument("--calls", choices=("record", "replay"), default="record")
    sweep.add_argument("--parallel", type=int, default=6)

    rep = sub.add_parser("report", help="render ops/evals.md")
    rep.add_argument("--arms", required=True)
    rep.add_argument("--out", default=str(find_repo_root() / "ops" / "evals.md"))

    args = parser.parse_args(argv)
    if args.command == "sweep":
        return _sweep(args)
    if args.command == "report":
        report.write(args.arms.split(","), Path(args.out))
        print(f"wrote {args.out}")
        return 0
    if args.command == "judge-validate":
        return _validate(args)
    if args.command == "judge":
        return _versus(args)
    if args.command == "run":
        return runner.run(runner.arm(args.arm), args.seed, args.days, calls=args.calls)
    if args.command == "measure":
        for name in args.arms.split(","):
            for seed in _seeds(args.seeds):
                m = runner.measure_world(runner.arm(name), seed)
                print(f"{name} {seed}: {len(m.values)} measures, digest {m.digest}")
        return 0
    return 2


def _sweep(args: argparse.Namespace) -> int:
    """Every (arm, seed) as its own process — each world sets its own
    `JEVE_DATABASE_URL`, so they cannot share one — then measure and report."""

    arms = args.arms.split(",")
    jobs = [(arm, seed) for arm in arms for seed in _seeds(args.seeds)]
    script = Path(__file__).resolve().parents[3] / "scripts" / "evals.py"
    running: list[tuple[str, int, subprocess.Popen[bytes]]] = []
    failed: list[str] = []
    while jobs or running:
        while jobs and len(running) < args.parallel:
            arm, seed = jobs.pop(0)
            command = [sys.executable, str(script), "run", "--arm", arm]
            command += ["--seed", str(seed), "--days", str(args.days)]
            command += ["--calls", args.calls]
            running.append((arm, seed, subprocess.Popen(command)))
        arm, seed, proc = running.pop(0)
        if proc.wait() != 0:
            failed.append(f"{arm}:{seed}")
    for arm in arms:
        for seed in _seeds(args.seeds):
            if f"{arm}:{seed}" not in failed:
                runner.measure_world(runner.arm(arm), seed)
    out = find_repo_root() / "ops" / "evals.md"
    report.write(arms, out)
    print(f"wrote {out}" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


# -- the judge ---------------------------------------------------------------


def _judge_conn() -> Connection[DictRow]:
    dsn = runner.ensure_database(JUDGE_DATABASE)
    # The gateway's ledger opens its own connection from the environment: the
    # judge's spend is metered in the judge's database, beside its verdicts.
    os.environ["JEVE_DATABASE_URL"] = dsn
    conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
    db.migrate(conn)
    return conn


def _records(arm: str, seed: int) -> list[transcripts.Record]:
    """Every closed episode of a world, except any in which a round was
    answered by the judge's own family: a judge must never score its own
    family's decisions (arXiv 2404.13076). Tier 1 falls back through
    LLM-0006's order, which includes the judge's model, so this happens."""

    dsn = runner.dsn_for(runner.database(arm, seed))
    family = judge.JUDGE.split("/")[0] + "/%"
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        ids = [
            int(r["id"])
            for r in conn.execute(
                "SELECT e.id FROM episodes e WHERE e.closed_sim IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM escalations x "
                "  JOIN decisions d ON d.id = x.decision_id "
                "  JOIN episode_participants p ON p.person_id = d.person_id "
                "  WHERE p.episode_id = e.id AND d.question_set = 'episode.round' "
                "  AND d.sim_time = e.opened_sim AND x.model LIKE %s) "
                "ORDER BY e.id",
                (family,),
            ).fetchall()
        ]
        found = [transcripts.load(conn, i) for i in ids]
    return [r for r in found if r is not None and r.rounds]


def _row(t: judge.Tally) -> dict[str, object]:
    return {
        "label": t.label,
        "n": t.n,
        "points": t.points,
        "consistent": t.consistent,
        "ties": t.ties,
    }


def _write(name: str, payload: dict[str, object]) -> None:
    report.JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    (report.JUDGE_DIR / f"{name}.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n"
    )


def _say(run: judge.Run, tallies: list[judge.Tally]) -> None:
    print(
        json.dumps(
            {
                "asked": run.asked,
                "missing": run.missing,
                "failed": run.failed,
                "cost_usd": round(run.cost_usd, 5),
                "tallies": [_row(t) for t in tallies],
            },
            indent=1,
        )
    )
    if run.missing:
        print(f"{run.missing} verdict(s) not yet asked; rerun with --live")


def _validate(args: argparse.Namespace) -> int:
    pool: list[tuple[str, object]] = []
    for spec in args.worlds.split(","):
        arm, _, seed = spec.partition(":")
        pool += [(f"{arm}:{seed}:{r.episode_id}", r) for r in _records(arm, int(seed))]
    pairs = judge.defect_pairs(pool, transcripts.DEFECTS, args.per_defect, seed=11)
    # Identical accounts: the only honest answer is a tie, or a split that
    # follows position. Whatever the judge does here is its position bias.
    rng = derive_rng(13, "identical")
    for ident, record in rng.sample(pool, min(args.per_defect, len(pool))):
        assert isinstance(record, transcripts.Record)
        text = transcripts.render(record)
        pairs.append(judge.Pair(f"identical:{ident}", text, text, "identical"))
    conn = _judge_conn()
    run = judge.judge(conn, pairs, live=args.live)
    tallies = judge.tally(run)
    _say(run, tallies)
    if run.missing:
        return 0
    retest = ""
    if args.retest:
        # Test-retest with the cache out of the way (the minimum validation
        # protocol of arXiv 2606.19544): the same pairs, another sampling seed.
        again = judge.judge(conn, pairs, live=args.live, seed=judge.SEED + 1)
        same = [
            (a.forward, a.backward) == (b.forward, b.backward)
            for a, b in zip(run.scored, again.scored, strict=True)
            if b.forward is not None and b.backward is not None
        ]
        run.cost_usd += again.cost_usd
        if same:
            retest = (
                f" Judged again under another seed, {sum(same)} of {len(same)} "
                f"pairs got the same two verdicts ({sum(same) / len(same):.2f})."
            )
    caught = [t for t in tallies if t.label != "identical"]
    n = sum(t.n for t in caught)
    accuracy = sum(t.points for t in caught) / n if n else 0.0
    _write(
        "0-validation",
        {
            "title": f"Validation: planted defects ({judge.JUDGE})",
            "note": "Each real episode against a copy of itself with one defect "
            "planted in its typed record; *right preferred* is how often the judge "
            f"chose the clean copy, both orders counted. Overall {accuracy:.2f} "
            f"on {n} pairs; the judge is used on arms only at "
            f"{judge.MIN_ACCURACY:.2f} or above. *identical* pairs show the "
            "same account twice: anything but 0.50 is position bias." + retest,
            "tallies": [_row(t) for t in tallies],
            "accuracy": accuracy,
            "footer": f"{run.asked} verdicts; ${run.cost_usd:.4f} spent on this run "
            "(zero when every verdict came from the cache).",
        },
    )
    return 0


def _versus(args: argparse.Namespace) -> int:
    validation = report.JUDGE_DIR / "0-validation.json"
    if not validation.exists():
        raise SystemExit("validate the judge first: judge-validate")
    accuracy = float(json.loads(validation.read_text()).get("accuracy") or 0.0)
    if accuracy < judge.MIN_ACCURACY:
        raise SystemExit(
            f"the judge caught {accuracy:.2f} of planted defects, under "
            f"{judge.MIN_ACCURACY}; its verdicts on arms would not be evidence"
        )
    pairs: list[judge.Pair] = []
    for seed in _seeds(args.seeds):
        by_stake: dict[str, tuple[list[transcripts.Record], ...]] = defaultdict(
            lambda: ([], [])
        )
        for side, arm in ((0, args.a), (1, args.b)):
            for r in _records(arm, seed):
                by_stake[r.stake][side].append(r)
        rng = derive_rng(seed, "pairs", args.a, args.b)
        per_stake = max(1, args.per_seed // max(1, len(by_stake)))
        for stake in sorted(by_stake):
            a, b = by_stake[stake]
            rng.shuffle(a)
            rng.shuffle(b)
            for x, y in list(zip(a, b, strict=False))[:per_stake]:
                pairs.append(
                    judge.Pair(
                        f"{seed}:{x.episode_id}:{y.episode_id}",
                        transcripts.render(x),
                        transcripts.render(y),
                        f"{args.b} over {args.a} ({stake})",
                    )
                )
    run = judge.judge(_judge_conn(), pairs, live=args.live)
    tallies = judge.tally(run)
    _say(run, tallies)
    if run.missing:
        return 0
    rows = [_row(t) for t in tallies]
    rows.append(
        _row(
            judge.Tally(
                f"{args.b} over {args.a} (all)",
                sum(t.n for t in tallies),
                sum(t.points for t in tallies),
                sum(t.consistent for t in tallies),
                sum(t.ties for t in tallies),
            )
        )
    )
    _write(
        f"{args.a}-vs-{args.b}-{args.seeds}",
        {
            "title": f"`{args.b}` against `{args.a}`, {args.seeds} seeds "
            f"({judge.JUDGE})",
            "note": "Episodes from the two arms, matched by what was at stake and "
            "by seed, shown both ways round. *Right preferred* is how often the "
            f"judge preferred `{args.b}`'s episode; 0.50 is no difference.",
            "tallies": rows,
            "footer": f"{run.asked} verdicts; ${run.cost_usd:.4f} spent on this run.",
        },
    )
    return 0
