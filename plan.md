# LifePilot — build plan

Working roadmap. `CLAUDE.md` is the spec (what and why); this file is the sequence (what order, what is
done). Update the checkboxes as work lands.

**Deadline:** Oct 23, 2026, 12:00 PM PDT · **Internal target:** Oct 20 · **Started:** Sep 29, 2026.

Phases are priority order. **Phases 1–8 plus experiments 1 and 2 are the minimum credible entry.**
If time runs short, drop in this order: stretch rows → Skills extension → #6 swap → #7 email.

---

## Verified facts

Established by inspecting this machine and the published wheels. Not assumptions.

| Fact | How we know |
|---|---|
| Python 3.12.4, uv 0.10.11, node 22.23.2, git 2.49 | `--version` |
| No `make`, no local Postgres, not yet a git repo | `command not found` |
| AWS works: IAM user `counter-dev`, `us-east-1` | `aws sts get-caller-identity` |
| `us.amazon.nova-micro-v1:0` ACTIVE | `aws bedrock list-inference-profiles` |
| `mcp 2.1.1` serves **2025-11-25** end to end | wire test negotiates it against a real uvicorn server |
| **Avast corrupts loopback HTTP** when the request carries `MCP-Protocol-Version` | a fixed-bytes socket server returns different bytes to the client with that header than without (friction log 7) |
| Upper pin `mcp<2.2` is forced by `strands-agents 1.57.1` | its `requires_dist` |
| Strands' modern API is `MCPClient(url=...)`; its published docs are stale | `strands/tools/mcp/_compat.py` |
| MCP Apps is first-party | `mcp/server/apps.py` |
| MCP **Skills** extension is *not* in the SDK, but `MethodBinding` lets us serve it | `mcp/server/extension.py:58` |
| Nova Micro has **no structured outputs**; tool calling yes | model card |
| Nova hallucinates on JSON tool results; `BedrockModel` auto-fixes it | `strands/models/bedrock.py:954` |
| Strands event loop has **no** iteration cap | only raises `MaxTokensReachedException` |
| Alexa+ MCP Toolkit is **US-only** — hence the simulator | developer.amazon.com |
| Rules explicitly allow simulating Alexa+ "via a web app" | Devpost resources |
| `SpeechRecognition` needs network; absent in Firefox by default | MDN |

### Blocker already solved: Avast TLS interception

Avast intercepts HTTPS with its own root CA. Python's `ssl` trusts it via the Windows store, but
**boto3 and awscli use certifi and fail** with `CERTIFICATE_VERIFY_FAILED` on every AWS call — so the
cause is not obvious. Verified fix:

```
AWS_CA_BUNDLE=C:\ProgramData\Avast Software\Avast\wscert.pem
```

Applied in `lifepilot_shared/llm.py` so both processes inherit it. First entry in the friction log.

### Opportunity: ship the MCP Skills extension

`io.modelcontextprotocol/skills` (SEP-2640) went **Final on Sep 13, 2026**, and the hackathon's "Build
with Agent Skills" resource points at it. The Python SDK does not implement it, but `skills/list` and
`skills/get` are not spec methods, so they are legal `MethodBinding`s. Shipping it hits a named judging
signal, and offering it upstream is our **Open Source mini challenge** entry — one piece of work, two
rewards.

---

## Phase 1 — Initialize the project

No model calls, no network beyond package installs.

- [x] `git init`, `.gitignore` (`.env`, `.venv/`, `eval/.cache/`, `eval/results/`, `__pycache__`), MIT
      `LICENSE`. Public GitHub repo with **MIT visible in the About section** — hard requirement 3.
- [x] `pyproject.toml` via uv, Python 3.12, pins commented with their reasons: `mcp>=2.1,<2.2` (forced
      by strands), `strands-agents`, `ortools`, `fastapi`, `uvicorn`, `sqlalchemy>=2.1`, `alembic`,
      `psycopg[binary]`, `boto3`, `cryptography`, `google-api-python-client`, `google-auth-oauthlib`,
      `pydantic`; dev `pytest`, `pytest-asyncio`, `ruff`. `uv sync` creates `.venv`.
