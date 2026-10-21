# LifePilot — build plan

`CLAUDE.md` is the spec (what and why). This file is the state: what is done, what is left, and the
decisions and numbers worth not re-deriving.

**Deadline:** Oct 23, 2026, 12:00 PM PDT · **Internal target:** Oct 20 · **Started:** Sep 29, 2026.

---

## Status (Oct 20 2026)

Build is complete bar the items below. **705 tests, ruff clean.** `make eval` runs experiments 1, 2,
3, 4, 5 and 6 from one command, writing six CSVs and five PNGs with **zero model calls**. Exp 7 is
cut. Every differentiator #1–#9 is built, and **#1–#7 and #9 have now been exercised by voice in a
browser** — #7 as of Oct 20, against a real Gmail inbox.

**Oct 20 (seventh pass):** **requirement 4 is finally tested** — a tree built from exactly what git
tracks, `uv sync`, the README and nothing else. It found a bug no amount of local testing could:
the Agent Skill's advertised digest did not match the bytes served on **any Windows clone**, so a
host rejected the skill and it never loaded. Then `make eval` reproduced all six experiments from
that clean tree with **zero model calls**, and three more defects were fixed and driven live. §4's
first and third items and §7's second are closed; written up under §10. **705 tests, ruff clean.**
Whole day's live spend: **$0.00028**.

**Oct 20 (sixth pass):** **the Gmail path ran end to end for the first time** — real inbox, real
OAuth token, Bedrock extraction, proposal, Dad's spoken yes, task written. §5 is closed. Driving it
found **five defects, none of which the suite could catch**, all fixed and re-verified in the
browser; written up under §9. **698 tests, ruff clean**, exp 4 **100% / 100% / 100%** on the full
set after re-recording two phrase replies (~$0.001). The through-line of all five: the data was
right every single time and the **presentation layer dropped it** — which is the opposite of the
failure mode the suite is built to catch.

**Oct 18:** first full browser run found seven defects, three of them on camera. **Five fixed and
re-verified in the browser the same day**, plus two found while re-testing. Experiment 4 unchanged
at 100% / 100% / 100% after a one-call cassette re-record.

**Oct 19 (fifth pass):** Varun kept driving it and found that **asking about one thing gets the
whole week read back**. Fixed, plus the window wording beside it. **692 tests, ruff clean**, exp 4
**100% / 100% / 100%**. Two gaps found in the same session are **left unbuilt on purpose** and are
written up under §7 -- they are new capability, not tidy-ups, the day before the internal target.
Also this pass: `docs/features.md` written, and **I wiped Varun's data by reseeding** (§8).

**Oct 19 (fourth pass):** Varun drove it himself and cancelling failed on both of his phrasings.
**Four root causes, none of which the suite could have caught**, all fixed and re-verified in the
browser. **690 tests**, exp 4 unchanged. Written up under §2 below.

**Oct 19 (third pass):** §1 and §2 are **closed**. **685 tests, ruff clean**, exp 4
**100% / 100% / 100%** on the full set (16 schemas) -- and that number now means something it did
not this morning, because **every one of the 55 transcripts asserts its answer**, not just its tool.
Coarse is 92.7 / 94.5 / 90.9; its answer score *fell* under the stricter assertions, which is the
measurement improving rather than the arm regressing.

**Oct 19 (second pass):** `cancel_event` built -- the write path goes both ways now. Flow B driven
end to end in a browser; three defects found there that the suite did not catch, all fixed and
re-verified. Recording the new transcripts cost ~50 model calls, about $0.02.

**Oct 19:** swap approval closed and the speaker switcher now clears the thread. "Anything waiting
for me?" is answered in code, and the asker is told whose call it is. **647 tests, ruff clean**,
exp 4 still 100% / 100% / 100% with **zero** model calls spent. **The five-turn swap shot was then
driven in a real browser**, Dad through Mom, and cost **one** model call in total ($0.000086): only
the swap request reaches the model, and the guard, the read-back, the card and Mom's yes are all
code.

**20 tools registered** on the server · **16 schemas** the model routes among · **9** in the coarse
arm. Whole project spend to date is inside the ~$1.50 estimate.

---

## What is left

The one authoritative list. Phase checkboxes below are history, not a to-do.

### 1. Fix what the browser run found (top priority)

**Five of seven fixed and verified in the browser, Oct 18.** Detail and evidence in **First full
browser run** below. **641 tests, ruff clean.** One model call was spent re-recording the cassette.

- [x] **#5 what-if was unreachable by voice.** Three phrasings, three separate defects, all fixed
      and re-checked in the browser:
      - `_pin_day` resolves a named weekday **in code**. The model answered Oct 21 for "Thursday".
      - `_starting_around` restricts a bare time to the **asker's own** diary and allows half an
        hour of rounding, so "my 4 PM" finds a 15:45 review and can no longer reach a child's
        16:00 project. A time with no title is a claim about one's own diary; naming an event is
        how you ask about somebody else's.
      - `_correct_title` replaces a title the model invented (`"my"`) with the one the sentence
        names, from the family's own event vocabulary; `_fill_until` reads "runs till 5:30" from
        the sentence.
- [x] **A worsened problem was reported as safe** -- found by re-testing, not in the original run.
      The football pickup went from "Dad arrives 17:25" to "Dad is in a meeting until 17:30" and
      `ripple` keyed it as `unchanged`, so the answer was "That works. Nothing new breaks."
      `Ripple.worsens` splits a problem whose explanation changed, `is_safe` accounts for it, and
      the card labels it "gets worse".
- [x] **The child view's voice contradicted its own card.** Root cause was in the facts, not the
      model: the hidden-event summary is suppressed when a subject is named, and redacted blocks
      were filtered out, so the facts were literally "Dad has 0 things on Thursday" and the model
      worded that faithfully. Asked about one person, a blocked-out hour **is** the answer, so
      `answerable` keeps them. Privacy holds -- "busy", never a title or a place.
- [x] **The swap card rendered `undefined changes` / `undefined →`.** `request_swap` never supplied
      `change_count`, `was` or `now`; the card is one template shared with `fix_week`. A test now
      pins that contract so a third card cannot drift.
- [x] **#3's sentence was raw.** "Not Grandpa: rule: only when no parent is free" now reads "Not
      Grandpa, because your rule says only when no parent is free. Mom can." The stored reason is
      unchanged -- `conflicts` classifies a rule clash by its `"rule:"` prefix -- so `say_reason`
      rewords it in the spoken layer, where every other sentence is built, and the card uses the
      same transform.
- [x] **24-hour times leaked into speech.** Six sites now use `say_time`: "arrives at 5:25 PM,
      needs to be there at 5 PM", "past your rule of 9 PM", "Thursday 7:30 PM". `say_time` takes a
      bare `time` too, because a rule stores its cut-off as one.
- [x] **A stale `app.js` survived a restart and a reload** -- half an hour chasing a bug that was
      already fixed, and a stale demo on camera waiting to happen. The simulator's static files now
      serve `Cache-Control: no-cache`, with a test.
#### Still open

**Swap approval: how Mom says yes.** Settled as a design, Oct 18, and **the voice path already
works** -- proven in the browser with no clicking at all:

| who | said | result |
|---|---|---|
| Dad | "ask Mom if she can take Thursday, I'll take Tuesday" | proposal held **against Mom** |
| Dad | "yes" | **refused**, 0 model calls |
| Mom | "yes" | `decided_by` = Mom, both legs executed in the DB |

`pending_proposal` is keyed by **who is being asked**, not who is speaking, which is why Dad cannot
approve his own swap. So the card's Approve button is **not the mechanism** -- it is additive, as
Phase 10 already says: cards support the spoken answer and never replace it. In production Mom has
her own device and her own session; the speaker switcher stands in for a second Echo.

The one real platform limit: **LifePilot cannot tap Mom on the shoulder.** No documented way exists
for an MCP add-on's server to start a conversation (`ProactiveEvents` is a classic-skill API that
delivers a notification, not speech), so Mom learns of it either by asking or in the morning
summary. Written up in `docs/alexa-platform-limits.md`; the simulator's speaks-first path is badged
simulated and makes zero model calls.

Two small changes close it, both decided **in code** rather than by the model, the same shape as
`_decision`, `_trouble_wins` and `_money_is_declined`:

- [x] **`_whats_waiting`** -- "anything waiting for me?", "do I have anything to approve?" matched
      in code and answered from **`list_proposals`**, re-speaking the proposal and re-showing its
      card. **Zero model calls** (a tool call is not a model call). Built off the server's
      `yours_to_decide` rather than session state, which is strictly better than planned: Mom can
      walk up to a *fresh* session, ask, and then say yes. The read-back is rebuilt in code, not
      replayed, because the server's sentence was addressed to whoever asked and talks about Mom in
      the third person. Of several pending, `_the_one_asked_of` prefers the one addressed to the
      speaker by name over a week-fix any parent could decide, then the newest. It re-arms
      `pending_proposal`, so the next "yes" settles that one.
- [x] **Reword the asker's refusal.** `_nothing_to_decide` names whose call it is: Dad now hears
      "That one is Mom's to answer." The cassette did **not** expire -- both paths are decided in
      code before the model, so exp 4 replayed 63 / recorded 0 and still reads 100% / 100% / 100%
      on the full set. The swap transcript gained Mom's read-back turn as a fifth exchange, so the
      demo's shot is now pinned by a test.

**Other open items:**

