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
| `mcp 2.1.1` serves spec **2025-11-25 and 2026-07-28** | `mcp-types` ships `_v2025_11_25/` + `_v2026_07_28/` |
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

- [ ] `scripts/probe_bedrock.py` — confirm `AWS_CA_BUNDLE` works from inside the venv and Nova Micro
      answers.
- [ ] **Forced tool choice** — the one unverified assumption everything rests on. One output-only tool
      (`title`, `child`, `due`, `category`, `prep_days`) with `toolChoice: {tool: {name: ...}}`. Assert
      exactly one `toolUse` and no stray text. Fallback: `toolChoice: {any: {}}` with a single tool.
- [ ] Same call on an email carrying an injection line. Assert the output is still only the schema. Keep
      as a test fixture — evidence, not a promise.
- [ ] Print token counts and cost; record in the friction log.

## Phase 3 — Data layer and seeded family

- [ ] `lifepilot/db/models.py` — SQLAlchemy 2.1 typed models for every entity in `CLAUDE.md`. Portable
      `sa.JSON` only. `school_message` has **no subject and no body columns**, enforced by schema.
- [ ] Alembic + first migration.
- [ ] `eval/generate.py` — seeded family (Dad, Mom, Aarav, Anaya, Grandpa), locations, `travel_time`.
- [ ] `make seed` against SQLite and Neon.

**Verify:** round-trip tests on SQLite, offline and free · same seed twice → identical rows.

## Phase 4 — MCP server skeleton

- [ ] `MCPServer` mounted via `streamable_http_app(streamable_http_path="/mcp")`. The **host** lifespan
      must enter `mcp.session_manager.run()` or every request hangs.
- [ ] `get_family`, `get_schedule`, **role-aware from the start** — a child sees parents' work as
      "Busy", a caregiver sees only their assignments. Tool layer, never a prompt. (#9 is cheap now,
      expensive to retrofit.)
- [ ] Test asserting the negotiated protocol version is **2025-11-25 or later on the wire** —
      requirements 1 and 2 proven, not claimed.

## Phase 5 — The simulated Alexa+ web UI

Alexa+ is US-only, so this UI *is* the demo. Vanilla HTML/CSS/JS, **no build step**. Real Alexa+ on a
display device renders as a chat thread, so that shape is both accurate and simple.

- [ ] `simulator/static/index.html` — conversation thread, large mic button, typed input, speaker
      switcher, collapsible debug drawer.
- [ ] `app.js` — WebSocket; `SpeechRecognition` in, `speechSynthesis` out; card renderers; iframe bridge.
- [ ] `app.css` — our own identity, light and dark.
- [ ] Mic states idle / listening / thinking / speaking, visibly distinct.
- [ ] **Typed input always available** — `SpeechRecognition` needs network and is absent in Firefox;
      feature-detect and notify rather than die. Also demo insurance.
- [ ] Speaker switcher (Dad / Mom / Aarav / Grandpa) = separate sessions, active role badged.
- [ ] Cards inline: conflict · proposal (Approve/Reject) · what-if ripple · swap · school task. The
      proposal card is a real MCP App in a sandboxed iframe; the rest are plain DOM.
- [ ] Debug drawer: tool, arguments, solver verdict, `solve_ms`, reasons, **running model-call count and
      estimated cost** — makes the cost discipline visible to a judge.
- [ ] Persistent labels "Simulated Alexa+ experience" and "Demo school · fake emails" (reqs 5, 10).
      **No Amazon/Alexa logos, no Echo look-alike, no blue-ring trade dress** (req 8).
- [ ] README states Chrome/Edge.

## Phase 6 — #1 can-it-actually-happen conflicts

The headline: not "two events overlap" but *a child needs to be somewhere and no eligible adult can get
them there*.

- [ ] `engine/reachability.py`, pure — no DB, no model calls. For each event needing transport at `T`,
      location `L`: candidates who `can_drive`, filtered by `eligibility` rules; `prev` = last
      commitment ending at or before `T`; `arrival = prev.end + travel_time[prev.location][L]`;
      reachable iff `arrival <= T`. Also check the **return leg** —
      `T + handling + travel_time[L][next.location] <= next.start` — so an assignment cannot silently
      break the adult's next commitment.
- [ ] **Record a per-candidate exclusion reason** ("Dad arrives 4:25, needs 4:00"; "rule: grandparents
      only when both parents are busy"). This makes #3 "why not X?" a lookup rather than an LLM guess,
      at zero model cost. The single highest-leverage design decision here.
- [ ] `tools/detect_conflicts.py` classifies: plain overlap · **unreachable (travel)** · no eligible
      adult · rule clash.
- [ ] **Experiment 1 in this phase**, with planted labelled conflicts *and* near-misses that are not
      conflicts. The overlap-only baseline catches plain overlap and nothing else — that gap is the
      headline number.

**Verify:** Dad's review ends 4:45 at the office 40 min away, Mom at piano till 5:00 → Aarav's 5:00
football pickup reported unreachable **while no two events overlap**. `make eval EXP=1` writes P/R/F1.

## Phase 7 — #8 family rules as real constraints

- [ ] `engine/rules.py` — the five types only (`immovable_event`, `latest_end`, `buffer_after`,
      `eligibility`, `load_balance`). Speech fitting no type is refused and queried, never invented.
- [ ] `add_rule` / `list_rules` / `remove_rule`, each read back for confirmation before it binds.
- [ ] Rules feed Phase 6 reachability, so #1 improves the moment this lands.

## Phase 8 — #2 decide, #4 repair

- [ ] `suggest_responsible` — deterministic ranking over reachable candidates: arrival slack, travel
      minutes, current load, soft rule preferences. Explicit tuple sort; the winning factor generates
      the one-sentence reason. The solver decides; the LLM only phrases.
- [ ] `fix_week` — the academic **Minimal Perturbation Problem**; use the known formulation rather than
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
- [ ] **Experiment 2**: % of plans breaking a rule (AI-only vs AI+solver), changes per fix, solve time
      median and p95.

**Verify:** seeded broken week repairs in 2 changes · immovable piano never moves · reruns are stable.

## Phase 9 — #3 why-not, #5 what-if

Both pure engine/solver work with **zero extra model calls**.

- [ ] `explain_choice` reads Phase 6's stored exclusion reasons; every answer names a specific rule,
      event or travel time.
- [ ] `what_if` applies a hypothetical, re-runs detect + solve on a copy, returns the ripple, changes
      nothing. Assert the DB is byte-identical afterwards.

## Phase 10 — Approval loop and the proposal card

The loop everything rests on: **observe → detect → propose → approve → execute.**

- [ ] `approve_proposal` / `reject_proposal`, `needs_approval_from` enforced server-side.
- [ ] Card via first-party `mcp.server.apps`: `Apps()`, `@apps.tool(resource_uri="ui://...")`,
      `add_html_resource(...)`, `MCPServer(extensions=[apps])`. Ship the `client_supports_apps()`
      text-only fallback **first** — the spoken answer is the product.
- [ ] Minimal MCP Apps **host** side in the simulator: sandboxed iframe, `ui/initialize`,
      `ui/notifications/tool-input` and `tool-result`, and proxying `tools/call` so **Approve** reaches
      `approve_proposal`. Easy to under-estimate; it is the core of the demo.

**Verify:** Approve mutates the plan · Reject leaves it untouched · a child's session cannot approve.

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