- [x] `.env.example` — every var in `CLAUDE.md` plus `AWS_CA_BUNDLE`, `AWS_REGION`.
- [x] `Makefile` — `dev`, `test`, `seed`, `eval`, `lint`, each delegating to `uv run` so the same work
      runs without `make` on Windows.
- [x] `docs/friction-log.md`, starting with the Avast finding. Worth up to 10% of judging.
- [x] Package skeletons; `pytest` collects zero tests and exits 0.

**Verify:** `uv sync` · `uv run pytest` · `uv run ruff check` · `git status` shows no secrets staged.

## Phase 2 — Prove the model assumptions (~$0.002)

First real Bedrock calls, now that a venv with `boto3` exists.

- [x] `scripts/probe_bedrock.py` — confirm `AWS_CA_BUNDLE` works from inside the venv and Nova Micro
      answers.
- [x] **Forced tool choice** — the one unverified assumption everything rests on. One output-only tool
      (`title`, `child`, `due`, `category`, `prep_days`) with `toolChoice: {tool: {name: ...}}`. Assert
      exactly one `toolUse` and no stray text. Fallback: `toolChoice: {any: {}}` with a single tool.
- [x] Same call on an email carrying an injection line. Assert the output is still only the schema. Keep
      as a test fixture — evidence, not a promise.
- [x] Print token counts and cost; record in the friction log.

## Phase 3 — Data layer and seeded family

- [x] `lifepilot/db/models.py` — SQLAlchemy 2.1 typed models for every entity in `CLAUDE.md`. Portable
      `sa.JSON` only. `school_message` has **no subject and no body columns**, enforced by schema.
- [x] Alembic + first migration.
- [x] `eval/generate.py` — seeded family (Dad, Mom, Aarav, Anaya, Grandpa), locations, `travel_time`.
- [x] `make seed` against SQLite and Neon (PostgreSQL 18.6). Portable `sa.JSON` verified on both:
      `member_ids` returns a list and `rule.params` a dict from Postgres, and the role-aware views
      answer correctly against it. `tests/conftest.py` clears `DATABASE_URL` so the suite stays
      offline and free whatever is in `.env`.

**Verify:** round-trip tests on SQLite, offline and free · same seed twice → identical rows.

## Phase 4 — MCP server skeleton

- [x] `MCPServer` mounted via `streamable_http_app(streamable_http_path="/mcp")`. The **host** lifespan
      must enter `mcp.session_manager.run()` or every request hangs.
- [x] `get_family`, `get_schedule`, **role-aware from the start** — a child sees parents' work as
      "Busy", a caregiver sees only their assignments. Tool layer, never a prompt. (#9 is cheap now,
      expensive to retrofit.)
- [x] Test asserting the negotiated protocol version is **2025-11-25 or later on the wire** —
      requirements 1 and 2 proven, not claimed.

## Phase 5 — The simulated Alexa+ web UI

Alexa+ is US-only, so this UI *is* the demo. Vanilla HTML/CSS/JS, **no build step**. Real Alexa+ on a
display device renders as a chat thread, so that shape is both accurate and simple.

- [x] `simulator/static/index.html` — conversation thread, large mic button, typed input, speaker
      switcher, collapsible debug drawer.
- [x] `app.js` — WebSocket; `SpeechRecognition` in, `speechSynthesis` out; card renderers; iframe bridge.
- [x] `app.css` — our own identity, light and dark.
- [x] Mic states idle / listening / thinking / speaking, visibly distinct.
- [x] **Typed input always available** — `SpeechRecognition` needs network and is absent in Firefox;
      feature-detect and notify rather than die. Also demo insurance.
- [x] Speaker switcher (Dad / Mom / Aarav / Grandpa) = separate sessions, active role badged.
- [~] Cards inline: renderer and card shell are in place, with **family** and **schedule** cards
      working. Conflict, proposal, what-if, swap and school-task cards arrive with the phases that
      produce them (6, 10, 9, 12, 11). The MCP Apps iframe host is phase 10.
