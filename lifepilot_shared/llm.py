"""The only module that calls Bedrock. Every cost control lives here, so there is one file to audit.

Controls: Nova Micro only, a hard call ceiling per voice turn, token and cost accounting, and the
AWS_CA_BUNDLE fix for machines where antivirus intercepts HTTPS.
"""

import os
from pathlib import Path

import boto3
from botocore.exceptions import SSLError
from dotenv import load_dotenv

from lifepilot_shared.certs import trust_bundle

# Explicitly the project root, not wherever the process happened to start. `load_dotenv()` searches
# up from the current directory, so launching uvicorn from anywhere else silently skipped .env --
# and the first sign of it was a certificate error from botocore with nothing to connect it to the
# working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# override=True on purpose: a project-local .env should beat whatever a shell happens to be carrying.
# Without it, one stale or empty AWS_CA_BUNDLE left in a terminal silently defeats the file, and the
# only symptom is a certificate error eighty frames deep with nothing pointing at the shell.
load_dotenv(PROJECT_ROOT / ".env", override=True)

# Nova Micro, Sep 2026: USD per million tokens.
INPUT_COST_PER_MTOK = 0.035
OUTPUT_COST_PER_MTOK = 0.14

# CLAUDE.md: hard ceiling of 3 model calls per voice turn. The Strands event loop has no
# iteration cap of its own, so nothing else would stop a runaway loop.
MAX_CALLS_PER_TURN = 3

DEFAULT_MODEL_ID = "us.amazon.nova-micro-v1:0"


class CallCeilingExceeded(RuntimeError):
    """A turn tried to make more model calls than its ceiling allows."""


class InterceptedHTTPS(RuntimeError):
    """AWS rejected the certificate. On this project that has always been antivirus inspection."""


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


def ca_bundle_problem() -> str | None:
    """Why HTTPS to AWS is about to fail, if it is, in words that name the cause."""
    configured = (os.environ.get("AWS_CA_BUNDLE") or "").strip()
    if configured and not Path(configured).is_file():
        return (
            f"AWS_CA_BUNDLE points at {configured}, which is not there. On a machine whose "
            "antivirus inspects HTTPS, that file is what lets AWS calls succeed."
        )
    return None


def client():
    """A Bedrock runtime client, told explicitly which certificates to trust.

    `verify=` rather than leaving botocore to resolve `AWS_CA_BUNDLE` itself. Resolution depends on
    the environment, the config file, `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` and the order things were
    imported in, and the same code on the same machine reached Bedrock from one terminal and not
    another. Passing the path removes every one of those variables. A fresh session, for the same
    reason: the global default one is created once and shared with whatever created it first.
    """
    problem = ca_bundle_problem()
    if problem:
        raise RuntimeError(problem)

    return boto3.session.Session().client(
        "bedrock-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        verify=trust_bundle(),
    )


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

    try:
        response = client().converse(**kwargs)
    except SSLError as blocked:
        raise InterceptedHTTPS(_ssl_advice()) from blocked

    if turn is not None:
        turn.record(response.get("usage", {}))
    return response


# A proxy changes which server answers, and so which certificate is presented. Set in one terminal
# and not another it is invisible, and it defeats a CA bundle that is otherwise perfectly correct.
PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
RIVAL_CERT_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


def _ssl_advice() -> str:
    """Everything that could be causing this, named, so the next person does not have to guess."""
    configured = (os.environ.get("AWS_CA_BUNDLE") or "").strip()
    lines = ["AWS rejected the certificate, which on this machine means antivirus HTTPS inspection."]
    lines.append(
        f"AWS_CA_BUNDLE is {configured}" if configured else "AWS_CA_BUNDLE is not set"
    )

    proxies = [name for name in PROXY_VARS if os.environ.get(name)]
    if proxies:
        lines.append(
            f"This shell sets {', '.join(proxies)}, so a proxy is answering instead of AWS and "
            "presenting its own certificate. That is the likely cause."
        )
    rivals = [name for name in RIVAL_CERT_VARS if os.environ.get(name)]
    if rivals:
        lines.append(f"This shell also sets {', '.join(rivals)}, which can override the bundle.")

    lines.append(
        "The bundle in use trusts the public roots as well as that file, so neither an intercepted "
        "nor a direct connection should fail on trust alone."
    )
    lines.append(
        f"Run `uv run python -m scripts.check_bedrock` in this same terminal, and see "
        f"{PROJECT_ROOT / '.env'} and docs/friction-log.md entry 1."
    )
    return " ".join(lines)
