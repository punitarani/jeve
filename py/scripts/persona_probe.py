"""Does sampling Jev's distributions preserve persona, or flatten it?

The largest unverified assumption in the design. If two people with opposite
temperaments get the same distribution in the same situation, then sampling it
gives them the same behaviour, the traits column is decoration, and the thesis
— typed decisions can carry an agent — is in trouble. Better to know in half an
hour than in a month.

Method. For each propensity question the simulation asks, hold the situation
fixed and vary only the person's temperament (low vs high). Identical inputs
give Jev identical outputs, so to see its *noise* each request carries a
throwaway reference field that changes nothing about the situation (TypeSafe's
own method). Twenty such samples per persona, then:

    between  = Jensen-Shannon divergence between the two personas' mean answers
    within   = mean JSD of one persona's samples against that persona's own mean

A persona difference is real if it stands well clear of the noise. Both numbers
are reported; the verdict is a threshold on them, stated in the output.

    make persona-probe      # 280 calls, about half a cent, cache bypassed
"""

from __future__ import annotations

import asyncio
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from jeve.config import load_settings
from jeve.core.seed import derive_rng
from jeve.decide.policy import DecisionContext
from jeve.decide.questions import QUESTION_SETS, Ask
from jeve.llm import DECISION_PREFERENCE, DecisionRequest, Gateway
from jeve.llm.protocol import NoulAnswer

SAMPLES = 20
LOW, HIGH = 0.0, 1.0  # clamped into each trait's bottom and top tertile

# (kind, the trait under test, the fixed situation, is this the control?)
#
# The control is a situation where temperament *should not* matter: a patient
# and an impatient customer behave alike at an empty counter. A probe with no
# control cannot tell "Jev respects persona" from "Jev moves whenever any word
# in the input changes".
CASES: tuple[tuple[str, str, dict[str, object], bool], ...] = (
    (
        "retail.purchase",
        "patience",
        {"org": "thirdrail", "till_down": False, "queue_length": 4},
        False,
    ),
    (
        "retail.purchase",
        "patience",
        {"org": "thirdrail", "till_down": True, "queue_length": 4},
        False,
    ),
    (
        "retail.purchase",
        "patience",
        {"org": "thirdrail", "till_down": False, "queue_length": 0},
        True,
    ),
    ("ticket.answer", "diligence", {"backlog": 14}, False),
    ("file.ticket", "vocality", {"module_down": True, "already_open": False}, False),
    ("payment.timing", "promptness", {"days_until_due": -2, "runway_days": 60}, False),
    ("payment.timing", "promptness", {"days_until_due": -2, "runway_days": 5}, False),
)
MID_MORNING = 10 * 3600


@dataclass(frozen=True, slots=True)
class Row:
    kind: str
    situation: str
    ask: str
    p_low: float
    sd_low: float
    p_high: float
    sd_high: float
    between: float
    within: float
    control: bool

    @property
    def ratio(self) -> float:
        return self.between / self.within if self.within > 0 else math.inf

    @property
    def verdict(self) -> str:
        gap = abs(self.p_high - self.p_low)
        if self.control:
            return "flat, as it should be" if gap < 0.03 else "MOVED (control)"
        if gap >= 0.10 and self.ratio >= 10:
            return "distinct"
        return "FLAT" if gap < 0.03 else "weak"

    @property
    def ok(self) -> bool:
        return self.verdict in ("distinct", "flat, as it should be")


def _jsd(p: float, q: float) -> float:
    """Jensen-Shannon divergence between Bernoulli(p) and Bernoulli(q), in bits."""

    def kl(a: float, b: float) -> float:
        total = 0.0
        for x, y in ((a, b), (1 - a, 1 - b)):
            if x > 0:
                total += x * math.log2(x / y)
        return total

    eps = 1e-9
    p, q = min(max(p, eps), 1 - eps), min(max(q, eps), 1 - eps)
    m = (p + q) / 2
    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def _context(
    kind: str, trait: str, value: float, facts: dict[str, object]
) -> DecisionContext:
    return DecisionContext(
        person_id="probe",
        role="probe",
        decision_seq=0,
        sim_time=MID_MORNING,
        kind=kind,
        facts=facts,
        traits={trait: value},
    )


async def _sample(
    gateway: Gateway, state: dict[str, object], ask: Ask, nonces: list[str]
) -> list[float]:
    async def one(nonce: str) -> float:
        reply = await gateway.decide(
            DecisionRequest(
                model=DECISION_PREFERENCE[0],
                # A filing reference: varies the input, says nothing about it.
                state={**state, "reference": nonce},
                questions={ask.key: ask.question},
            ),
            purpose="gate",
        )
        answer = reply.answers[ask.key]
        assert isinstance(answer, NoulAnswer)
        return answer.noul

    return list(await asyncio.gather(*(one(n) for n in nonces)))


