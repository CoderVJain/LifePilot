"""Experiment 5: "what am I forgetting?" against deadline-only reminders.

Same tasks, same weeks, two systems.

    deadline-only   warns the day before a task is due, which is what a reminder app does
    lifepilot       warns as soon as the free hours left stop being enough, counting the rules

Two things are measured, and the second is the point. **Catch rate** is how many of the tasks that
were going to be missed got flagged at all. **Days of warning** is how long before the deadline the
warning first appeared, because a warning you cannot act on is not help.

A deadline reminder only knows about tasks somebody typed in. `CLAUDE.md` asks for tasks that exist
only in a school email, and those are invisible to it however good its reminders are -- the costume
is needed by Friday and nobody ever put it in a list. That is counted here rather than argued about.

False alarms are reported too. A scanner that flags everything has a perfect catch rate and is
useless, and only the tasks that are genuinely fine expose that -- the same lesson as experiment 1.

Days of warning are measured by replaying the real scan as of each day, so the number is the
product's own behaviour and not a second opinion about it.
"""

import csv
import os
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from eval.experiment1 import RESULTS_DIR, provenance
from lifepilot.engine.reachability import Commitment
from lifepilot.engine.risk import Task, first_warning_day, scan

MONDAY = date(2026, 10, 19)
AARAV = 3
SCHOOL, HOME, GROUND = 4, 1, 5

NO_LATE_STUDY = {"type": "latest_end", "params": {"category": "study", "latest_end": "21:00"}}
RULES = (NO_LATE_STUDY,)

#: How many days before a deadline a reminder app speaks up. One is generous for the baseline.
DEADLINE_NOTICE_DAYS = 1


@dataclass(frozen=True)
class Planted:
    """One task, the week around it, and whether it was going to be missed."""

    name: str
    task: Task
    commitments: tuple[Commitment, ...]
    at_risk: bool
    booked: tuple[int, ...] = ()


@dataclass
class Score:
    system: str
    planted_at_risk: int = 0
    caught: int = 0
    false_alarms: int = 0
    planted_fine: int = 0
    warning_days: list[int] = field(default_factory=list)
    offered_a_slot: int = 0
    invisible: int = 0

    @property
    def catch_rate(self) -> float:
        return self.caught / self.planted_at_risk if self.planted_at_risk else 0.0

    @property
    def false_alarm_rate(self) -> float:
        return self.false_alarms / self.planted_fine if self.planted_fine else 0.0

    @property
    def mean_warning(self) -> float:
        return statistics.fmean(self.warning_days) if self.warning_days else 0.0

    @property
    def median_warning(self) -> float:
        return statistics.median(self.warning_days) if self.warning_days else 0.0


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def _school(day: date, event_id: int) -> Commitment:
    return Commitment(event_id, "school", at(day, 8), at(day, 15), SCHOOL, (AARAV,), "school", False)


def _busy(day: date, event_id: int, from_hour: int = 15, to_hour: int = 21) -> Commitment:
    return Commitment(event_id, "cricket practice", at(day, from_hour), at(day, to_hour), GROUND,
                      (AARAV,), "activity", True)


def _weekdays(count: int = 5) -> list[date]:
    return [MONDAY + timedelta(days=offset) for offset in range(count)]


def _task(index: int, title: str, due: date, est: int, prep: int, source: str = "voice") -> Task:
    return Task(
        id=index, title=title, due=at(due, 8), est_minutes=est, owner_id=AARAV,
        prep_days=prep, category="study", source=source,
    )


