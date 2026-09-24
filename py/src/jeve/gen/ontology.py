"""Ontology gaps: where the offered options did not fit, and what a person might
add (tier 2, DECIDE-0002; design/005).

Every choice the world asks carries `other`. Mass on it is the project's own
research measurement: how often a typed decision could not say what the person
would do. A decision whose `other` mass is at least 0.35 is a **gap**; a
question whose gaps pass 5% of its decisions has options that are too small,
which is a modelling problem to fix in the question set, not a routing one
(design/005, "reverse if").

The counting is free and is all SQL over `decisions`. Proposals are the one
generative job tier 2 has besides prose: for the worst gaps, a model is shown
the question, its options and situations where `other` was heavy, and asked,
in a strict schema, whether they map onto an existing option or want a new
one. The answer is written to `ops/ontology-gaps.md` for a person to review.
Like all of `jeve.gen`, nothing that computes the world may import this
(CORE-0008), and nothing it writes is read back.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from jeve.core.hashing import content_hash
from jeve.llm.protocol import ChatMessage, ChatRequest

KIND = "ontology"
GAP_MASS = 0.35
TOO_SMALL = 0.05
EXAMPLES = 5
MAX_TOKENS = 1600
VERDICTS = ("map_to_existing", "new_option", "no_change")
FIELDS = ("verdict", "option", "definition", "why")


@dataclass(frozen=True, slots=True)
class Gap:
    question_set: str
    ask: str
    decisions: int
    gaps: int
    mean_other: float

    @property
    def rate(self) -> float:
        return self.gaps / self.decisions if self.decisions else 0.0

    @property
    def too_small(self) -> bool:
        return self.rate > TOO_SMALL


def gaps(conn: Connection[DictRow]) -> list[Gap]:
    """Every question that offers `other`, with how often it was reached for.

    Rules-twin decisions never put mass on `other` except as a deliberate
    draw, so only decisions a model answered are counted.
    """

    rows = conn.execute(
        """
        SELECT d.question_set, q.key AS ask, count(*) AS decisions,
               count(*) FILTER (WHERE (q.value->>'other')::float >= %s) AS gaps,
               avg((q.value->>'other')::float) AS mean_other
        FROM decisions d, jsonb_each(d.distributions) q
        WHERE d.source IN ('jev', 'llm') AND q.value ? 'other'
        GROUP BY 1, 2
        ORDER BY 4 DESC, 1, 2
        """,
        (GAP_MASS,),
    ).fetchall()
    return [
        Gap(
            question_set=str(row["question_set"]),
            ask=str(row["ask"]),
            decisions=int(row["decisions"]),
            gaps=int(row["gaps"]),
            mean_other=float(row["mean_other"] or 0.0),
        )
        for row in rows
    ]


def examples(conn: Connection[DictRow], gap: Gap, limit: int = EXAMPLES) -> list[Any]:
    """The situations behind the heaviest `other` answers: what Jev was shown,
    read from the call cache, distinct, heaviest first."""

    rows = conn.execute(
        """
        SELECT m.request->'state' AS state, m.request->'questions'->%s AS question,
               max((d.distributions->%s->>'other')::float) AS other
        FROM decisions d JOIN model_calls m ON m.hash = d.model_call
        WHERE d.question_set = %s
          AND (d.distributions->%s->>'other')::float >= %s
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT %s
        """,
        (gap.ask, gap.ask, gap.question_set, gap.ask, GAP_MASS, limit),
    ).fetchall()
    return [{"state": row["state"], "question": row["question"]} for row in rows]


SYSTEM = (
    "You review the options a simulation offers its people. One question is "
    "shown with its options, and several situations in which the person "
    "answered 'other': none of the options fitted. Say whether what they "
    "wanted maps onto an existing option, needs a new option, or needs no "
    "change. A new option is one short snake_case name and a one-sentence "
    "definition in the style of the others. Answer in the JSON shape required."
)
SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "option": {"type": "string"},
        "definition": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": list(FIELDS),
    "additionalProperties": False,
}


def proposal_request(gap: Gap, shown: Sequence[Any], model: str) -> ChatRequest:
    return ChatRequest(
        model=model,
        messages=[
            ChatMessage(role="system", content=SYSTEM),
            ChatMessage(
                role="user",
                content=json.dumps(
                    {
                        "question_set": gap.question_set,
                        "question": gap.ask,
                        "situations": list(shown),
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
        max_tokens=MAX_TOKENS,
        seed=0,
        temperature=0.0,
        response_schema=SCHEMA,
    )


def request_key(request: ChatRequest) -> str:
    return content_hash({"kind": KIND, **request.model_dump(mode="json")})


def parse_proposal(text: str) -> dict[str, str] | None:
    """A proposal, or nothing. Never raises on a bad reply: this is for a
    person to read, and an unreadable one is simply not shown."""

    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or raw.get("verdict") not in VERDICTS:
        return None
    return {key: str(raw.get(key, ""))[:400] for key in FIELDS}


def render(
    found: Sequence[Gap], proposals: dict[tuple[str, str], dict[str, str]]
) -> str:
    lines = [
        "# Ontology gaps",
        "",
        f"A gap is a decision that put at least {GAP_MASS:.0%} of its mass on "
        f"`other`. A question whose gaps pass {TOO_SMALL:.0%} of its decisions "
        "has options that are too small (design/005). Model-answered decisions "
        "only. Written by `make ontology-gaps`; proposals are for review and "
        "nothing in the world reads them.",
        "",
    ]
    if not found:
        return "\n".join(
            [*lines, "No model-answered choice has offered `other` yet.", ""]
        )
    lines += [
        "| set | question | decisions | gaps | rate | mean `other` | |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for gap in found:
        flag = "**too small**" if gap.too_small else ""
        lines.append(
            f"| {gap.question_set} | {gap.ask} | {gap.decisions} | {gap.gaps} "
            f"| {gap.rate:.1%} | {gap.mean_other:.3f} | {flag} |"
        )
    if proposals:
        lines += ["", "## Proposals", ""]
        for (kind, ask), proposal in sorted(proposals.items()):
            lines += [
                f"### {kind} · {ask}",
                "",
                f"- **Verdict:** {proposal['verdict']}",
                f"- **Option:** `{proposal['option']}`",
                f"- **Definition:** {proposal['definition']}",
                f"- **Why:** {proposal['why']}",
                "",
            ]
    return "\n".join(lines) + "\n"