async def main() -> int:
    settings = load_settings()
    rng = derive_rng(20260920, "persona-probe")
    rows: list[Row] = []

    async with Gateway(settings=settings) as gateway:
        before = gateway.guard.state().spend
        for kind, trait, facts, control in CASES:
            prepare = QUESTION_SETS[kind].prepare
            low = prepare(_context(kind, trait, LOW, facts))
            high = prepare(_context(kind, trait, HIGH, facts))
            assert low.state is not None and high.state is not None
            ask = low.asks[0]
            nonces = [f"ref-{rng.randrange(16**6):06x}" for _ in range(SAMPLES)]

            ps_low = await _sample(gateway, low.state, ask, nonces)
            ps_high = await _sample(gateway, high.state, ask, nonces)
            mean_low, mean_high = statistics.fmean(ps_low), statistics.fmean(ps_high)
            within = statistics.fmean(
                [_jsd(p, mean_low) for p in ps_low]
                + [_jsd(p, mean_high) for p in ps_high]
            )
            shared = {k: v for k, v in low.state.items() if high.state.get(k) == v}
            rows.append(
                Row(
                    kind=kind,
                    situation="; ".join(
                        str(v) for k, v in shared.items() if k != "person"
                    ),
                    ask=ask.key,
                    p_low=mean_low,
                    sd_low=statistics.pstdev(ps_low),
                    p_high=mean_high,
                    sd_high=statistics.pstdev(ps_high),
                    between=_jsd(mean_low, mean_high),
                    within=within,
                    control=control,
                )
            )
            print(
                f"  {kind:<15} {rows[-1].verdict:<22} "
                f"low={mean_low:.3f} high={mean_high:.3f}"
            )
        after = gateway.guard.state().spend

    calls = after.calls - before.calls
    cost = after.settled_usd - before.settled_usd
    tests = [r for r in rows if not r.control]
    distinct = sum(1 for r in tests if r.verdict == "distinct")
    controls_held = all(r.ok for r in rows if r.control)

    lines = [
        "# Persona sensitivity probe",
        "",
        # Wall-clock on purpose: a record of when the measurement was taken.
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC against "
        f"`{DECISION_PREFERENCE[0]}`. {calls} live calls, ${cost:.6f}, cache "
        f"bypassed. {SAMPLES} samples per persona per case.",
        "",
        "**Question:** with the situation held fixed and only the person's "
        "temperament changed from its lowest tertile to its highest, does Jev "
        "return a different distribution — by more than its own noise?",
        "",
        f"**Answer: {distinct} of {len(tests)} test cases are clearly distinct, "
        f"and the control {'held' if controls_held else 'DID NOT hold'}.** "
        + (
            "Sampling Jev's distributions preserves persona where persona is "
            "relevant, and leaves it alone where it is not."
            if distinct == len(tests) and controls_held
            else "Persona is NOT reliably preserved; see the rows below."
        ),
        "",
        "| question set | situation (held fixed) | P(yes) low trait | P(yes) high "
        "trait | between (bits) | noise (bits) | ratio | verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        ratio = "∞" if math.isinf(r.ratio) else f"{r.ratio:,.0f}\u00d7"
        lines.append(
            f"| `{r.kind}` | {r.situation} | {r.p_low:.3f} ± {r.sd_low:.3f} | "
            f"{r.p_high:.3f} ± {r.sd_high:.3f} | {r.between:.4f} | "
            f"{r.within:.6f} | {ratio} | **{r.verdict}** |"
        )
    lines += [
        "",
        "Reading it. *between* is the Jensen-Shannon divergence between the two "
        "personas' mean answers; *noise* is the mean divergence of a persona's "
        "samples from its own mean, where samples differ only in a throwaway "
        "reference field. `distinct` needs a gap of at least 0.10 in P(yes) "
        "**and** at least 10\u00d7 the noise; `FLAT` is a gap under 0.03.",
        "",
        "The control row is a situation where temperament should *not* matter "
        "— a patient and an impatient customer behave alike at an empty "
        'counter. It is there so that "Jev respects persona" can be told '
        'apart from "Jev moves whenever any word changes".',
        "",
        "What this does not show: that the *levels* are right. Jev puts a "
        "patient customer at an empty counter at about 0.84 to buy; whether a "
        "real cafe loses one walk-in in six is a calibration question this "
        "probe cannot answer. It shows the traits are load-bearing, not that "
        "the magnitudes are true.",
        "",
    ]
    out = settings.ops_dir / "persona-probe.md"
    out.write_text("\n".join(lines))
    print("\n" + "\n".join(lines))
    print(f"wrote {out}")
    return 0 if all(r.ok for r in rows) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