- [x] **Switching speaker keeps the previous speaker's turns on screen.** The switcher now clears
      the thread, because it stands in for a second device and has to look like one. The debug
      drawer is deliberately kept: it is the engineer's view of the whole run, not anybody's
      session. Only an explicit click clears -- the server also calls `setSpeaker` at session
      start, and clearing there would wipe the greeting. Pinned by a test in `test_session.py`.
- [x] **Audit the other `args={}` transcripts.** Done Oct 19. **16 of 55 asserted nothing about the
      answer**; all 55 do now, so the 100% finally certifies answers and not just routing. The audit
      found one real defect: asked "when does Mom finish work on Friday", LifePilot said **"she has
      school from 8 AM to 3 PM"** -- the children's school is in Mom's day because she *drives* it,
      and `mine_only` stripped the names off every line. `driven` is computed for the **viewer**,
      not the subject, so the lift phrasing never fired for a question about somebody else. Fixed in
      the spoken layer rather than the server, deliberately: `event_view`'s `driven` also gates
      caregiver visibility, and that is not a path to loosen for a wording bug.
      The refusals are asserted too, which is what routing alone had been missing: "order milk"
      scored *correct* while reciting the whole diary, because `cannot_help` was the right tool name
      and nobody looked at the sentence.
- [x] **Two wording warts seen in passing.** Both fixed Oct 19. `_on` drops the preposition before
      a day that is already an adverb ("Today at 5 PM", but "On Thursday at 5 PM"). `_why_them`
      says the name once: **every** reason `allocation` records opens with the name, so
      "{name}, because {reason}" doubled it every single time -- "Mom is the only one who can get
      there." is the whole answer. The stored reason is untouched; the card and "why not X" use it
      on its own, where the name has to be there. The fallback puts the name in front rather than
      reaching for "because", which would need a pronoun nobody has told us.

### 2. Cancelling an event — the write path only goes one way

Raised by Varun, Oct 18, and verified in the code. **You can book an event and you cannot cancel
one.** A planner that only adds is not a planner.

**Built Oct 19. `cancel_event` is the 17th registered tool and the 16th the model routes among.**
Flow B is complete and was driven in a browser: propose, repair-the-week, approve, rule guard,
override, reject, and the "which one?" question. Flow A is complete **as a booking over a taken
slot**; the two-verb sentence is not, and is the one thing left in this section (below).

Found in the browser, not by the suite -- the second time that has happened:

- **A day the sentence never named.** Asked to "cancel Anaya's piano class", the model filled in
  `day=2026-10-20`. Piano is on Thursday, so the answer was "I cannot find piano class" followed by
  a list of the diary **with piano class in it**. The day and the time now come from the sentence or
  not at all, the same rule as `_correct_the_day` and `_pin_day`. Third instance of that lesson.
- **"order milk" routed to `cancel_event`** once a sixteenth schema was in the block, and recited
  the whole diary at somebody asking for milk. Sharpening the description did **not** fix it, which
  was measured rather than assumed; `_errands_are_declined` does, in the shape `_money_is_declined`
  already set. LifePilot is not a grocery list, and declining out-of-scope requests is a judging
  signal.
- **Two deletions described as one deletion and one repair.** "Cancelling the science project block
  also fixes the science project block" is one event said twice. `_really_freed` drops both the
  cancelled event and any lift that went with it, so what is left is the real claim: cancelling
  Dad's review makes Thursday's football pickup reachable.

- No cancel tool: `lifepilot/tools/` has `add_event.py` and nothing that deletes, and no schema in
  `TOOL_SCHEMAS` mentions one.
- **`_apply_remove` already exists and works** (`approve.py:179`), taking the lift assignments with
  it — but it is reachable *only* as the `remove` leg of an `add_event` swap over a taken slot.
  **Fourth instance of Lesson 1:** built, tested, unreachable.
- `cancelled` exists only as a `what_if` hypothetical, so you can ask what the ripple *would* be and
  then have no way to act on it.
- **Word collision to settle first:** `"cancel"` is in the `NO` set (`agent.py:530`), so "cancel
  football practice" can read as refusing a pending proposal rather than deleting an event. It will
  misfire exactly when a proposal is pending unless this is decided before a schema lands.

**A cancellation cannot create a clash** — it frees time. So the check is not `add_event`'s check run
backwards; it is the opposite direction: *what did this event unblock, and who still needs covering.*
Two flows, both specified by Varun, Oct 18.

#### Flow A — cancel a shared plan and put something in its place

*"Cancel our lunch at Grandpa's and book lunch with Mom instead."*

One proposal carrying `remove` + `add`, applied together or not at all. **The shape already exists**:
`add_event` builds exactly this when booking over a taken slot, and `_apply_remove` takes the lift
assignments with it. Nothing new in `approve.py`.

