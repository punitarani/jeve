"""A blinded pairwise judge, and the planted-defect test it must pass first.

**The judge.** Two accounts of a meeting, rendered by `transcripts.render`
from typed records, side by side as A and B; a model says which describes more
plausible behaviour for real people in those roles, or that they are level.
Every pair is asked **both ways round**: a verdict that follows position rather
than content cancels, and the share of pairs where the two orders disagree is
reported as position bias rather than hidden in the average.

**Who judges.** A different model family from any model under test: Jev is
TypeSafe's and the roles this harness evaluates answer through GLM (LLM-0006),
so the judge is OpenAI's GPT-5.6 Luna. A judge that shares a family with the
arm it scores prefers its own family's outputs (arXiv 2404.13076).

**The test it must pass first** (workbench L14 to L16). Real episodes are paired
with copies of themselves that carry one planted defect; the judge must prefer
the clean copy. Accuracy is reported per defect, both orders counted. Below
`MIN_ACCURACY`, the judge's verdicts on arms are not reported at all — an
instrument that cannot see a planted defect is not evidence that two arms
differ, or that they do not.

**Money.** Verdicts are cached in `model_calls` (kind `judge`) under the
content hash of the request, in the judge's own database, so a re-run of the
same comparison is free. `live=False` counts what a run would ask and prices
it; nothing is sent.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.core.hashing import content_hash
from jeve.core.seed import derive_rng
from jeve.decide.recorder import insert_call
from jeve.llm import ChatMessage, ChatRequest, Gateway

type Verdict = Literal["A", "B", "tie"]

JUDGE = "openai/gpt-5.6-luna"
KIND = "judge"
MAX_TOKENS = 2000
"""Luna reasons before it answers and cannot be told not to reliably; a reply
cut off mid-thought is empty (ChatRequest.reasoning)."""
SEED = 7
MIN_ACCURACY = 0.8
"""Below this share of planted defects caught, the judge is not used."""

SYSTEM = (
    "You audit a computer simulation of a small business district: a software "
    "company, a law firm, an accounting firm and a cafe, and the people who work "
    "there. You will see two accounts, A and B, each describing one short "
    "encounter between some of those people. Both accounts were produced from the "
    "simulation's records by the same fixed template, so their wording and style "
    "carry no information: judge only what happens in them.\n\n"
    "Decide which account describes more plausible behaviour for real people in "
    "these roles, with this matter between them, at this time and place. Consider "
    "whether the people who act are ones who could act on the matter, whether what "
    "happened afterwards follows from what was said, whether the conversation "
    "develops the way real conversations do, whether people behave in keeping "
    "with how they are described, and whether the time and place make sense. "
    "If neither is more plausible than the other, answer tie. Reply in the JSON "
    "shape required and nothing else."
)
SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "more_plausible": {"type": "string", "enum": ["A", "B", "tie"]},
        "least_plausible_detail": {"type": "string"},
    },
    "required": ["more_plausible", "least_plausible_detail"],
    "additionalProperties": False,
}


def request(
    first: str, second: str, model: str = JUDGE, seed: int = SEED
) -> ChatRequest:
    return ChatRequest(
        model=model,
        messages=[
            ChatMessage(role="system", content=SYSTEM),
            ChatMessage(
                role="user",
                content=f"Account A:\n{first}\n\nAccount B:\n{second}\n\n"
                "Which account is more plausible: A, B, or tie? In "
                "least_plausible_detail, name the single least plausible thing in "
                "the account you did not choose, in under twenty words.",
            ),
        ],
        max_tokens=MAX_TOKENS,
        seed=seed,
        temperature=0.0,
        response_schema=SCHEMA,
    )


def request_key(req: ChatRequest) -> str:
    return content_hash({"kind": KIND, **req.model_dump(mode="json")})


def parse(text: str) -> Verdict | None:
    try:
        raw = json.loads(text.strip().removeprefix("```json").removesuffix("```"))
    except json.JSONDecodeError:
        return None
    value = raw.get("more_plausible") if isinstance(raw, dict) else None
    return value if value in ("A", "B", "tie") else None


@dataclass(frozen=True, slots=True)
class Pair:
    """Two accounts to compare. `left` is shown first in the forward order."""

    id: str
    left: str
    right: str
    label: str = ""
    """What the pair is about: a defect's name, or `arm-a vs arm-b`."""


@dataclass(slots=True)
class Scored:
    """A pair's two verdicts, turned into points for the right-hand side."""

    pair: Pair
    forward: Verdict | None
    backward: Verdict | None

    @property
    def right_points(self) -> float | None:
        """1 if both orders prefer `right`, 0 if both prefer `left`, a half
        for a tie or a split; None if either order has no verdict."""

        if self.forward is None or self.backward is None:
            return None
        # Forward shows right as B; backward shows it as A.
        score = {"B": 1.0, "A": 0.0, "tie": 0.5}[self.forward]
        score += {"A": 1.0, "B": 0.0, "tie": 0.5}[self.backward]
        return score / 2

    @property
    def consistent(self) -> bool | None:
        if self.forward is None or self.backward is None:
            return None
        flipped = {"A": "B", "B": "A", "tie": "tie"}[self.backward]
        return self.forward == flipped


