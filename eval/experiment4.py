"""Experiment 4: does the answer answer the question?

Three scores, the ones agent evaluation settled on: did it choose the right tool, did it choose the
right arguments, and did the reply say what it had to say. The first two are the trajectory; the
third is the only one a person notices.

Deterministic throughout. "Does the reply contain 3:45 PM" is a fact and costs nothing to check;
"is the reply good" is a judgement, needs a model to answer, and the model is the thing under test.
"""

import csv
import os
from collections.abc import Sequence
from dataclasses import dataclass, field

from eval.experiment1 import RESULTS_DIR, provenance
from eval.harness import Answered, answer, running_stack
from eval.transcripts import ALL, by_name
from simulator.toolsets import TOOLSET_ENV


@dataclass
class Verdict:
    """One exchange, judged."""

    said: str
    speaker: str
    routed: str | None
    expected: str | None
    tool_ok: bool
    args_ok: bool
    answer_ok: bool
    spoken: str
    complaints: list[str] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return self.tool_ok and self.args_ok and self.answer_ok


def judge(result: Answered) -> Verdict:
    """Score one answer against what the transcript says a right answer looks like."""
    wanted = result.exchange
    complaints: list[str] = []

    if result.error:
        return Verdict(wanted.said, wanted.speaker, None, wanted.tool, False, False, False, "",
                       [result.error])

    allowed = (wanted.tool,) if isinstance(wanted.tool, str) else wanted.tool
    tool_ok = allowed is None or result.routed in allowed
    if not tool_ok:
        complaints.append(f"chose {result.routed or 'nothing'}, wanted {' or '.join(allowed)}")

    args_ok = True
    for key, value in wanted.expected_args().items():
        actual = result.arguments.get(key)
        if str(actual) != str(value):
            args_ok = False
            complaints.append(f"{key}={actual!r}, wanted {value!r}")

    spoken = result.spoken or ""
    lowered = spoken.lower()
    answer_ok = True
    for phrase in wanted.expected_say():
        if phrase.lower() not in lowered:
            answer_ok = False
            complaints.append(f"never said {phrase!r}")
    for phrase in wanted.must_not_say:
        if phrase.lower() in lowered:
            answer_ok = False
            complaints.append(f"said {phrase!r}, which it must not")

    return Verdict(wanted.said, wanted.speaker, result.routed, wanted.tool,
                   tool_ok, args_ok, answer_ok, spoken, complaints)


def share(verdicts: Sequence[Verdict], field_name: str) -> float:
    if not verdicts:
        return 0.0
    return sum(1 for v in verdicts if getattr(v, field_name)) / len(verdicts)


def print_report(verdicts: Sequence[Verdict], cassette) -> None:
    print(f"\n{len(verdicts)} exchanges through the whole stack\n")
    print(f"{'tool correctness':<22}{share(verdicts, 'tool_ok'):>8.1%}")
    print(f"{'argument correctness':<22}{share(verdicts, 'args_ok'):>8.1%}")
    print(f"{'answer correctness':<22}{share(verdicts, 'answer_ok'):>8.1%}")
    print(f"{'all three':<22}{share(verdicts, 'all_ok'):>8.1%}")

    failures = [v for v in verdicts if not v.all_ok]
    if failures:
        print(f"\n{len(failures)} that would reach a person:\n")
        for verdict in failures:
            print(f'  [{verdict.speaker}] "{verdict.said}"')
            for complaint in verdict.complaints:
                print(f"      {complaint}")
            if verdict.spoken:
                print(f'      said: "{verdict.spoken[:130]}"')
            print()
    print(cassette)


