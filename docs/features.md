# What LifePilot can do

Plain-English list of everything LifePilot does today. Written for someone who has never seen the
code.

**The one-line idea:** other assistants *show* your family's calendar. LifePilot *fixes* it.

**How you use it:** you talk, it talks back. There is no app to fill in, no form, no upload screen.
The only thing you ever click is a one-time "Link Gmail" button, the same way you link Spotify to a
speaker.

**The golden rule:** LifePilot never changes your plan by itself. It works out what to do, tells
you, and waits for a parent to say "yes".

---

## 1. It tells you what will actually go wrong

Most calendars only notice when two things are at the same time. LifePilot asks a harder question:
**can a real person actually get there?**

> "Any problems this week?"

> *"Thursday at 5 PM, football practice pickup: Dad is down for it but arrives 5:25 PM, needs 5 PM.
> Mom could cover it instead."*

Nothing on Dad's calendar overlaps. His meeting ends at 4:45 and football starts at 5. A calendar
sees no problem. LifePilot knows the office is 40 minutes from the football ground, so Dad cannot
be there — and it says who can.

It checks four kinds of trouble:

- two things at the same time
- **nobody can physically get there in time** (this is the one nobody else does)
- no grown-up is allowed or available to go
- the plan breaks one of your family rules

---

## 2. It says who should go, and why

> "Who should pick up Aarav?"

> *"Mom is only 10 minutes away."*

It ranks every grown-up who could do it by who is free, how far away they are, how many pickups
they have already done this week, and what your family rules allow. The answer always comes with
the reason.

---

## 3. It answers "why not them?"

> "Why not Grandpa?"

> *"Not Grandpa, because your rule says only when no parent is free. Mom can."*

Every answer points at a specific rule, a specific event, or a specific travel time. It never gives
a vague "that might not work".

---

## 4. It repairs the week with the fewest changes

> "Fix our week."

> *"2 changes: Mom takes Thursday pickup, Aarav's project block moves to Wednesday 6 PM."*

It changes **only what is broken**. It does not rebuild your week. Things you said cannot move,
never move. You see the short list of changes — each with its reason — and approve that list, not a
whole new schedule.

---

## 5. It answers "what if…" without changing anything

> "What if my 4 PM runs until 5:30?"

> *"Nothing new breaks, but football practice pickup gets worse. Dad is down for it but is at
> performance review until 5:30 PM."*

This is a safe sandbox. Nothing is saved, nothing moves. You can also ask it forwards:

> "Can I say yes to a 6 PM meeting on Friday?"

It will tell you what saying yes would cost you before you say it.

---

## 6. Two parents, two devices, one plan

> Dad: "Ask Mom if she can take Thursday, I'll take Tuesday."

> *"I have asked Mom to take football practice pickup Thursday at 5 PM, with you taking cricket
> practice pickup Tuesday at 6 PM. It works for both of you. Mom has to agree before anything
> changes."*

LifePilot first checks that **both** halves of the swap are actually possible. Then it waits for
Mom.

If Dad tries to approve his own request, he is told: *"That one is Mom's to answer."* Mom, on her
own device, can ask *"Anything waiting for me?"*, hear exactly what she is being asked, and say
yes. Only then does anything change.

---

## 7. It reads the school's emails and turns them into a plan

> "Any news from school?"

> *"One new email from school: Aarav needs a costume by Friday. That clashes with Thursday. Should
> Mom go Wednesday?"*

It does not just read the email out. It pulls out the task and the date, checks whether it breaks
your week, and offers the fix — all in one answer.

