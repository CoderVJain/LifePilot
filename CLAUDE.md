# CLAUDE.md — LifePilot

> **Other assistants show your family's calendar. LifePilot fixes it.**

LifePilot is a **Family Coordination Agent** for working parents, built as an **MCP server for Alexa+**. It doesn't
just list what's happening. It works out whether the week can actually be done by the people available, finds what
breaks, decides who should handle it and why, and repairs the plan with the fewest changes. **A parent always
approves before anything changes.**

**Voice only.** No dashboard, no uploads, no forms. Parents talk; LifePilot talks back. The only non-voice step is
a one-time Gmail sign-in, the same way people link Spotify to Alexa.

This project replaces **Counter** as the hackathon entry. Nothing from Counter's domain (shops, stock, credit)
belongs here, and no code path is named `counter/`.

- **Hackathon:** Build, Ship, Shape: Amazon Developer Hackathon (Devpost)
- **Primary track:** Alexa+ (our own simulated Alexa+ experience on the web; see requirement 5)
- **Mini challenges:** AWS Builder + Open Source
- **Submission deadline:** Oct 23, 2026, 12:00 PM PDT. **Internal target: submit by Oct 20.**
- **Rules:** https://amazonappdev2026.devpost.com/rules (re-check when unsure; the rules win over this file)

---

## Positioning (read this before building any feature)

Many entries in this hackathon are household or family helpers: daily briefings, shared calendars, chore and
grocery lists, bus times, reminders, approval before deleting things, eldercare dashboards. **If LifePilot looks
like any of those in the demo, it loses.**

**LifePilot is NOT:**
- a shared family calendar or daily briefing app
- a reminder or to-do app
- a load balancer or chore-splitting app ("who did more pickups" is a side effect, never the headline)
- a family chatbot that answers questions about the schedule
- a dashboard or an app with upload screens

**LifePilot IS:** a voice planner that reasons about **people, places, time and rules together**, and repairs the
week.

Rule for every feature: if it only *shows* information, it's supporting cast. The headline features *decide or
repair* something. When in doubt, ask: "Could a shared calendar do this?" If yes, it's not a differentiator.

---

## The differentiators (what nobody else in this lane does)

### 1. Can-it-actually-happen conflicts
A conflict is not "two events at the same time". It's **a child who needs to be somewhere and no eligible adult
can get them there**, counting travel time, who can drive, and family rules.
Example: Dad's review ends 4:45 at the office, the office is 40 min from the football ground, Mom is at piano with
Anaya until 5:00. Aarav's 5:00 football pickup is **unreachable**, even though no two events overlap.

### 2. "Who should do it?" with reasons
Ranks eligible adults by availability, travel time, current load and family rules, and says **why** in one
sentence: "Mom, because she's 10 minutes away after piano; Grandpa only covers when both of you are busy."

### 3. "Why not X?" explanations
"Why not Grandma?" → "Your rule says grandparents only when both parents are busy, and Mom is free at 4:30."
Every answer points at a specific rule, event or travel time. No vague LLM answers.

### 4. Fix the week with the fewest changes
"Fix our week" repairs **only what's broken** and minimises disruption. Immovable events never move. The answer is
a short diff ("2 changes: Mom takes Thursday pickup, Aarav's project block moves to Wednesday 6 PM"). Parents
approve the diff, not a whole new schedule.

### 5. What-if before it happens
"What if my 4 PM runs until 5:30?" → shows the ripple effect (which pickups break, who could cover) **without
changing anything**. Also: "Can I say yes to a 6 PM meeting on Friday?"

### 6. Partner swap requests
"Ask Priya if she can take Thursday, I'll take Monday." LifePilot checks both swaps are feasible, then sends a
**swap proposal** to the other parent. She accepts or declines in **her own session**, and the plan updates. Two
people, two sessions, one shared plan.

