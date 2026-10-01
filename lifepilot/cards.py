"""The proposal card: an MCP App bound to `fix_week`.

The spoken answer is the product; this is support. A client that never negotiated Apps gets the same
structured result and the same sentence, and loses nothing but the buttons -- which is what
`client_supports_apps` is for and why the card is additive rather than load-bearing.

The HTML is one self-contained document with no network access of its own. It talks to the host over
`postMessage` using the ext-apps message names, and the host is the only thing that can reach
`approve_proposal`. A card cannot change a family's plan on its own; it can only ask.
"""

PROPOSAL_URI = "ui://lifepilot/proposal.html"

PROPOSAL_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  :root {
    color-scheme: dark light;
    --ink: #161b23; --line: #2a323f; --text: #e8ecf2; --dim: #9aa6b6;
    --accent: #f0913f; --accent-soft: rgba(240,145,63,.14);
    --good: #5cc08a; --alarm: #e56a6a;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --ink: #fff; --line: #e2ddd5; --text: #1b1f26; --dim: #5b6572;
      --accent: #c96a17; --accent-soft: rgba(201,106,23,.1);
      --good: #2f8457; --alarm: #c0453f;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 14px; background: var(--ink); color: var(--text);
    font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  h1 { margin: 0 0 2px; font-size: .95rem; }
  .sub { margin: 0 0 12px; font-size: .78rem; color: var(--dim); }
  ol { list-style: none; margin: 0 0 14px; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  li { border: 1px solid var(--line); border-radius: 10px; padding: 9px 11px; }
  .what { font-weight: 600; }
  .from-to { font-size: .85rem; color: var(--dim); }
  .from-to b { color: var(--text); font-weight: 600; }
  .why { font-size: .8rem; color: var(--dim); margin-top: 3px; }
  .buttons { display: flex; gap: 8px; }
  button {
    flex: 1; padding: 10px 14px; border-radius: 9px; font: inherit; font-weight: 600;
    cursor: pointer; border: 1px solid var(--line); background: transparent; color: var(--text);
  }
  button.yes { border-color: var(--accent); background: var(--accent-soft); }
  button.yes:hover { background: var(--accent); color: #17120c; }
  button:disabled { opacity: .5; cursor: default; }
  .settled { margin: 0; font-size: .9rem; font-weight: 600; }
  .settled.approved { color: var(--good); }
  .settled.rejected { color: var(--dim); }
  .settled.failed { color: var(--alarm); }
</style>
</head>
<body>
<div id="card"><p class="sub">Waiting for the proposal…</p></div>

<script>
(() => {
  "use strict";
  let nextId = 1;
  const pending = new Map();
  let proposalId = null;

  function send(method, params) {
    const id = nextId++;
    window.parent.postMessage({ jsonrpc: "2.0", id, method, params }, "*");
    return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  }

  window.addEventListener("message", (event) => {
    const message = event.data;
    if (!message || message.jsonrpc !== "2.0") return;

    if (message.id !== undefined && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      message.error ? reject(new Error(message.error.message)) : resolve(message.result);
      return;
    }
    if (message.method === "ui/notifications/tool-result") {
      render(message.params && message.params.structuredContent);
    }
  });

  function card() {
    return document.getElementById("card");
  }

  function render(result) {
    const card = document.getElementById("card");
    card.textContent = "";
    if (!result || !result.changes || !result.changes.length) {
      card.innerHTML = '<p class="sub">Nothing needs changing.</p>';
      tellHostOurSize();
      return;
    }
    proposalId = result.proposal_id;

    const title = document.createElement("h1");
    title.textContent = result.change_count === 1 ? "One change" : result.change_count + " changes";
    const sub = document.createElement("p");
    sub.className = "sub";
    sub.textContent = "Nothing happens until you say yes.";
    card.append(title, sub);

    const list = document.createElement("ol");
    result.changes.forEach((change) => {
      const item = document.createElement("li");

      const what = document.createElement("div");
      what.className = "what";
      what.textContent = change.title;

      const move = document.createElement("div");
      move.className = "from-to";
      move.append(document.createTextNode(change.was + " \\u2192 "));
      const now = document.createElement("b");
      now.textContent = change.now;
      move.appendChild(now);

      const why = document.createElement("div");
      why.className = "why";
      why.textContent = change.reason;

      item.append(what, move, why);
      list.appendChild(item);
    });
    card.appendChild(list);

    const buttons = document.createElement("div");
    buttons.className = "buttons";
    buttons.append(button("Approve", "yes", "approve_proposal"), button("Not now", "", "reject_proposal"));
    card.appendChild(buttons);
    tellHostOurSize();
  }

  function tellHostOurSize() {
    // The host cannot measure inside a sandboxed frame, so the frame has to say how tall it is.
    // Without this the card is rendered at whatever the stylesheet guessed and the last change is
    // cut off, which on a two-change diff means hiding half of what is being approved.
    window.parent.postMessage(
      {
        jsonrpc: "2.0",
        method: "ui/notifications/size-changed",
        // Measure the content, not the document: documentElement stretches to whatever height
        // the host gave the frame, so asking it returns that back and the card never shrinks.
        params: { height: Math.ceil(card().getBoundingClientRect().height) + 28 },
      },
      "*"
    );
  }

  function button(label, cls, tool) {
    const element = document.createElement("button");
    element.className = cls;
    element.textContent = label;
    element.addEventListener("click", () => decide(tool, element));
    return element;
  }

  async function decide(tool, clicked) {
    document.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      // The card cannot change anything itself: the host owns the connection and makes the call.
      const result = await send("tools/call", {
        name: tool,
        arguments: { proposal_id: proposalId },
      });
      const content = (result && result.structuredContent) || {};
      // Short, because the host says the full sentence aloud and puts it in the conversation.
      // Repeating it here made the same words appear twice on screen.
      settle(
        content.approved ? "Approved" : "Left as it was",
        content.approved ? "approved" : "rejected"
      );
    } catch (error) {
      settle(error.message || "That did not work.", "failed");
      document.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
  }

  function settle(text, state) {
    const card = document.getElementById("card");
    card.textContent = "";
    const line = document.createElement("p");
    line.className = "settled " + state;
    line.textContent = text;
    card.appendChild(line);
    tellHostOurSize();
  }

  send("ui/initialize", { protocolVersion: "2025-11-25" }).catch(() => {});
})();
</script>
</body>
</html>
"""