@dataclass(slots=True)
class Run:
    scored: list[Scored] = field(default_factory=list)
    asked: int = 0
    missing: int = 0
    failed: int = 0
    cost_usd: float = 0.0


def _requests(pairs: Sequence[Pair], model: str, seed: int) -> dict[str, ChatRequest]:
    out: dict[str, ChatRequest] = {}
    for pair in pairs:
        forward = request(pair.left, pair.right, model, seed)
        backward = request(pair.right, pair.left, model, seed)
        for req in (forward, backward):
            out[request_key(req)] = req
    return out


def _cached(
    conn: Connection[DictRow], keys: Sequence[str]
) -> dict[str, Verdict | None]:
    rows = conn.execute(
        "SELECT hash, response FROM model_calls WHERE hash = ANY(%s)", (list(keys),)
    ).fetchall()
    return {
        str(r["hash"]): parse(str((r["response"] or {}).get("text", ""))) for r in rows
    }


async def _ask(
    conn: Connection[DictRow], missing: dict[str, ChatRequest], run: Run
) -> None:
    async with Gateway() as gateway:
        replies = await asyncio.gather(
            *(gateway.complete(req, purpose="gate") for req in missing.values()),
            return_exceptions=True,
        )
    for (key, req), reply in zip(missing.items(), replies, strict=True):
        if isinstance(reply, BaseException):
            run.failed += 1
            continue
        run.cost_usd += reply.usage.cost_usd
        body = req.model_dump(mode="json")
        insert_call(
            conn,
            {
                "hash": key,
                "kind": KIND,
                "model": reply.model,
                "provider": reply.provider,
                "request": body,
                "wire": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                "response": {"text": reply.text, "model": reply.model},
                "input_tokens": reply.usage.input_tokens,
                "output_tokens": reply.usage.output_tokens,
                "cost_usd": reply.usage.cost_usd,
                "cost_estimated": reply.usage.cost_is_estimated,
                "latency_s": reply.latency_s,
            },
        )


def judge(
    conn: Connection[DictRow],
    pairs: Sequence[Pair],
    *,
    model: str = JUDGE,
    live: bool = False,
    seed: int = SEED,
) -> Run:
    """Score every pair both ways round, from the cache and — if `live` — by
    asking for what the cache lacks. Another `seed` is another request, so a
    retest is never answered from the first run's cache."""

    run = Run()
    requests = _requests(pairs, model, seed)
    run.asked = len(requests)
    verdicts = _cached(conn, list(requests))
    missing = {k: r for k, r in requests.items() if k not in verdicts}
    if missing and live:
        asyncio.run(_ask(conn, missing, run))
        verdicts = _cached(conn, list(requests))
    run.missing = sum(1 for k in requests if k not in verdicts)
    for pair in pairs:
        fwd = request_key(request(pair.left, pair.right, model, seed))
        bwd = request_key(request(pair.right, pair.left, model, seed))
        run.scored.append(Scored(pair, verdicts.get(fwd), verdicts.get(bwd)))
    return run


# -- what the numbers say ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tally:
    label: str
    n: int
    points: float
    consistent: int
    ties: int

    @property
    def rate(self) -> float | None:
        return self.points / self.n if self.n else None


def tally(run: Run) -> list[Tally]:
    """Per label: how much of the time the right-hand side was preferred."""

    groups: dict[str, list[Scored]] = {}
    for s in run.scored:
        groups.setdefault(s.pair.label, []).append(s)
    out: list[Tally] = []
    for label in sorted(groups):
        done = [s for s in groups[label] if s.right_points is not None]
        verdicts = Counter(v for s in done for v in (s.forward, s.backward))
        out.append(
            Tally(
                label,
                len(done),
                sum(s.right_points or 0.0 for s in done),
                sum(1 for s in done if s.consistent),
                verdicts["tie"],
            )
        )
    return out


def defect_pairs(
    records: Sequence[tuple[str, object]],
    defects: Sequence[str],
    per_defect: int,
    seed: int,
) -> list[Pair]:
    """Clean on the right, broken on the left: the judge should prefer right.

    `records` are `(id, transcripts.Record)`; typed loosely here so this module
    does not import the renderer's types into its signature twice.
    """

    from jeve.evals import transcripts

    rng = derive_rng(seed, "defects")
    pairs: list[Pair] = []
    for defect in defects:
        pool = list(records)
        rng.shuffle(pool)
        made = 0
        for ident, record in pool:
            assert isinstance(record, transcripts.Record)
            broken = transcripts.plant(record, defect, rng)
            if broken is None:
                continue
            pairs.append(
                Pair(
                    f"{defect}:{ident}",
                    transcripts.render(broken),
                    transcripts.render(record),
                    defect,
                )
            )
            made += 1
            if made >= per_defect:
                break
    return pairs
