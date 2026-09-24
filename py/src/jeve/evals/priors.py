"""Stylized facts, each with the real-world band it is judged against and
where that band comes from.

A band is PASS, FAIL or ABSENT (workbench's fidelity bands): ABSENT when the
world cannot answer — no late bills to average, or a horizon too short for a
monthly rate to be anything but zero — and ABSENT is reported, never counted
as a pass. A band that everything passes is not a check (workbench L16), so
each one here was set from its source before any jeve world was measured
against it, and the report shows the value beside the band, not only the
verdict.

The sources are practitioner surveys and platform data, not experiments, and
jeve is four firms on one street: these are a plausibility envelope (02 §3.6),
the lowest rung of validation, and are read as such. `docs/research/04` has the
full citations and what each figure does and does not measure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type Verdict = Literal["PASS", "FAIL", "ABSENT"]


@dataclass(frozen=True, slots=True)
class Prior:
    measure: str
    low: float
    high: float
    unit: str
    source: str
    note: str
    min_days: int = 0
    """Below this horizon the measure cannot be told from zero: ABSENT."""

    def verdict(self, value: float | None, days: int) -> Verdict:
        if value is None or days < self.min_days:
            return "ABSENT"
        return "PASS" if self.low <= value <= self.high else "FAIL"


PRIORS: tuple[Prior, ...] = (
    Prior(
        "invoice_late_share",
        0.30,
        0.60,
        "share of bills due",
        "Atradius Payment Practices Barometer, US 2025: 43% of B2B invoice value "
        "overdue, 52% paid on time",
        "By value in the survey, by count here. The band is wide on purpose.",
    ),
    Prior(
        "days_late_mean",
        4.5,
        20.0,
        "days, among bills paid late",
        "Xero Small Business Insights, Dec quarter 2025: 7.8 days late (US), "
        "4.5-9.7 across five countries; Atradius US: overdue B2B invoices "
        "collected about 20 days past due",
        "The low end is Xero's lowest country, the high end Atradius's collection lag.",
    ),
    Prior(
        "cafe_peak_hour",
        8.0,
        10.0,
        "hour of day with most sales",
        "Square POS data, 2018: busiest hours 8-10am (US), 10-11am (UK)",
        "Real coffee shops peak in the morning; the band takes the UK hour too.",
    ),
    Prior(
        "ticket_close_hours_median",
        0.5,
        72.0,
        "calendar hours, open to closed",
        "Freshworks Customer Service Benchmark 2024-25: median account resolves "
        "in 8h17m of business hours; tiers from 32 minutes to 36 hours",
        "Business hours in the source, calendar hours here, so the top is widened "
        "by the nights and a weekend.",
    ),
    Prior(
        "subscription_churn_monthly",
        0.005,
        0.061,
        "share of subscribers a month",
        "ChartMogul 2022: median monthly logo churn 2.2% (ARPA > $500) to 6.1% "
        "(ARPA < $25); SaaS Capital 2025: ~90% gross revenue retention a year "
        "for small contracts (~0.9% a month)",
        "Needs a month to say anything; a week of zero cancellations is not a pass.",
        min_days=28,
    ),
    Prior(
        "staff_turnover_monthly",
        0.0,
        0.035,
        "share of staff a month",
        "BLS JOLTS, July 2026: monthly quits 1.2% (financial) to 3.5% "
        "(accommodation and food)",
        "Twenty-four staff: one departure in a month is 4%. Needs a month.",
        min_days=28,
    ),
)
"""No band for the share of tickets escalated to engineering: the survey
found no primary source (docs/research/04 §F). It is reported, not judged."""

BY_MEASURE: dict[str, Prior] = {p.measure: p for p in PRIORS}