- [x] Debug drawer: tool, arguments, solver verdict, `solve_ms`, reasons, **running model-call count and
      estimated cost** — makes the cost discipline visible to a judge.
- [x] Persistent labels "Simulated Alexa+ experience" and "Demo school · fake emails" (reqs 5, 10).
      **No Amazon/Alexa logos, no Echo look-alike, no blue-ring trade dress** (req 8).
- [~] README states Chrome/Edge — the page feature-detects and falls back to typing; the README
      sentence lands with the rest of the README in phase 13.

### Phase 5b — the Bedrock path (done ahead of plan)

- [x] `simulator/agent.py` — Nova Micro routes the utterance to a tool (forced `toolChoice`), the
      server answers, Nova words the reply. Two model calls per turn, one when routing declines.
- [x] `speaker` is stripped from every schema the model sees and injected from the session, so the
      model cannot hand a child a parent's view. Tested.
- [x] The model words **facts the server computed**, never raw tool JSON. Handing it JSON produced
      fluent falsehoods; see friction log 12.
- [x] `get_schedule` returns a `members` list per event, so nothing can misattribute an event.
- [x] `LIFEPILOT_LLM=0` falls back to the keyword router: free, offline, and the baseline for
      experiments 1-4.
- [x] Measured: $0.00016903 for four turns, 1.3-4.4 s each.
- [ ] Prompt caching (`CacheConfig`, 5-minute TTL) — the next lever on latency and cost.

## Phase 6 — #1 can-it-actually-happen conflicts

The headline: not "two events overlap" but *a child needs to be somewhere and no eligible adult can get
them there*.

- [x] `engine/reachability.py`, pure — no DB, no model calls. For each event needing transport at `T`,
      location `L`: candidates who `can_drive`, filtered by `eligibility` rules; `prev` = last
      commitment ending at or before `T`; `arrival = prev.end + travel_time[prev.location][L]`;
      reachable iff `arrival <= T`. Also check the **return leg** —
      `T + handling + travel_time[L][next.location] <= next.start` — so an assignment cannot silently
      break the adult's next commitment.