- [x] **One row or two, decided from the data, not the words.** `lunch at grandpa's` is a *single*
      event (id 22) with `member_ids = [1, 2, 3, 4, 5]`, so "cancel it for both of us" is one
      `remove` — but it also clears the event from **both kids and Grandpa**. Where the same plan is
      two rows (each parent's `work`), it is two `remove` changes in one proposal. The proposal says
      whose day it clears either way.
- [x] **Name everyone who loses the event, not just the asker.** `who_else_loses_it`, shared by
      `cancel_event` and `add_event`'s replacement path. Grandpa is on this one and is a
      caregiver who cannot approve; the kids are on it too. A cancellation that silently empties
      three other people's afternoons is the failure mode here.
- [x] **Judge the replacement against the post-cancel week, not the current one.** Was broken and
      is now proved: booking over Dad's review reported "Dad is in two places at once: performance
      review and coffee with Mom" -- a clash with the very event being removed. `_week_after` builds
      the week the whole proposal would leave, and the repair is solved from that week too.
      `test_add_event.py` pins it, and the test that asserted the phantom clash was rewritten. Lunch with Mom is
      only feasible once the old lunch is gone. This is the principle `request_swap` already
      learned — judging a parent while they still hold what they are handing over is judging the
      wrong week — so reuse it rather than rediscovering it.
- [x] **A fixed commitment is offered, with the words attached.** Already true for `add_event`;
      `cancel_event` keeps `movable = False` and an `immovable_event` rule distinct the same way. `lunch at grandpa's` is
      `movable = False`, which is seed data, **not** an `immovable_event` family rule. The Oct 2
      precedent already decides this: offer it, because a parent is the authority on their own diary,
      but say "which is a fixed commitment". Keep `movable = False` and a family rule distinct — the
      first is a property, the second is something the family said.

#### Flow B — cancel one person's own event, after showing the knock-on

*"Cancel my meeting."* (Mom)

- [x] **Resolve which event first.** `Ambiguous`, modelled on `request_swap`: "cancel my work"
      answers "Which one: work today ... or work Friday?" and proposes nothing. The asker's own
      events win over the other parent's. Overlapping or adjacent work makes "my meeting" ambiguous, and
      that is the real overlap check here: a day holding two of Mom's meetings is a **question, not a
      guess** — the rule `request_swap` already follows for a day holding two lifts.
- [x] **Then state the knock-on, before the yes.** All three, via `what_if(kind="cancelled")`. Reuse `what_if(kind="cancelled")`, which already
      computes this ripple and changes nothing:
      - who is **freed**, and what that now makes possible — a cancelled 15:45 meeting is exactly what
        makes Thursday's 17:00 football pickup reachable for Dad, so a cancellation can *repair* the
        week, and saying so is the differentiator;
      - which **lifts no longer need anyone**, if the cancelled event itself needed transport;
      - what is **left stranded** — the one case where cancelling genuinely breaks something, e.g.
        cancelling the school run.
- [x] Only then approve and apply. Parent-only, like every other write.

#### Shared

- [x] `cancel_event` → `Proposal(kind="event")` carrying one or more `remove` changes → existing
      `approve_proposal`. Zero new approval machinery, exactly as predicted.
- [x] **Refuse what a family rule pins.** Cancelling an `immovable_event` outright is a stronger act
      than moving it, so it needs an explicit parent override, never a silent yes.
- [x] Resolve the `"cancel"` / `NO` collision, and assert the **answer** in a transcript (Lesson 2),
      not just the routing. **The collision needed no code change, which was proved rather than
      assumed:** `_all_decision_words` already requires everything after "cancel" to be more
      agreeing or refusing, so "cancel football practice" was never a refusal. Only bare "cancel"
      and "cancel please" are -- and said straight after "shall I put it in?", that is correct. Both
      sides are now pinned by tests so nobody re-opens it.

#### Found by Varun driving it, Oct 19 — all fixed

Two sentences, four separate defects. Every one of them is the gap between a tool that works when
called correctly and a product that works when spoken to.

- [x] **"Cancel the work event for tomorrow"** -> *"I cannot find work event in the diary."* Two
      causes at once. The title matched as a **whole phrase**, so "work event" did not find "work";
      it now falls back to matching on real words, with the wrapper words ("the", "event", "my",
      "appointment") stripped. And **"tomorrow" was not a day**: `named_day` only ever knew weekday
      names, so the day was dropped and the search ran across five identical "work" rows.
      `_day_meant` understands today, tonight, tomorrow and yesterday.
- [x] **"Work for Tuesday 9:30 to 2:15 p.m. cancel it"** -> the model put the whole time phrase in
      `title`. `_correct_title` already fixed exactly this for `what_if` (`title: "my"`), so cancel
      now reuses it -- but **only after a miss**, so the common path pays nothing. One more call to
      the server, no model call, the same recovery `_decide` makes from "which lift?".
- [x] **The "I cannot find X" list was the whole family's diary.** Ten titles including other
      people's piano and cricket, one sentence after being told "you have two things tomorrow".
      That is what made it look like LifePilot had lost the schedule -- it had not, it was answering
      a different question from the one asked. It now lists **what that person has on the day they
      asked about**: "I cannot find yoga tomorrow. You have: school and work."
- [x] **"on tomorrow"** -- the same wart as "On today at 5 PM", in a second place. `say_on` now
      lives in `lifepilot_shared/speech.py` and both sides use it.

Then, in the same session:

- [x] **"When do I have lunch with Mom?" read the whole week back** -- eight work blocks, and the
      lunch never mentioned. The model picked `get_schedule`, filled `start`, `end` and `about`,
      and **left `title` empty**, so everything came back and everything was recited. The filter
      works perfectly when it is passed; nobody was passing it. `_when_is_question` now reads the
      thing out of the sentence from the family's own event names, the same shape as
      `_lift_question` next to it -- but **keeps `about`**, because "when does Mom finish work" is
      about Mom *and* about work, and dropping her answers with everybody's working day.
      It fixed a second answer for free: *"when does Mom finish work on Friday"* went from a
      three-sentence recital that wrongly said **"she has school"** to **"Mom's work is tomorrow
      from 9 AM to 2:30 PM at her office."**
- [x] **The "nothing found" sentence named a different window from the card beside it** -- "last
      Saturday to Friday" spoken, `2026-10-19 to 2026-10-23` on the card. It quoted the session's
      loaded week instead of the window actually searched. Two answers to one question.

**Lesson 0, again, and this is the fourth time:** every one of these is a tool that passed its own
tests. 690 tests did not catch a single one. A person typing a sentence caught six in two minutes.

#### Closed Oct 19 (second pass)

- [x] **One sentence, two verbs.** Built as a `replace_with` leg on `cancel_event` rather than as
      routing one utterance to two tools: **one tool call, one proposal carrying `remove` + `add`,
      one model call.** That is CLAUDE.md's own cost rule -- let server tools do the chaining --
      and it is why no new routing machinery was needed. The replacement takes the cancelled
      event's slot, because "instead" means the same slot; a different time is a separate booking.
      Both legs are judged against the week the whole proposal would leave.
      The model then left Mom out of "book lunch **with Mom** instead" and the replacement came back
      "for Dad", so who it is with is read from the sentence against the family's own roster --
      which `_known_things` was already fetching and throwing away. Only the tail after "with" is
      scanned: "lunch at Grandpa's" names him as part of what is cancelled, not as a guest at what
      replaces it. Driven in the browser, propose through approve.
- [x] **Answering the "which one?" question.** `_settle_choice`, the same shape as `pending_child`.
      The options differ only by day, so the day is the answer, matched in code -- **zero model
      calls**, verified in the browser ("cancel my work" -> "Which one?" -> "Thursday"). It falls
      through when the words name none of them, so changing the subject still works.
- [x] **Cancelling something already past** now says so ("That one has already happened. Shall I
      still take it out?"). Said as one more clause rather than an early return, because who else
      loses it and what it strands are still the answer.

### 3. Demo-script decisions (not code)

- [ ] **`fix_week` takes Thursday football off Dad, killing the swap's premise.** Demo the swap
      before the fix, or reseed between takes.
- [ ] Settle the running order and run the whole script once more, clean, after the fixes land.
- [ ] Shoot the swap as **five spoken turns, no clicks** -- all five verified in a browser Oct 19 (see §1's swap-approval item for why the
      button is not the mechanism):

      | who | says | answer |
      |---|---|---|
      | Dad | "Ask Mom if she can take Thursday, I'll take Tuesday" | "...Mom has to agree before anything changes." |
      | Dad | "Yes" | *the guard* -- "That one is Mom's to answer." |
      | — | *switch speaker to Mom* | the demo control standing in for Mom's own device |
      | Mom | "Anything waiting for me?" | the swap, read back (`_whats_waiting`, built Oct 19) |
      | Mom | "Yes" | "Done. Mom has football practice, and Dad has cricket practice." |

      The refusal is the shot that makes the guard look real rather than scripted. Leaving it out
      makes the swap look like a form submission.

### 4. Submission

- [x] **Fresh clone → `.env` from `.env.example` → follow only the README.** Done Oct 20, and it
      was quietly broken: see §10. The tree was built from `git checkout-index` -- exactly the 145
      files git tracks, no `.venv`, no `.env`, no `demo.db`, no `eval/results/` -- then `uv sync`,
      `cp .env.example .env`, seed, tests, both processes, a driven turn. Four defects, two of them
      invisible from the working tree. Worth repeating from the real GitHub URL before submitting;
      the one thing this method cannot reproduce is `git_sha`, which reads `unknown` without a
      `.git` directory and resolves normally in a real clone.
- [ ] README: concise, fresh-clone setup, every number traced to a CSV, plus the honest notes
      `CLAUDE.md` requires and the three in **Honesty notes** below.
- [x] `make eval` from clean -- done Oct 20 in the fresh-clone tree, and **re-run Oct 21 at
      `e967952`** so all six CSVs stamp the commit being submitted rather than the two older SHAs
      they carried. Identical numbers, **0 model calls**. One command, six CSVs and
      five PNGs, **0 recorded / 0 model calls**: exp 1 overlap F1 0.400 against LifePilot 1.000,
      exp 4 100% / 100% / 100% full and 92.7 / 94.5 / 90.9 coarse, exp 5 100% caught against 60%,
      exp 6 spread 0.43 against 5.00. Every README number traces to one of those CSVs.
- [ ] Product feedback for every Amazon/AWS tool used, plus the friction log. **The friction log is
      current as of Oct 21**: entries 36-42 cover the Oct 18-20 work, which until then lived only in
      this file -- the browser run, `cost`/`costume`, the token limit eating the deadline, the four
      presentation defects, the wrong hop, the fresh-clone run and the CRLF skill digest. Feedback
      for Bedrock and the MCP Python SDK is written up inside entries 38 and 42. **Still to do:**
      gather the feedback scattered across nine entries into one `docs/product-feedback.md` and
      paste it into the Devpost form -- a judge will not find it inside a 1,350-line log.
- [x] **`docs/features.md` written** (Oct 19) -- every feature in plain language, with a real
      spoken example for each, taken from browser and eval output rather than invented. Carries two
      sections that matter as much as the features: what LifePilot **deliberately does not do**
      (not a to-do list, not a chore scoreboard, no dashboard, never acts on its own) and the
      honest notes (synthetic family, our own demo emails, partner notifications simulated, fixed
      travel-time table, **and that the Gmail path has never run against a real inbox**). Useful
      raw material for the README and the submission text.
- [x] **`CLAUDE.md`'s counts corrected, Oct 21** on Varun's say-so: **20 registered, 16 vs 9**, the
      coarse set quoted at its measured **92.7%** (args 94.5%, answers 90.9%, all three 87.3%) with
      the conclusion unchanged, `cancel_event` and `scan_risks` in the tool table, `update_task`
      named as the one thing in it not built, and the cost table's tool block corrected from "~3,500
      tokens of 18 schemas" to the measured **1,879 tokens of 16**. Nothing else in the spec touched.

### 5. Gmail (#7) — closed Oct 20

- [x] **The path from real Gmail through Bedrock to the solver has now executed.** Dad linked
      `lifepilot.demo.2026@gmail.com`, a costume email was sent from the sender playing the school,
      `check_school_email` read it, Nova extracted the task, the week was checked, a proposal came
      back and Dad's spoken yes wrote it. The stored row is exactly what `CLAUDE.md` promises:

      ```
      school_message: freelancer.dev05@gmail.com  2026-10-20  extracted   (no subject, no body)
      task:           'Farmer costume for Annual Day'  owner=Aarav  due 2026-10-23  source=email
      ```

- [x] Allowed senders set by voice ("only read emails from ..."), and the allowlist refusal proved
      real on the way: with no sender set, `check_school_email` declines rather than reading.
- [ ] Transcripts for #7, now that the inbox has mail in it. Note the **cache by Gmail message id**
      makes re-recording awkward: an email is extracted once ever, so a transcript needs a fresh
      message or a cleared `school_message` row.
- [ ] Still unexercised against a real inbox: the **closure** email (`closure_tomorrow`) and the
      **injection** email (`injection_cancel_pickups`). Both pass against the fake client. The
      injection one is the security claim in the README, so running it live is worth the ten
      minutes.
- [ ] **Re-link on video day.** Testing-mode refresh tokens expire every 7 days, so the Oct 20 link
      is dead by Oct 27. Already in `CLAUDE.md`'s video-day list; repeated here because it is the
      single most likely thing to break on camera and it is silent until email is asked for.

### 6. Optional

- [ ] Grow transcripts from 47 towards ~100. Replays free; purely authoring time.
- [ ] Offer the Skills extension upstream (Open Source mini challenge). **Check first whether a
      newer SDK already ships one** — the Python SDK docs list an `mcp/server/skills` module that
      2.1.1 does not have, so this may be a backport note rather than a feature.
- [ ] Write the coarse-set wording caveat into the README rather than tuning the descriptions.

### 7. Found by Varun, Oct 19 — one built Oct 20, one still deliberately NOT built

Both were **missing capability**, not bugs, and both were found the day before the internal target.
Varun's call, not an assistant's. The second was built on Oct 20 and is kept here with its original
diagnosis, because that diagnosis turned out to be wrong in a way worth not repeating (§10).

- [ ] **"On which day can I schedule a lunch with Mom at 1 PM?" cannot be answered.** There is no
      tool that **searches across days for a free slot**. The whole tool set either shows what is
      there, judges one named day (`what_if`), or writes. So the model routed to `get_schedule`
      with `at=1 PM` and answered about **today** -- a correct answer to a question nobody asked.
      The hard part already exists: `free_gaps()` in `lifepilot/engine/risk.py` finds usable free
      stretches across a date range, and `scan_risks` already uses it to pick a slot for a task at
      risk. What is missing is overlapping **two** people's gaps and a `find_time` tool to route
      to. Estimated: the tool and the wiring are small, the two-person overlap is a few hours.
- [x] **`add_event` does not read "with Mom" from the sentence** -- built Oct 20, and the fifteen
      minutes were right about the size and wrong about the shape. See §10: the diagnosis in this
      entry was itself wrong, which is why driving it mattered.

**The bigger point Varun made, which is worth keeping:** when a question falls outside the tool
set, LifePilot gives a **near-miss answer instead of saying it cannot do that one yet**. Answering
about today when the week was asked about is worse than admitting the gap. This is not the model's
fault -- by design the model only routes and phrases, and is never allowed to judge availability,
because an invented availability answer is a missed pickup. But the honest behaviour for an
unanswerable question is a refusal, and `cannot_help` already exists to carry one.

### 8. Reseeding destroyed Varun's data — my fault, not a bug

While testing, I ran `eval.generate --seed-db --reset` against `demo.db` three times to get a clean
slate. Each one dropped every table. One of them destroyed the `lunch with Mom` that Varun had
created in the browser, and he then reasonably asked why LifePilot could not find it.

The `.env` rule written into `CLAUDE.md` earlier the same day (lesson 9) says a remote reseed is the
owner's call. **The same reasoning applies to the local demo database once somebody is using it**,
and I did not apply it. A reseed is not a neutral setup step; it is destroying whatever is there.

- [ ] Nothing to build. The rule is already written; it needs to be **followed for `demo.db` too**,
      and a reseed asked for rather than assumed whenever Varun has the browser open.

### 9. Found by Varun driving Gmail, Oct 20 — all five fixed

Every one of these had **correct data in the database** and lost it on the way to the person. The
suite asserts tool results, so none of the four could have been caught by it. The question that
exposed them — *"when is the farmer costume due"* — now answers in one sentence.

- [x] **`"cost" in "costume"` declined a school task as a money question.** `MONEY` was matched as
      a **substring**, so `_money_is_declined` overrode a correctly-routed `get_schedule` and
      answered *"LifePilot keeps no record of money"* about a costume LifePilot had written down
      itself. Nova was never wrong here; our own guard was. Now matched on whole words
      (`MONEY_WORDS`), with six regression tests. **Sixth instance of the lesson that a cheap
      keyword guard is a liability the moment the family's own vocabulary collides with it.**
- [x] **Deadlines were spoken last, so the token limit ate them.** `_facts` appended `_task_facts`
      after up to eight event lines, and `phrase` ran at `max_tokens=160`. A seven-event week was
      cut mid-word and the costume was never said. Deadlines now come **before** the day's shape:
      a deadline is the part that gets missed if it is not said, and school and work are the part
      already known.
- [x] **A truncated sentence could be spoken at all.** `max_tokens` is now 320 and `phrase` checks
      `stopReason`: on `max_tokens` it says the computed facts instead of a sentence that stops
      mid-word. No retry, no second call, so the ceiling is untouched.
- [x] **The schedule card never drew tasks.** `agent.py` had been sending `card.tasks` in the
      payload all along and `renderScheduleCard` only iterated `card.events` — the word `task`
      appeared nowhere in `app.js`. Tasks now render as a "due" row with day and owner, before the
      events, and a day with only deadlines no longer reads "Nothing visible to you this week."
- [x] **The family's vocabulary did not include its own tasks.** `_known_things` indexed event
      titles and locations only, so `_the_thing_they_named` could never match "costume" and the
      question fell through to the model's guess — the asker's whole week. Tasks are now indexed
      too. Half a fix on its own, though: with `title='costume'` but `about='Dad'`,
      `context.get_schedule` filtered Aarav's task straight back out (`about='Dad'` → 0 tasks;
      `about=None` → the costume). So `_when_is_question` now **drops `about` when the named thing
      is a deadline**, because a deadline belongs to whoever owns it, not whoever asked. `work`
      and the rest keep `about` — *"when does Mom finish work on Friday"* still answers about Mom.

- [x] **The simulator blamed the wrong hop.** The cheap option is built and driven live Oct 20:
      `_why_degraded` has a third branch, so a dead session now says **"I cannot reach the planning
      server"** rather than "Something went wrong reaching the language model". Proved in the real
      failure mode -- the MCP server killed under a running session, not a mocked exception. It had
      by then cost half an hour once and a confused cycle twice more, the second time to me while
      verifying something else.
      **Reconnection is still not built, on purpose:** `lifespan` still opens one `MCPClient` and
      holds it for the life of the process, so restarting the MCP server alone still leaves that
      session dead -- it now says so honestly. Touching the hot path three days from the deadline
      buys less than it risks. **Operationally: start the MCP server first, then the simulator**,
      and restart both after a server-side change. That order is now in the README, because it cost
      a cycle today: a server-side sentence was fixed, only the simulator was restarted, and the
      old sentence came back from the stale server process.

**Not a defect, worth knowing:** "Nothing new from school" was correct when the allowlist named the
**linked inbox** rather than the **sender playing the school** — the query `from:(the demo account)`
genuinely matched nothing. The answer was honest and still sent us looking at the wrong thing. An
allowlist equal to the linked account is a detectable mistake and could be worth one sentence back
("that is the account you linked; who sends the school's email?").

### 10. The fresh-clone run, Oct 20 — four defects, two invisible from here

Requirement 4 had never been tested, and it was the only remaining item that could fail the entry
outright rather than cost it points. The tree was built with `git checkout-index` so it held exactly
the 145 files git tracks, then driven by the README alone.

**Two of the four could not have been found in the working tree.** That is a different category from
Lesson 0: not a tool that passes its own tests, but a repository whose contents differ from the
developer's disk.

- [x] **`docs/features.md` was never in the repo.** `.gitignore` carried a bare `features.md`,
      which matches at any depth, so the file written on Oct 19 was ignored. The other two docs
      survived only because they were tracked before that rule landed -- git ignores do not apply
      to already-tracked files, which is exactly why the mistake was invisible. The friction log was
      safe, which matters: it is requirement 7.
- [x] **The Agent Skill advertised a digest for bytes it does not serve.** `skills.py` digested
      `path.read_bytes()` while serving `path.read_text()`, whose universal-newline translation
      turns CRLF into LF. Our tree is LF, so the two agreed by luck. `core.autocrlf` is **Git's
      default on Windows**, so every Windows judge got a catalogue claiming 3413 bytes
      (`e6cb528d…`) for the 3344 served (`37f89e46…`), and SEP-2640 has the host reject the
      mismatch: **the skill silently never loads.** That is the Open Source mini challenge's own
      artefact failing on the most likely judging machine. `_served_bytes()` digests what goes on
      the wire; the regression test writes its own CRLF file, so it fails on an LF checkout too
      rather than waiting for another Windows clone.
- [x] **`make test` failed on a fresh clone.** `tests/test_app.py` used `TestClient(app)` as a
      context manager, which runs `lifespan` and opens a real `MCPClient`, so both tests died with
      `ConnectError` where nothing was running -- under a docstring reading "Offline and free". The
      routes under test are mounted at import time and never needed it. `test_session.py` had
      already avoided the real lifespan for this reason.
- [x] **Stale README numbers.** 369 tests (it was 698, now 705) and 35 utterances (55). Both are
      numbers a judge can check in one command, which is the point of promising them.

**Then `make eval` from that clean tree**: one command, six CSVs, five PNGs, **0 recorded, 0 model
calls**, every experiment reproducing. The one thing the method cannot reproduce is `git_sha`, which
reads `unknown` with no `.git` directory.

#### Three more fixed while verifying, all driven live

- [x] **`add_event` now reads "with Mom" — and §7's diagnosis of it was wrong.** §7 said `_members`
      defaults to the asker "when the model fills no `members` list". Driven in a browser, the model
      **did** fill it: `["Dad"]`. So a fallback for the empty case never fired, and the booking came
      back titled *"Lunch with Mom"* with Mom not on it. It is a **union**, not a default: anyone
      named after "with" is added to whoever the model named. **This is not cosmetic** -- with Mom
      actually on the event the solver sees that *she* is double-booked, which it structurally could
      not before. **Seventh instance of Lesson 0, and the first one where my own new test had the
      wrong shape and passed anyway.** 705 tests did not notice; one typed sentence did.
- [x] **"It breaks 2 things:" named one of them.** `add_event.py` announced the count and then spoke
      `breaks[0]` alone, while the card beside it listed both -- two answers to one question, and a
      parent approving a problem nobody told them about. Pre-existing, and only reachable once a
      booking could put two people in the clash, so the fix above is what surfaced it. **Third
      instance of the Oct 20 pattern: the data was right and the presentation dropped it.**
- [x] **The failed hop is named** -- see §9.

**What this run says about the suite.** 698 tests passed on a machine where the Agent Skill was
broken for every Windows judge, `make test` failed from a clean clone, and a promised document was
not in the repository. None of those are logic errors, and no unit test was ever going to see them:
they live in the gap between the working tree and what is published. Worth repeating the whole
exercise once from the real GitHub URL before submitting.

**Cut:** exp 7 (user study — not code, and the first item in the drop order; a study thin enough to
run in the time would be the one invented number in a set where everything traces to a CSV). Stretch
tools `make_study_plan` and `get_load_summary`.

---

## First full browser run (Oct 18 2026)

The demo script driven end to end in a real browser for the first time, as Dad, then Mom, then
Aarav, against the seeded family on local SQLite. Ten turns, $0.0003 total. **Three of the seven
findings are in the video and none would have been caught by the test suite.**

The seven findings below are kept **as first observed**, because the symptom is the useful record and
each one's cause is worth not rediscovering. What is fixed, and how, is in *What is left* §1 --
five of seven, same day. Two more surfaced while re-testing and are recorded there too.

### What worked, verified rather than assumed

- **#1** `detect_conflicts`, 151 ms: the unreachable Thursday pickup ("Dad arrives 17:25, needs
  17:00") **and** the 9 PM rule breach, with no two events overlapping. The headline holds live.
- **#2** `suggest_responsible`, 34 ms, with per-candidate exclusions on the card.
- **#4** `fix_week`, 146 ms: a 2-change diff on a real MCP App card in a sandboxed iframe, each
  change carrying its reason.
- **The Approve button**, never pressed before: reached `approve_proposal` through the host bridge in
  55 ms with **zero extra model calls**. Both changes confirmed in SQLite — block moved to
  19:30–21:00, pickup reassigned Dad → Mom, proposal `approved`. Re-asking returned "Nothing
  broken." **The loop closes.**
- **#6 across two sessions**, the other never-tested path: Dad proposes, Mom accepts in her own
  session, both legs execute, `decided_by` = Mom. The refusal path is also right — asked for a day
  Dad held no lift, it said so.
- **#9 at the data layer**: Aarav sees only his own events; a parent's work comes back masked as
  `Busy`.
- Prompt caching, the cost counter and the parse cache all visibly working.

### The seven findings

**1. The child view's voice contradicts its own card.** As Aarav, "what is Dad doing on Thursday
afternoon" → card shows **Busy** 9:30–3:45 and **Busy** 3:45–4:45; the spoken answer is *"Dad has
nothing scheduled on Thursday afternoon."* 3:45–4:45 PM is plainly the afternoon. On a voice-first
product the spoken line **is** the product. Cause not traced — the likely shape is that the sentence
path treats a masked event as no event while the card renderer counts it, but that is a hypothesis
and wants proving before anything is changed.

**2. #5 what-if is unreachable by voice.** Three phrasings, three different failures:

| said | routed args | result |
|---|---|---|
| "...till 5:30 on Thursday" | `start 2026-10-21T16:00` | Oct 21 is **Wednesday**; no event; refusal |
| "...my performance review runs till 5:30" | `title: "my"`, no `until` | fell back to listing every event in the week |
| "what if my four o'clock runs until half five" | `start 2026-10-18T16:00` | **today, Sunday**, where Dad has nothing → "That works. Nothing new breaks." |

Root cause is diagnosable from the contrast: **`request_swap` parses days in code** and got
Thursday/Tuesday right in the same session, while **`what_if` trusts the model** and does not.
`days_named_in_order` already exists and solves exactly this.

And it scores **100% in experiment 4** because the #5 transcript asserts `args={}` with no
`must_say` — tool name only. The third phrasing is the transcript's own wording, and its confident
"Nothing new breaks" is vacuously true. **A transcript that asserts only routing can score a
refusal, a vacuous answer and a correct answer identically.** Worth auditing the other `args={}`
entries.

**3. The swap card renders `undefined`.** Heading "undefined changes"; each row "undefined →"
instead of "Dad → Mom". Reasons render correctly ("Mom free from 16:45, 10 minutes away"), and the
fix card beside it is right, so the swap proposal's changes are missing whatever keys the card reads
for the count and the from/to. On camera at 1:30–2:05.

**4. The demo script's own order breaks the swap.** `fix_week` reassigns Thursday football to Mom,
so by the swap shot Dad no longer holds the lift the swap assumes. Live it correctly refused: *"You
do not have a lift Thursday to swap."* Not a bug — a running-order problem, and it only appears when
the script is run in one sitting, which is the whole argument for having done so.

**5. No voice path to pending proposals.** "Do I have anything to approve" → `fix_week`, which minted
a second proposal instead of surfacing the pending swap. `list_proposals` is deliberately not
model-routable, so there is no "what is waiting for me" path at all.

**6. #3's sentence is raw.** *"Not Grandpa: rule: only when no parent is free."* The spec promises
*"Your rule says grandparents only when both of you are busy, and Mom is free at 4:30."* The right
rule is named; it is the phrasing that is unfinished.

**7. Two smaller ones.** 24-hour times leak into speech ("moves to Thursday 19:30"), against the
Oct 2 rule. And switching speaker leaves the previous speaker's turns on screen, so Dad and Mom's
swap negotiation is still visible in Aarav's session — server enforcement is correct, but it
undercuts the #9 shot visually.

### The lesson, again

Four now: `request_swap`, `scan_risks`, `what_if` (reachable but wrong) and `_apply_remove` (no way
to ask for a cancellation at all — see *What is left* §2). This run found three more findings in ten
turns, and Varun found the cancel gap by asking for something obvious. **The suite cannot
tell a registered tool from a shipped feature, and a transcript that checks only the tool name
cannot tell a good answer from a refusal.** Before submission: for every registered tool, either a
routing schema and an assertion about the *answer*, or a written note saying why not.

---

## Verified facts

Established by inspecting this machine and the published wheels. Not assumptions.

| Fact | How we know |
|---|---|
| Python 3.12.4, uv 0.10.11, node 22.23.2, git 2.49 | `--version` |
| No `make` and no local Postgres on this box | `command not found` |
| AWS works: IAM user `counter-dev`, `us-east-1` | `aws sts get-caller-identity` |
| `us.amazon.nova-micro-v1:0` ACTIVE | `aws bedrock list-inference-profiles` |
| `mcp 2.1.1` serves **2025-11-25** end to end | wire test negotiates it against a real uvicorn server |
| **Avast corrupts loopback HTTP** when the request carries `MCP-Protocol-Version` | a fixed-bytes socket server returns different bytes with that header than without (friction log 7) |
| Upper pin `mcp<2.2` is forced by `strands-agents 1.57.1` | its `requires_dist` |
| Strands' modern API is `MCPClient(url=...)`; its published docs are stale | `strands/tools/mcp/_compat.py` |
| MCP Apps is first-party | `mcp/server/apps.py` |
| MCP **Skills** extension is not in `mcp 2.1.1`, but `MethodBinding` lets us serve it | `mcp/server/extension.py:58`; no `mcp/server/skills.py` in the installed wheel |
| Nova Micro has **no structured outputs**; tool calling yes | model card |
| Nova hallucinates on JSON tool results; `BedrockModel` auto-fixes it | `strands/models/bedrock.py:954` |
| Nova Micro **rejects** a `cachePoint` inside `toolConfig.tools`; one in `system` caches the tool block too | measured against the live model, friction log 35 |
| Converse reports `cacheReadInputTokens` / `cacheWriteInputTokens`, and `inputTokens` excludes them | AWS `TokenUsage` reference, confirmed on the wire |
| The tool-schema block is **1,879 tokens**, not the ~3,500 `CLAUDE.md` estimated | measured |
| Strands event loop has **no** iteration cap | only raises `MaxTokensReachedException` |
| Alexa+ MCP Toolkit is **US-only** — hence the simulator | developer.amazon.com |
| Rules explicitly allow simulating Alexa+ "via a web app" | Devpost resources |
| `SpeechRecognition` needs network; absent in Firefox by default | MDN |

### The Avast blocker, solved

Avast intercepts HTTPS with its own root CA. Python's `ssl` trusts it via the Windows store, but
**boto3 and awscli use certifi and fail** with `CERTIFICATE_VERIFY_FAILED` on every AWS call — so the
cause is not obvious. Fix, applied in `lifepilot_shared/llm.py` so both processes inherit it:

```
AWS_CA_BUNDLE=C:\ProgramData\Avast Software\Avast\wscert.pem
```

---

## Results

Every number comes from `make eval`. Model id, seed and git SHA logged with each run.

**Exp 1 — conflict detection** (35 scenarios: 20 planted, 15 deliberately fine)

| detector | precision | recall | F1 |
|---|---|---|---|
| overlap baseline | 1.000 | 0.250 | 0.400 |
| **LifePilot** | **1.000** | **1.000** | **1.000** |
| AI only (Nova Micro) | 0.000 | 0.000 | 0.000 |

The overlap baseline's 0.250 recall is the headline for #1. A control call proved the AI-only harness
could have scored above zero.

**Exp 2 — plan feasibility** (20 broken weeks, 15 repairable)

| system | breaks a rule | left broken | changes per fix | median | p95 |
|---|---|---|---|---|---|
| **LifePilot** | **0%** | **0%** | **0.8** | 14 ms | 16 ms |
| AI only | 25% | 100% | — (proposed nothing) | — | — |

Both plans applied and judged by the same detector.

**Exp 3 — family rules stored vs not** (20 scenarios: 15 repairs, 5 decisions)

| setting | accepted | broke a rule | left broken | proposed nothing |
|---|---|---|---|---|
| rules stored | **100.0%** | **0.0%** | 33.3% | 5 |
| not stored | 0.0% | 100.0% | 100.0% | 0 |

Somebody the rules bar, offered anyway on the decide path: **0%** stored, **100%** not. Per rule,
times broken when not stored: `immovable_event` 5, `latest_end` 5, `buffer_after` 5, `eligibility` 5.

**Exp 4 — tool use** (55 exchanges per arm, replayed free; re-recorded Oct 20)

| toolset | schemas | tool | args | answers | all three |
|---|---|---|---|---|---|
| full | 16 | **100.0%** | **100.0%** | **100.0%** | **100.0%** |
| coarse | 9 | 92.7% | 94.5% | 90.9% | 87.3% |

**The coarse set is worse** — a result to report, not a mitigation held in reserve. Read the 100% with
finding 2 above attached: for `what_if` it certifies routing, not the answer.

**Exp 5 — "what am I forgetting?"**

| system | caught | false alarms | mean warning | median | never saw the task |
|---|---|---|---|---|---|
| **lifepilot** | **100.0%** | **0.0%** | **3.0 days** | 3.0 | 0 |
| deadline-only | 60.0% | 66.7% | 1.0 day | 1.0 | 3 |

Warnings that came with a bookable slot: **3 of 5**. A deadline reminder offers none by construction.

**Exp 6 — load balancing** (7 weeks per arm, 2–8 lifts, same weeks both ways)

| setting | mean spread | std dev | worst | busiest share |
|---|---|---|---|---|
| with `load_balance` | **0.43** | 0.49 | **1** | 54.3% |
| without the rule | 5.00 | 2.00 | 8 | 100.0% |

Report it; never headline it.

### Honesty notes for the README

Three numbers need a sentence attached or they overclaim:

- **Exp 3's scenarios are adversarial by construction** — each is built so the rule decides the
  outcome, and a test enforces that. They show the mechanism working, not a base rate for an
  ordinary week.
- **Exp 6's "100% to one parent"** is not unfairness: with the rule off, nothing gives the solver a
  reason to prefer Mom and the deterministic tie-break orders by person id. A fair baseline, but it
  needs that sentence.
- **The coarse descriptions are one merge of the originals, written once**, and the gap is sensitive
  to their wording. Say so in a line rather than iterating — four attempts at prompt wording in this
  project have cost more than they bought.

---

## Lessons that keep repeating

Written down because each has cost real time more than once.

0. **Fix it, then watch it in the browser.** Every one of the Oct 18 fixes was confirmed by a
   passing test and then re-checked by hand in the page, and two of them were still wrong at that
   point: the what-if's rounding exposed a ripple that called a worsened problem safe, and a cached
   `app.js` showed the old card after a server restart *and* a reload. A green suite says the code
   does what the test says, not that the product does what a person sees.
1. **Registering a tool is not shipping a feature.** Four times now: `request_swap`, `scan_risks`,
   `what_if` (reachable but wrong) and `_apply_remove` (no way to ask for a cancellation at all).
   Each was built, tested and unreachable. Nothing in the suite detects this. Grep `simulator/` for a
   tool's name — that is how three of the four were found.
2. **A transcript that asserts only the tool name proves almost nothing.** It scores a refusal, a
   vacuous answer and a correct answer the same. Assert the answer.
3. **Resolve named days in code, never in the model.** Nova Micro returns the wrong date for
   "Tuesday" and "Thursday" reliably enough to break features. `days_named_in_order` and `named_day`
   exist for this.
4. **Prompt wording is the expensive fix and usually the wrong one.** Four attempts, all net
   negative. The deterministic overrides (`_money_is_declined`, `_trouble_wins`) are what actually
   worked, and they are narrow on purpose: only a tool trying to answer from the family's own data is
   ever overridden. **But narrow in scope is not narrow in matching:** `_money_is_declined` tested
   `"cost" in said`, so "costume" was money and a school task was declined (Oct 20). A keyword guard
   matches **whole words**, or the family's own vocabulary will eventually collide with it. The next
   collision is already written: `ERRANDS` carries `"buy "` and `"shopping"`.
5. **A cassette key covers the phrasing call too.** A change to what a tool *returns* expires
   recordings just as a change to a prompt does. Compute the key both ways before spending anything.
6. **Anything touching `simulator.*` must do it inside the test stack.** `conversation` freezes the
   loaded window at import; importing early makes every recording miss.
7. **Prove the cause before fixing.** The flaky exp 3, the two routing regressions and the
   `cacheReadInputTokens` typo were all mis-diagnosable and all cheap to prove.
8. **A number that flatters us is a bug until checked.** Exp 5's "66.7% false alarms" was wrong
   ground truth, not a wrong scan; the 100% exp 4 hides finding 2.
9. **Name the database in the command; never let `.env` choose it.** `db/session.py` calls
   `load_dotenv()`, so a command run without an explicit `DATABASE_URL` acts on **Neon**, not the
   local `demo.db`. `eval.generate --seed-db --reset` run that way dropped and recreated every table
   in the real database when the intent was a local reseed before a browser check (Oct 19). Not
   reading `.env` is not the same as not being steered by it. Reseeding or resetting the remote
   database is Varun's call, asked for each time — it is never a step on the way to something else.
   `tests/conftest.py` deletes `DATABASE_URL` for the whole suite, which is why this can only happen
   outside the tests. The rule is written up in `CLAUDE.md` under "Never let `.env` decide what a
   command acts on".
10. **A question about one thing must be narrowed to that thing.** The model routes correctly and
   then leaves the narrowing field empty, so the server returns everything and the answer becomes a
   recital. Four separate outings now -- `_lift_question`, `_correct_title`, `_when_is_question`,
   and tasks missing from `_known_things` (Oct 20) -- and each was reported as "it doesn't answer my
   question", never as "the title was empty". When an answer is true, complete and not what was
   asked, look at the **arguments**, not the wording. The Oct 20 one adds a second half: narrowing
   to the right **thing** is not enough if the answer stays narrowed to the wrong **person**. A
   deadline belongs to whoever owns it, so `about` has to go with it.
11. **An answer outside the tool set should be a refusal, not a near miss.** Asked which day a lunch
   could go, LifePilot reported on today, because there is no free-slot search and `get_schedule`
   was the closest thing. A near-miss answer reads as "it does not understand me"; `cannot_help`
   reads as an honest limit. The model is not at fault -- it may never judge availability -- but
   routing to the nearest tool and answering anyway is worse than declining.
12. **Right in the database is not right in the answer.** All five Oct 20 defects had correct rows
   and correct tool output; every one of them was lost **after** the tool returned -- eaten by a
   keyword guard, cut off by a token limit, left out of the card renderer, or filtered by an
   argument. The suite asserts tool results, so it was green through all five. The cheap check that
   would have caught four of them is one line: call the tool directly, then compare what it returned
   against what the page said and the voice spoke. `get_schedule` returned the costume the whole
   time.
13. **Say which hop failed.** "Something went wrong reaching the language model" was shown for a
   dead **MCP session**, and sent half an hour into Bedrock, credentials and TLS -- while a one-call
   `converse` proved the model fine in seconds. A fallback message that names the wrong subsystem is
   worse than a generic one. Built Oct 20, after it cost a cycle twice more.
14. **Test what is published, not what is on disk.** A green suite on this machine says nothing
   about the repository a judge downloads. Three Oct 20 defects lived purely in that gap: a bare
   `.gitignore` pattern kept a promised document out of the repo, `core.autocrlf` broke the Agent
   Skill's digests on every Windows clone, and `make test` failed from a clean tree while passing
   here. None is a logic error and no unit test could see any of them. `git checkout-index -a
   --prefix=` builds exactly what git tracks, which is the only tree worth testing before
   submitting -- and a CRLF-sensitive check should **write its own CRLF** rather than depend on how
   the checkout happened to land.
15. **My own new test can have the wrong shape and pass.** The `add_event` "with Mom" fix was
   written, tested green, and did nothing: the test assumed the model leaves `members` empty, and in
   a browser it fills it `["Dad"]`. Lesson 0 applies to the fix *and* to the test written beside it.
   One typed sentence beat 705 tests.

---

## Build log

Compressed. What landed, and only the decisions worth not re-deriving.

**Phase 1 — project** · git, MIT `LICENSE`, `pyproject.toml` (pins commented with reasons),
`.env.example`, `Makefile` delegating to `uv run` so the same work runs without `make` on Windows,
`docs/friction-log.md`.

**Phase 2 — model assumptions proven (~$0.002)** · `scripts/probe_bedrock.py`. **Forced tool choice
works** — the one assumption everything rested on: one output-only tool with
`toolChoice: {tool: {name: ...}}` yields exactly one `toolUse` and no stray text, including on an
email carrying an injection line. Kept as a fixture: evidence, not a promise.

**Phase 3 — data** · SQLAlchemy 2.1 typed models, portable `sa.JSON` only, verified on both SQLite
and Neon (PostgreSQL 18.6). `school_message` has **no subject and no body columns**, enforced by
schema. Alembic migration. `eval/generate.py` seeds the family. `tests/conftest.py` clears
`DATABASE_URL` so the suite stays offline and free whatever is in `.env`.

**Phase 4 — MCP server** · `MCPServer` via `streamable_http_app(streamable_http_path="/mcp")`; the
**host** lifespan must enter `mcp.session_manager.run()` or every request hangs. Role-aware views
from the start — cheap now, expensive to retrofit. Wire test asserts 2025-11-25 negotiated on the
wire (requirements 1 and 2 proven, not claimed).

**Phase 5 — the simulated Alexa+ UI** · Vanilla HTML/CSS/JS, no build step. Conversation thread, mic
with four visibly distinct states, **typed input always available** (first-class path, not a
fallback), speaker switcher, debug drawer showing tool, arguments, `solve_ms`, reasons, running
model-call count and estimated cost. Persistent "Simulated Alexa+ experience" and "Demo school · fake
emails" labels; no Amazon marks anywhere (reqs 5, 8, 10).

**Phase 5b — the Bedrock path** · `simulator/agent.py`: Nova Micro routes with forced `toolChoice`,
the server answers, Nova words the reply. Two calls per turn.
- `speaker` is **stripped from every schema the model sees** and injected from the session, so the
  model cannot hand a child a parent's view.
- The model words **facts the server computed**, never raw tool JSON — handing it JSON produced
  fluent falsehoods (friction log 12).
- `LIFEPILOT_LLM=0` falls back to a keyword router: free, offline, and the baseline for exps 1–4.
- **Prompt caching: 81% off the routing call's input cost.** The documented placement is the one Nova
  rejects — a cache point inside `toolConfig.tools` fails with `extraneous key [cachePoint] is not
  permitted`; one at the end of `system` is accepted and caches the prefix *including* the tool
  block, because Bedrock reads tools → system → messages. Measured: uncached 2,023 input tokens
  ($0.0000763); warm 69 input + 1,954 read (**$0.0000147**). 1,954 + 69 = 2,023 proves the tool block
  sits inside the cached prefix. Friction log 35.
- **A cost control that was measuring nothing:** `Turn.record` read `cacheReadInputTokenCount`;
  Converse reports `cacheReadInputTokens` (the `...TokenCount` spelling is InvokeModel's). The only
  source of the wrong name was our own test, so it passed while cached tokens counted as zero
  forever.

**Phase 6 — #1 conflicts** · `engine/reachability.py`, pure: candidates who `can_drive`, filtered by
`eligibility`; `arrival = prev.end + travel_time[prev.location][L]`; reachable iff `arrival <= T`.
Also checks the **return leg**, so an assignment cannot silently break the adult's next commitment.
- **Recording a per-candidate exclusion reason was the highest-leverage decision in the project.** It
  makes #3 "why not X?" a lookup rather than an LLM guess, at zero model cost — and #3 then fell out
  of phase 8 for free.
- `tools/detect_conflicts.py` classifies: plain overlap · unreachable (travel) · no eligible adult ·
  rule clash.

**Phase 7 — #8 rules** · `engine/rules.py`, the five types only; speech fitting no type is refused and
queried, never invented. A rule stated by voice changes what `detect_conflicts` reports on the very
next call. Names and categories are closed vocabularies, so a rule cannot store cleanly and then
match nothing (friction log 15).

**Phase 8 — #2 decide, #4 repair** · `suggest_responsible` ranks deterministically (arrival slack,
travel, load, soft preferences) by explicit tuple sort; the winning factor generates the reason. The
solver decides, the LLM only phrases.
- `fix_week` is the academic **Minimal Perturbation Problem**, using the known formulation rather than
  an invented one: `assignee[e]` per transport event, `start[m]` for movable items only; hard
  constraints for immovable starts, travel feasibility via `only_enforce_if`, `add_no_overlap` over
  each adult's intervals including travel, `latest_end`, `buffer_after`, `eligibility`. Objective
  reifies `kept[x] <=> (x == current_value)` and **minimises Hamming distance** to the current plan.
  Minimal change *is* the objective. `add_hint` with the current plan, `max_time_in_seconds ≈ 5`.
- **`num_search_workers = 8`.** OR-Tools 9.15.6755 segfaults (`Check failed: heuristics.fixed_search
  != nullptr`) on high core counts, and the reported trigger is a model that presolves to zero
  variables with a solution hint — exactly our warm-started, already-feasible case. Fixed in 10.0;
  cap workers until then.

**Phase 9 — #3 why-not, #5 what-if** · Both pure engine work, **zero extra model calls**.
`explain_choice` reads phase 6's stored reasons. `what_if` applies a hypothetical on a copy and
changes nothing — the database is byte-identical after four what-ifs (every row of every table hashed
before and after), and no proposal row is written. The ripple separates what a change *would* break
from what was already broken, so an old problem is never blamed on a new meeting.

**Phase 10 — approval loop and the proposal card** · `approve_proposal` / `reject_proposal` with
`needs_approval_from` enforced server-side. Card via first-party `mcp.server.apps`, with the
`client_supports_apps()` text-only fallback shipped **first** — the spoken answer is the product.
Minimal MCP Apps **host** in the simulator: sandboxed iframe, `ui/initialize`,
`ui/notifications/tool-input` and `tool-result`, proxying `tools/call` so Approve reaches
`approve_proposal`.
- **`@apps.tool` had to be dropped** in favour of a core tool carrying `_meta.ui.resourceUri`,
  because it hid `fix_week` from every client that had not negotiated Apps (friction log 19).
- An all-or-nothing test shows a proposal naming a deleted event applies none of its changes.

*Hardening from live testing (Oct 1):* `.env` loaded from an explicit project root with
`override=True`; a rejected certificate raises `InterceptedHTTPS` naming the antivirus, the variable
and the fix instead of an eighty-frame botocore trace; the model path falling back to the keyword
router **says so out loud**, because a silent degradation reads as "the product does not understand
me"; a week is summarised and a single day given in full; an empty window names the week that is
loaded rather than reporting an empty diary; the demo week follows the real calendar
(`lifepilot_shared/week.py`); times are spoken, not formatted (`lifepilot_shared/speech.py`, shared
by both paths so they cannot drift).

*Answer quality and the write path (Oct 2):* five answers that were true and did not answer the
question. A lift names who has to be moved (`say_lift`) — "somebody has to collect them" named
nobody. The answer window starts today. `get_schedule(title=...)` narrows *after* the visibility
rules, so naming a parent's meeting cannot reach it. `add_event` → `Proposal(kind="event")` →
`approve_proposal` is **how data gets in**; unknown names, times and places are refused, not guessed.
A taken slot is offered as a **swap** (one proposal carrying a `remove` and an `add`, applied together
or not at all), but a containing block more than twice the new event's length is reported as a clash
rather than offered for deletion, so an hour inside a working day cannot delete the day. A sentence
asking whether a time is free is a **check, not an instruction**. `simulator/reminders.py` warns when
a lift is about to become impossible, with **zero model calls**, asserted by parsing the module.
- **Built then removed the same day:** "who am I speaking to?" at the start of every session. It taxes
  every session to establish an identity the platform will not give us anyway. Sessions assume the
  linked account's parent (`DEFAULT_SPEAKER`); the limitation is documented in
  `docs/alexa-platform-limits.md`.

*The school run (Oct 2):* the family had two school-age children getting themselves home. School now
`needs_transport` with a 3 PM collection every weekday, split Mom four days and Dad one. An event you
only drive now **reads as your errand** ("You collect Aarav from football ground at 5 PM", not
"football practice 4 to 5, and someone has to drive Aarav"). Who drives is on every event
(`lift_by`). A lift sorts by when the person must be there, not when the event starts.

*The weekend the demo is given on (Oct 17):* seeded data covered Mon–Fri, so asked on a Saturday the
whole demo sat two days in the future. `demo_span()` beside `demo_week()`; one property test runs
every day of a year and asserts today is never outside it. The weekend is deliberately easy, so the
week's only unreachable lift stays Thursday's. Two latent bugs it exposed: `named_day` read a day's
**position in `DAY_NAMES` as an offset from `WEEK_START`**, which only holds while that start is a
Monday; and `_find_need` took the **earliest** lift in the window, so "who should pick up Aarav" asked
on Thursday answered about Saturday's match. Also `rank()` passed `runner_up=None` for the *last*
candidate as well as a lone one, so whoever came last claimed to be "the only one who can get there"
while ranked behind somebody who also could.

**Phase 11 — #7 school email** · Google Cloud project, Gmail API, OAuth client (Web, redirect
`http://localhost:8931/oauth/callback`), consent screen in Testing with a **dedicated demo Gmail** as
its one test user. Everything was built against the fake client first, so nothing waited on accounts.
- Read-only scope only · allowlist in every query (`allowlist.query` **cannot be built without one**)
  and checked again on arrival · one Nova Micro call per email, cached by `gmail_message_id` · store
  id, sender, date and tasks only, **body discarded and never logged** · Fernet tokens server-side ·
  disconnect revokes with Google and deletes all rows.
