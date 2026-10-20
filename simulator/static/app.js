/* LifePilot simulator client.

   Deliberately thin: it captures text, renders what comes back, and speaks it. Every decision --
   who may see what, whether the week works, what to change -- happens on the server. */

(() => {
  "use strict";

  const thread = document.getElementById("thread");
  const empty = document.getElementById("empty");
  const mic = document.getElementById("mic");
  const micState = document.getElementById("micState");
  const typedForm = document.getElementById("typedForm");
  const typed = document.getElementById("typed");
  const speechNote = document.getElementById("speechNote");
  const conn = document.getElementById("conn");
  const drawerToggle = document.getElementById("drawerToggle");
  const drawerBody = document.getElementById("drawerBody");
  const drawerEmpty = document.getElementById("drawerEmpty");
  const trace = document.getElementById("trace");
  const meter = document.getElementById("meter");

  let speaker = "Dad";
  let socket = null;
  let modelCalls = 0;
  let cachedTokens = 0;
  let costUsd = 0;

  /* ---------- connection ---------- */

  function connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}/ws`);

    socket.addEventListener("open", () => setConn("open", "connected"));
    socket.addEventListener("close", () => {
      setConn("closed", "disconnected");
      setMic("idle");
      setTimeout(connect, 2000);
    });
    socket.addEventListener("error", () => setConn("closed", "error"));
    socket.addEventListener("message", (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      if (payload.type === "reply") receiveReply(payload);
      if (payload.type === "card_result") settleCardCall(payload);
    });
  }

  function setConn(state, label) {
    conn.dataset.state = state;
    conn.textContent = label;
  }

  /* ---------- sending ---------- */

  function send(text) {
    const said = text.trim();
    if (!said) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      addTurn("agent", "I am not connected to the server yet. One moment.");
      return;
    }
    addTurn("person", said);
    setMic("thinking");
    socket.send(JSON.stringify({ speaker, text: said }));
  }

  function receiveReply(payload) {
    // The server decides who is speaking: it asks at the start of every session, because a real
    // Alexa+ add-on is not told which household member is talking.
    if (payload.speaker) setSpeaker(payload.speaker);
    addTurn("agent", payload.speak, payload.cards || [], payload.proactive);
    recordTrace(payload.debug || {});
    speak(payload.speak);
  }

  /* ---------- conversation rendering ---------- */

  function addTurn(from, text, cards = [], proactive = null) {
    if (empty && empty.parentNode) empty.remove();

    const turn = document.createElement("div");
    turn.className = `turn from-${from}`;
    if (proactive) turn.classList.add("is-proactive");

    const who = document.createElement("span");
    who.className = "who";
    who.textContent = from === "person" ? speaker : "LifePilot";
    turn.appendChild(who);

    // Said without being asked. A real add-on cannot do this, so the label is not decoration.
    if (proactive) {
      const mark = document.createElement("span");
      mark.className = "sim-badge";
      mark.textContent = proactive === "warning"
        ? "spoke first — simulated"
        : "reminder — simulated";
      turn.appendChild(mark);
    }

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    turn.appendChild(bubble);

    cards.forEach((card) => {
      const node = renderCard(card);
      if (node) turn.appendChild(node);
    });

    thread.appendChild(turn);
    turn.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  const CARDS = {
    family: renderFamilyCard,
    schedule: renderScheduleCard,
    conflicts: renderConflictsCard,
    rule: renderRuleCard,
    rules: renderRulesCard,
    whatif: renderWhatIfCard,
    proposal: renderProposalCard,
  };

  function renderCard(card) {
    const build = CARDS[card.kind];
    return build ? build(card) : null;
  }

  function cardShell(kind, title) {
    const el = document.createElement("section");
    el.className = "card";

    const head = document.createElement("div");
    head.className = "card-head";

    const t = document.createElement("span");
    t.className = "card-title";
    t.textContent = title;

    const k = document.createElement("span");
    k.className = "card-kind";
    k.textContent = kind;

    head.append(t, k);

    const body = document.createElement("div");
    body.className = "card-body";

    el.append(head, body);
    return { el, body };
  }

  function renderFamilyCard(card) {
    const { el, body } = cardShell("family", card.title);
    card.members.forEach((member) => {
      const row = document.createElement("div");
      row.className = "row";

      const when = document.createElement("span");
      when.className = "row-when";
      when.textContent = member.role;

      const what = document.createElement("span");
      what.className = "row-what";
      what.textContent = member.name + (member.is_you ? " (you)" : "");
      if (member.can_drive) what.appendChild(pill("drives", "is-transport"));

      row.append(when, what);
      body.appendChild(row);
    });
    return el;
  }

  function renderScheduleCard(card) {
    const { el, body } = cardShell("schedule", card.title);

    const tasks = card.tasks || [];

    if (!card.events.length && !tasks.length) {
      const row = document.createElement("div");
      row.className = "row";
      row.textContent = "Nothing visible to you this week.";
      body.appendChild(row);
      return el;
    }

    // Deadlines first, and without a time: a costume is due on Friday, not at midnight on Friday.
    // They were sent in the payload and never drawn, so a task approved from a school email was
    // in the database, spoken about, and absent from the card beside the answer.
    tasks.forEach((task) => {
      const row = document.createElement("div");
      row.className = "row is-due";

      const when = document.createElement("span");
      when.className = "row-when";
      when.textContent = shortDay(task.due);

      const what = document.createElement("span");
      what.className = "row-what";
      what.textContent = task.title;
      what.appendChild(pill("due", "is-due"));
      if (task.owner) what.appendChild(pill(task.owner, "is-owner"));

      row.append(when, what);
      body.appendChild(row);
    });

    card.events.forEach((event) => {
      const row = document.createElement("div");
      row.className = "row" + (event.redacted ? " is-hidden" : "");

      const when = document.createElement("span");
      when.className = "row-when";
      when.textContent = shortSpan(event.start, event.end);

      const what = document.createElement("span");
      what.className = "row-what";
      what.textContent = event.title;
      if (event.needs_transport) what.appendChild(pill("needs a lift", "is-transport"));
      if (event.movable === false) what.appendChild(pill("fixed", "is-fixed"));

      row.append(when, what);

      if (event.location) {
        const where = document.createElement("span");
        where.className = "row-where";
        where.textContent = event.location;
        row.appendChild(where);
      }

      body.appendChild(row);
    });

    return el;
  }

  const KIND_LABEL = {
    no_eligible_adult: "no one allowed",
    overlap: "two places at once",
    rule_clash: "breaks a rule",
  };

  function kindLabel(conflict) {
    // "unreachable" covers two different situations, and calling both "no one can get there" is
    // wrong when somebody else could: the card would contradict its own next line.
    if (conflict.kind === "unreachable") {
      return conflict.could_cover && conflict.could_cover.length
        ? "whoever is down for it can't make it"
        : "no one can get there";
    }
    return KIND_LABEL[conflict.kind] || conflict.kind;
  }

  function renderConflictsCard(card) {
    const { el, body } = cardShell("problems", card.title);

    if (!card.conflicts.length) {
      const row = document.createElement("div");
      row.className = "row";
      row.textContent = `Nothing broken. Checked ${card.checked.events} events, ` +
        `${card.checked.lifts_needed} lifts and ${card.checked.rules} rules.`;
      body.appendChild(row);
      return el;
    }

    card.conflicts.forEach((conflict) => {
      const row = document.createElement("div");
      row.className = "row is-problem";

      const when = document.createElement("span");
      when.className = "row-when";
      when.textContent = shortWhen(conflict.when);

      const what = document.createElement("span");
      what.className = "row-what";

      const headline = document.createElement("span");
      headline.className = "problem-detail";
      headline.textContent = conflict.detail;
      what.appendChild(headline);
      what.appendChild(pill(kindLabel(conflict), "is-alarm"));

      if (conflict.could_cover && conflict.could_cover.length) {
        const fix = document.createElement("span");
        fix.className = "problem-fix";
        fix.textContent = `${conflict.could_cover.join(" or ")} could cover it`;
        what.appendChild(fix);
      }

      // Every candidate, with the recorded reason. This is what answers "why not Grandpa?".
      if (conflict.candidates && conflict.candidates.length) {
        const why = document.createElement("details");
        why.className = "why";
        const summary = document.createElement("summary");
        summary.textContent = "why not the others?";
        why.appendChild(summary);
        const list = document.createElement("ul");
        conflict.candidates
          .filter((c) => !c.reachable)
          .forEach((c) => {
            const li = document.createElement("li");
            li.textContent = `${c.name}: ${sayReason(c.reason)}`;
            list.appendChild(li);
          });
        why.appendChild(list);
        what.appendChild(why);
      }

      row.append(when, what);
      body.appendChild(row);
    });

    const foot = document.createElement("div");
    foot.className = "row card-foot";
    foot.textContent = `Checked ${card.checked.events} events, ` +
      `${card.checked.lifts_needed} lifts and ${card.checked.rules} family rules.`;
    body.appendChild(foot);

    return el;
  }

  /* ---------- MCP App host ----------

     The proposal card is a real MCP App: a document served by the MCP server, rendered in a
     sandboxed iframe, talking to this page over postMessage. It has no connection of its own, so
     "Approve" is a request to the host, which the server then decides on. That is the whole point:
     the card can ask, and only the server can act. */

  const cardFrames = new Map();
  let nextCardRequest = 1;
  const cardWaiting = new Map();

  function renderProposalCard(card) {
    const frame = document.createElement("iframe");
    frame.className = "app-frame";
    frame.title = "Proposed changes";
    frame.setAttribute("sandbox", "allow-scripts");
    frame.src = "/card/proposal";

    frame.addEventListener("load", () => {
      cardFrames.set(frame.contentWindow, frame);
      post(frame, {
        jsonrpc: "2.0",
        method: "ui/notifications/tool-result",
        params: { structuredContent: card.proposal },
      });
    });
    return frame;
  }

  function post(frame, message) {
    if (frame.contentWindow) frame.contentWindow.postMessage(message, "*");
  }

  window.addEventListener("message", (event) => {
    const frame = cardFrames.get(event.source);
    if (!frame) return; // not one of ours
    const message = event.data;
    if (!message || message.jsonrpc !== "2.0" || !message.method) return;

    if (message.method === "ui/initialize") {
      post(frame, { jsonrpc: "2.0", id: message.id, result: { protocolVersion: "2025-11-25" } });
      return;
    }
    if (message.method === "ui/notifications/size-changed") {
      const height = (message.params && message.params.height) || 0;
      if (height) frame.style.height = `${height + 8}px`;
      return;
    }
    if (message.method === "tools/call") {
      const requestId = nextCardRequest++;
      cardWaiting.set(requestId, { frame, id: message.id });
      socket.send(JSON.stringify({
        type: "card_call",
        speaker,
        request_id: requestId,
        tool: message.params && message.params.name,
        arguments: (message.params && message.params.arguments) || {},
      }));
    }
  });

  function settleCardCall(payload) {
    const waiting = cardWaiting.get(payload.request_id);
    if (!waiting) return;
    cardWaiting.delete(payload.request_id);

    post(waiting.frame, payload.error
      ? { jsonrpc: "2.0", id: waiting.id, error: { code: -32000, message: payload.error } }
      : { jsonrpc: "2.0", id: waiting.id, result: { structuredContent: payload.result } });

    if (payload.debug) recordTrace(payload.debug);
    if (payload.result && payload.result.say) {
      addTurn("agent", payload.result.say);
      speak(payload.result.say);
    }
  }

  // The stored reason is machine-readable -- the server classifies a rule clash by its "rule:"
  // prefix -- so it is reworded for the screen the same way the spoken answer rewords it.
  function sayReason(reason) {
    const text = String(reason || "");
    return text.startsWith("rule:")
      ? `your rule says ${text.slice("rule:".length).trim()}`
      : text;
  }

  function renderWhatIfCard(card) {
    const safe = card.ripple.safe;
    const { el, body } = cardShell(safe ? "that works" : "that breaks things", card.title);

    const rows = [
      ["would break", card.ripple.breaks, "is-problem"],
      ["gets worse", card.ripple.worsens, "is-problem"],
      ["would clear", card.ripple.resolves, "is-resolved"],
      ["already broken", card.ripple.unchanged, "is-muted"],
    ];

    rows.forEach(([label, items, cls]) => {
      (items || []).forEach((conflict) => {
        const row = document.createElement("div");
        row.className = `row ${cls}`;

        const when = document.createElement("span");
        when.className = "row-when";
        when.textContent = label;

        const what = document.createElement("span");
        what.className = "row-what";
        what.textContent = conflict.detail;

        row.append(when, what);
        body.appendChild(row);
      });
    });

    if (card.fix && card.fix.changes && card.fix.changes.length) {
      const fix = document.createElement("div");
      fix.className = "row is-fix";
      const label = document.createElement("span");
      label.className = "row-when";
      label.textContent = "you could";
      const what = document.createElement("span");
      what.className = "row-what";
      what.textContent = card.fix.changes
        .map((c) => (c.kind === "assign" ? `${c.now} takes ${c.title}` : `${c.title} moves to ${c.now}`))
        .join(", and ");
      fix.append(label, what);
      body.appendChild(fix);
    }

    if (!body.children.length) {
      const row = document.createElement("div");
      row.className = "row";
      row.textContent = "Nothing changes either way.";
      body.appendChild(row);
    }
    return el;
  }

  function renderRuleCard(card) {
    const { el, body } = cardShell(card.pending ? "awaiting your yes" : "rule", card.title);

    const heard = document.createElement("div");
    heard.className = "row";
    const heardWhat = document.createElement("span");
    heardWhat.className = "row-what";
    heardWhat.textContent = `You said: "${card.spoken_text}"`;
    heard.appendChild(heardWhat);
    body.appendChild(heard);

    if (card.readback) {
      const read = document.createElement("div");
      read.className = "row is-readback";
      const readWhat = document.createElement("span");
      readWhat.className = "row-what";
      readWhat.textContent = card.readback;
      read.appendChild(readWhat);
      body.appendChild(read);
    }
    return el;
  }

  function renderRulesCard(card) {
    const { el, body } = cardShell("rules", card.title);
    card.rules.forEach((rule) => {
      const row = document.createElement("div");
      row.className = "row";

      const kind = document.createElement("span");
      kind.className = "row-when";
      kind.textContent = rule.hard ? "always" : "prefer";

      const what = document.createElement("span");
      what.className = "row-what";
      what.textContent = rule.readback;

      const said = document.createElement("span");
      said.className = "row-where";
      said.textContent = `"${rule.spoken_text}"`;

      row.append(kind, what, said);
      body.appendChild(row);
    });
    return el;
  }

  function pill(text, extra) {
    const p = document.createElement("span");
    p.className = `pill ${extra || ""}`.trim();
    p.textContent = text;
    return p;
  }

  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  function clock(timePart) {
    // 4 PM, not 16:00. The card is read at a glance beside an answer that is spoken the same way.
    const [h, min] = String(timePart || "").split(":").map(Number);
    if (Number.isNaN(h)) return "";
    const hour = h % 12 || 12;
    const suffix = h < 12 ? "am" : "pm";
    return min ? `${hour}:${String(min).padStart(2, "0")} ${suffix}` : `${hour} ${suffix}`;
  }

  function shortWhen(iso) {
    // Server sends naive local time on purpose; parsing the parts avoids a timezone shift.
    const [datePart, timePart] = String(iso).split("T");
    const [y, m, d] = datePart.split("-").map(Number);
    const day = DAYS[new Date(y, m - 1, d).getDay()];
    return `${day} ${clock(timePart)}`.trim();
  }

  function shortDay(iso) {
    // A deadline is a day. Reusing shortWhen put "Fri 12 am" on a task stored at midnight.
    const [y, m, d] = String(iso).split("T")[0].split("-").map(Number);
    return DAYS[new Date(y, m - 1, d).getDay()];
  }

  function shortSpan(startIso, endIso) {
    // Showing only the start does not answer when anyone needs collecting, which is the usual
    // reason for looking.
    const start = shortWhen(startIso);
    if (!endIso) return start;
    const [startDate] = String(startIso).split("T");
    const [endDate, endTime] = String(endIso).split("T");
    return endDate === startDate ? `${start}-${clock(endTime)}` : `${start} - ${shortWhen(endIso)}`;
  }

  /* ---------- debug drawer ---------- */

  function recordTrace(debug) {
    modelCalls += debug.model_calls || 0;
    cachedTokens += debug.cached_tokens || 0;
    costUsd += debug.estimated_cost_usd || 0;
    const cached = cachedTokens ? ` · ${cachedTokens} cached` : "";
    meter.textContent = `${modelCalls} model calls${cached} · $${costUsd.toFixed(6)}`;

    if (drawerEmpty && drawerEmpty.parentNode) drawerEmpty.remove();

    const li = document.createElement("li");
    const tool = debug.tool || "(no tool)";
    const failed = debug.status && debug.status !== "success";

    const name = document.createElement("span");
    name.className = failed ? "t-fail" : "t-tool";
    name.textContent = tool;

    const rest = document.createElement("span");
    const bits = [];
    if (debug.arguments) bits.push(JSON.stringify(debug.arguments));
    if (debug.tool_ms !== undefined) bits.push(`${debug.tool_ms} ms`);
    if (debug.status) bits.push(debug.status);
    if (debug.note) bits.push(debug.note);
    rest.textContent = bits.length ? ` ${bits.join("  ·  ")}` : "";

    li.append(name, rest);
    trace.appendChild(li);
  }

  drawerToggle.addEventListener("click", () => {
    const open = drawerToggle.getAttribute("aria-expanded") === "true";
    drawerToggle.setAttribute("aria-expanded", String(!open));
    drawerBody.hidden = open;
  });

  /* ---------- speaker switcher ---------- */

  // Shared, because the server also decides who is speaking: it asks at the start of the session,
  // and the answer has to move the switcher or the two disagree about who is in the room.
  function setSpeaker(name) {
    if (!name || name === speaker) return;
    speaker = name;
    document.querySelectorAll(".speaker").forEach((button) => {
      const mine = button.dataset.speaker === name;
      button.classList.toggle("is-active", mine);
      button.setAttribute("aria-checked", String(mine));
    });
    pointLinkAtSpeaker();
  }

  // The sign-in is per parent, so the one non-voice step has to follow the switcher.
  const linkGmail = document.getElementById("linkGmail");
  function pointLinkAtSpeaker() {
    linkGmail.href = "/link-gmail?speaker=" + encodeURIComponent(speaker);
  }
  pointLinkAtSpeaker();

  // The switcher stands in for a second device, so switching has to look like one. Leaving Dad and
  // Mom's swap negotiation on screen in Aarav's session contradicts the role view the server is
  // enforcing underneath -- the #9 shot was undercut by its own transcript. The debug drawer is
  // kept: it is the engineer's view of the whole run, not anybody's session.
  function clearThread() {
    thread.textContent = "";
  }

  document.querySelectorAll(".speaker").forEach((button) => {
    button.addEventListener("click", () => {
      const was = speaker;
      setSpeaker(button.dataset.speaker);
      if (speaker === was) return;
      clearThread();
      addTurn("agent", `Now speaking as ${speaker}. You will see what ${speaker} is allowed to see.`);
    });
  });

  /* ---------- typed input: always available ---------- */

  typedForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = typed.value;
    typed.value = "";
    send(text);
  });

  /* ---------- speech ---------- */

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;

  function setMic(state) {
    mic.dataset.state = state;
    micState.textContent = {
      idle: "Tap to speak",
      listening: "Listening",
      thinking: "Thinking",
      speaking: "Speaking",
    }[state];
  }

  if (!Recognition) {
    mic.disabled = true;
    setMic("idle");
    micState.textContent = "Typing only";
    speechNote.hidden = false;
    speechNote.textContent =
      "Speech input needs Chrome or Edge with a network connection. Typing works everywhere.";
  } else {
    recognition = new Recognition();
    recognition.lang = "en-IN";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.addEventListener("result", (event) => {
      send(event.results[0][0].transcript);
    });
    recognition.addEventListener("end", () => {
      if (mic.dataset.state === "listening") setMic("idle");
    });
    recognition.addEventListener("error", (event) => {
      setMic("idle");
      speechNote.hidden = false;
      speechNote.textContent =
        event.error === "not-allowed"
          ? "Microphone permission denied. Typing still works."
          : `Speech input failed (${event.error}). Typing still works.`;
    });

    mic.addEventListener("click", () => {
      if (mic.dataset.state === "listening") {
        recognition.stop();
        setMic("idle");
        return;
      }
      window.speechSynthesis.cancel();
      try {
        recognition.start();
        setMic("listening");
      } catch {
        setMic("idle");
      }
    });
  }

  function speak(text) {
    if (!("speechSynthesis" in window) || !text) {
      setMic("idle");
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-IN";
    utterance.addEventListener("start", () => setMic("speaking"));
    utterance.addEventListener("end", () => setMic("idle"));
    utterance.addEventListener("error", () => setMic("idle"));
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }

  connect();
})();