### 7. School email to plan
LifePilot reads **school emails only** from the parent's Gmail (read-only), turns them into dated tasks ("costume
by Friday", "fee by the 15th"), checks whether they break the week, and offers a fix, all by voice:
*"One new email from school: Aarav needs a costume by Friday. That clashes with Thursday. Should Mom go Wednesday?"*
This is the multi-service moment: **Gmail API → Bedrock → solver → approval**. See "Gmail access and security".

### 8. Family rules as real constraints
Parents state a rule once, in plain speech. It's parsed into a structured constraint, read back for confirmation,
and enforced by the solver on every plan. The LLM never applies rules itself, so it can't "forget" one.

### 9. Role-aware privacy
Parents see everything, a child sees their own schedule with parents' work as "Busy", a grandparent sees only
what's assigned to them.

### 10. Proven, not claimed
Every headline claim has a number from `make eval` behind it (see Experiments).

**Already common in other entries, keep but don't headline:** daily summary, reminders, approval before changes,
audit logs.

---

## Hackathon hard requirements (never break these)

1. MCP server implements **spec 2025-11-25 or later** over **Streamable HTTP** (not stdio, not the old
   HTTP+SSE transport). The rules set 2025-11-25 as the **minimum** acceptable version, not an exact
   pin; we negotiate both 2025-11-25 and 2026-07-28.
2. The MCP SDK is **imported and actually called at runtime**. Naming it in the README does not count.
3. Public GitHub repo with an **MIT license visible in the About section**.
4. README has **clear setup + run instructions**; a judge must be able to run it from a fresh clone.
5. The Alexa+ MCP Toolkit, `alexa-ai` CLI and device simulator are US-only/partner-gated. We ship our **own
   simulated Alexa+ web client** (allowed by the rules). Say this plainly in the README and submission.
6. Demo video is **under 3 minutes**, English, public on YouTube, and shows LifePilot working in the simulator.
7. Submission includes **product feedback** for every Amazon/AWS tool used, plus a **friction log**
   (`docs/friction-log.md`, up to 10% judging bonus). Log friction as it happens.
8. No Amazon/Alexa/Gmail/WhatsApp logos, Echo look-alikes, third-party trademarks, copyrighted music, or real
   people's data.
9. **Demo uses a dedicated demo Gmail account with fake school emails we write ourselves.** Never a real inbox,
   never a real school's emails.
10. Anything simulated (partner notifications, the demo school) is **labelled as simulated** in the UI.

## Judging signals this must visibly hit

From the rules' "creative" list for Alexa+: agentic workflow across services (#7), state across sessions (#6, #8),
cards / **MCP Apps** (proposal card), **Agent Skill** (ship one). Purchasing is not part of LifePilot; don't bolt it
on.

---

## Core design

### One loop for every request
**observe → detect → propose → approve → execute.** Write tools create a **pending proposal**; only
`approve_proposal`, called by a **parent** (or the other parent, for a swap), executes it.

### Division of labour
- **LLM (Bedrock Nova Micro, in `simulator/`):** understands speech, parses rules and school emails into a fixed
  structured form, phrases answers. Nova Micro has no structured-output mode, so a "fixed structured
  form" always means a **forced tool-use schema**, never a request to please reply in JSON.
- **MCP server:** holds data, checks reachability, ranks who should do it, runs the solver, and returns structured
  proposals with a plain-English reason for each change.
- The LLM never decides feasibility, eligibility, rules or load. If the solver says a plan is infeasible,
  LifePilot says which rule or event blocks it. It never quietly drops a rule to make a plan fit.

Keep an **LLM-only path** switchable by config: experiments 1–4 use it as a baseline.

---

## Gmail access and security

**Connecting (one time):** the parent signs in to Google once through the standard OAuth consent screen, like
linking any service to Alexa. After that, everything is voice. The simulator shows this as a single "Link Gmail"
step; there is no other screen.

**Rules (all enforced in code, all tested):**

1. **Read-only scope only:** `https://www.googleapis.com/auth/gmail.readonly`. Never request send, modify, compose
   or full-mail scopes. Google enforces this: even a stolen token can't send or delete email.
