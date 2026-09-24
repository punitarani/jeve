"""`make ontology-gaps`: where `other` was reached for, and, with `--propose`,
what a model suggests adding (tier 2; `jeve.gen.ontology`).

Counting is free. Proposals ask the first generative model that answers, in
LLM-0006's order, about the questions whose gaps pass 5% of their decisions;
each reply is kept in `model_calls`, so asking again costs nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from psycopg import Connection
from psycopg.rows import DictRow

from jeve import db
from jeve.config import find_repo_root, load_settings
from jeve.decide.recorder import insert_call
from jeve.errors import JeveError
from jeve.gen import ontology
from jeve.llm import GENERATIVE_PREFERENCE, Gateway

REPORT = find_repo_root() / "ops" / "ontology-gaps.md"
MOST = 5


def _cached(
    conn: Connection[DictRow], gap: ontology.Gap, shown: list[object]
) -> dict[str, str] | None:
    keys = [
        ontology.request_key(ontology.proposal_request(gap, shown, model))
        for model in GENERATIVE_PREFERENCE
    ]
    rows = conn.execute(
        "SELECT hash, response FROM model_calls WHERE hash = ANY(%s)", (keys,)
    ).fetchall()
    by_hash = {str(row["hash"]): dict(row["response"]) for row in rows}
    for key in keys:
        if key in by_hash:
            proposal = ontology.parse_proposal(str(by_hash[key].get("text", "")))
            if proposal is not None:
                return proposal
    return None


async def _propose(
    conn: Connection[DictRow], gap: ontology.Gap, shown: list[object]
) -> dict[str, str] | None:
    async with Gateway(settings=load_settings()) as gateway:
        for model in gateway.generative_models:
            request = ontology.proposal_request(gap, shown, model)
            try:
                reply = await gateway.complete(request, purpose="explore")
            except JeveError as error:
                print(f"  {model}: {type(error).__name__}", file=sys.stderr)
                continue
            body = request.model_dump(mode="json")
            insert_call(
                conn,
                {
                    "hash": ontology.request_key(request),
                    "kind": ontology.KIND,
                    "model": model,
                    "provider": reply.provider,
                    "request": body,
                    "wire": json.dumps(body, ensure_ascii=False),
                    "response": {"text": reply.text, "model": reply.model},
                    "input_tokens": reply.usage.input_tokens,
                    "output_tokens": reply.usage.output_tokens,
                    "cost_usd": reply.usage.cost_usd,
                    "cost_estimated": reply.usage.cost_is_estimated,
                    "latency_s": reply.latency_s,
                },
            )
            proposal = ontology.parse_proposal(reply.text)
            if proposal is not None:
                return proposal
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make ontology-gaps", description=__doc__)
    parser.add_argument("--propose", action="store_true", help="ask a model (spends)")
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    with db.connect(autocommit=True) as conn:
        found = ontology.gaps(conn)
        proposals: dict[tuple[str, str], dict[str, str]] = {}
        for gap in [g for g in found if g.too_small][:MOST]:
            shown = ontology.examples(conn, gap)
            proposal = _cached(conn, gap, shown)
            if proposal is None and args.propose:
                proposal = asyncio.run(_propose(conn, gap, shown))
            if proposal is not None:
                proposals[(gap.question_set, gap.ask)] = proposal
        args.out.write_text(ontology.render(found, proposals))
    print(f"wrote {args.out}: {sum(g.too_small for g in found)} question(s) too small")
    return 0


if __name__ == "__main__":
    sys.exit(main())
