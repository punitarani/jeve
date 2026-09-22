"""Sim time (CORE-0003).

An integer count of sim-seconds from a seeded epoch. Sim time 0 is 00:00 on a
Monday. Nothing here reads the wall clock — ruff's banned-api rule enforces
that outside `jeve.llm`.
"""

from __future__ import annotations

from dataclasses import dataclass

from jeve.core.orgs import ORGS, Hours

SECOND = 1
MINUTE = 60
HOUR = 3600
DAY = 86400

TICK = 15 * MINUTE
"""Scheduler quantum. Not how often an agent thinks — that is a decision point."""

WORK_START = 9 * HOUR
WORK_END = 17 * HOUR
"""Office hours: when the flows that need the offices run (WORLD-0005)."""

# The district's day is the union of every firm's hours (CORE-0012): the cafe
# and the gym open before the offices and trade on Saturday, so "anything
# open" is wider than "the offices are open" and comes from the roster, not
# from a second list of who opens when.
DISTRICT_OPEN = min(org.hours.open for org in ORGS) * HOUR
DISTRICT_CLOSE = max(org.hours.close for org in ORGS) * HOUR
SATURDAY_OPEN = (
    min((org.hours.open for org in ORGS if org.hours.saturday), default=24) * HOUR
)
SATURDAY_CLOSE = (
    max((org.hours.close for org in ORGS if org.hours.saturday), default=0) * HOUR
)

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True, slots=True)
class SimTime:
    """A moment, with the calendar questions the rules actually ask."""

    seconds: int

    @property
    def day(self) -> int:
        return self.seconds // DAY

    @property
    def weekday(self) -> int:
        """0 = Monday."""

        return self.day % 7

    @property
    def time_of_day(self) -> int:
        return self.seconds % DAY

    @property
    def is_weekend(self) -> bool:
        return self.weekday >= 5

    @property
    def is_workday(self) -> bool:
        return not self.is_weekend

    @property
    def in_office_hours(self) -> bool:
        return self.is_workday and WORK_START <= self.time_of_day < WORK_END

    def open_for(self, hours: Hours) -> bool:
        """Whether a firm keeping `hours` is open at this moment."""

        if self.weekday == 6 or (self.weekday == 5 and not hours.saturday):
            return False
        return hours.open * HOUR <= self.time_of_day < hours.close * HOUR

    @property
    def anything_open(self) -> bool:
        """False in dead time: the hours a run loop skips rather than ticks.

        The one definition. It was written out in five places, which meant the
        next change to what a night is would have had to find all five.
        """

        if self.weekday == 6:
            return False
        if self.weekday == 5:
            return SATURDAY_OPEN <= self.time_of_day < SATURDAY_CLOSE
        return DISTRICT_OPEN <= self.time_of_day < DISTRICT_CLOSE

    def label(self) -> str:
        hours, rest = divmod(self.time_of_day, HOUR)
        return f"d{self.day} {_WEEKDAYS[self.weekday]} {hours:02d}:{rest // MINUTE:02d}"

    def __str__(self) -> str:
        return self.label()


def at(day: int, hour: int = 0, minute: int = 0) -> int:
    return day * DAY + hour * HOUR + minute * MINUTE


def next_office_open(seconds: int) -> int:
    """The next moment the offices are open, or now if they already are."""

    now = SimTime(seconds)
    if now.in_office_hours:
        return seconds
    day = now.day
    if now.is_workday and now.time_of_day < WORK_START:
        return at(day, 9)
    # After hours, or a weekend: walk forward to the next weekday morning.
    day += 1
    while SimTime(at(day)).is_weekend:
        day += 1
    return at(day, 9)


def next_open(seconds: int) -> int:
    """The next moment *anything* is open — an office, the cafe, the gym — or now.

    Not the same as `next_office_open`: the cafe opens two hours before the
    offices and trades on Saturday. Skipping dead time to the next *office*
    opening silently dropped the cafe's mornings on every day after the first,
    and all of its Saturdays.
    """

    moment = seconds - seconds % TICK if seconds % TICK == 0 else seconds
    # Bounded: some tick within a week is always open.
    for _ in range(7 * DAY // TICK + 1):
        now = SimTime(moment)
        if now.anything_open:
            return moment
        moment = moment - moment % TICK + TICK
    raise AssertionError("nothing opens for a whole week")
