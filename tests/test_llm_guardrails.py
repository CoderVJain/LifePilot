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
    """A cached read must not consume ceiling budget, and must not let a loop bypass the ceiling.

    The field is `cacheReadInputTokens`. This test used to supply `cacheReadInputTokenCount`, which
    is the InvokeModel name, so it passed while the real accounting read zero for every cached turn.
    """
    turn = Turn()
    turn.spend()
    turn.record({"inputTokens": 900, "outputTokens": 40, "cacheReadInputTokens": 2600})
    assert turn.calls == 1
    assert turn.cache_hits == 2600
    assert turn.cache_reads == 2600


def test_a_cached_read_is_billed_at_a_tenth_of_the_input_rate():
    """Nova charges nothing extra to write a cache entry and 90% less to read one."""
    cached = Turn()
    cached.record({"inputTokens": 0, "outputTokens": 0, "cacheReadInputTokens": 1_000_000})
    assert cached.cost_usd == pytest.approx(0.035 * 0.1)

    written = Turn()
    written.record({"inputTokens": 0, "outputTokens": 0, "cacheWriteInputTokens": 1_000_000})
    assert written.cost_usd == pytest.approx(0.035), "a write costs the ordinary input rate"


def test_the_cache_point_goes_in_system_and_never_in_the_tool_list():
    """Nova rejects a cache point inside toolConfig.tools: "extraneous key [cachePoint] is not
    permitted". One point at the end of `system` caches the prefix before it, tools included.
    """
    from lifepilot_shared.llm import CACHE_POINT, _with_cache_points

    tools = [{"toolSpec": {"name": "get_schedule"}}]
    config = {"tools": tools, "toolChoice": {"any": {}}}
    system = [{"text": "you route utterances"}]

    for _ in range(3):
        cached_config, cached_system = _with_cache_points(config, system)

    assert CACHE_POINT not in cached_config["tools"], "Nova refuses the request outright"
    assert cached_config == config
    assert cached_system[-1] == CACHE_POINT
    assert len(system) == 1, "the caller's constant is untouched"


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


# --------------------------------------------------------------------------- .env and the shell


def test_the_file_wins_for_the_variables_llm_owns():
    """A stale AWS_CA_BUNDLE in a terminal silently defeats .env, and the symptom is a certificate
    error eighty frames deep. For these three, the file is the authority."""
    from lifepilot_shared.llm import BEDROCK_VARS

    assert BEDROCK_VARS == ("AWS_CA_BUNDLE", "AWS_REGION", "BEDROCK_MODEL_ID")


def test_the_shell_wins_for_everything_else():
    """`make serve` points the demo at local SQLite by setting DATABASE_URL in the shell. A blanket
    override sent it to Neon instead -- 1.9 seconds a tool call, with nothing said about it."""
    import subprocess
    import sys

    probe = (
        "import os; os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///probe.db';"
        "import lifepilot_shared.llm;"
        "print(os.environ['DATABASE_URL'])"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.stdout.strip() == "sqlite+pysqlite:///probe.db", result.stderr