- **The sign-in lives on the MCP server, not the simulator** (`/oauth/start`, `/oauth/callback`), so a
  Gmail token never enters the process running the agent. A granted scope wider than
  `gmail.readonly`, or a grant with no refresh token, is refused rather than stored.
- `check_school_email` returns task **+** conflict **+** proposed fix in one result — tool-side
  chaining is what keeps a voice turn inside the 3-call ceiling.
- Two deliberate deviations: the extraction schema gained `action_needed` beside the five fixed fields,
  because forced tool use obliges the model to fill the form and without that bit a newsletter invents
  a task; and "does this task break the week?" is answered by checking the days from prep day to due
  date for conflicts **already there**, rather than inventing a prep event the family never agreed to.
- Required security tests pass: injection executes zero actions · non-allowlisted sender never read ·
  revoked token leaves no rows · no body in logs or DB.

**Phase 12 — #6 swap, and the Skills extension** · `request_swap` checks both legs feasible, then
raises **one** proposal carrying two `assign` changes with `needs_approval_from` set to the other
parent. **Zero model calls.** Reused rather than rebuilt: `_apply` already knew `assign`, approval
already enforced `needs_approval_from`, `assess` already recorded reasons.
- Feasibility is judged against the **swapped** week, not the current one.
- A day holding more than one of that person's lifts is a question, not a guess.
- Deliberately narrow: a swap only moves existing lifts between two parents. Inventing a lift or
  pulling in Grandpa is `fix_week`'s job.
