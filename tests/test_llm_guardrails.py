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


def test_an_empty_ca_bundle_is_treated_as_unset_not_as_a_path(monkeypatch):
    """A shell carrying AWS_CA_BUNDLE="" defeated .env and reported no problem at all."""
    from lifepilot_shared.llm import ca_bundle_problem

    monkeypatch.setenv("AWS_CA_BUNDLE", "   ")
    assert ca_bundle_problem() is None


def test_a_ca_bundle_pointing_nowhere_says_so_before_any_call(monkeypatch):
    from lifepilot_shared.llm import ca_bundle_problem

    monkeypatch.setenv("AWS_CA_BUNDLE", "C:/does/not/exist.pem")
    problem = ca_bundle_problem()
    assert "is not there" in problem
    assert "antivirus" in problem


def test_a_rejected_certificate_explains_itself(monkeypatch):
    """The failure this project hits most is eighty frames deep and mentions neither the antivirus
    nor the setting that fixes it. It should arrive as one sentence that names both."""
    import botocore.exceptions

    from lifepilot_shared import llm

    class Exploding:
        def converse(self, **kwargs):
            raise botocore.exceptions.SSLError(endpoint_url="https://bedrock", error="bad cert")

    monkeypatch.setattr(llm, "client", lambda: Exploding())
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-micro-v1:0")

    with pytest.raises(llm.InterceptedHTTPS) as raised:
        llm.converse(messages=[{"role": "user", "content": [{"text": "hi"}]}])

    message = str(raised.value)
    assert "antivirus" in message
    assert ".env" in message
    assert "friction-log" in message
