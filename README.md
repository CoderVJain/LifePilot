# LifePilot

**Other assistants show your family's calendar. LifePilot fixes it.**

A family coordination agent for working parents, built as an **MCP server for Alexa+**. It works out
whether the week can actually be done by the people available, finds what breaks, decides who should
handle it and why, and repairs the plan with the fewest changes. **A parent approves before anything
changes.**

A conflict here is not "two events at the same time". It is *a child who needs to be somewhere and no
eligible adult can get them there* — counting travel time, who can drive, and the family's own rules.
In the demo week no two events overlap, and Thursday's football pickup still cannot be made.

## Run it

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/). No AWS account is required for the tests.

```bash
uv sync
cp .env.example .env          # then set BEDROCK_MODEL_ID and AWS credentials for the voice path

# seed the demo family (synthetic: no real child's data, ever)
DATABASE_URL="sqlite+pysqlite:///demo.db" uv run python -m eval.generate --seed-db

# two processes
DATABASE_URL="sqlite+pysqlite:///demo.db" uv run uvicorn lifepilot.server:app --port 8931
uv run uvicorn simulator.app:app --port 8000
```

Open <http://127.0.0.1:8000>. Set `LIFEPILOT_LLM=0` on the simulator to run the offline keyword path
with no Bedrock calls at all.

Try, in order: `any problems this week` → `who should pick up Aarav` → `why not Grandpa` →
`fix our week` → `yes` → `what is the piano class timing` → `book a dentist at 10 on Friday` → `yes`.

### Tests and numbers

```bash
uv run pytest                           # 369 tests, offline, free
uv run python -m eval.run --exp 4       # end-to-end, replayed from recordings, free
uv run python -m eval.run --exp 1       # conflict detection vs. an overlap check
```

Every number in this repo comes from `eval/`, never typed in by hand. Experiment 4 runs 35 real
utterances through the whole stack — words → Nova → tool choice → MCP → spoken answer — and currently
scores **100% tool correctness, 100% argument correctness, 100% answer correctness**. Model replies are
recorded to `eval/cassettes/`, so re-running costs nothing; `--with-llm` re-records deliberately.

## Being straight about three things

**This is our own simulated Alexa+ experience, not a real Echo.** The Alexa+ MCP Toolkit, the
`alexa-ai` CLI and the device simulator are US-only and partner-gated, so we ship a web client that
plays the same role. The rules allow this. The MCP server itself is real: official MCP Python SDK,
Streamable HTTP, spec 2025-11-25 negotiated on the wire and proven in `tests/test_mcp_wire.py`.

**LifePilot cannot tell who is speaking.** A classic Alexa skill can receive a `personId` from a
matched Voice Profile. An Alexa+ MCP add-on receives an OAuth token for the *linked account* — one
account, not one person. A session therefore assumes the linked parent, and the speaker switcher is a
labelled demo control for seeing the other role views. Roles are enforced on the server from the
database on every call, never in a prompt, so a wrong assumption changes whose week is shown and never
what the rules allow.

**When LifePilot speaks first, that is the simulator.** There is no documented way for an add-on's
server to start a conversation; `ProactiveEvents` is a classic-skill API that delivers a notification,
not speech. Every unprompted message in the UI carries a "simulated" badge, and that path makes **zero
model calls** — the sentences come from templates, because a timer pointed at Bedrock bills for as long
as the page is open.

Both limitations are written up with sources in [docs/alexa-platform-limits.md](docs/alexa-platform-limits.md).

## How it is put together

```
browser      thin: mic → text, speaks replies, renders MCP App cards
   │         WebSocket
simulator/   FastAPI + Strands agent + Bedrock Nova Micro → MCP client
   │         Streamable HTTP, MCP spec 2025-11-25
lifepilot/   FastAPI + official MCP Python SDK
             engine/ (reachability, allocation, rules) · solver/ (OR-Tools CP-SAT) · SQLAlchemy
lifepilot_shared/llm.py   the only module that calls Bedrock
eval/        synthetic families, golden transcripts, experiments
```

Writes never happen directly. A write tool creates a **pending proposal**; `approve_proposal`, called
by a parent, is the only thing that executes one.

**Cost discipline:** Nova Micro only, a hard ceiling of 3 model calls per voice turn enforced in
`llm.py`, prompt caching on the tool-schema block, parse caching, and `EVAL_MAX_CALLS` on every eval
run. What-if, why-not, reachability, repair and reminders are solver and code work with no model call.

## Scope

Seeded synthetic data; no real calendar sync, no Maps API (fixed travel-time table), no upload screens.
WhatsApp is future work: the official API cannot read a parent's personal chats.

## School email

One Gmail sign-in, then everything is voice. LifePilot asks for `gmail.readonly` and nothing else, so
no token it holds can send, modify or delete mail — Google enforces that, not us.

**Linking:** click **Link Gmail** on the page, sign in, come back. The sign-in is served by the MCP
server (`/oauth/start`, `/oauth/callback` on port 8931), not the simulator, so a Gmail token never
enters the process running the agent. Then say which sender is the school — *"only read emails from
the school office"* — because a fresh link reads nothing until a parent says what it may read.

**Be clear about what we do promise ourselves.** `gmail.readonly` technically allows reading the whole
inbox. LifePilot reads only the senders a parent has allowed: every Gmail query is built from that
allowlist, a query without a sender filter cannot be constructed, and each message's sender is checked
again when it arrives. That narrowing is our code's promise, not Google's.

Of an email LifePilot keeps the Gmail message id, the sender, the date and the tasks it extracted.
The subject and body are held for one extraction and dropped; `school_message` has no column for
them. Tokens are encrypted at rest with Fernet (`TOKEN_ENCRYPTION_KEY`), server-side only, never sent
to the model, the browser or a log. "Disconnect my email" revokes with Google and deletes every row.

Extraction is one Nova Micro call carrying exactly one output-only tool, forced with `toolChoice`.
No action tool is in scope, so an instruction inside an email has nothing to reach for. Email is
checked only when asked for, never polled, and each message costs at most one model call ever.

**Google limits while the OAuth app is in Testing mode:** up to 100 test users, refresh tokens expire
every 7 days (reconnect weekly), and users see an "unverified app" screen. A public launch would need
Google verification and a CASA assessment for restricted Gmail scopes. The demo uses a dedicated demo
account and fake school emails we wrote ourselves — never a real inbox, never a real school.

## Licence

MIT. See [LICENSE](LICENSE).