- **The demo week had to be made to admit a feasible swap.** Every pairing was correctly refused,
  because each parent works until 16:30 on any day they do not collect. Mom now holds a **Tuesday
  17:00–18:00 cricket collection** at `cricket nets`, 30 minutes from Dad's office — Tuesday because
  it is the one weekday she does not collect from school, so it stays her only lift that day.
  `tests/test_seed_family.py` pins the property so seed drift cannot silently kill the swap shot.
- `_propose_swap` keys `pending_proposal` by **who is being asked**, so Mom's yes settles it and Dad's
  does not. Keying by speaker would have inverted the whole feature.
- **The two days are read from the sentence, not the model** (`days_named_in_order`): asked to resolve
  both, Nova Micro returned a Friday for "Tuesday".

**The Skills extension** · `skill/lifepilot/SKILL.md` and `lifepilot/extensions/skills.py`.
`skills/list` and `skills/get` **answer over real Streamable HTTP**, proven in
`tests/test_mcp_wire.py`. Wire shapes taken from SEP-2640 (Final), not guessed. `MethodBinding` is
legal because neither is a spec method, and a test proves the framework refuses one that is.
- **A test checks the digests against the bytes actually served** — a listing whose digests disagree
  fails a host's verification and the skill silently never loads.
- `resources` lists **every** file in the directory, because a host treats a read of an unlisted file
  as a verification failure.
