"""The only module that calls Bedrock. Every cost control lives here, so there is one file to audit.

Controls: Nova Micro only, a hard call ceiling per voice turn, token and cost accounting, and the
AWS_CA_BUNDLE fix for machines where antivirus intercepts HTTPS.
"""

import os
from pathlib import Path

import boto3
from botocore.exceptions import SSLError
from dotenv import dotenv_values, load_dotenv

from lifepilot_shared.certs import trust_bundle

# Explicitly the project root, not wherever the process happened to start. `load_dotenv()` searches
# up from the current directory, so launching uvicorn from anywhere else silently skipped .env --
# and the first sign of it was a certificate error from botocore with nothing to connect it to the
# working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: The variables this module is responsible for. For these, the file beats the shell: one stale or
#: empty AWS_CA_BUNDLE left in a terminal silently defeats .env, and the only symptom is a
#: certificate error eighty frames deep with nothing pointing at the shell.
#:
#: Everything else in .env loads the ordinary way, so a shell that sets a variable means it. That
#: matters for DATABASE_URL: `make serve` points the demo at local SQLite precisely by setting it,
#: and a blanket override sent the demo to Neon instead -- 1.9 seconds a tool call, silently.
BEDROCK_VARS = ("AWS_CA_BUNDLE", "AWS_REGION", "BEDROCK_MODEL_ID")

load_dotenv(PROJECT_ROOT / ".env")
for _name, _value in dotenv_values(PROJECT_ROOT / ".env").items():
    if _name in BEDROCK_VARS and _value is not None:
        os.environ[_name] = _value

# Nova Micro, Sep 2026: USD per million tokens.
INPUT_COST_PER_MTOK = 0.035
OUTPUT_COST_PER_MTOK = 0.14

# Nova charges nothing extra to write a cache entry and gives a 90% discount on reading one. So a
# cache write costs the ordinary input rate and a read costs a tenth of it.
CACHE_READ_COST_PER_MTOK = INPUT_COST_PER_MTOK * 0.1

# Nova's prompt-caching limits: at least 1K tokens per checkpoint, at most 4 checkpoints, 20K
# cacheable, and a fixed 5-minute TTL. There is no ttl field on a Converse cache point, so the
# "TTLs must not increase across sections" rule cannot be broken from here.
MIN_CACHEABLE_TOKENS = 1_000
CACHE_POINT = {"cachePoint": {"type": "default"}}

# CLAUDE.md: hard ceiling of 3 model calls per voice turn. The Strands event loop has no
# iteration cap of its own, so nothing else would stop a runaway loop.
MAX_CALLS_PER_TURN = 3

DEFAULT_MODEL_ID = "us.amazon.nova-micro-v1:0"


class CallCeilingExceeded(RuntimeError):
    """A turn tried to make more model calls than its ceiling allows."""


class InterceptedHTTPS(RuntimeError):
    """AWS rejected the certificate. On this project that has always been antivirus inspection."""


class Turn:
    """Budget and accounting for one voice turn. Cache reads are counted but do not spend budget.

    Converse reports cached tokens separately from `inputTokens`: the total sent is
    `inputTokens + cacheReadInputTokens + cacheWriteInputTokens`. So the three are added up here
    rather than treated as overlapping, and only the read is discounted.
    """

    def __init__(self, max_calls: int = MAX_CALLS_PER_TURN):
        self.max_calls = max_calls
        self.calls = 0
        self.cache_reads = 0
        self.cache_writes = 0
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
        self.cache_reads += usage.get("cacheReadInputTokens", 0)
        self.cache_writes += usage.get("cacheWriteInputTokens", 0)

    @property
    def cache_hits(self) -> int:
        """Tokens served from the cache this turn. Named for the drawer, which shows it to a judge."""
        return self.cache_reads

    @property
    def cost_usd(self) -> float:
        billed_at_input_rate = self.input_tokens + self.cache_writes
        return (
            billed_at_input_rate * INPUT_COST_PER_MTOK
            + self.cache_reads * CACHE_READ_COST_PER_MTOK
            + self.output_tokens * OUTPUT_COST_PER_MTOK
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
    cache: bool = False,
) -> dict:
    """One plain `converse` call. No Knowledge Bases, Agents or Guardrails: they bill outside tokens.

    `cache=True` asks Bedrock to cache the prefix: the tool block, then the system prompt. Worth it
    only where that prefix is both large and identical call after call, which on this project means
    the routing call and its 18 tool schemas.
    """
    if turn is not None:
        turn.spend()

    if cache:
        tool_config, system = _with_cache_points(tool_config, system)

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


def _with_cache_points(tool_config: dict | None, system: list[dict] | None):
    """A copy of the system block ending in a cache point. One point, and it covers the tool block.

    Measured against `us.amazon.nova-micro-v1:0`, not assumed:

    - A cache point inside `toolConfig.tools` is **rejected**: "extraneous key [cachePoint] is not
      permitted". The AWS guide shows that placement, but not for this model.
    - A cache point in `system` is accepted and caches the whole prefix before it, tools included.
      Bedrock reads the sections tools -> system -> messages, so one point at the end of `system`
      covers both. Proven: an uncached routing call bills 2,023 input tokens; the first cached one
      writes 1,954 and bills 69; every later one reads those 1,954 back and still bills 69.

    A copy, not an edit: the caller's system block is a module-level constant, and appending in place
    would add another cache point every call until Bedrock refused the request.
    """
    if system:
        system = [*system, CACHE_POINT]
    return tool_config, system


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
        f"{PROJECT_ROOT / '.env'} and FRICTION-LOG.md entry 1."
    )
    return " ".join(lines)
