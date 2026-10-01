"""The product, end to end: words in, spoken answer out. Offline and free.

Everything else in this suite tests a layer. This replays recorded model answers through the real
agent, the real MCP client, a real server on a real socket and a real database, and asks the only
question a person asks: did the reply answer what was said?

Four rounds of bugs reached a human tester while 298 tests passed, because every one of those tests
checked that the right tool was called with the right arguments. These check the answer.

Recordings live in eval/cassettes. A missing one fails loudly rather than reaching for a paid API:
re-record deliberately with `uv run python -m eval.run --exp 4 --with-llm`.
"""

import pytest

from eval.experiment4 import judge
from eval.harness import answer, running_stack
from eval.transcripts import ALL


@pytest.fixture(scope="module")
def answered():
    """Every transcript, run once through the whole stack."""
    results = []
    with running_stack("experiment4", live=False) as (client, _cassette):
        state: dict = {}
        for exchange in ALL:
            if not exchange.follows_on:
                state = {}
            results.append(answer(client, exchange, state))
    return results


def verdicts(answered):
    return [judge(result) for result in answered]


def test_every_transcript_chooses_the_right_tool(answered):
    """Known misses are listed in the transcripts and excluded here, so this catches new breakage.
    The eval still scores them against the total; experiment4.csv has the honest number."""
    known = {e.said for e in ALL if e.known_miss}
    wrong = [v for v in verdicts(answered) if not v.tool_ok and v.said not in known]
    assert not wrong, "\n".join(f'"{v.said}" -> {v.routed}, wanted {v.expected}' for v in wrong)


def test_known_misses_are_still_missing(answered):
    """If one starts passing, the marker is stale and should be deleted rather than left to rot."""
    known = {e.said for e in ALL if e.known_miss}
    now_passing = [v.said for v in verdicts(answered) if v.said in known and v.tool_ok]
    assert not now_passing, f"these now pass, so drop their known_miss: {now_passing}"


def test_every_transcript_gets_the_right_arguments(answered):
    wrong = [v for v in verdicts(answered) if not v.args_ok]
    assert not wrong, "\n".join(f'"{v.said}": {"; ".join(v.complaints)}' for v in wrong)


def test_every_answer_answers_the_question(answered):
    """The one that matters. A true sentence that does not answer what was asked is a failure."""
    wrong = [v for v in verdicts(answered) if not v.answer_ok]
    assert not wrong, "\n".join(
        f'"{v.said}": {"; ".join(v.complaints)}\n    said: {v.spoken}' for v in wrong
    )


def test_nothing_spoken_anywhere_contains_a_timestamp(answered):
    """These are read aloud. This has been fixed three times in three different places."""
    offenders = [
        (result.exchange.said, result.spoken)
        for result in answered
        if "2026-" in (result.spoken or "") or "T16:" in (result.spoken or "")
    ]
    assert not offenders, offenders


def test_no_exchange_raised(answered):
    broken = [(r.exchange.said, r.error) for r in answered if r.error]
    assert not broken, broken


def test_a_child_never_hears_a_parents_meeting(answered):
    """Differentiator #9, checked on what was actually said rather than on a tool result."""
    for result in answered:
        if result.exchange.speaker == "Aarav":
            assert "performance review" not in (result.spoken or "").lower()


def test_out_of_scope_requests_are_declined_rather_than_improvised(answered):
    declined = [r for r in answered if r.exchange.tool == "cannot_help"]
    assert len(declined) >= 4
    for result in declined:
        assert result.routed == "cannot_help", f'"{result.exchange.said}" -> {result.routed}'