- **No `allowed-tools`, enforced by a test.** A host must ignore that field for an MCP-origin skill
  unless explicitly approved; shipping it would request elevated access on someone else's machine.
- `directoryRead` advertised **false**, because `resources/directory/read` is unimplemented and
  claiming it would be a lie on the wire.
- *Limitation, not a defect:* `capabilities.extensions` does not reach the client over the **legacy**
  handshake this box is pinned to — SEP-2133 extension negotiation arrived later, and the modern
  handshake is unusable here because of Avast (friction log 7). The capability map is asserted
  directly; the **methods** are proven over the transport, which is the part that matters.

**`scan_risks` and exp 5** · `engine/risk.py` (pure), `tools/scan_risks.py` (DB, proposal).
- **It warns *and repairs*** — Varun's correction, and what makes it a headline feature rather than
  supporting cast. One result carries the task, the risk and a pending proposal for the slot.
- The slot books **what the task needs, not the whole gap**: claiming the lot would make the next
  thing look impossible.
- **Risk is "nothing is booked and the window is closing", not "cannot be done".** Defining it as
  impossibility made the repair unreachable — any task with a big enough gap was by definition not at
  risk, so a warning could never carry a slot. Circular, and caught by a test that could not be made
  to pass. Three kinds: `not_enough_time`, `needs_splitting`, `unbooked`.
