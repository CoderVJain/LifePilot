"""Repair the week with the fewest changes: the Minimal Perturbation Problem, in CP-SAT.

We do not build a new schedule. We look for the feasible schedule closest to the one the family
already has, because a plan that fixes Thursday by rearranging Tuesday is not a fix anyone will
accept. Minimal change is the objective function, not a filter applied afterwards.

    variables   who covers each lift; the day and time of each movable event
    hard        immovable events stay put; nobody in two places at once; the family's rules
    objective   maximise what stays the same, then even out the load a little

Time is measured in minutes from midnight on the first day of the week, never minutes past midnight:
otherwise Monday 09:00 and Tuesday 09:00 are the same number and the no-overlap constraint invents a
clash between them.

Two settings are not tuning and must not be "cleaned up":

`num_search_workers=8` -- OR-Tools 9.15.6755 segfaults (`Check failed: heuristics.fixed_search !=
nullptr`) on a model that presolves to nothing while carrying a solution hint, which is exactly a
warm-started repair of an already-feasible week. Fixed in 10.0; until then the worker count is capped.

`max_time_in_seconds=5` -- this runs inside a voice turn.

**Approximation, stated plainly.** Whether an adult can reach a lift is decided by
`engine.reachability` against their fixed commitments, and the solver then keeps the lifts one adult
takes from colliding with each other and with their day: each lift occupies the handover itself. It
does not re-derive travel between two lifts one person takes back to back, so two collections fifteen
minutes and forty minutes apart would be allowed. For a family with a handful of lifts a week that is
sound and explainable; a household running five school runs a day would need the full routing
formulation.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ortools.sat.python import cp_model

from lifepilot.engine.conflicts import Week
from lifepilot.engine.reachability import HANDOVER_MINUTES, assess

# See the module docstring: neither of these is a tuning knob.
MAX_SOLVE_SECONDS = 5.0
SEARCH_WORKERS = 8

DAY_MINUTES = 24 * 60
SLOT_MINUTES = 15
EARLIEST_HOUR = 6
LATEST_HOUR = 22
SLOTS_PER_DAY = ((LATEST_HOUR - EARLIEST_HOUR) * 60) // SLOT_MINUTES

# A change costs far more than an imbalance, so the solver never shuffles the week to even the load.
# The third term only ever separates plans that are otherwise identical in cost. Without it the eight
# search workers break ties by whichever finishes first, and the same broken week can be repaired two
# different ways on two runs -- fine for a solver, unacceptable for something a family is asked to
# approve. The weights are decades apart so a tie-break can never outrank a real preference.
CHANGE_WEIGHT = 10_000_000
IMBALANCE_WEIGHT = 100_000
TIEBREAK_WEIGHT = 1

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class Change:
    """One change, in words for a person and in values for a machine.

    `was`/`now` are what gets read aloud; `person_id`/`start_iso` are what an evaluator applies. Both
    come from the same solution, so a plan can never be described one way and scored another.
    """

    kind: str
    title: str
    was: str
    now: str
    reason: str
    event_id: int | None = None
    person_id: int | None = None
    start_iso: str | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "was": self.was,
            "now": self.now,
            "reason": self.reason,
            "event_id": self.event_id,
            "person_id": self.person_id,
            "start_iso": self.start_iso,
        }


@dataclass
class Repair:
    status: str
    changes: list[Change] = field(default_factory=list)
    solve_ms: int = 0
    unfixable: list[str] = field(default_factory=list)

    @property
    def change_count(self) -> int:
        return len(self.changes)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "change_count": self.change_count,
            "changes": [c.as_dict() for c in self.changes],
            "solve_ms": self.solve_ms,
            "unfixable": self.unfixable,
        }


@dataclass
class _Plan:
    """The model's variables, kept together so the reading-back step cannot drift from the building."""

    base: datetime
    days: int
    covers: dict[tuple[int, int], cp_model.IntVar] = field(default_factory=dict)
    starts: dict[int, cp_model.IntVar] = field(default_factory=dict)
    slots: dict[int, cp_model.IntVar] = field(default_factory=dict)
    moved: dict[int, cp_model.IntVar] = field(default_factory=dict)
    movable: list = field(default_factory=list)
    unfixable: list[str] = field(default_factory=list)


