"""Run the experiments. `make eval`, or `make eval EXP=1`.

Model calls are opt-in and the estimate is printed before any of them happen, so nobody discovers the
bill afterwards. `EVAL_MAX_CALLS` is the hard ceiling.
"""

import argparse
import os

from eval import experiment1, experiment2, experiment4
from eval.scenarios import build

EXPERIMENTS = {
    1: ("conflict detection", experiment1.run),
    2: ("plan feasibility", experiment2.run),
    4: ("does the answer answer the question", experiment4.run),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LifePilot experiments.")
    parser.add_argument("--exp", type=int, help="run one experiment by number")
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="include the model baselines (costs money; free without it)",
    )
    parser.add_argument("--per-kind", type=int, default=5, help="scenarios per planted kind")
    args = parser.parse_args()

    with_llm = args.with_llm or os.environ.get("EVAL_WITH_LLM") == "1"
    chosen = [args.exp] if args.exp else sorted(EXPERIMENTS)

    for number in chosen:
        if number not in EXPERIMENTS:
            parser.error(f"no experiment {number}; have {sorted(EXPERIMENTS)}")

    _announce(chosen, with_llm, args.per_kind)

    for number in chosen:
        name, run = EXPERIMENTS[number]
        print(f"\n=== experiment {number}: {name} ===")
        run(with_llm=with_llm, per_kind=args.per_kind)


def _announce(chosen: list[int], with_llm: bool, per_kind: int) -> None:
    """Say what this will cost before spending anything."""
    ceiling = int(os.environ.get("EVAL_MAX_CALLS", "200"))
    if not with_llm:
        print("model baselines are off: this run makes no model calls and costs nothing.")
        print("pass --with-llm to include them.")
        return

    from eval.llm_baseline import estimate_calls
    from eval.llm_repair import estimate_calls as estimate_repair_calls

    scenarios = build(per_kind=per_kind)
    calls = estimate_calls(scenarios) if 1 in chosen else 0
    calls += estimate_repair_calls(scenarios) if 2 in chosen else 0
    if 4 in chosen:
        from eval.transcripts import ALL

        # Two calls an exchange, and only for anything not already recorded.
        calls += len(ALL) * 2
    # Nova Micro, measured: about 1,000 input and 20 output tokens per scenario.
    cost = (calls * 1000 * 0.035 + calls * 20 * 0.14) / 1_000_000
    print(f"about {calls} model calls, roughly ${cost:.4f}. Ceiling EVAL_MAX_CALLS={ceiling}.")
    if calls > ceiling:
        raise SystemExit(f"refusing to start: {calls} calls exceeds EVAL_MAX_CALLS={ceiling}")


if __name__ == "__main__":
    main()
