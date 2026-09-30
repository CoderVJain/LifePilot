"""The only module that calls Bedrock. Every cost control lives here, so there is one file to audit.

Controls: Nova Micro only, a hard call ceiling per voice turn, token and cost accounting, and the
AWS_CA_BUNDLE fix for machines where antivirus intercepts HTTPS.
"""

import os

import boto3
from dotenv import load_dotenv

load_dotenv()

# Nova Micro, Sep 2026: USD per million tokens.
INPUT_COST_PER_MTOK = 0.035
OUTPUT_COST_PER_MTOK = 0.14

# CLAUDE.md: hard ceiling of 3 model calls per voice turn. The Strands event loop has no
# iteration cap of its own, so nothing else would stop a runaway loop.
MAX_CALLS_PER_TURN = 3

DEFAULT_MODEL_ID = "us.amazon.nova-micro-v1:0"


class CallCeilingExceeded(RuntimeError):
    """A turn tried to make more model calls than its ceiling allows."""


class Turn:
    """Budget and accounting for one voice turn. Cache hits are counted but do not spend budget."""

    def __init__(self, max_calls: int = MAX_CALLS_PER_TURN):
        self.max_calls = max_calls
        self.calls = 0
        self.cache_hits = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def spend(self) -> None:
        if self.calls >= self.max_calls:
            raise CallCeilingExceeded(
                f"turn already made {self.calls} model calls (ceiling {self.max_calls})"
            )
        self.calls += 1

    def record(self, usage: dict) -> None:
        self.input_tokens += usage.get("inputTokens", 0)
        self.output_tokens += usage.get("outputTokens", 0)
        self.cache_hits += usage.get("cacheReadInputTokenCount", 0)

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens * INPUT_COST_PER_MTOK + self.output_tokens * OUTPUT_COST_PER_MTOK
        ) / 1_000_000


def model_id() -> str:
    """The configured model, rejecting anything but Nova Micro. Cost rule, enforced not documented."""
    configured = os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    if "nova-micro" not in configured:
        raise ValueError(f"BEDROCK_MODEL_ID must be a Nova Micro profile, got {configured!r}")
    return configured


def client():
    """A Bedrock runtime client. AWS_CA_BUNDLE from .env is already in the environment via load_dotenv."""
    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def converse(
    messages: list[dict],
    *,
    system: list[dict] | None = None,
    tool_config: dict | None = None,
    turn: Turn | None = None,
    max_tokens: int = 512,
) -> dict:
    """One plain `converse` call. No Knowledge Bases, Agents or Guardrails: they bill outside tokens."""
    if turn is not None:
        turn.spend()

    kwargs: dict = {
        "modelId": model_id(),
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.0},
    }
    if system:
        kwargs["system"] = system
    if tool_config:
        kwargs["toolConfig"] = tool_config

    response = client().converse(**kwargs)
    if turn is not None:
        turn.record(response.get("usage", {}))
    return response