- The due day itself does not count: something due 8 AM Friday cannot be done Friday evening.
- Days of warning are measured by **replaying the real scan as of each day**, so the number is the
  product's behaviour, not a second opinion about it.

**The coarse 9-tool set** · `TOOLSET=full|coarse` in `simulator/toolsets.py`. Nine merged schemas,
each translated back to the same fine-grained tool, so the server stays spec-pure and nothing
downstream of routing knows a toolset exists. A coarse tool is told apart by **the arguments the
model already filled**, not a mode word. `COVERS` plus a sync test fails loudly if a schema is added
to one set and forgotten in the other. Both arms run from one command, because every published number
must come out of `make eval`.
- **Root cause of the coarse set being worse:** merging tools moves the decision from "which tool" to
  "which arguments", and Nova Micro is worse at the second.
- One failure was a real bug: `get_context` must allow start and end to be **omitted** (the same
  schema answers "who is in the family"), and the missing field reached the speaker as a pydantic
  validation error.

**Two routing regressions, both closed (Oct 5)** · Each diagnosed before anything was changed, and
neither needed the coarse set.
- `"no, leave it"` → `get_schedule` was **not a routing bug**: it was the third refusal in a row, and
  with nothing pending the words fell through to the model, which sensibly picked `get_schedule`. The
  real defect was reciting the week at someone saying no. A bare yes or no with nothing pending now
  answers *"There is nothing waiting for a yes or no."* in code, at zero model cost.