**What it is allowed to read:** only emails from senders you name out loud ("only read emails from
Aarav's school"). It can only ever *read* — it can never send, reply to, or delete anything. It
throws the email text away after pulling out the task, so no email is ever stored. Instructions
hidden inside an email cannot make LifePilot do anything; it can only fill in a task form.

You can disconnect at any time, by voice, and everything it stored is deleted.

---

## 8. You can add things to the calendar

> "Book a dentist appointment at 10 on Friday."

It checks the new event against travel times and your family rules first, tells you what it would
break, and asks before saving. If that slot is already taken by something of yours, it offers to
**replace** it rather than quietly stacking two things on top of each other — and if the thing it
would replace is a fixed commitment, it says so, so nobody drops a performance review by accident.

---

## 9. You can cancel things too — and it tells you what that frees up

> "Cancel my performance review on Thursday."

> *"Cancelling performance review, Thursday at 3:45 PM to 4:45 PM. It also fixes football practice
> pickup. Shall I cancel it?"*

Cancelling is not just deleting. LifePilot tells you:

- **what it fixes** — the meeting was the reason Thursday's pickup was impossible, so cancelling it
  repairs the week
- **who else loses it** — cancelling the family lunch clears the afternoon for four other people,
  and they are named before you say yes
- **which lifts nobody needs any more**
- **what it would strand**, in the rare case cancelling breaks something

It also handles the awkward parts properly:

- If more than one thing matches ("cancel my meeting" when you have three), it **asks which one**
  instead of guessing. You answer with the day.
- If a family rule pins that event, it **refuses** until you say "cancel it anyway".
- If the event already happened, it says so.

And you can do both halves in one sentence:

> "Cancel our lunch at Grandpa's and book lunch with Mom instead."

Both changes are approved together, or neither happens.

---

## 10. Family rules, said once, obeyed every time

Say a rule out loud. LifePilot reads it back to make sure it understood, and from then on every
plan it makes respects it.

| What you say | What it means |
|---|---|
| "Anaya's piano class cannot be moved." | that event never moves |
| "No homework after 9 PM." | study has to finish by 9 PM |
| "Aarav needs 30 minutes rest after school." | leave a gap after school |
| "Grandparents only when both parents are busy." | who is allowed to cover |
| "Try to keep pickups even between us." | prefer a fair split |

The rules are stored as real settings, not as a note in a prompt, so LifePilot cannot "forget" one
to make a plan fit. If a plan is impossible, it tells you which rule is in the way instead of
quietly dropping it.

You can ask "what are our rules?" at any time, and remove one by voice.

---

## 11. Everyone sees only what they should

The same question gives a different answer depending on who is asking.

| Who is asking | What they see |
|---|---|
| **Parent** | everything, and only they can approve changes |
| **Child** | their own day; a parent's work shows as just "Busy", never the title or place |
| **Grandparent / caregiver** | only the pickups and events assigned to them |

This is enforced inside LifePilot, not by politely asking the AI to keep a secret.

---

## 12. "What am I forgetting?"

> "What am I forgetting?"

It looks for things quietly heading for trouble — a task due soon with no time set aside for it —
and does more than warn you. It finds a free slot and offers to book it, so you can just say yes.

---

## 13. Everyday questions

The ordinary things you would expect, which support everything above:

- "What have I got today?" / "What's on tomorrow?"
- "What is Anaya doing on Thursday?"
- "When does Mom finish work on Friday?"
- "Who is in the family?"

It answers in the order the day actually happens to **you**. If you are only driving a child to
school, it tells you the time at the gate, not that you are at school all day.

---

## 14. It can speak up before something breaks

If a lift is about to become impossible, LifePilot says so without being asked, and names who could
go instead — *"Dad cannot reach the football ground by 5. Mom could."* That is different from a
reminder app saying "football in 15 minutes", which it also does, but quietly.

This one is **labelled "spoke first — simulated"** on screen, because a real voice assistant add-on
has no supported way to start a conversation by itself. In a real product this would be a
notification.

---

## 15. Cards you can see while it talks

When something has a decision in it, a small card appears beside the spoken answer: the list of
changes, each with its reason, and Approve / Not now buttons. The card always **supports** the
spoken answer — it never replaces it. You can do everything by voice alone.

There is also an "Under the hood" drawer that shows which tool ran, how long it took, and what it
has cost so far. That is for judges and engineers, not for parents.

---

## What LifePilot deliberately does **not** do

Saying no to these is a design decision, not a missing piece:

- **It is not a to-do or shopping list.** "Order milk" gets a polite "I can't do that one."
- **It is not a chore scoreboard.** It knows who has done more pickups, and uses it to balance
  fairly — but it will never make that the headline.
- **It never gives medical advice.** An appointment is a time and a place, nothing more.
- **It never acts on its own.** No background scanning of your email, no silent changes.
- **It has no dashboard and no upload screen.** If it only *shows* information, it is not the
  point.

---

## Honest notes

Things a reader should know, so nothing here is oversold:

- **The family is made up.** The demo uses a synthetic family. No real child's data is anywhere in
  this project.
- **The school emails are ours.** They are written by us and sent to a demo inbox we own. LifePilot
  never reads a real school's email or a real person's inbox.
- **Partner notifications are simulated.** LifePilot cannot tap Mom on the shoulder — there is no
  supported way for it to start a conversation on her device. She finds out when she asks, or in
  her morning summary. Anything simulated is labelled as simulated on screen.
- **Travel times come from a fixed table**, not a live maps service.
- **Google's rules apply to the email feature.** The sign-in is read-only, and while the app is in
  testing it has to be reconnected about once a week.
- **The email feature has not yet been run against a real inbox.** Everything about it is built and
  tested — the sender allowlist, pulling the task out, the injection defence, deleting everything on
  disconnect — but so far against a stand-in for Gmail rather than Gmail itself. Connecting the real
  demo inbox is still to do.
