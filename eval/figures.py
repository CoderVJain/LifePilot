"""Figures for the README and the video, drawn from the CSVs the experiments wrote.

**The CSV is the source of truth.** Every figure reads one, and none recomputes anything, so a
chart cannot disagree with a published number -- which is the whole point of `CLAUDE.md`'s rule that
nothing is typed in by hand. A missing CSV is skipped with a note rather than invented.

Design decisions, all from the dataviz method and not from taste:

* **Two series everywhere, in fixed slot order**: blue is always the baseline, orange always
  LifePilot. Colour follows the entity, never its rank, so the eye learns the pair once.
* The categorical pair is validated, not eyeballed: `#2a78d6` / `#eb6834` on a `#fcfcfb` surface
  passes all five checks, worst-adjacent CVD Delta E 24.7 against a target of 8.
* **A legend is always present, and every bar is directly labelled**, so identity and value are
  never carried by colour alone.
* Recessive axes: no top or right spine, a faint y-grid behind the bars, text in ink rather than
  in the series colour.
* One axis per chart. Where an experiment has two scales -- a share and a count of days -- it gets
  two panels rather than two y-axes.
"""

import csv
from pathlib import Path

import matplotlib

# Agg: these run headless in `make eval`, and importing pyplot without a backend set opens a
# window-system connection that is not there.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  - must follow matplotlib.use
from matplotlib.ticker import PercentFormatter  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
FIGURES = RESULTS / "figures"

SURFACE = "#fcfcfb"
BASELINE = "#2a78d6"
LIFEPILOT = "#eb6834"
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e3e2de"


def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.size": 10,
        "text.color": INK,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.edgecolor": GRID,
    })


def _frame(ax, ylabel: str = "", ymax: float | None = None, percent: bool = False) -> None:
    """Recessive axes: the data is the ink, the frame stays out of the way.

    `percent` makes the tick labels agree with the bar labels. A 0.0-1.0 axis beside a bar reading
    "100%" is two units for one quantity, and the reader has to reconcile them.
    """
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    if ylabel:
        ax.set_ylabel(ylabel)
    if ymax is not None:
        ax.set_ylim(0, ymax)
    if percent:
        ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))


def _pair_bars(ax, labels, left, right, left_name, right_name, fmt="{:.0%}"):
    """Two series, grouped, every bar directly labelled. Blue is always the baseline."""
    positions = range(len(labels))
    width = 0.3
    gap = 0.012  # a surface gap between adjacent fills, per the mark spec

    bars_left = ax.bar(
        [p - width / 2 - gap for p in positions], left, width, label=left_name,
        color=BASELINE, edgecolor=SURFACE, linewidth=1.2,
    )
    bars_right = ax.bar(
        [p + width / 2 + gap for p in positions], right, width, label=right_name,
        color=LIFEPILOT, edgecolor=SURFACE, linewidth=1.2,
    )
    for group in (bars_left, bars_right):
        for bar in group:
            ax.annotate(
                fmt.format(bar.get_height()),
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                textcoords="offset points", xytext=(0, 3),
                ha="center", fontsize=8.5, color=MUTED,
            )
    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels)
    return bars_left, bars_right


def _legend(ax) -> None:
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, 1.02), ncol=2, fontsize=9)


def _read(name: str) -> list[list[str]]:
    """A CSV's rows, comment lines dropped. Returns [] when the experiment has not been run."""
    path = RESULTS / name
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        # Comment lines go; blank lines stay. They are what separates one block from the next, and
        # dropping them let a section run on into the one below it.
        return [row for row in csv.reader(handle) if not (row and row[0].startswith("#"))]


def _section(rows: list[list[str]], *header: str) -> list[list[str]]:
    """The block of rows under the header row that starts with `header`.

    The header is matched cell by cell, as many cells as are given. A CSV can hold two blocks whose
    first column has the same name -- experiment 1 has a headline `detector,precision,...` and a
    per-kind `detector,planted_kind,...` -- and matching on the first cell alone picked the wrong
    one and then read its header as data.
    """
    width = len(header)
    for index, row in enumerate(rows):
        if len(row) >= width and tuple(row[:width]) == header:
            block = []
            for following in rows[index + 1:]:
                if not following or not following[0]:
                    break
                block.append(following)
            return block
    return []


def _save(fig, name: str) -> Path:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / name
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------------- the figures


def experiment1() -> Path | None:
    """Recall by kind of conflict. The headline: an overlap check only finds overlaps."""
    rows = _read("experiment1.csv")
    block = _section(rows, "detector", "planted_kind", "found", "total", "recall")
    if not block:
        return None

    recall: dict[str, dict[str, float]] = {}
    for detector, kind, _found, _total, value in block:
        recall.setdefault(kind, {})[detector] = float(value)

    kinds = sorted(recall)
    labels = [kind.replace("_", " ") for kind in kinds]
    overlap = [recall[kind].get("calendar-overlap", 0.0) for kind in kinds]
    ours = [recall[kind].get("lifepilot", 0.0) for kind in kinds]

    fig, ax = plt.subplots(figsize=(7, 3.6))
    _pair_bars(ax, labels, overlap, ours, "calendar overlap check", "LifePilot")
    _frame(ax, "recall", ymax=1.18, percent=True)
    ax.set_title("A calendar check only finds the conflicts that overlap", loc="left", pad=28)
    _legend(ax)
    return _save(fig, "experiment1-recall-by-kind.png")


