"""Effect sizes with their variance, never a single run's difference.

Every contrast is **paired by seed**: arm B against arm A on the same seed is
one observation, because both worlds were drawn from the same keyed randomness
(CORE-0009) and differ only in what the arm changes. The spread of those
differences across seeds is the noise the effect has to stand clear of.

* `summary` — mean, sample standard deviation, n.
* `paired` — mean difference, a percentile bootstrap 95% interval, and d_z
  (mean difference over its standard deviation), the effect size for a paired
  design. The bootstrap is seeded, so a report regenerates byte for byte.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from jeve.core.seed import derive_rng

BOOTSTRAP = 4000
BOOTSTRAP_SEED = 20260924


@dataclass(frozen=True, slots=True)
class Summary:
    mean: float | None
    sd: float | None
    n: int

    def text(self, digits: int = 3) -> str:
        if self.mean is None:
            return "—"
        if self.sd is None:
            return f"{self.mean:.{digits}f}"
        return f"{self.mean:.{digits}f} ± {self.sd:.{digits}f}"


@dataclass(frozen=True, slots=True)
class Paired:
    delta: float | None
    low: float | None
    high: float | None
    d_z: float | None
    n: int

    @property
    def clear(self) -> bool:
        """The interval excludes zero."""

        return (
            self.low is not None
            and self.high is not None
            and (self.low > 0 or self.high < 0)
        )

    def text(self, digits: int = 3) -> str:
        if self.delta is None:
            return "—"
        interval = (
            f" [{self.low:+.{digits}f}, {self.high:+.{digits}f}]"
            if self.low is not None and self.high is not None
            else ""
        )
        effect = f", d_z {self.d_z:+.2f}" if self.d_z is not None else ""
        return f"{self.delta:+.{digits}f}{interval}{effect}"


def summary(values: Sequence[float | None]) -> Summary:
    present = [v for v in values if v is not None and math.isfinite(v)]
    if not present:
        return Summary(None, None, 0)
    sd = statistics.stdev(present) if len(present) > 1 else None
    return Summary(statistics.fmean(present), sd, len(present))


def paired(
    a: Sequence[float | None], b: Sequence[float | None], *, seed: int = BOOTSTRAP_SEED
) -> Paired:
    """B minus A, seed by seed; pairs where either side is absent are dropped."""

    diffs = [
        y - x
        for x, y in zip(a, b, strict=True)
        if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)
    ]
    if not diffs:
        return Paired(None, None, None, None, 0)
    mean = statistics.fmean(diffs)
    if len(diffs) < 2:
        return Paired(mean, None, None, None, 1)
    sd = statistics.stdev(diffs)
    rng = derive_rng(seed, "bootstrap")
    means = sorted(
        statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(BOOTSTRAP)
    )
    low = means[int(0.025 * BOOTSTRAP)]
    high = means[int(0.975 * BOOTSTRAP) - 1]
    d_z = mean / sd if sd > 0 else None
    return Paired(mean, low, high, d_z, len(diffs))


def proportion_interval(wins: float, n: int) -> tuple[float, float] | None:
    """Wilson 95% interval for a rate; ties count half a win each."""

    if n <= 0:
        return None
    z = 1.959964
    p = wins / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)
