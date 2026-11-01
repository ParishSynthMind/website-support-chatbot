/*
 * Support chat widget. Vanilla JS, no dependencies, one script tag:
 *
 *   <script src="https://your-chat-host/widget.js" data-api="https://your-chat-host"
 *           data-company="Orbitly" data-color="#5b4cf0" defer></script>
 *
 * Optional attributes:
 *   data-open="true"              open the panel on load
 *   data-mode="recorded"          replay a recorded conversation instead of calling the API
 *   data-transcript="file.json"   the recording to replay (recorded mode only)
 *
 * Everything renders inside a shadow root, so the host page's CSS can't break
 * it and it can't break the host page. All text is inserted with textContent.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script || window.__supportChatLoaded) return;
  window.__supportChatLoaded = true;

  var cfg = {
    api: (script.getAttribute("data-api") || "").replace(/\/$/, ""),
    company: script.getAttribute("data-company") || "Support",
    color: script.getAttribute("data-color") || "#5b4cf0",
    open: script.getAttribute("data-open") === "true",
    mode: script.getAttribute("data-mode") || "live",
    transcript: script.getAttribute("data-transcript") || "transcript.json",
    maxChars: parseInt(script.getAttribute("data-max-chars") || "500", 10)
  };
  var recorded = cfg.mode === "recorded";

  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}",
    ".launcher{position:fixed;right:20px;bottom:20px;width:60px;height:60px;border-radius:50%;border:0;cursor:pointer;",
    "background:var(--c);color:#fff;box-shadow:0 8px 24px rgba(0,0,0,.22);display:flex;align-items:center;justify-content:center;z-index:2147483000}",
    ".launcher svg{width:28px;height:28px}",
    ".panel{position:fixed;right:20px;bottom:92px;width:370px;height:min(600px,calc(100vh - 120px));background:#fff;border-radius:16px;",
    "box-shadow:0 16px 48px rgba(0,0,0,.22);display:none;flex-direction:column;overflow:hidden;z-index:2147483000;color:#1d1d1f}",
    ".panel.open{display:flex}",
    ".head{background:var(--c);color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px}",
    ".head .t{flex:1;min-width:0}.head b{display:block;font-size:15px}.head small{opacity:.85;font-size:12px}",
    ".head button{background:rgba(255,255,255,.18);color:#fff;border:0;border-radius:8px;padding:6px 9px;font-size:12px;cursor:pointer}",
    ".head .x{font-size:18px;line-height:1;padding:4px 9px}",
    ".banner{background:#fff6db;color:#5c4400;font-size:12px;padding:7px 12px;border-bottom:1px solid #f0e2b0}",
    ".msgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:#f6f6f9}",
    ".m{max-width:85%;padding:9px 12px;border-radius:14px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}",
    ".m.v{align-self:flex-end;background:var(--c);color:#fff;border-bottom-right-radius:4px}",
    ".m.a{align-self:flex-start;background:#fff;border:1px solid #e4e4ea;border-bottom-left-radius:4px}",
    ".m.sys{align-self:center;background:transparent;color:#6b6b76;font-size:12px;text-align:center}",
    ".cites{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}",
    ".cite{font-size:11px;background:#f0effc;color:#3d3399;border-radius:6px;padding:2px 7px}",
    ".hbtn{margin-top:8px;background:var(--c);color:#fff;border:0;border-radius:8px;padding:7px 11px;font-size:13px;cursor:pointer}",
    ".typing{align-self:flex-start;color:#888;font-size:13px;padding:4px 6px}",
    ".chips{display:flex;flex-wrap:wrap;gap:6px;padding:0 14px 10px;background:#f6f6f9}",
    ".chip{border:1px solid var(--c);color:var(--c);background:#fff;border-radius:16px;padding:5px 10px;font-size:12px;cursor:pointer}",
    "form.send{display:flex;gap:8px;padding:10px;border-top:1px solid #e4e4ea;background:#fff}",
    "form.send input{flex:1;border:1px solid #d6d6de;border-radius:10px;padding:10px 12px;font-size:16px;min-width:0}",
    "form.send button{background:var(--c);color:#fff;border:0;border-radius:10px;padding:0 14px;font-size:14px;cursor:pointer}",
    "button:disabled,input:disabled{opacity:.55;cursor:default}",
    ".ho{background:#fff;border:1px solid #e4e4ea;border-radius:12px;padding:12px;display:flex;flex-direction:column;gap:8px;align-self:stretch}",
    ".ho b{font-size:14px}.ho label{font-size:12px;color:#555;display:flex;flex-direction:column;gap:3px}",
    ".ho input,.ho textarea{border:1px solid #d6d6de;border-radius:8px;padding:8px 10px;font-size:16px;font-family:inherit;resize:vertical}",
    ".ho .err{color:#b00020;font-size:12px;min-height:14px}",
    ".ho .row{display:flex;gap:8px}.ho .row button{flex:1;border:0;border-radius:8px;padding:9px;font-size:14px;cursor:pointer}",
    ".ho .go{background:var(--c);color:#fff}.ho .cancel{background:#ececf1;color:#333}",
    "@media (max-width:480px){.panel{right:0;bottom:0;width:100vw;height:100%;border-radius:0}",
    ".panel.open~.launcher{display:none}}"
  ].join("");

  var host = document.createElement("div");
  host.id = "support-chat-widget";
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    "<style>" + CSS + "</style>" +
    '<div class="panel" role="dialog" aria-label="Chat with ' + "support" + '">' +
    '  <div class="head"><div class="t"><b></b><small>Answers from our help docs</small></div>' +
    '    <button class="person" type="button">Talk to a person</button>' +
    '    <button class="x" type="button" aria-label="Close chat">&times;</button></div>' +
    '  <div class="msgs" aria-live="polite"></div>' +
    '  <div class="chips"></div>' +
    '  <form class="send"><input type="text" aria-label="Your message" autocomplete="off">' +
    '    <button type="submit">Send</button></form>' +
    "</div>" +
    '<button class="launcher" type="button" aria-label="Open chat">' +
    '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2z"/></svg></button>';

  host.style.setProperty("--c", cfg.color);
  var $ = function (sel) { return root.querySelector(sel); };
  var panel = $(".panel"), msgs = $(".msgs"), chips = $(".chips"), form = $("form.send");
  var input = form.querySelector("input"), sendBtn = form.querySelector("button");
  $(".head b").textContent = cfg.company + " support";
  input.maxLength = cfg.maxChars;
  input.placeholder = "Ask a question...";

  var history = [];      // [{role:"visitor"|"assistant", text}]
  var busy = false;
  var started = false;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function scroll() { msgs.scrollTop = msgs.scrollHeight; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function addMessage(role, text, extra) {
    var m = el("div", "m " + (role === "visitor" ? "v" : role === "system" ? "sys" : "a"), text);
    extra = extra || {};
    if (extra.citations && extra.citations.length) {
      var c = el("div", "cites");
      extra.citations.forEach(function (ci) {
        c.appendChild(el("span", "cite", "Source: " + ci.source + (ci.heading ? " (" + ci.heading + ")" : "")));
      });
      m.appendChild(c);
    }
    if (extra.offerHandover) {
      var b = el("button", "hbtn", "Talk to a person");
      b.type = "button";
      b.addEventListener("click", function () { if (!recorded) openHandover(extra.reason); });
      m.appendChild(b);
    }
    msgs.appendChild(m);
    if (role === "visitor" || role === "assistant") history.push({ role: role, text: text });
    scroll();
    return m;
  }

  function showTyping() {
    var t = el("div", "typing", cfg.company + " assistant is typing...");
    msgs.appendChild(t); scroll();
    return t;
  }

  function setBusy(b) { busy = b; sendBtn.disabled = b || recorded; input.disabled = b || recorded; }

  function lastVisitorText() {
    for (var i = history.length - 1; i >= 0; i--) if (history[i].role === "visitor") return history[i].text;
    return "";
  }

  // ---- handover form ----
  function buildHandover(reason, prefill) {
    var existing = root.querySelector(".ho");
    if (existing) existing.remove();
    var f = el("form", "ho");
    f.appendChild(el("b", null, "Pass this to the team"));
    f.appendChild(el("div", null, "Leave your details and a person will reply by email."));
    function field(label, tag, name, type) {
      var l = el("label", null, label);
      var i = document.createElement(tag);
      i.name = name; if (type) i.type = type;
      if (tag === "textarea") i.rows = 3;
      i.required = true;
      l.appendChild(i); f.appendChild(l);
      return i;
    }
    var nameI = field("Name", "input", "name", "text");
    var emailI = field("Email", "input", "email", "email");
    var qI = field("Your question", "textarea", "question");
    nameI.maxLength = 120; emailI.maxLength = 254; qI.maxLength = 2000;
    qI.value = (prefill && prefill.question) || lastVisitorText();
    var err = el("div", "err");
    f.appendChild(err);
    var row = el("div", "row");
    var cancel = el("button", "cancel", "Cancel"); cancel.type = "button";
    var go = el("button", "go", "Send to the team"); go.type = "submit";
    row.appendChild(cancel); row.appendChild(go); f.appendChild(row);
    cancel.addEventListener("click", function () { f.remove(); });
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      if (recorded) return;
      err.textContent = "";
      go.disabled = true;
      fetch(cfg.api + "/handover", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nameI.value, email: emailI.value, question: qI.value,
                               reason: reason || "visitor_request", transcript: history.slice(-20) })
      }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, d: d }; });
      }).then(function (res) {
        if (!res.ok) { err.textContent = (res.d && typeof res.d.detail === "string") ? res.d.detail : "Please check the form and try again."; go.disabled = false; return; }
        f.remove();
        addMessage("system", res.d.message);
      }).catch(function () { err.textContent = "Couldn't send that. Please try again."; go.disabled = false; });
    });
    msgs.appendChild(f); scroll();
    return { form: f, name: nameI, email: emailI, question: qI, go: go };
  }
  function openHandover(reason) { var h = buildHandover(reason); h.name.focus(); }

  // ---- live mode ----
  function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    if (text.length > cfg.maxChars) { addMessage("system", "Please keep messages under " + cfg.maxChars + " characters."); return; }
    chips.innerHTML = "";
    var prior = history.slice(-6);
    addMessage("visitor", text);
    input.value = "";
    setBusy(true);
    var typing = showTyping();
    fetch(cfg.api + "/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: prior })
    }).then(function (r) {
      return r.json().then(function (d) { return { status: r.status, d: d }; });
    }).then(function (res) {
      typing.remove();
      if (res.status !== 200) {
        addMessage("system", (res.d && typeof res.d.detail === "string") ? res.d.detail : "Something went wrong. Please try again.");
        return;
      }
      var d = res.d;
      addMessage("assistant", d.reply, { citations: d.citations, offerHandover: d.offer_handover, reason: d.handover_reason });
      if (d.offer_handover && d.handover_reason === "visitor_request") openHandover(d.handover_reason);
    }).catch(function () {
      typing.remove();
      addMessage("system", "Can't reach the assistant right now.");
      var b = el("button", "hbtn", "Leave a message for the team"); b.type = "button";
      b.addEventListener("click", function () { openHandover("connection_error"); });
      msgs.appendChild(b);
    }).then(function () { setBusy(false); input.focus(); });
  }

  function greet() {
    addMessage("assistant", "Hi! I'm the " + cfg.company + " assistant. I answer from our help docs, and I'll tell you if something isn't covered. Ask me anything, or tap \"Talk to a person\" at any time.");
    history = [];  // the greeting isn't part of the conversation sent to the server
    if (!recorded) {
      ["How much is the Growth plan?", "Can I get a refund on an annual plan?", "Do you integrate with Slack?"].forEach(function (q) {
        var c = el("button", "chip", q); c.type = "button";
        c.addEventListener("click", function () { send(q); });
        chips.appendChild(c);
      });
    }
  }

  // ---- recorded mode: replay a real transcript, no API calls ----
  async function typeInto(node, text, perChar) {
    node.value = "";
    for (var i = 0; i < text.length; i++) { node.value += text[i]; await sleep(perChar); }
  }

  async function replay() {
    var data;
    try {
      var r = await fetch(cfg.transcript, { cache: "no-store" });
      data = await r.json();
    } catch (e) { addMessage("system", "Couldn't load the recorded conversation."); return; }
    for (var i = 0; i < data.turns.length; i++) {
      var t = data.turns[i];
      if (t.role === "visitor") {
        await sleep(700);
        await typeInto(input, t.text, 18);
        await sleep(250);
        input.value = "";
        addMessage("visitor", t.text);
      } else {
        var typing = showTyping();
        await sleep(1100);
        typing.remove();
        addMessage("assistant", t.text, { citations: t.citations, offerHandover: t.offer_handover, reason: t.handover_reason });
      }
    }
    if (data.handover) {
      await sleep(900);
      var h = buildHandover(data.handover.reason, data.handover);
      await typeInto(h.name, data.handover.name, 35);
      await typeInto(h.email, data.handover.email, 25);
      await sleep(500);
      h.form.remove();
      addMessage("system", data.handover.response_message);
    }
    await sleep(600);
    var end = el("div", "m sys", "End of recording (" + (data.recorded_on || "") + "). ");
    var again = el("button", "chip", "Replay"); again.type = "button";
    again.addEventListener("click", function () { msgs.innerHTML = ""; history = []; greet(); replay(); });
    end.appendChild(again); msgs.appendChild(end); scroll();
  }

  function openPanel() {
    panel.classList.add("open");
    $(".launcher").setAttribute("aria-label", "Close chat");
    if (!started) {
      started = true;
      if (recorded) {
        var banner = el("div", "banner", "Recorded demo: this replays a real conversation with the live bot. Typing is off.");
        panel.insertBefore(banner, msgs);
        input.placeholder = "Recorded demo (replay only)";
        setBusy(false);
      }
      greet();
      if (recorded) replay();
    }
    if (!recorded) input.focus();
  }
  function closePanel() { panel.classList.remove("open"); $(".launcher").setAttribute("aria-label", "Open chat"); }

  $(".launcher").addEventListener("click", function () { panel.classList.contains("open") ? closePanel() : openPanel(); });
  $(".x").addEventListener("click", closePanel);
  $(".person").addEventListener("click", function () { if (!recorded) openHandover("visitor_request"); });
  form.addEventListener("submit", function (e) { e.preventDefault(); send(input.value); });
  if (recorded) setBusy(false);
  if (cfg.open) openPanel();
})();