def repair(week: Week) -> Repair:
    """The nearest feasible week to this one."""
    started = time.perf_counter()
    if not week.commitments:
        return Repair(status="optimal", solve_ms=0)

    model = cp_model.CpModel()
    plan = _Plan(base=_base(week), days=_span_days(week))

    _lift_variables(model, week, plan)
    _event_variables(model, week, plan)
    _no_person_in_two_places(model, week, plan)
    _apply_rules(model, week, plan)

    kept = _keep_current_assignees(week, plan)
    reassignments = len(week.needs) - sum(kept) if kept else 0
    imbalance = _load_imbalance(model, week, plan)
    model.minimize(
        CHANGE_WEIGHT * (reassignments + sum(plan.moved.values()))
        + IMBALANCE_WEIGHT * imbalance
        + TIEBREAK_WEIGHT * _tiebreak(week, plan)
    )
    _warm_start(model, week, plan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = MAX_SOLVE_SECONDS
    solver.parameters.num_search_workers = SEARCH_WORKERS
    solver.parameters.random_seed = 1
    status = solver.solve(model)
    solve_ms = round((time.perf_counter() - started) * 1000)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Repair(status="infeasible", solve_ms=solve_ms, unfixable=plan.unfixable)

    return Repair(
        status="optimal" if status == cp_model.OPTIMAL else "feasible",
        changes=_read_changes(solver, week, plan),
        solve_ms=solve_ms,
        unfixable=plan.unfixable,
    )


# --------------------------------------------------------------------------- variables


def _lift_variables(model: cp_model.CpModel, week: Week, plan: _Plan) -> None:
    """One boolean per (lift, adult who could actually do it)."""
    eligibility = [rule["params"] for rule in week.rules if rule["type"] == "eligibility"]

    for need in week.needs:
        candidates = assess(
            need, week.people, week.commitments, week.travel, week.driven, eligibility
        )
        able = [c.person_id for c in candidates if c.reachable]
        if not able:
            plan.unfixable.append(f"nobody can cover {need.title}")
            continue
        for person_id in able:
            plan.covers[(need.event_id, person_id)] = model.new_bool_var(
                f"covers_{need.event_id}_{person_id}"
            )
        model.add_exactly_one(plan.covers[(need.event_id, p)] for p in able)


def _event_variables(model: cp_model.CpModel, week: Week, plan: _Plan) -> None:
    """A day and a quarter-hour slot for each movable event, plus a flag for having moved it.

    Splitting day from time keeps the waking-hours window simple and lets an event move to another
    day, which is often the smallest real change -- homework moves to Wednesday rather than being
    squeezed into a Thursday that does not fit.
    """
    plan.movable = [c for c in week.commitments if _is_movable(week, c)]

    for commitment in plan.movable:
        day = model.new_int_var(0, plan.days - 1, f"day_{commitment.id}")
        slot = model.new_int_var(0, SLOTS_PER_DAY, f"slot_{commitment.id}")
        start = model.new_int_var(0, plan.days * DAY_MINUTES, f"start_{commitment.id}")
        model.add(start == day * DAY_MINUTES + EARLIEST_HOUR * 60 + SLOT_MINUTES * slot)
        plan.starts[commitment.id] = start
        # How far this event moved, in quarter hours. Used only to separate plans that cost the
        # same: among equal repairs, prefer the one that shifts things least. "Prefer earlier" was
        # tried first and dragged Thursday homework to Monday morning, which is one change on paper
        # and a different week in practice. Bounded well under the imbalance weight above.
        span = (plan.days * DAY_MINUTES) // SLOT_MINUTES
        ordinal = model.new_int_var(0, span, f"ord_{commitment.id}")
        model.add_division_equality(ordinal, start, SLOT_MINUTES)
        drift = model.new_int_var(-span, span, f"drift_{commitment.id}")
        model.add(drift == ordinal - _minutes(plan.base, commitment.start) // SLOT_MINUTES)
        shift = model.new_int_var(0, span, f"shift_{commitment.id}")
        model.add_abs_equality(shift, drift)
        plan.slots[commitment.id] = shift

        flag = model.new_bool_var(f"moved_{commitment.id}")
        current = _minutes(plan.base, commitment.start)
        model.add(start != current).only_enforce_if(flag)
        model.add(start == current).only_enforce_if(~flag)
        plan.moved[commitment.id] = flag


def _is_movable(week: Week, commitment) -> bool:
    """Movable in the data, not named by an immovable_event rule, and not something with a lift.

    An event somebody has to be collected from is pinned for now: the pickup time is derived from
    when the event ends, so moving the event without moving the lift would quietly describe a
    collection that nobody is driving to.
    """
    if not commitment.movable:
        return False
    if any(need.event_id == commitment.id for need in week.needs):
        return False
    for rule in week.rules:
        if rule["type"] == "immovable_event":
            named = rule["params"].get("title", "").lower()
            if named and named in commitment.title.lower():
                return False
    return True


# --------------------------------------------------------------------------- constraints


def _no_person_in_two_places(model: cp_model.CpModel, week: Week, plan: _Plan) -> None:
    """Each person's week, as intervals that may not overlap."""
    movable_ids = {c.id for c in plan.movable}

    for person in week.people:
        intervals = []

        for commitment in week.commitments:
            if person.id not in commitment.member_ids:
                continue
            length = max(1, int((commitment.end - commitment.start).total_seconds() // 60))
            if commitment.id in movable_ids:
                start = plan.starts[commitment.id]
                end = model.new_int_var(0, plan.days * DAY_MINUTES + length, f"end_{commitment.id}")
                model.add(end == start + length)
                intervals.append(
                    model.new_interval_var(start, length, end, f"iv_{person.id}_{commitment.id}")
                )
            else:
                begin = _minutes(plan.base, commitment.start)
                intervals.append(
                    model.new_fixed_size_interval_var(
                        begin, length, f"fixed_{person.id}_{commitment.id}"
                    )
                )

        for need in week.needs:
            key = (need.event_id, person.id)
            if key not in plan.covers:
                continue
            # The lift occupies the handover itself. Widening it to include travel from home
            # double-counts: Mom collecting Anaya at 16:45 and Aarav at 17:00 ten minutes away is
            # perfectly possible, and an interval anchored on her home would forbid it. Whether she
            # can reach each lift at all is already settled by engine.reachability.
            intervals.append(
                model.new_optional_fixed_size_interval_var(
                    _minutes(plan.base, need.moment),
                    HANDOVER_MINUTES,
                    plan.covers[key],
                    f"lift_{need.event_id}_{person.id}",
                )
            )

        if len(intervals) > 1:
            model.add_no_overlap(intervals)


def _apply_rules(model: cp_model.CpModel, week: Week, plan: _Plan) -> None:
    """The family's stated rules, as constraints on the movable events."""
    for rule in week.rules:
        if rule["type"] == "latest_end":
            _rule_latest_end(model, week, plan, rule["params"])
        elif rule["type"] == "buffer_after":
            _rule_buffer_after(model, week, plan, rule["params"])


def _rule_latest_end(model, week: Week, plan: _Plan, params: dict) -> None:
    limit = _clock_minutes(params["latest_end"])
    category = params.get("category")
    for commitment in plan.movable:
        if category and commitment.category != category:
            continue
        length = int((commitment.end - commitment.start).total_seconds() // 60)
        # start is day*1440 + 360 + 15*slot, so time of day is start minus the day part.
        day_part = model.new_int_var(0, plan.days * DAY_MINUTES, f"daypart_{commitment.id}")
        model.add_modulo_equality(day_part, plan.starts[commitment.id], DAY_MINUTES)
        model.add(day_part + length <= limit)


def _rule_buffer_after(model, week: Week, plan: _Plan, params: dict) -> None:
    person = next((p for p in week.people if p.name == params.get("member")), None)
    if person is None:
        return
    gap = params["minutes"]
    anchors = [
        c for c in week.commitments if c.title == params.get("after") and person.id in c.member_ids
    ]
    for commitment in plan.movable:
        if person.id not in commitment.member_ids:
            continue
        for anchor in anchors:
            if anchor.id == commitment.id:
                continue
            # The buffer only bites on the anchor's own day; landing on another day is fine.
            anchor_day = _minutes(plan.base, anchor.start) // DAY_MINUTES
            same_day = model.new_bool_var(f"sameday_{commitment.id}_{anchor.id}")
            day_index = model.new_int_var(0, plan.days - 1, f"dayidx_{commitment.id}_{anchor.id}")
            model.add_division_equality(day_index, plan.starts[commitment.id], DAY_MINUTES)
            model.add(day_index == anchor_day).only_enforce_if(same_day)
            model.add(day_index != anchor_day).only_enforce_if(~same_day)
            model.add(
                plan.starts[commitment.id] >= _minutes(plan.base, anchor.end) + gap
            ).only_enforce_if(same_day)


def _keep_current_assignees(week: Week, plan: _Plan) -> list[cp_model.IntVar]:
    """One boolean per lift: is it still with whoever has it now?"""
    kept = []
    for need in week.needs:
        current = week.assigned.get(need.event_id)
        if current is not None and (need.event_id, current) in plan.covers:
            kept.append(plan.covers[(need.event_id, current)])
    return kept


def _load_imbalance(model: cp_model.CpModel, week: Week, plan: _Plan):
    """Spread between the busiest and least busy adult, as a tie-breaker only."""
    adults = [p for p in week.people if p.can_drive]
    if len(adults) < 2 or not plan.covers:
        return 0

    totals = []
    for person in adults:
        mine = [var for (_, pid), var in plan.covers.items() if pid == person.id]
        total = model.new_int_var(0, len(week.needs), f"load_{person.id}")
        model.add(total == sum(mine) if mine else total == 0)
        totals.append(total)

    high = model.new_int_var(0, len(week.needs), "busiest")
    low = model.new_int_var(0, len(week.needs), "least_busy")
    model.add_max_equality(high, totals)
    model.add_min_equality(low, totals)
    spread = model.new_int_var(0, len(week.needs), "spread")
    model.add(spread == high - low)
    return spread


def _tiebreak(week: Week, plan: _Plan):
    """A deterministic preference between plans that cost exactly the same.

    Earlier in the family's own order, and as close as possible to where things already were. The
    point is that the same week is always repaired the same way, rather than differently depending on
    which of eight search workers finished first.
    """
    order = {person.id: index for index, person in enumerate(sorted(week.people, key=lambda p: p.id))}
    terms = [var * order.get(person_id, 0) for (_, person_id), var in sorted(plan.covers.items())]
    terms += [plan.slots[event_id] for event_id in sorted(plan.slots)]
    return sum(terms) if terms else 0


def _warm_start(model: cp_model.CpModel, week: Week, plan: _Plan) -> None:
    """Hint the current plan, so the search begins from what the family already has."""
    for (event_id, person_id), var in plan.covers.items():
        model.add_hint(var, 1 if week.assigned.get(event_id) == person_id else 0)
    for commitment in plan.movable:
        model.add_hint(plan.starts[commitment.id], _minutes(plan.base, commitment.start))


# --------------------------------------------------------------------------- reading back


def _read_changes(solver, week: Week, plan: _Plan) -> list[Change]:
    names = {p.id: p.name for p in week.people}
    changes = []

    for need in week.needs:
        current = week.assigned.get(need.event_id)
        chosen = next(
            (
                pid
                for (event_id, pid), var in plan.covers.items()
                if event_id == need.event_id and solver.value(var)
            ),
            None,
        )
        if chosen is None or chosen == current:
            continue
        changes.append(
            Change(
                kind="assign",
                title=need.title,
                was=names.get(current, "nobody"),
                now=names.get(chosen, "nobody"),
                reason=(
                    f"{names[current]} cannot get there in time"
                    if current in names
                    else "nobody was down for it"
                ),
                event_id=need.event_id,
                person_id=chosen,
            )
        )

    for commitment in plan.movable:
        was = _minutes(plan.base, commitment.start)
        now = solver.value(plan.starts[commitment.id])
        if now == was:
            continue
        changes.append(
            Change(
                kind="move",
                title=commitment.title,
                was=_clock(plan.base, was),
                now=_clock(plan.base, now),
                reason="it broke one of your rules where it was",
                event_id=commitment.id,
                start_iso=(plan.base + timedelta(minutes=now)).isoformat(timespec="minutes"),
            )
        )
    return changes


# --------------------------------------------------------------------------- small helpers


def _base(week: Week) -> datetime:
    """Midnight on the first day in the week: the origin every time is measured from."""
    earliest = min(c.start for c in week.commitments)
    return earliest.replace(hour=0, minute=0, second=0, microsecond=0)


def _span_days(week: Week) -> int:
    base = _base(week)
    latest = max(c.end for c in week.commitments)
    return max(1, int((latest - base).total_seconds() // (24 * 3600)) + 1)


def _minutes(base: datetime, moment: datetime) -> int:
    return int((moment - base).total_seconds() // 60)


def _clock(base: datetime, minutes: int) -> str:
    moment = base + timedelta(minutes=minutes)
    return f"{DAYS[moment.weekday()]} {moment:%H:%M}"


def _clock_minutes(value: str) -> int:
    hour, _, minute = value.partition(":")
    return int(hour) * 60 + int(minute or 0)
