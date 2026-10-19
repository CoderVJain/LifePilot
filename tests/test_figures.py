"""The figures are drawn from the CSVs, so they cannot disagree with a published number.

These run matplotlib for real but write to a temporary directory, so they are offline and free.
"""

import csv

import pytest

from eval import figures


@pytest.fixture(autouse=True)
def _headless(monkeypatch, tmp_path):
    monkeypatch.setattr(figures, "RESULTS", tmp_path)
    monkeypatch.setattr(figures, "FIGURES", tmp_path / "figures")


def _write(tmp_path, name: str, rows: list[list]):
    with (tmp_path / name).open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)


def test_a_missing_csv_is_skipped_rather_than_invented(tmp_path, capsys):
    """An experiment that has not been run yet must not produce a chart of nothing."""
    assert figures.build_all() == []
    assert "no CSV yet" in capsys.readouterr().out


def test_blank_lines_separate_blocks(tmp_path):
    """Dropping them let one section run on into the one below it, which silently mixed two
    different tables into one chart."""
    _write(tmp_path, "experiment1.csv", [
        ["# experiment", "1"],
        [],
        ["detector", "precision", "recall"],
        ["lifepilot", "1.000", "1.000"],
        [],
        ["detector", "planted_kind", "found", "total", "recall"],
        ["lifepilot", "overlap", "5", "5", "1.000"],
    ])
    rows = figures._read("experiment1.csv")
    headline = figures._section(rows, "detector", "precision", "recall")
    assert headline == [["lifepilot", "1.000", "1.000"]], "the block stops at the blank line"


def test_a_header_is_matched_cell_by_cell(tmp_path):
    """Two blocks can share a first column name. Matching on it alone picked the wrong block and
    then read its header row as data."""
    _write(tmp_path, "experiment1.csv", [
        ["detector", "precision", "recall", "f1", "tp", "fp", "fn", "clean"],
        ["calendar-overlap", "1.000", "0.250", "0.400", "5", "0", "15", "0"],
        [],
        ["detector", "planted_kind", "found", "total", "recall"],
        ["calendar-overlap", "overlap", "5", "5", "1.000"],
        ["lifepilot", "overlap", "5", "5", "1.000"],
    ])
    rows = figures._read("experiment1.csv")
    block = figures._section(rows, "detector", "planted_kind", "found", "total", "recall")
    assert [row[0] for row in block] == ["calendar-overlap", "lifepilot"]


def test_experiment1_draws_recall_by_kind(tmp_path):
    _write(tmp_path, "experiment1.csv", [
        ["detector", "planted_kind", "found", "total", "recall"],
        ["calendar-overlap", "overlap", "5", "5", "1.000"],
        ["calendar-overlap", "unreachable", "0", "10", "0.000"],
        ["lifepilot", "overlap", "5", "5", "1.000"],
        ["lifepilot", "unreachable", "10", "10", "1.000"],
    ])
    figures._style()
    path = figures.experiment1()
    assert path is not None and path.is_file() and path.stat().st_size > 0


def test_experiment6_keeps_the_two_arms_apart(tmp_path):
    """"without the rule" also starts with "with", which put every row in one arm and skipped the
    figure entirely."""
    _write(tmp_path, "experiment6.csv", [
        ["lifts_in_week", "setting", "dad", "mom", "spread"],
        ["2", "with load_balance", "1", "1", "0"],
        ["2", "without the rule", "2", "0", "2"],
        ["4", "with load_balance", "2", "2", "0"],
        ["4", "without the rule", "4", "0", "4"],
    ])
    figures._style()
    path = figures.experiment6()
    assert path is not None and path.is_file()


def test_the_validated_palette_is_the_one_in_use():
    """Blue is always the baseline and orange always LifePilot, in fixed slot order: colour
    follows the entity, never its rank. The pair passed all five checks of the validator."""
    assert figures.BASELINE == "#2a78d6"
    assert figures.LIFEPILOT == "#eb6834"
    assert figures.SURFACE == "#fcfcfb"