- `"how much did we spend on football this month"` → `get_family` **was** genuine confusion. Fixed
  deterministically: `grep` over `lifepilot/db/models.py` for `cost|amount|price|spend|money|currency`
  returns **nothing** — LifePilot stores no amounts, so a money question is unanswerable by
  construction and declining is the only correct answer.
- Adding `request_swap` as the fourteenth schema pushed **"any problems this week"** off
  `detect_conflicts`; `_trouble_wins` sends a question about what is broken there whatever the model
  chose. Adding `scan_risks` as the fifteenth **moved nothing** — so the regression was about those
  two descriptions overlapping, not tool count. Worth saying plainly, because "more tools confuse a
  small model" is the easy conclusion and this is evidence against it.

**Figures** · `eval/figures.py`, called from `eval/run.py`, so one command writes CSVs and PNGs.
`--no-figures` opts out. matplotlib is a **dev** dependency, so a judge gets figures from a fresh
clone without a plotting library in the server's runtime. Five figures (exps 1, 3, 4, 5, 6); exp 2 is
four numbers and a time, which is a table — drawing it would be decoration.
- **Every figure reads a CSV and recomputes nothing**, so a chart cannot disagree with a published
  number.
- Colour chosen by method and **validated rather than eyeballed**: `#2a78d6` / `#eb6834` on `#fcfcfb`
  passes all five checks, worst adjacent CVD ΔE 24.7 against a target of 8. Blue is always the
  baseline, orange always LifePilot — colour follows the entity, never its rank.
- One axis per chart; every bar directly labelled, so identity and value never depend on colour alone.
- **Looked at every figure** rather than trusting the code, which is how a unit mismatch and three
  parsing bugs were caught (`_read` dropped the blank lines separating CSV blocks; `_section` matched
  a header on its first cell alone and exp 1 has two blocks starting `detector`; and
  `"without the rule".startswith("with")` is true, which put both arms of exp 6 in one bucket).

**The flaky experiment** · `tests/test_experiment3.py` failed about **one run in six** while passing
in isolation. Probed by repairing every scenario twelve times. Root cause: the blind arm of one
`latest_end` draw had **two equally cheap repairs** and only one broke the rule, so CP-SAT returned
either. Fixed in the scenario, not the solver — cricket is now immovable, like any coached session.
`test_every_scenario_actually_bites` now runs **every** draw; at `per_kind=1` it never saw the
ambiguous one, which is exactly how this got through.

---

## Cost guardrails

Measured, at $0.035 / $0.14 per 1M tokens:

| | |
|---|---|
| One voice turn (the 1,879-token tool-schema block dominates) | $0.000335 |
| Same turn, prompt-cached | $0.000152 |
| One school-email extraction | $0.000067 |
| One full `make eval` | $0.45 |
| Whole project with the cache working | **~$1.50** |

Per-call price is not the risk; repetition is. At 5 calls/second an unbounded retry burns the $20
Bedrock pool in **6.6 hours**. Hence the 3-call per-turn ceiling in `llm.py` (nothing in Strands
enforces one), `EVAL_MAX_CALLS` with the estimate printed first, the cache on in evals too, Nova Micro
only, and plain `converse` only — no Knowledge Bases, Agents, Guardrails or provisioned throughput,
which bill outside tokens. Cache hits are counted separately and spend no ceiling budget. AWS budget
alert ≤$10 before demo week.

## Open risks

| Risk | Handling |
|---|---|
| `SpeechRecognition` fails live | Typed input is a first-class path, not a bolted-on fallback. Chrome or Edge; Firefox lacks it by default. |
| Gmail Testing mode: refresh tokens expire weekly | **Re-link the demo account the morning of recording.** Silent until you ask for email — the single most likely thing to break on the day. |
| Seeded week drifts into the past | Reseed on video day and **check the dates**, not just the exit code. |
| More features built but unreachable | See *Lessons* 1 and 2. Audit every registered tool before submission. |

*Closed:* Nova Micro refusing forced `toolChoice` (proven in phase 2) · OR-Tools segfault (workers
capped at 8) · Nova too weak for 15 tools (measured: 100%, and the coarse set is worse) · Strands
reaching the MCP server on this box (`simulator/mcp_handshake.py` pins the handshake so the header is
never sent; `assert_patchable()` fails loudly if an upgrade moves the name) · MCP Apps host bridge
(shipped).

## Before submitting

- [x] Fresh clone → `.env` from `.env.example` → `make dev`, following the README only (req 4).
      Done Oct 20 from a `git checkout-index` tree; four defects, see §10. **Repeat once from the
      real GitHub URL**, which also exercises `git_sha` and the clone itself.
- [x] Negotiated protocol version 2025-11-25+ **on the wire**; SDK called at runtime. Asserted by
      `tests/test_mcp_wire.py`, which passes in the fresh clone.
- [ ] Demo script end to end in one sitting, after the browser-run fixes land.
- [x] `make eval` from clean; every README number traced to a CSV. Nothing typed by hand. Done
      Oct 20 in the fresh clone: six CSVs, five PNGs, 0 model calls.
- [ ] All Gmail security tests passing (**68 pass**, including injection-executes-nothing), and the
      **prompt-injection email run once against the real inbox** — still the one gap: the model's
      behaviour was probed live on Sep 30 and the Gmail hop ran on Oct 20, but never in the same
      run. Needs the injection and closure emails **sent into the demo inbox** first.
- [ ] Every registered tool either routable or noted as deliberately not.
- [ ] Labels visible; MIT in the GitHub About section; no Amazon marks in the UI or video.