def experiment3() -> Path | None:
    """What storing the family's rules changes about what gets proposed."""
    rows = _read("experiment3.csv")
    block = _section(rows, "setting", "weeks")
    if len(block) < 2:
        return None

    by_setting = {row[0]: row for row in block}
    stored = by_setting.get("rules stored")
    blind = by_setting.get("rules not stored")
    if stored is None or blind is None:
        return None

    labels = ["parent accepted\nthe plan", "plan broke\na rule", "week left\nbroken"]
    blind_values = [float(blind[2]), float(blind[3]), float(blind[4])]
    stored_values = [float(stored[2]), float(stored[3]), float(stored[4])]

    fig, ax = plt.subplots(figsize=(7, 3.6))
    _pair_bars(ax, labels, blind_values, stored_values, "rules not stored", "rules stored")
    _frame(ax, "share of weeks", ymax=1.18, percent=True)
    ax.set_title("A rule the solver has not been told is a rule it breaks", loc="left", pad=28)
    _legend(ax)
    return _save(fig, "experiment3-rules.png")


def experiment4() -> Path | None:
    """Tool granularity: the coarse set was meant to help a small model and does not."""
    rows = _read("experiment4.csv")
    block = _section(rows, "toolset", "schemas")
    if len(block) < 2:
        return None

    by_setting = {row[0]: row for row in block}
    full, coarse = by_setting.get("full"), by_setting.get("coarse")
    if full is None or coarse is None:
        return None

    labels = ["right tool", "right arguments", "right answer", "all three"]
    coarse_values = [float(coarse[i]) for i in (2, 3, 4, 5)]
    full_values = [float(full[i]) for i in (2, 3, 4, 5)]

    fig, ax = plt.subplots(figsize=(7, 3.6))
    _pair_bars(
        ax, labels, coarse_values, full_values,
        f"{coarse[1]} merged tools", f"{full[1]} tools",
    )
    _frame(ax, "share of 45 exchanges", ymax=1.18, percent=True)
    ax.set_title("Merging tools made the small model worse, not better", loc="left", pad=28)
    _legend(ax)
    return _save(fig, "experiment4-toolsets.png")


def experiment5() -> Path | None:
    """Two panels, because a share and a number of days are different scales. Never two y-axes."""
    rows = _read("experiment5.csv")
    block = _section(rows, "system", "planted_at_risk")
    if len(block) < 2:
        return None

    by_system = {row[0]: row for row in block}
    ours, baseline = by_system.get("lifepilot"), by_system.get("deadline-only")
    if ours is None or baseline is None:
        return None

    fig, (left, right) = plt.subplots(1, 2, figsize=(8.4, 3.6))

    _pair_bars(
        left, ["tasks caught", "false alarms"],
        [float(baseline[3]), float(baseline[5])],
        [float(ours[3]), float(ours[5])],
        "deadline reminder", "LifePilot",
    )
    _frame(left, "share", ymax=1.18, percent=True)
    left.set_title("What it catches", loc="left", pad=28)
    _legend(left)

    _pair_bars(
        right, ["mean", "median"],
        [float(baseline[6]), float(baseline[7])],
        [float(ours[6]), float(ours[7])],
        "deadline reminder", "LifePilot",
        fmt="{:.1f}d",
    )
    _frame(right, "days of warning", ymax=max(float(ours[6]), float(ours[7])) * 1.45)
    right.set_title("How much warning", loc="left", pad=28)
    _legend(right)

    fig.suptitle("")
    return _save(fig, "experiment5-forgetting.png")


def experiment6() -> Path | None:
    """Pickup spread with and without the soft rule. Reported, never headlined."""
    rows = _read("experiment6.csv")
    block = _section(rows, "lifts_in_week", "setting")
    if not block:
        return None

    sizes, with_rule, without = [], [], []
    for row in block:
        lifts, setting, spread = row[0], row[1], int(row[4])
        # "without the rule" also starts with "with", which quietly put every row in one arm and
        # skipped the figure entirely.
        if "without" not in setting:
            sizes.append(int(lifts))
            with_rule.append(spread)
        else:
            without.append(spread)
    if not sizes or len(without) != len(sizes):
        return None

    fig, ax = plt.subplots(figsize=(7, 3.6))
    _pair_bars(
        ax, [str(size) for size in sizes], without, with_rule,
        "without the rule", "with load_balance",
        fmt="{:.0f}",
    )
    _frame(ax, "gap between the two parents", ymax=max(without) * 1.35)
    ax.set_xlabel("lifts in the week")
    ax.set_title("Stating the rule is what evens the pickups out", loc="left", pad=28)
    _legend(ax)
    return _save(fig, "experiment6-load.png")


FIGURE_BUILDERS = (
    ("1", experiment1),
    ("3", experiment3),
    ("4", experiment4),
    ("5", experiment5),
    ("6", experiment6),
)


def build_all() -> list[Path]:
    """Every figure whose CSV exists. Skips the rest with a note rather than inventing data."""
    _style()
    written = []
    for number, builder in FIGURE_BUILDERS:
        path = builder()
        if path is None:
            print(f"  experiment {number}: no CSV yet, figure skipped")
            continue
        written.append(path)
        print(f"  wrote {path.relative_to(RESULTS.parent)}")
    return written


if __name__ == "__main__":
    print("figures:")
    build_all()