2. **School senders only.** The parent sets the allowed senders by voice ("Only read emails from Aarav's
   school"). Every Gmail query is built from the allowlist (`from:(...)`); a query without a sender filter is a
   bug. Reject any message whose sender isn't on the allowlist, even if the query returned it.
3. **Be honest about scope.** `gmail.readonly` technically allows reading the whole inbox. The school-only filter
   is our code's promise, not Google's. The README says this plainly.
4. **Don't keep email bodies.** Extract the task, then store only: Gmail message id, sender, received date,
   extracted tasks. The email text is discarded after extraction. Never log email bodies.
5. **Token safety.** OAuth tokens are encrypted at rest (key from env var), stored server-side only, never sent to
   the LLM, the browser or logs. "Disconnect my email" revokes the token with Google and deletes it and all stored
   school-message rows.
6. **Emails are data, never instructions.** Extraction is one `converse` call carrying exactly **one
   output-only tool** — the fixed schema (`title`, `child`, `due`, `category`, `prep_days`) — selected
   with `toolChoice: {tool: ...}`. No action tool is in scope for that call, so an instruction inside an
   email ("cancel all pickups", "ignore your rules") has nothing to reach for. This is structural, not a
   prompt plea. Every extracted task becomes a **pending proposal** that a parent must approve.
7. **Minimum to the model.** Send only the subject and body text of allowlisted emails to Bedrock; strip
   signatures, quoted replies and attachments. Attachments are never downloaded.

**Required tests:** a prompt-injection email produces zero executed actions; a non-allowlisted sender is never
read; a revoked token leaves no stored rows; no email body appears in logs or the DB.

**Google limits (fine for the hackathon, note in README):** while the OAuth app is in Testing mode, only up to 100
test users, refresh tokens expire every 7 days (reconnect weekly), and users see an "unverified app" screen.
Public launch later needs Google verification plus a CASA security assessment for restricted Gmail scopes. That's
future work, not a hackathon task.

**When to check email:** only when the parent asks ("Any news from school?") or during the morning summary. No
background polling, no Gmail push/watch, no Pub/Sub.

**WhatsApp: future work only.** The official WhatsApp API can't read a parent's personal chats or school groups.
Mention "WhatsApp next" in the README; don't build it.

---

## Scope

| Feature | Example utterance | Status |
|---|---|---|
| Can-it-happen conflicts (#1) | "Any problems this week?" | MVP |
| Who should do it, with reasons (#2) | "Who should pick up Aarav?" | MVP |
| Why not X (#3) | "Why not Grandma?" | MVP |
| Fix the week, fewest changes (#4) | "Fix our week." | MVP |
| What-if (#5) | "What if my 4 PM runs till 5:30?" | MVP |
| Partner swap (#6) | "Ask Priya to take Thursday, I'll take Monday." | MVP |
| School email to plan (#7) | "Any news from school?" | MVP |
| Family rules (#8) | "Remember, Anaya's piano can't move." | MVP |
| Role views (#9) | Switch speaker to Aarav / Grandpa | MVP |
| Risk scan | "What am I forgetting?" | MVP (supporting) |
| Tomorrow summary | "What's happening tomorrow?" | MVP (supporting) |
| Study plan for projects | "Make a plan for Aarav's project." | Stretch |
| Load view | "Who's doing most of the pickups?" | Stretch (never headline) |
| WhatsApp messages | — | **Out of scope** (future work) |
| Birthday/event planning | "Plan Anaya's birthday." | **Out of scope** |
| Real Google/Outlook calendar sync | — | **Out of scope** (seeded data) |
| Maps API travel times | — | **Out of scope** (fixed travel-time table) |
| Any upload screen or dashboard | — | **Out of scope, never** |

Build order: #1 → #8 → #2 → #4 → #3 → #5 → #7 → #6 → #9. Each must work end to end (voice → tool → proposal →
approve → spoken reply) before the next starts. If a task drifts into an out-of-scope row, stop and flag it.

---

## Family rules

| Spoken rule | Stored as | Type |
|---|---|---|
| "Anaya's piano class cannot be moved." | event `piano`, `movable = false` | Hard |
| "No homework after 9 PM." | task category `study`, latest end `21:00` | Hard |
| "Aarav needs 30 minutes rest after school." | buffer 30 min after `school_end` for Aarav | Hard |
| "Grandparents only when both parents are busy." | eligibility: `grandparent` only if no parent free | Hard |
| "Try to keep pickups even between us." | penalty on load imbalance | Soft |

Supported rule types: `immovable_event`, `latest_end`, `buffer_after`, `eligibility`, `load_balance`. If speech
doesn't fit a supported type, say so and ask; don't invent a type on the fly.

## Roles and access (enforced on the server, not in prompts)

- **Parent:** full view; can approve plans, accept swaps, edit rules, link or disconnect Gmail.
- **Child:** own schedule and tasks; parents' work meetings appear as **"Busy"**. No access to school emails.
- **Caregiver (grandparent):** only the pickups and events assigned to them.

## Safeguards

- Demo and repo use a **synthetic family only**. No real children's data.
- Every write needs an approving parent. The agent never changes plans on its own.
- **No medical advice:** appointments are time and place only.
- Post-hackathon: parental consent before any child profile, in line with India's DPDP Act, 2023 (verify with
  counsel before launch). Mention in the README; don't build it now.

---

## Architecture

Two Python processes plus static files. **No secrets ever reach the browser.**

```
browser       thin client, "simulated Alexa+ experience" (voice in, voice out, cards; no upload UI)
  mic -> Web Speech API -> plain text; speaks replies; renders MCP App cards in a sandboxed iframe
  speaker switcher (Dad / Mom / Aarav / Grandpa) = separate sessions
  one-time "Link Gmail" (Google OAuth), nothing else
                                                  |
                                WebSocket (text in / text + card out)
                                                  |
simulator/   FastAPI - serves the page AND hosts the agent
  Strands agent + LifePilotModel (Bedrock Nova Micro) -> MCP client
  minimal MCP Apps HOST bridge, so a card's Approve button can reach approve_proposal
                                                  |
                                 Streamable HTTP (spec 2025-11-25+)
                                                  |
lifepilot/   FastAPI + official MCP Python SDK
  tools/ -> engine/ (context, reachability, allocation, explain, rules, risk, what-if)
         -> solver/ (OR-Tools CP-SAT, minimal-change repair)
         -> mail/   (Gmail API read-only, sender allowlist, extraction, token vault)
         -> Postgres
lifepilot_shared/llm.py   the ONLY module that calls Bedrock; both processes import it
skill/       Agent Skill package describing how to use LifePilot's tools
eval/        synthetic families + synthetic school emails, baselines, harness, results
```

**Why the agent is not in the browser:** Strands Agents is a Python SDK and any Bedrock call needs AWS
credentials, so page code could neither import it nor hold its keys. The browser stays thin; the agent
runs in `simulator/`.

**Why both processes call Bedrock:** the simulator runs the conversation; the MCP server extracts
school-email tasks and must do so server-side because Gmail tokens never leave it. `llm.py` is shared
so there is exactly one file to read when asking what spends money.

- **Proposal card as an MCP App:** shows the diff (what changes, who, why) with Approve / Reject. Also cards for
  the conflict warning, what-if ripple, swap request and new school task. Cards support the voice answer; they
  never replace it.
- **Debug drawer** in the simulator: tool called, arguments, solver verdict, reasons.

## Stack

- Python 3.12, FastAPI, official MCP Python SDK (Streamable HTTP)
- **`mcp>=2.1,<2.2`** (2.1.1). The upper bound is not ours: `strands-agents` requires `mcp<2.2`.
  Bumping it is a deliberate act, not a routine upgrade. In 2.x the server class is `MCPServer`
  (`mcp.server.mcpserver`), not `FastMCP`, and `mcp-types` ships both `_v2025_11_25` and
  `_v2026_07_28`, so this pin satisfies hard requirement 1 with room to spare.
- **MCP Apps is first-party**: `mcp.server.apps` (`Apps`, `@apps.tool(resource_uri="ui://...")`,
  `add_html_resource`, `client_supports_apps`). No third-party UI library needed.
- LLM: **Amazon Bedrock Nova Micro only** (see cost rules). Model ID from env var.
  Nova Micro has **no structured outputs** — every fixed schema is a tool-use schema.
- Agent loop: Strands Agents SDK, in `simulator/`. The MCP server stays plain and spec-pure.
  Strands' published docs still show `streamablehttp_client`, removed in mcp 2.x; use
  `MCPClient(url=...)`.
- Solver: Google OR-Tools CP-SAT
- Email: Gmail API (`google-api-python-client`, `google-auth-oauthlib`), read-only scope, OAuth app in Testing mode
- Token encryption: `cryptography` (Fernet), key from env var
- DB: SQLAlchemy 2.1 + Alembic. `DATABASE_URL` unset -> in-memory SQLite (tests and evals: free,
  offline, fast); set -> Neon Postgres (`make seed`, demo). Portable `sa.JSON` only, so both work.
- Travel time: fixed table `travel_time(from_location, to_location, minutes)` in seed data
- Speech: browser Web Speech API (free). **Nova Sonic is an explicit non-goal**: it would replace a
  free browser API with per-second audio billing and pull the model into the transport layer.

---

## Data model (starting point)

- `family` — id, name, timezone
- `member` — id, family_id, name, role (`parent` | `child` | `caregiver`), can_drive, home_location_id
- `location` — id, family_id, name
- `travel_time` — from_location_id, to_location_id, minutes
- `event` — id, family_id, member_ids, title, category, start, end, location_id, needs_transport, movable, visibility
- `task` — id, family_id, owner_id, title, category, due, est_minutes, prep_days, status, source (`voice` | `email`)
- `rule` — id, family_id, type, hard, params (JSON), spoken_text, confirmed_by, active
- `assignment` — id, event_id, member_id, kind (`drop` | `pickup`)
- `proposal` — id, family_id, kind (`fix` | `assign` | `swap` | `rule` | `event` | `task`), created_by,
  changes (JSON, each with a `reason`), violations (JSON), solve_ms, status (`pending` | `approved` |
  `rejected` | `expired`), needs_approval_from (member_id), decided_by
- `email_link` — id, family_id, parent_id, encrypted_token, allowed_senders (list), linked_at, last_checked_at
- `school_message` — id, family_id, gmail_message_id (unique), sender, received_at, extracted_tasks (JSON), status.
  **No subject, no body.**

---

## MCP tools

The full set is **18 tools**; experiment 4 compares it with a **9-tool** merged set behind `TOOLSET=full|coarse`.
Same capabilities, different granularity. Keep both sets in sync.

**Full set (18):**

| Area | Tools |
|---|---|
| Context | `get_family`, `get_schedule` (events + tasks) |
| Rules | `add_rule`, `list_rules`, `remove_rule` |
| Detect | `detect_conflicts` (#1), `scan_risks` |
| Decide | `suggest_responsible` (#2), `explain_choice` (#3, "why" and "why not X") |
| Repair | `fix_week` (#4), `what_if` (#5, read-only) |
| Approve | `approve_proposal`, `reject_proposal` |
| Partner | `request_swap` (#6) |
| Changes | `add_event`, `update_task` |
| School email | `check_school_email` (#7), `manage_email_access` (set allowed senders, disconnect) |

**Coarse set (9):** `get_context`, `update_rules`, `find_problems`, `decide_and_explain`, `plan_changes`,
`decide_proposal`, `request_swap`, `update_schedule`, `school_email`.

Stretch tools (`make_study_plan`, `get_load_summary`) sit behind `STRETCH=1` and are in neither set.

---

## Experiments (results to produce)

Every number in the README and video comes from `make eval`, never typed in by hand.

| # | Experiment | Compare | Metric |
|---|---|---|---|
| 1 | Conflict detection | Calendar-overlap check vs. AI only vs. LifePilot | Precision, recall, F1 on planted conflicts |
| 2 | Plan feasibility | AI only vs. AI + solver | % of plans breaking a family rule; solve time |
| 3 | Family rules | With vs. without stored rules | Rule violations; how often the proposal is accepted |
| 4 | Tool use | 18 vs. 9 tools; tools vs. plain chatbot | Correct-tool rate + task success on ~100 scripted requests |
| 5 | "What am I forgetting?" | LifePilot vs. deadline-only reminders | Share of at-risk tasks caught; days of warning |
| 6 | Load balancing | Before vs. after rebalancing | Spread of pickups between parents |
| 7 | User study | Manual coordination vs. LifePilot | SUS, NASA-TLX, minutes spent per week |

- **Synthetic families:** `eval/generate.py` builds seeded families. Same seed → same data.
- **Synthetic school emails:** `eval/emails/` holds labelled fake school emails (with the expected tasks), including
  near-misses (newsletters with no task) and prompt-injection emails. Evals read these files; they never call the
  real Gmail API.
- **Exp 1:** plant labelled conflicts: plain overlap, **unreachable (travel time)**, no eligible adult, rule clash.
  Include near-misses that are *not* conflicts. The overlap baseline only catches plain overlap; that gap is the
  headline number for differentiator #1.
- **Exp 2:** also report **changes per fix** (#4) and solve time as median and p95.
- **Exp 3:** acceptance comes from a scripted, deterministic persona with hidden rules.
- **Exp 4:** ~100 requests in `eval/requests.jsonl`, including what-if, why-not, swap and school-email requests.
- **Exp 5:** include tasks that only appear in school emails; report how many LifePilot catches vs. the
  deadline-only baseline.
- **Exp 6:** pickup spread (max − min, std dev) with and without the soft rule. Report it; don't headline it.
- **Exp 7:** small within-subjects study (adults only, informed consent). Report n honestly.
- **Outputs:** `eval/results/*.csv` and `eval/results/figures/*.png` from one command. Log model ID, seed and git
  SHA with every run.
- **For judging, exp 1 and 2 matter most.** They prove differentiators #1 and #4.

---

## Demo video (under 3 minutes)

1. **0:00–0:15** — The problem in one line and the pitch: "Other assistants show your family's calendar.
   LifePilot fixes it."
2. **0:15–0:50** — "Any problems this week?" → Thursday pickup is unreachable (#1). "Who should go?" (#2).
   "Why not Grandpa?" (#3).
3. **0:50–1:30** — "Fix our week." → 2-change diff on the MCP App card → "Yes" (#4). "Any news from school?" →
   costume by Friday → it breaks Thursday → fixed (#7).
4. **1:30–2:05** — "What if my 4 PM runs late?" (#5). Swap request → switch to Mom's session → she accepts (#6).
5. **2:05–2:30** — Switch to Aarav's view: Dad's meeting shows as "Busy" (#9).
6. **2:30–2:55** — One number from exp 1 or 2, the architecture in one frame, "simulated Alexa+ experience" and
   "demo school, fake emails" labels.

Never open the video with a schedule or a daily briefing. Never show a real inbox.

---

## Cost rules (the goal is ₹0)

Pools as of Sep 26, 2026: **$20 Bedrock, $100 AWS free-tier, $150 hackathon credit**. More credit does not mean
a looser rule. Treat every model call as spending money that isn't ours to waste.

**All spending goes through `lifepilot_shared/llm.py`.** It is the only module that calls Bedrock, and it
holds every control below. One file to audit.

Measured, not guessed (Nova Micro at $0.035 / $0.14 per 1M tokens):

| | |
|---|---|
| One voice turn (2 calls; the ~3,500-token block of 18 tool schemas dominates) | $0.000335 |
| Same turn with prompt caching | $0.000152 |
| One school-email extraction | $0.000067 |
| One full `make eval`, all 7 experiments | $0.45 |
| Whole project, with the parse cache working | **~$1.50** |
| Whole project, if the cache is neglected | ~$14 |

The risk is repetition and runaway loops, not per-call price: at 5 calls/second an unbounded retry burns
the $20 Bedrock pool in **6.6 hours**.

- An AWS budget alert must exist (≤ $10). Check spend in the Billing console before demo week.
- **Nova Micro only.** Nothing passes `smart=True`. No Nova Lite call without an eval showing Micro fails.
  `llm.py` rejects any other model ID outright.
- **Hard ceiling of 3 model calls per voice turn**, enforced in `llm.py`. The Strands event loop has no
  iteration cap of its own, so nothing else will stop a loop.
- Keep the agent loop short by letting **server tools do the chaining**: `check_school_email` returns the
  task, the conflict it causes and a proposed fix in one result.
- What-if, why-not, reachability and fix-week are solver/code work: **no extra model calls**.
- **Plain `converse` only.** No Knowledge Bases, Agents, Guardrails or provisioned throughput: they bill
  outside tokens (OpenSearch Serverless alone is ~$350/month at zero traffic).
- Prompt-cache the tool-schema block: `CacheConfig(tools_ttl="5m", system_prompt_ttl="5m")`. Nova's limits
  are 1K tokens minimum per checkpoint, 4 checkpoints, **5-minute TTL**, 20K cacheable, and Bedrock
  rejects TTLs that *increase* across `toolConfig` -> `system` -> `messages`, so keep them equal.
- Count **calls and cache hits separately**. A cache hit must not consume ceiling budget, and the ceiling
  must not be bypassable by one.
- The Gmail API is free; the cost is Bedrock. **One Nova Micro call per new school email**, cached by Gmail
  message id so the same email is never processed twice. Check email only on request or in the morning summary.
- **Cache repeated parses** (same utterance + same family-context version → same result). Cache stays on, including
  in evals (`eval/.cache/`).
- Unit tests use `FakeModel` and a fake Gmail client; they cost nothing.
- **Every eval run has a hard call ceiling** (`EVAL_MAX_CALLS`) and prints the estimated call count first.
- Never point a loop, a retry or a scheduled job at the model without a hard call ceiling.

---

## Commands (update once setup is real)

```bash
make dev         # MCP server + simulator locally
make test        # unit tests with FakeModel + fake Gmail — free, offline
make seed        # load the demo family into Postgres
make eval        # all experiments -> eval/results/ (respects EVAL_MAX_CALLS)
make eval EXP=1  # one experiment
```

Every target is a one-liner delegating to `uv run`, so where `make` is absent (Windows dev box) the same
work runs as `uv run ...`. The `Makefile` stays committed because the README promises it to judges.

Env vars (never commit): `BEDROCK_MODEL_ID`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`TOKEN_ENCRYPTION_KEY`, `EVAL_MAX_CALLS`.

### Dev environment gotcha: TLS interception

On a machine where antivirus intercepts HTTPS (Avast here), `boto3` and `awscli` use certifi and fail on
every AWS call with `CERTIFICATE_VERIFY_FAILED`, while Python's own `ssl` succeeds via the Windows store —
so the cause is not obvious. Point `AWS_CA_BUNDLE` at the interceptor's root cert in `.env`:

```
AWS_CA_BUNDLE=C:\ProgramData\Avast Software\Avast\wscert.pem
```

`llm.py` applies it so both processes inherit it. This belongs in `docs/friction-log.md`.

---

## Working with Varun

- Varun wants to **learn agentic AI deeply**, not just ship generated code. Before building a non-trivial piece
  (reachability check, allocation ranking, minimal-change solver, what-if, swap flow, Gmail extraction, eval
  harness), explain the approach and trade-offs briefly in simple language, then build it in small, reviewable
  steps.
- Small diffs. Run tests after changes. Don't refactor unrelated code.
- Every feature must earn its place in the video, the README or an experiment table.
- If something makes LifePilot look like a calendar, reminder app, load balancer or dashboard, say so before
  building it.
- If a decision affects hackathon eligibility, security, or the cost rules, say so explicitly before doing it.