- [x] **Record a per-candidate exclusion reason** ("Dad arrives 4:25, needs 4:00"; "rule: grandparents
      only when both parents are busy"). This makes #3 "why not X?" a lookup rather than an LLM guess,
      at zero model cost. The single highest-leverage design decision here.
- [x] `tools/detect_conflicts.py` classifies: plain overlap · **unreachable (travel)** · no eligible
      adult · rule clash.
- [x] **Experiment 1**: 35 scenarios, 20 planted and 15 deliberately fine. Overlap baseline
      P 1.000 / R 0.250 / F1 0.400; LifePilot 1.000 / 1.000 / 1.000; AI-only (Nova Micro) 0.000
      across the board, with a control call proving the harness could have scored above zero.
      `eval/results/experiment1.csv`, logged with model id, seed and git SHA. See friction log 14.
- [ ] Figure for the README and video (`eval/results/figures/`) — deferred to phase 13 with the rest
      of the charts; the CSV is the source of truth either way.

**Verify:** Dad's review ends 4:45 at the office 40 min away, Mom at piano till 5:00 → Aarav's 5:00
football pickup reported unreachable **while no two events overlap**. `make eval EXP=1` writes P/R/F1.

## Phase 7 — #8 family rules as real constraints

- [x] `engine/rules.py` — the five types only (`immovable_event`, `latest_end`, `buffer_after`,
      `eligibility`, `load_balance`). Speech fitting no type is refused and queried, never invented.
- [x] `add_rule` / `list_rules` / `remove_rule`, each read back for confirmation before it binds.
- [x] Rules feed Phase 6 reachability, so #1 improves the moment this lands.

**Verified:** a rule stated by voice changes what `detect_conflicts` reports on the very next call,
and retiring the grandparent rule moves Grandpa into `could_cover`. Names and categories are closed
vocabularies, so a rule cannot store cleanly and then match nothing (friction log 15).

## Phase 8 — #2 decide, #4 repair

- [x] `suggest_responsible` — deterministic ranking over reachable candidates: arrival slack, travel
      minutes, current load, soft rule preferences. Explicit tuple sort; the winning factor generates
      the one-sentence reason. The solver decides; the LLM only phrases.
- [x] `fix_week` — the academic **Minimal Perturbation Problem**; use the known formulation rather than
      inventing one:
      - Variables `assignee[e]` per transport event; `start[m]` for movable items only.
      - Hard: immovable starts fixed · travel feasibility via `only_enforce_if` · no adult in two places
        (`add_no_overlap` over their intervals including travel) · `latest_end` · `buffer_after` ·
        `eligibility`.
      - Objective: reify `kept[x] <=> (x == current_value)` and **minimize the Hamming distance** to the
        current plan, plus a small load-imbalance term. Minimal change *is* the objective.
      - `add_hint` with the current plan; `max_time_in_seconds ≈ 5` so voice never hangs.
      - **`num_search_workers = 8`.** OR-Tools 9.15.6755 segfaults (`Check failed:
        heuristics.fixed_search != nullptr`) on high core counts, and the reported trigger is a model
        that *presolves to zero variables with a solution hint* — exactly our warm-started, already
        feasible case. Fixed in 10.0; cap workers until then.
      - Output: short diff, a `reason` per change, `solve_ms`, change count.
- [x] **Experiment 2**: 20 broken weeks, 15 repairable. LifePilot breaks a rule 0%, leaves 0%
      broken, 0.8 changes per fix, 14 ms median / 16 ms p95. AI-only (Nova Micro) breaks a rule 25%
      and leaves 100% broken, having proposed nothing at all — with a control call proving it could
      have. Both plans applied and judged by the same detector. `eval/results/experiment2.csv`,
      friction log 17.

**Verify:** seeded broken week repairs in 2 changes · immovable piano never moves · reruns are stable.

**Done ahead of plan:** `explain_choice` (#3, phase 9) fell out of this phase for free, because the
per-candidate exclusion reasons were already recorded in phase 6. Also delivered: a deterministic
tie-break so the same week always repairs the same way, and a test that applies the diff and asserts
the conflicts are gone (friction log 16).

## Phase 9 — #3 why-not, #5 what-if

Both pure engine/solver work with **zero extra model calls**.

- [x] `explain_choice` reads Phase 6's stored exclusion reasons; every answer names a specific rule,
      event or travel time.
- [x] `what_if` applies a hypothetical, re-runs detect + solve on a copy, returns the ripple, changes
      nothing. Assert the DB is byte-identical afterwards.

**Verified:** the database is byte-identical after four what-ifs (every row of every table hashed
before and after), and no proposal row is written even though the same solver runs underneath. The
ripple separates what a change would break from what was already broken, so an old problem is never
blamed on a new meeting. Friction log 18.

## Phase 10 — Approval loop and the proposal card

The loop everything rests on: **observe → detect → propose → approve → execute.**

- [x] `approve_proposal` / `reject_proposal`, `needs_approval_from` enforced server-side.
- [x] Card via first-party `mcp.server.apps`: `Apps()`, `@apps.tool(resource_uri="ui://...")`,
      `add_html_resource(...)`, `MCPServer(extensions=[apps])`. Ship the `client_supports_apps()`
      text-only fallback **first** — the spoken answer is the product.
- [x] Minimal MCP Apps **host** side in the simulator: sandboxed iframe, `ui/initialize`,
      `ui/notifications/tool-input` and `tool-result`, and proxying `tools/call` so **Approve** reaches
      `approve_proposal`. Easy to under-estimate; it is the core of the demo.

**Verify:** Approve mutates the plan · Reject leaves it untouched · a child's session cannot approve.

**Verified in a browser:** Approve inside the sandboxed iframe moved the football pickup from Dad to
Mom and the project block from 20:00 to 19:30, with the proposal marked `approved` and `decided_by`
recorded. Reject leaves everything untouched. A child cannot approve, and an all-or-nothing test
shows a proposal naming a deleted event applies none of its changes. `@apps.tool` had to be dropped
in favour of a core tool carrying `_meta.ui.resourceUri`, because it hid `fix_week` from every client
that had not negotiated Apps (friction log 19).

### Hardening from live testing (Oct 1, 2026)

- [x] `.env` loaded from an explicit project root with `override=True`, so neither the working
      directory nor a stale shell variable can defeat it.
- [x] A rejected certificate raises `InterceptedHTTPS` naming the antivirus, the variable and the
      fix, instead of an eighty-frame botocore trace.
- [x] The model path falling back to the keyword router now says so out loud. A silent degradation
      reads as "the product does not understand me" and sends you debugging the wrong thing.
- [x] A week is summarised, not recited; a single day is given in full. Instructions no longer leak
      into spoken answers.
- [x] A window with no data names the week that is loaded instead of reporting an empty diary.
- [x] The demo week follows the real calendar (`lifepilot_shared/week.py`), so "tomorrow" is a day
      with events in it. `LIFEPILOT_WEEK=fixed` pins it for tests and the recorded demo.
- [x] "My schedule" answers with the speaker's own day, not the household's week (`only_mine`).
- [x] Dates and times are spoken, not formatted: "tomorrow at 4 PM", never "2026-10-08T16:00".
      `lifepilot_shared/speech.py`, shared by both paths so they cannot drift. Friction log 23.

Friction log 20 and 21.

### Experiment 4 and end-to-end transcripts (brought forward, Oct 1 2026)

- [x] `eval/transcripts.py` — 24 realistic utterances with expected tool, expected arguments and
      deterministic checks on the spoken answer. Every reported wrong answer is in it.
- [x] `eval/harness.py` — the real stack end to end; only the model's reply is substituted.
- [x] `eval/recorder.py` — cassettes, so a check costs one model call ever rather than one per run.
- [x] `eval/experiment4.py` — tool correctness 95.8%, argument correctness 100%, answer correctness
      100%. `eval/results/experiment4.csv`.
- [x] `tests/test_transcripts.py` — the same checks in CI, replayed free.
- [x] `LIFEPILOT_TODAY` pins the clock so date-dependent answers are testable.
- [ ] Grow the transcripts towards the ~100 in CLAUDE.md, and add the 9-tool coarse set comparison.

Friction log 28.

## Phase 11 — #7 school email to plan

- [ ] **Step 0, accounts not code:** Google Cloud project, enable Gmail API, OAuth client, test user,
      a **dedicated demo Gmail**, and fake school emails we write ourselves. Everything earlier uses a
      fake Gmail client, so nothing was blocked waiting on this.
- [ ] Read-only scope only · allowlist in every query (`from:(...)`; a query without a sender filter is
      a bug) · one Nova Micro call per email, cached by `gmail_message_id` · store id, sender, date and
      tasks only, **body discarded and never logged** · Fernet tokens server-side · disconnect revokes
      with Google and deletes all rows.
- [ ] `check_school_email` returns task **+** conflict **+** proposed fix in one result — tool-side
      chaining is what keeps the agent inside its 3-call ceiling.
- [ ] Required tests: injection executes zero actions · non-allowlisted sender never read · revoked
      token leaves no rows · no body in logs or DB.

## Phase 12 — #6 swap, and the Skills extension

- [ ] `request_swap` — check both legs feasible, create a proposal needing the *other* parent's
      approval; she accepts in her own session. Cross-session state is a named judging signal.
- [ ] `lifepilot/extensions/skills.py` — `io.modelcontextprotocol/skills` on the SDK's `Extension`
      framework: `identifier`, `settings()`, `MethodBinding("skills/list")`,
      `MethodBinding("skills/get")`, `skill://lifepilot/...` resources over `skill/SKILL.md`. Honour the
      security rule: **`allowed-tools` is ignored for MCP-origin skills** without explicit approval.
- [ ] Offer it upstream to `modelcontextprotocol/python-sdk` (or publish standalone) as the **Open
      Source mini challenge** entry; put the contribution URL in the submission.

## Phase 13 — Evals, README, video, submission

- [ ] `make eval` → all 7 experiments to `eval/results/*.csv` + `figures/*.png`, logging model ID, seed
      and git SHA. `EVAL_MAX_CALLS`, estimate printed **before** the run.
- [ ] README: concise, fresh-clone setup, and the honest notes `CLAUDE.md` requires (`gmail.readonly`
      breadth is our promise not Google's; Testing-mode limits; simulated Alexa+; WhatsApp and Nova
      Sonic as future work).
- [ ] Video under 3 min, per `CLAUDE.md`'s shot list. Never opens on a schedule or a briefing.
- [ ] Product feedback for every Amazon/AWS tool used, plus the friction log.

---

## Cost guardrails

Measured, at $0.035 / $0.14 per 1M tokens:

| | |
|---|---|
| One voice turn (the ~3,500-token tool-schema block dominates) | $0.000335 |
| Same turn, prompt-cached | $0.000152 |
| One school-email extraction | $0.000067 |
| One full `make eval` | $0.45 |
| Whole project with the cache working | **~$1.50** |

Per-call price is not the risk; repetition is. At 5 calls/second an unbounded retry burns the $20 Bedrock
pool in **6.6 hours**. Hence the 3-call per-turn ceiling in `llm.py` (nothing in Strands enforces one),
`EVAL_MAX_CALLS` with the estimate printed first, the cache on in evals too, Nova Micro only, and plain
`converse` only — no Knowledge Bases, Agents, Guardrails or provisioned throughput, which bill outside
tokens. AWS budget alert ≤$10 before demo week.

## Risks

| Risk | Handling |
|---|---|
| Nova Micro refuses forced `toolChoice` | Phase 2, ~$0.002, before anything depends on it. Fallback `{any: {}}` with one tool. |
| **OR-Tools 9.15 segfault** on hinted models that presolve to nothing | `num_search_workers = 8`. Our warm-started repair is the exact reported trigger. |
| Nova Micro too weak to pick among 18 tools | Experiment 4 measures exactly this; the coarse 9-tool set behind `TOOLSET` is the planned mitigation. No Nova Lite without an eval showing Micro fails. |
| ~~Strands cannot reach the MCP server on this dev box~~ **solved in code, no machine changes**: `simulator/mcp_handshake.py` pins the `initialize` handshake so the header is never sent | Covered by `tests/test_strands_client.py`; `assert_patchable()` fails loudly if a Strands upgrade moves the name. Friction log 10. |
| `SpeechRecognition` fails live | Typed input is a first-class path, not a bolted-on fallback. |
| MCP Apps host bridge eats days | Text-only answer ships first; the card is additive. |
| CP-SAT repair model is fiddly | Phase 6 reachability is pure and fully tested first, so the solver arrives with a known-good conflict set and a literature formulation. |
| Gmail Testing mode: refresh tokens expire weekly | Reconnect the demo account the morning of recording; stated in README. |
| Three weeks, nine differentiators | Phases are priority order; drop order stated at the top. |

## Before submitting

- [ ] Fresh clone → `.env` from `.env.example` → `make dev`, following the README only. Requirement 4,
      and the thing most likely to be quietly broken.
- [ ] Negotiated protocol version 2025-11-25+ **on the wire**; SDK called at runtime.
- [ ] Demo script end to end: conflict → who → why not → fix → approve → school email → what-if → swap
      across two sessions → child view.
- [ ] `make eval` from clean; every README number traced to a CSV. Nothing typed by hand.
- [ ] All Gmail security tests passing.
- [ ] Labels visible; MIT in the GitHub About section; no Amazon marks in the UI or video.
