# What Alexa+ actually allows, and what LifePilot does about it

Two things LifePilot wants, the platform does not offer. Both are worked around honestly rather than
pretended away, and both shaped the design, so they are written down here instead of being
rediscovered later.

Checked against Amazon's own documentation in October 2026. If any of this changes, the rules win
over this file.

---

## 1. Who is speaking

**The question.** LifePilot shows a parent everything, a child their own schedule with parents' work
as "Busy", and a grandparent only what is assigned to them (differentiator #9). That needs to know
which household member is talking.

**What a classic Alexa skill gets.** If a customer has set up a Voice Profile and enabled
*Personalize skills*, Alexa recognises the voice and puts a `context.System.person` object in the
request, carrying a `personId`. The same `personId` comes back every time that person speaks, it
contains no personal information, and a skill can look up contact details through the Person Profile
REST API with the request's `apiAccessToken`.

**What an Alexa+ MCP add-on gets.** An OAuth 2.1 access token for the **linked Amazon account**. The
add-on documentation describes account linking as connecting "a customer's Amazon account to their
account in your service", and says every request carries that access token. It does not mention
`personId`, voice profiles, or how two household members sharing one device are told apart.

**So:** one account, not one person. LifePilot cannot assume the platform will say who is in the room.

**What LifePilot does.** A session assumes the linked account's parent and answers straight away.
Asking "who am I speaking to?" first was tried and removed: it taxed every single session with a
question whose answer the platform will not give us anyway, and it made the demo slower to watch.
Roles are still enforced on the server — `resolve_viewer` reads the role from the
database on every single call, and the speaker is injected server-side and never taken from the model
— so a wrong answer changes whose week is shown, never what the rules allow.

The speaker switcher in the simulator is a **demo control**, labelled as simulated. It is how a judge
sees four role views in ninety seconds; it is not a claim about how a real device identifies people.

**If Amazon exposes per-person identity to add-ons later**, the switcher is the only thing that
changes: everything behind it already keys off a resolved member.

---

## 2. Speaking without being asked

**The question.** A plan that is about to become impossible is worth saying before it does.

**What exists for classic skills.** The `ProactiveEvents` API. A skill sends an event built from one
of Amazon's predefined schemas, and Alexa delivers it through the **Alexa Notifications** channel: a
chime and a light ring, which the customer then asks about. Alexa's own Reminders API is the thing
that actually speaks at a time.

**What exists for MCP add-ons.** Nothing documented. The only push mentioned in the add-on docs is
during account linking, where a headless device cannot show a QR code and Alexa sends a notification
to the customer's phone. There is no documented way for an add-on's server to start a conversation.

**So:** a real add-on, today, answers questions. It does not interrupt.

**What LifePilot does.** Proactive speech is a property of **our simulator**, and every such message
carries a visible badge — "spoke first — simulated" or "reminder — simulated". Hard requirement 10
says anything simulated is labelled, and this is the main thing being labelled.

Two kinds, and the difference is the product:

| kind | example | what it is |
|---|---|---|
| **warning** | "Before this gets away from us: Dad is down for the football pickup but arrives at 5:25 and needs to be there at 5:00. Mom could go instead." | a plan about to break, with a way out |
| **nudge** | "Aarav's football practice starts in 10 minutes, at 4:25 PM." | something about to start |

The warning is the one in the demo. The nudge is what every reminder app already does, and CLAUDE.md
is explicit that reminders are supporting cast and never the headline.

**It costs nothing.** `simulator/reminders.py` imports no model, and a test parses the module to prove
it: every sentence comes from a template. The cost rules forbid pointing a loop or a scheduled job at
Bedrock, and a timer that phrased its output through Nova would bill for as long as the page is open.
The loop makes two MCP reads every 30 seconds and does the rest in pure Python.

---

## 3. Questions a reader usually asks next

**Do I need an Echo per person?** No. One Echo serves the household. Adults share one Alexa account
and one Alexa+ membership, each with their own profile in the Alexa app, and Voice Profiles let Alexa
recognise who is speaking. Up to six profile invitations can be sent at a time, and Amazon's Household
feature additionally links two adult accounts to the same speaker.

**I am at the office and the Echo is at home.** Use the Alexa app on your phone, signed in to the same
account. No second device, and nothing in LifePilot changes: the add-on sees the same linked account.

**Where does the data come from?** Seeded synthetic data for a synthetic family. Real calendar sync is
out of scope (CLAUDE.md), and new events are added by voice through `add_event`, which a parent
approves before anything is written.

## 4. How a parent links Gmail, on a real Alexa+

There are **two** links, and they are easy to confuse.

| | what it connects | whose flow |
|---|---|---|
| 1 | the parent's Amazon account to LifePilot | Amazon's, from the Alexa app |
| 2 | the parent's Google account to LifePilot | ours |

**Link 1 is account linking**, and it is the standard mechanism: Alexa+ MCP add-ons use OAuth 2.1,
authorization code grant only, with PKCE for user-level consent. The parent enables the add-on in
the Alexa app, is sent to our authorization page, signs in, and from then on **every request Alexa
sends carries their access token**. The implicit grant is not supported. Our Gmail flow already
matches that shape -- authorization code with PKCE, a refresh token, no implicit grant -- so link 2
is the same kind of object as link 1, not a different pattern bolted on.

**Link 2 is ours and it is the one the demo shows.** Alexa's linking page is a web page we serve, so
the Google consent step belongs in that page: the parent links LifePilot and connects the school's
email in one visit. Voice can start it later too -- "connect my email" and LifePilot sends a card to
the Alexa app -- but a consent screen cannot be spoken, so some screen has to exist exactly once.
That is why CLAUDE.md allows one non-voice step and only one. In the simulator that step is the
**Link Gmail** control; on a real Alexa+ it is the same page, reached from the Alexa app.

Everything after it is voice: which senders may be read, what the school has sent, and
"disconnect my email".

### It is linked once, not once per restart

The token is encrypted and stored in `email_link`. It survives restarts of both processes, and the
only things that end a link are the parent saying "disconnect my email", Google expiring the refresh
token (every 7 days while the OAuth app is in Testing mode -- see the README), or the database being
thrown away.

Being asked to link again after a restart means the server was using **in-memory SQLite**, which is
what `DATABASE_URL` unset gives you. That is right for tests and wrong for anything a person does,
so the server now says so in its log at startup rather than letting it look like the product
forgetting. `--reset` on the seeder also drops the link, because it drops every table; that is the
one deliberate way to lose it.

---

## Sources

- [Add Personalization to Your Alexa Skill](https://developer.amazon.com/en-US/docs/alexa/custom-skills/add-personalization-to-your-skill.html)
- [Person Profile REST API Reference](https://developer.amazon.com/docs/custom-skills/person-profile-api-reference.html)
- [Account Linking for MCP Add-ons](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-account-linking.html)
- [Authentication for MCP Add-ons](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-authentication.html)
- [Alexa+ launches new ways to build experiences](https://developer.amazon.com/alexaplus/blogs/2026/07/alexa-plus-new-ways-to-build-experiences)
- [Send Timely Information with the ProactiveEvents API](https://developer.amazon.com/en-US/blogs/alexa/alexa-skills-kit/2018/12/proactiveeventsapi-launch-announcement)
- [About Sharing Your Alexa Experience in the Alexa App](https://www.amazon.com/gp/help/customer/display.html?nodeId=T48dPgnGzAqBHmXVHB)