def write_csv(verdicts: Sequence[Verdict], meta: dict, arms: dict | None = None):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "experiment4.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["# experiment", "4 - does the answer answer the question"])
        for key, value in meta.items():
            writer.writerow([f"# {key}", value])
        writer.writerow([])
        writer.writerow(["measure", "share"])
        for name, attribute in (
            ("tool correctness", "tool_ok"),
            ("argument correctness", "args_ok"),
            ("answer correctness", "answer_ok"),
            ("all three", "all_ok"),
        ):
            writer.writerow([name, f"{share(verdicts, attribute):.3f}"])
        if arms:
            writer.writerow([])
            writer.writerow(["toolset", "schemas", "tool", "args", "answers", "all_three"])
            for setting in ("full", "coarse"):
                rows = arms.get(setting)
                if not rows:
                    continue
                writer.writerow([
                    setting,
                    len(_schemas_for(setting)),
                    f"{share(rows, 'tool_ok'):.3f}",
                    f"{share(rows, 'args_ok'):.3f}",
                    f"{share(rows, 'answer_ok'):.3f}",
                    f"{share(rows, 'all_ok'):.3f}",
                ])
        writer.writerow([])
        writer.writerow(["speaker", "said", "wanted_tool", "routed", "tool_ok", "args_ok",
                         "answer_ok", "complaints", "spoken"])
        for v in verdicts:
            writer.writerow([v.speaker, v.said, v.expected, v.routed, v.tool_ok, v.args_ok,
                             v.answer_ok, "; ".join(v.complaints), v.spoken])
    return path


def _one_arm(exchanges, with_llm: bool, setting: str) -> list[Verdict]:
    """Every exchange through the whole stack, with whichever toolset is currently set.

    The schema count is printed from inside the stack on purpose. `simulator.conversation` freezes
    the loaded window at import, `running_stack` pins the clock, and counting the schemas first
    imported the agent before that pin: the window became the real one, the routing prompt carries
    it, the prompt is part of the cassette key, and every single recording missed. Both arms then
    scored 4.4% on a suite that had just scored 100%.
    """
    with running_stack("experiment4", live=with_llm) as (client, cassette):
        print(f"\n--- {setting} toolset ({len(_schemas_for(setting))} schemas offered) ---")
        results = []
        state: dict = {}
        for exchange in exchanges:
            if not exchange.follows_on:
                state = {}  # a new question, not a continuation
            results.append(answer(client, exchange, state))
        verdicts = [judge(result) for result in results]
        print_report(verdicts, cassette)
    return verdicts


def run(with_llm: bool = False, group: str = "all", **_ignored) -> list[Verdict]:
    """Both toolsets, scored the same way. Replays by default; `with_llm` records anything new.

    The granularity comparison is the experiment's second half, so it runs here rather than being
    assembled by hand: `CLAUDE.md` requires every published number to come out of `make eval`.
    Each arm is a separate run of the same exchanges, because the schema block the model sees is
    the only thing that differs.
    """
    exchanges = by_name(group)
    arms = {}
    for setting in ("full", "coarse"):
        previous = os.environ.get(TOOLSET_ENV)
        os.environ[TOOLSET_ENV] = setting
        try:
            arms[setting] = _one_arm(exchanges, with_llm, setting)
        finally:
            if previous is None:
                os.environ.pop(TOOLSET_ENV, None)
            else:
                os.environ[TOOLSET_ENV] = previous

    _print_comparison(arms)

    meta = provenance(None)
    meta["exchanges"] = len(exchanges)
    meta["model_replayed_from"] = "cassette" if not with_llm else "live, and recorded"
    for setting in arms:
        meta[f"{setting}_schemas"] = len(_schemas_for(setting))
    path = write_csv(arms["full"], meta, arms=arms)
    print(f"wrote {path}")
    return arms["full"]


def _schemas_for(setting: str) -> list[dict]:
    from simulator.agent import TOOL_SCHEMAS
    from simulator.toolsets import COARSE_SCHEMAS

    return COARSE_SCHEMAS if setting == "coarse" else TOOL_SCHEMAS


def _print_comparison(arms: dict[str, list[Verdict]]) -> None:
    """The headline of experiment 4's second half: does granularity help a small model?"""
    print("\n=== tool granularity ===\n")
    print(f"{'toolset':<12}{'schemas':>9}{'tool':>9}{'args':>9}{'answers':>9}{'all three':>11}")
    print("-" * 59)
    for setting in ("full", "coarse"):
        verdicts = arms.get(setting)
        if not verdicts:
            continue
        print(
            f"{setting:<12}{len(_schemas_for(setting)):>9}"
            f"{share(verdicts, 'tool_ok'):>8.1%}"
            f"{share(verdicts, 'args_ok'):>9.1%}"
            f"{share(verdicts, 'answer_ok'):>9.1%}"
            f"{share(verdicts, 'all_ok'):>11.1%}"
        )


if __name__ == "__main__":
    run(with_llm=os.environ.get("EVAL_WITH_LLM") == "1", group=os.environ.get("EVAL_GROUP", "all"))


__all__ = ["ALL", "judge", "run"]