def build() -> list[Planted]:
    """Tasks that were going to be missed, and tasks that were genuinely fine."""
    friday = MONDAY + timedelta(days=4)
    planted = []

    # 1. A project with nothing set aside and a week that is busy but not full.
    # Busy but not sealed: Wednesday evening is free, so there is something to offer. A week with
    # no gap at all can only be reported, and the offer is half the feature.
    busy = [
        c for day in _weekdays()
        for c in ([_school(day, 100 + day.day)]
                  + ([] if day.weekday() == 2 else [_busy(day, 200 + day.day)]))
    ]
    planted.append(Planted(
        "unbooked-project",
        _task(1, "science project model", friday, est=180, prep=3),
        tuple(busy),
        at_risk=True,
    ))

    # 2. A costume that exists only because the school emailed. Nobody typed it anywhere.
    planted.append(Planted(
        "email-costume",
        _task(2, "costume making", friday, est=120, prep=2, source="email"),
        tuple(busy),
        at_risk=True,
    ))

    # 3. A fee from an email, due mid-week, small but easy to forget.
    wednesday = MONDAY + timedelta(days=2)
    planted.append(Planted(
        "email-fee",
        _task(3, "school fee payment", wednesday, est=30, prep=2, source="email"),
        tuple(busy),
        at_risk=True,
    ))

    # 4. A reading task in a week with no evenings left at all: no slot exists, something must move.
    packed = [
        c for day in _weekdays()
        for c in (_school(day, 300 + day.day), _busy(day, 400 + day.day, 7, 21))
    ]
    planted.append(Planted(
        "no-room-reading",
        _task(4, "reading log", friday, est=120, prep=4),
        tuple(packed),
        at_risk=True,
    ))

    # 5. A study task the 9 PM rule makes impossible, and would not be without it.
    late = [
        c for day in _weekdays()
        for c in (_school(day, 500 + day.day), _busy(day, 600 + day.day, 15, 20, ))
    ]
    planted.append(Planted(
        "rule-tightened-essay",
        _task(5, "history essay", friday, est=200, prep=3),
        tuple(late),
        at_risk=True,
    ))

    # --- the ones that are genuinely fine, which is what exposes a scanner that cries wolf ---
    #
    # "Fine" has to mean *nothing will be missed*, and the only honest way for an open task to
    # qualify is that time is already set aside for it. A first version used a task weeks away and
    # a twenty-minute one, and counted LifePilot's warnings about them as false alarms. They were
    # not: both were unbooked, and "nothing is set aside for this and it is due soon" is useful
    # whatever the calendar looks like. Scoring correct warnings as errors would have understated
    # the product and overstated the baseline at the same time.

    # 6. Time already set aside for it, in a week otherwise identical to scenario 1.
    booked_day = MONDAY + timedelta(days=1)
    with_block = list(busy) + [
        Commitment(700, "science project block", at(booked_day, 15), at(booked_day, 18), HOME,
                   (AARAV,), "study", True)
    ]
    planted.append(Planted(
        "already-booked",
        _task(6, "science project model", friday, est=180, prep=3),
        tuple(with_block),
        at_risk=False,
        booked=(6,),
    ))

    # 7. A second booked one, from an email, so the baseline's blind spot is not the only
    #    difference between the arms on email-sourced work.
    planted.append(Planted(
        "booked-costume",
        _task(7, "costume making", friday, est=120, prep=2, source="email"),
        tuple(list(busy) + [
            Commitment(701, "costume making time", at(booked_day, 18), at(booked_day, 20), HOME,
                       (AARAV,), "study", True)
        ]),
        at_risk=False,
        booked=(7,),
    ))

    # 8. Already finished.
    planted.append(Planted(
        "finished-spelling",
        Task(id=8, title="spelling practice", due=at(friday, 8), est_minutes=20, owner_id=AARAV,
             prep_days=1, category="study", status="done"),
        tuple(busy),
        at_risk=False,
    ))

    return planted


def _lifepilot(score: Score, planted: Planted) -> None:
    """Flagged at all, and how many days before the deadline it was first flagged."""
    due_day = planted.task.due.date()
    first = first_warning_day(
        planted.task, list(planted.commitments), RULES, booked=planted.booked
    )
    flagged = first is not None and first <= due_day

    if planted.at_risk and flagged:
        score.caught += 1
        score.warning_days.append((due_day - first).days)
        found = scan([planted.task], list(planted.commitments), first, RULES, planted.booked)
        if found and found[0].slot is not None:
            score.offered_a_slot += 1
    elif not planted.at_risk and flagged:
        score.false_alarms += 1


