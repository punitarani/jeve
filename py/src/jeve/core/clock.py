"""Sim time (CORE-0003).

An integer count of sim-seconds from a seeded epoch. Sim time 0 is 00:00 on a
Monday. Nothing here reads the wall clock — ruff's banned-api rule enforces
that outside `jeve.llm`.
"""

from __future__ import annotations

from dataclasses import dataclass

SECOND = 1
MINUTE = 60
HOUR = 3600
DAY = 86400

TICK = 15 * MINUTE
"""Scheduler quantum. Not how often an agent thinks — that is a decision point."""

WORK_START = 9 * HOUR
WORK_END = 17 * HOUR
CAFE_OPEN = 7 * HOUR
CAFE_CLOSE = 18 * HOUR
"""An hour after the offices: people stop in on the way home."""

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

    @property
    def cafe_open(self) -> bool:
        # The cafe also works Saturday; Sunday it is shut.
        return self.weekday <= 5 and CAFE_OPEN <= self.time_of_day < CAFE_CLOSE

    @property
    def anything_open(self) -> bool:
        """False in dead time: the hours a run loop skips rather than ticks.

        The one definition. It was written out in five places, which meant the
        next change to what a night is would have had to find all five.
        """

        return self.in_office_hours or self.cafe_open

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
    """The next moment *anything* is open — an office or the cafe — or now.

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
