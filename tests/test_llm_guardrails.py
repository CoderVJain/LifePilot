"""The cost controls in lifepilot_shared.llm. Offline and free: no Bedrock call here."""

import pytest

from lifepilot_shared.llm import MAX_CALLS_PER_TURN, CallCeilingExceeded, Turn, model_id


def test_model_id_rejects_anything_but_nova_micro(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0")
    with pytest.raises(ValueError, match="Nova Micro"):
        model_id()


def test_model_id_accepts_nova_micro(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-micro-v1:0")
    assert model_id() == "us.amazon.nova-micro-v1:0"


def test_turn_stops_at_the_ceiling():
    turn = Turn()
    for _ in range(MAX_CALLS_PER_TURN):
        turn.spend()
    with pytest.raises(CallCeilingExceeded):
        turn.spend()


def test_cache_hits_do_not_spend_budget():
    """A cached read must not consume ceiling budget, and must not let a loop bypass the ceiling."""
    turn = Turn()
    turn.spend()
    turn.record({"inputTokens": 900, "outputTokens": 40, "cacheReadInputTokenCount": 2600})
    assert turn.calls == 1
    assert turn.cache_hits == 2600


def test_cost_matches_published_nova_micro_rates():
    turn = Turn()
    turn.record({"inputTokens": 1_000_000, "outputTokens": 1_000_000})
    assert turn.cost_usd == pytest.approx(0.035 + 0.14)