def _deadline_only(score: Score, planted: Planted) -> None:
    """A reminder app: it speaks the day before, and only about tasks somebody entered.

    A task that arrived in a school email was never entered, so it cannot be reminded about. That
    is not a straw man -- it is the whole reason differentiator #7 exists.
    """
    if planted.task.source == "email":
        score.invisible += 1
        return

    if planted.at_risk:
        score.caught += 1
        score.warning_days.append(DEADLINE_NOTICE_DAYS)
    else:
        # It warns about everything with a deadline, whether or not there is a problem.
        score.false_alarms += 1


def run(with_llm: bool = False, per_kind: int = 5, **_ignored) -> list[Score]:
    """Both systems over the same planted tasks. No model calls."""
    planted = build()
    at_risk = sum(1 for p in planted if p.at_risk)
    fine = len(planted) - at_risk

    scores = []
    for system, judge in (("lifepilot", _lifepilot), ("deadline-only", _deadline_only)):
        score = Score(system=system, planted_at_risk=at_risk, planted_fine=fine)
        for item in planted:
            judge(score, item)
        scores.append(score)

    print_report(scores, planted)
    meta = provenance(None)
    meta["tasks"] = len(planted)
    meta["planted_at_risk"] = at_risk
    meta["deadline_notice_days"] = DEADLINE_NOTICE_DAYS
    path = write_csv(scores, planted, meta)
    print(f"wrote {path}")
    return scores


def print_report(scores: Sequence[Score], planted: Sequence[Planted]) -> None:
    at_risk = sum(1 for p in planted if p.at_risk)
    from_email = sum(1 for p in planted if p.task.source == "email")
    print(f"\n{len(planted)} tasks: {at_risk} were going to be missed, "
          f"{len(planted) - at_risk} were fine. {from_email} exist only in a school email.\n")
    print(f"{'system':<16}{'caught':>9}{'false alarms':>14}{'mean warning':>15}"
          f"{'median':>9}{'never saw':>11}")
    print("-" * 74)
    for score in scores:
        print(
            f"{score.system:<16}{score.catch_rate:>9.1%}{score.false_alarm_rate:>14.1%}"
            f"{score.mean_warning:>12.1f}d{score.median_warning:>8.1f}d{score.invisible:>11}"
        )

    offered = next((s.offered_a_slot for s in scores if s.system == "lifepilot"), 0)
    print(f"\nwarnings that came with a slot to book: {offered} of {at_risk}")
    print("a deadline reminder offers none, by construction: it knows the date, not the week")


def write_csv(scores: Sequence[Score], planted: Sequence[Planted], meta: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "experiment5.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["# experiment", "5 - what am I forgetting, against deadline reminders"])
        for key, value in meta.items():
            writer.writerow([f"# {key}", value])
        writer.writerow([])
        writer.writerow(["system", "planted_at_risk", "caught", "catch_rate", "false_alarms",
                         "false_alarm_rate", "mean_warning_days", "median_warning_days",
                         "never_saw_the_task", "offered_a_slot"])
        for score in scores:
            writer.writerow([
                score.system, score.planted_at_risk, score.caught, f"{score.catch_rate:.3f}",
                score.false_alarms, f"{score.false_alarm_rate:.3f}",
                f"{score.mean_warning:.2f}", f"{score.median_warning:.2f}",
                score.invisible, score.offered_a_slot,
            ])
        writer.writerow([])
        writer.writerow(["task", "source", "due", "minutes", "prep_days", "planted_at_risk"])
        for item in planted:
            writer.writerow([
                item.task.title, item.task.source, item.task.due.date().isoformat(),
                item.task.est_minutes, item.task.prep_days, item.at_risk,
            ])
    return path


if __name__ == "__main__":
    run(with_llm=os.environ.get("EVAL_WITH_LLM") == "1")
