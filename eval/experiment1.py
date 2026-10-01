"""Experiment 1: conflict detection. Calendar-overlap check vs AI only vs LifePilot.

Each detector returns a set of `(kind, event_id)` pairs per scenario. Scoring them against the
planted labels gives precision, recall and F1 for each.

A caution about reading the result. LifePilot scoring well on scenarios written alongside it is weak
evidence by itself; what the experiment actually measures is the *gap* between detectors on identical
input, and the clean scenarios are what stop a detector buying recall with false alarms.
"""

import csv
import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eval.scenarios import Scenario, build
from lifepilot.engine.conflicts import Week, detect

RESULTS_DIR = Path(__file__).resolve().parent / "results"

Prediction = set[tuple[str, int]]


# --------------------------------------------------------------------------- detectors


def overlap_only(week: Week) -> Prediction:
    """What a shared calendar can do: two events for the same person at the same time.

    It has no idea where anyone is, who can drive, or what the family decided. That is the point.
    """
    found: Prediction = set()
    for i, a in enumerate(week.commitments):
        for b in week.commitments[i + 1:]:
            if not set(a.member_ids) & set(b.member_ids):
                continue
            if a.end <= b.start or b.end <= a.start:
                continue
            found.add(("overlap", a.id))
    return found


def lifepilot(week: Week) -> Prediction:
    return {(c.kind, c.event_id) for c in detect(week) if c.event_id is not None}


# --------------------------------------------------------------------------- scoring


@dataclass
class Score:
    detector: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    clean_weeks_called_broken: int = 0
    by_kind_found: dict[str, int] = None
    by_kind_total: dict[str, int] = None

    def __post_init__(self):
        self.by_kind_found = self.by_kind_found or {}
        self.by_kind_total = self.by_kind_total or {}

    @property
    def precision(self) -> float:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else 0.0

    @property
    def recall(self) -> float:
        actual = self.true_positives + self.false_negatives
        return self.true_positives / actual if actual else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def score(detector: str, scenarios: Sequence[Scenario], predictions: Sequence[Prediction]) -> Score:
    result = Score(detector)
    for scenario, predicted in zip(scenarios, predictions, strict=True):
        expected = set(scenario.expected)
        result.true_positives += len(predicted & expected)
        result.false_positives += len(predicted - expected)
        result.false_negatives += len(expected - predicted)

        if not expected and predicted:
            result.clean_weeks_called_broken += 1

        if expected:
            kind = scenario.planted
            result.by_kind_total[kind] = result.by_kind_total.get(kind, 0) + 1
            if expected <= predicted:
                result.by_kind_found[kind] = result.by_kind_found.get(kind, 0) + 1
    return result


# --------------------------------------------------------------------------- reporting


def provenance(model_id: str | None) -> dict:
    return {
        "git_sha": _git_sha(),
        "model_id": model_id or "none (no model calls)",
        "seed": 7,
    }


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent.parent,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def write_csv(scores: Sequence[Score], scenarios: Sequence[Scenario], meta: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "experiment1.csv"
    clean = sum(1 for s in scenarios if not s.expected)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["# experiment", "1 - conflict detection"])
        for key, value in meta.items():
            writer.writerow([f"# {key}", value])
        writer.writerow(["# scenarios", len(scenarios)])
        writer.writerow(["# clean scenarios", clean])
        writer.writerow([])
        writer.writerow(
            ["detector", "precision", "recall", "f1", "tp", "fp", "fn", "clean_weeks_called_broken"]
        )
        for s in scores:
            writer.writerow([
                s.detector,
                f"{s.precision:.3f}",
                f"{s.recall:.3f}",
                f"{s.f1:.3f}",
                s.true_positives,
                s.false_positives,
                s.false_negatives,
                s.clean_weeks_called_broken,
            ])
        writer.writerow([])
        writer.writerow(["detector", "planted_kind", "found", "total", "recall"])
        for s in scores:
            for kind in sorted(s.by_kind_total):
                total = s.by_kind_total[kind]
                found = s.by_kind_found.get(kind, 0)
                writer.writerow([s.detector, kind, found, total, f"{found / total:.3f}"])
    return path


def print_table(scores: Sequence[Score], scenarios: Sequence[Scenario]) -> None:
    clean = sum(1 for s in scenarios if not s.expected)
    print(f"\n{len(scenarios)} scenarios ({clean} of them deliberately fine)\n")
    print(f"{'detector':<18}{'precision':>10}{'recall':>9}{'f1':>7}{'false alarms':>15}")
    print("-" * 59)
    for s in scores:
        print(
            f"{s.detector:<18}{s.precision:>10.3f}{s.recall:>9.3f}{s.f1:>7.3f}"
            f"{s.clean_weeks_called_broken:>15}"
        )

    print("\nrecall by planted kind")
    print("-" * 59)
    kinds = sorted({k for s in scores for k in s.by_kind_total})
    print(f"{'kind':<20}" + "".join(f"{s.detector:>14}" for s in scores))
    for kind in kinds:
        row = f"{kind:<20}"
        for s in scores:
            total = s.by_kind_total.get(kind, 0)
            found = s.by_kind_found.get(kind, 0)
            row += f"{(found / total if total else 0):>14.3f}"
        print(row)


def run(with_llm: bool = False, per_kind: int = 5) -> list[Score]:
    """Both code detectors always; the model baseline only when asked, because it costs money."""
    scenarios = build(per_kind=per_kind)

    scores = [
        score("calendar-overlap", scenarios, [overlap_only(s.week) for s in scenarios]),
        score("lifepilot", scenarios, [lifepilot(s.week) for s in scenarios]),
    ]
    model_id = None

    if with_llm:
        from eval.llm_baseline import estimate_calls, predict_all

        print(f"model baseline: about {estimate_calls(scenarios)} calls to Bedrock")
        predictions, model_id = predict_all(scenarios)
        scores.append(score("ai-only", scenarios, predictions))

    meta = provenance(model_id)
    print_table(scores, scenarios)
    path = write_csv(scores, scenarios, meta)
    print(f"\nwrote {path}")
    print(json.dumps(meta))
    return scores


if __name__ == "__main__":
    run(with_llm=os.environ.get("EVAL_WITH_LLM") == "1")
