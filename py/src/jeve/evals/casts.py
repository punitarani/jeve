"""One moment, two casts: a judge that can see persona (EVAL-0004).

The pairwise judge compares an episode from one arm with an episode from
another. Persona is a between-person property, so a judge shown one account
at a time never sees a quiet person beside a loud one in the same moment, and
it could not tell a model that kept people distinct from one that flattened
them (docs/ops/llm-integration.md, "what the laboratory learned").

Here, each side of a pair shows one conversation moment twice. The situation
is the same both times; only the person deciding changes, described first as
outspoken and sociable, then as quiet and reserved. Each version shows what
that person did. The words are the ones the deciding model was given, from the
state its question was prepared with. Nothing is generated.

The judge must first catch planted defects on real moments:

* **flattened:** both versions do the same thing;
* **swapped:** each version does what the other should.

The clean side gives the outspoken version the act that fits an outspoken
person in their part: an asker pushes, a bystander chats. The reserved version
breaks off. As for `transcripts`, a judge below `judge.MIN_ACCURACY` on these
is not evidence of anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from jeve.decide.policy import DecisionContext
from jeve.decide.questions import QUESTION_SETS
from jeve.evals import transcripts
from jeve.evals.judge import Pair

KIND = "episode.round"
OUTGOING: dict[str, object] = {"vocality": 0.9, "sociability": 0.9}
RESERVED: dict[str, object] = {"vocality": 0.1, "sociability": 0.1}
CASTS: tuple[tuple[str, dict[str, object]], ...] = (
    ("outgoing", OUTGOING),
    ("reserved", RESERVED),
)
DEFECTS: tuple[str, ...] = ("flattened", "swapped")

SYSTEM = (
    "You audit a computer simulation of a small business district: a software "
    "company, a law firm, an accounting firm and a cafe, and the people who work "
    "there. You will see two accounts, A and B. Each shows one moment in a "
    "conversation twice: the situation is the same both times, but the person "
    "deciding is described differently in each version, and each version says "
    "what that person did. Both accounts were produced from the simulation's "
    "records by the same fixed template, so their wording and style carry no "
    "information: judge only what the person does.\n\n"
    "Decide which account shows more plausible behaviour: in each version, does "
    "what the person did fit the person as described there, and does it fit the "
    "situation they are in? If neither account is more plausible than the "
    "other, answer tie. Reply in the JSON shape required and nothing else."
)

_CLEAN: dict[str, tuple[str, str]] = {
    "asker": ("press", "leave"),
    "bystander": ("small_talk", "leave"),
}
"""The act that fits each cast, for a part where a reader can tell: someone
held up by the matter, and someone it is not about. What the one who could
act ought to do is less plain, so they are not planted."""


def cast(ctx: DecisionContext, traits: Mapping[str, object]) -> DecisionContext:
    return replace(ctx, traits={**ctx.traits, **traits})


def state(ctx: DecisionContext) -> dict[str, object]:
    prepared = QUESTION_SETS[ctx.kind].prepare(ctx)
    assert prepared.state is not None
    return dict(prepared.state)


def _words(value: object) -> str:
    if isinstance(value, Mapping):
        return "; ".join(str(v) for v in value.values()) + "."
    return str(value)


@dataclass(frozen=True, slots=True)
class Version:
    state: dict[str, object]
    """The words the deciding model saw."""
    stake: str
    act: str


def render(versions: Sequence[Version]) -> str:
    lines: list[str] = []
    for n, v in enumerate(versions, start=1):
        s = v.state
        standing = " ".join(
            _words(s[k]) for k in ("so_far", "how_long", "just_now") if k in s
        )
        lines += [
            f"Version {n}:",
            f"Where and when: {_words(s.get('where'))}, {_words(s.get('time'))}.",
            f"The person: {_words(s.get('person'))}. "
            f"{_words(s.get('temperament')).capitalize()}; "
            f"{_words(s.get('speaks_up'))}.",
            f"Also there: {_words(s.get('who_is_here'))}",
            f"What is between them: {_words(s.get('what_this_is_about'))}",
            f"Their part in it: {_words(s.get('their_part_in_it'))}",
            f"How it stands: {standing}",
            f"The mood: {_words(s.get('mood_of_the_room'))} "
            f"{_words(s.get('feeling'))} {_words(s.get('how_they_get_on'))}",
            f"What they did: {transcripts.did(v.stake, v.act)}.",
            "",
        ]
    return "\n".join(lines).rstrip()


def side(ctx: DecisionContext, acts: Mapping[str, str]) -> str:
    """The moment under each cast, with what the person did under it."""

    stake = str(ctx.facts.get("stake", "news"))
    return render(
        [Version(state(cast(ctx, traits)), stake, acts[name]) for name, traits in CASTS]
    )


def planted(
    ctxs: Sequence[tuple[str, DecisionContext]], per_defect: int, rng: Any
) -> list[Pair]:
    """Clean on the right, broken on the left; then identical sides, whose
    only honest verdict is a tie or a split that follows position."""

    usable = [
        (ident, ctx)
        for ident, ctx in ctxs
        if str(ctx.facts.get("role_in_stake", "bystander")) in _CLEAN
    ]
    pairs: list[Pair] = []
    for defect in (*DEFECTS, "identical"):
        pool = list(usable)
        rng.shuffle(pool)
        for ident, ctx in pool[:per_defect]:
            loud, quiet = _CLEAN[str(ctx.facts.get("role_in_stake", "bystander"))]
            clean = {"outgoing": loud, "reserved": quiet}
            if defect == "flattened":
                one = rng.choice((loud, quiet))
                broken = {"outgoing": one, "reserved": one}
            elif defect == "swapped":
                broken = {"outgoing": quiet, "reserved": loud}
            else:
                broken = clean
            pairs.append(
                Pair(
                    f"cast-{defect}:{ident}",
                    side(ctx, broken),
                    side(ctx, clean),
                    defect,
                    SYSTEM,
                )
            )
    return pairs
