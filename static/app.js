"use strict";
/* Vegas 6-Max front end: lobby, live table, hand history + replayer, stats. No dependencies. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = $("#view");
const RANKS = "23456789TJQKA", SUITS = "cdhs", SYM = { c: "♣", d: "♦", h: "♥", s: "♠" };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fmt = n => (n < 0 ? "-" : "") + "$" + Math.abs(Math.round(n)).toLocaleString();
const sfmt = n => (n > 0 ? "+" : "") + fmt(n);
const cls = n => (n > 0 ? "pos" : n < 0 ? "neg" : "muted");
const pct = x => (x == null ? "—" : Math.round(x * 100) + "%");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } },
};

function cstr(c) { return typeof c === "number" ? RANKS[c >> 2] + SUITS[c & 3] : c; }
function cardHTML(c, extra = "") {
  if (!c) return `<span class="card back ${extra}"></span>`;
  c = cstr(c);
  const r = c[0] === "T" ? "10" : c[0];
  return `<span class="card s-${c[1]} ${extra}"><b>${r}</b><i>${SYM[c[1]]}</i></span>`;
}
function miniCards(str) {
  if (!str) return "";
  return `<span class="mini">${str.split(" ").map(c => `<span class="${c[1]}">${c[0]}${SYM[c[1]]}</span>`).join(" ")}</span>`;
}

async function api(path, body) {
  const opts = body !== undefined ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opts);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || "Request failed");
  return j;
}
function toast(msg, ms = 2600) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), ms);
}
async function refreshBankroll() {
  try {
    const l = await api("/api/lobby");
    $("#bankroll").innerHTML = fmt(l.bankroll) + (l.table_stack != null ? ` <span class="muted" style="font:12px var(--sans)">+ ${fmt(l.table_stack)} on table</span>` : "");
    $("#nav-table").classList.toggle("live", l.in_session);
    return l;
  } catch (e) { return null; }
}

/* ------------------------------------------------------------------ router */
let cleanup = null;
window.addEventListener("hashchange", route);
async function route() {
  if (cleanup) { cleanup(); cleanup = null; }
  const h = location.hash.slice(1) || "lobby";
  const [pathPart, query] = h.split("?");
  const [name, arg] = pathPart.split("/");
  const params = new URLSearchParams(query || "");
  $$("nav a").forEach(a => a.classList.toggle("active", a.dataset.nav === (name === "hand" ? "hands" : name)));
  try {
    if (name === "table") await showTable();
    else if (name === "hands") await showHands(params);
    else if (name === "hand") await showHand(+arg);
    else if (name === "stats") await showStats(params);
    else await showLobby();
  } catch (e) {
    view.innerHTML = `<div class="panel empty">Error: ${esc(e.message)}</div>`;
  }
  refreshBankroll();
}

/* ------------------------------------------------------------------ lobby */
async function showLobby() {
  const l = await api("/api/lobby");
  const seated = l.in_session;
  view.innerHTML = `
  <div class="hero-band">
    <div class="panel br-card">
      <div class="muted">Bankroll</div>
      <div class="big">${fmt(l.bankroll)}</div>
      <div class="muted">Started with $1,000${l.topups ? ` · bought $1,000 ${l.topups} time${l.topups > 1 ? "s" : ""}` : ""}</div>
      ${l.can_topup ? `<div class="row" style="margin-top:12px"><button class="primary" id="topup">Buy $1,000</button>
        <span class="muted">Available because you're under $200.</span></div>` : ""}
      <div class="row" style="margin-top:12px">
        <span class="muted">Playing as</span>
        <input id="hname" value="${esc(l.hero_name)}" style="width:130px" maxlength="20">
        <button class="ghost" id="hsave">Save name</button>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="danger" id="erase">Erase everything and start over</button>
      </div>
    </div>
    <div class="panel" style="flex:2 1 420px">
      <div class="row"><h3 style="margin:0">Bankroll history</h3></div>
      <div class="chart" id="brchart"></div>
    </div>
  </div>
  ${seated ? `<div class="panel row" style="margin-bottom:16px;border-color:var(--gold)">
      <b>You're seated at a table.</b><span class="spacer"></span><a href="#table"><button class="primary">Return to table</button></a></div>` : ""}
  <h2>Pick a table</h2>
  <p class="muted" style="margin-top:-6px">No-limit hold'em with 4 to 10 players (random each time you sit down). Everyone sits with the buy-in (100 big blinds). Leave whenever you want and keep your stack.</p>
  <div class="grid tables">
    ${l.stakes.map(s => `
      <div class="tcard ${s.locked ? "locked" : ""}">
        <div class="chip"></div>
        <div class="stake">$${(s.buyin / 1000).toLocaleString()}K</div>
        <div class="blinds">Blinds $${s.sb.toLocaleString()} / $${s.bb.toLocaleString()} · buy-in ${fmt(s.buyin)}</div>
        <p>${esc(s.blurb)}</p>
        <button class="primary" data-join="${s.id}" ${s.locked || seated ? "disabled" : ""}>
          ${s.locked ? `Need ${fmt(s.buyin)}` : seated ? "Already seated" : "Sit down"}</button>
      </div>`).join("")}
  </div>
  <h2>Recent sessions</h2>
  <div class="panel">${sessionsTable(l.sessions)}</div>`;
  $$("[data-join]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api("/api/join", { stakes: b.dataset.join });
      T.reset(); T.pending = r.frames; location.hash = "#table";
    } catch (e) { toast(e.message); b.disabled = false; }
  });
  const tu = $("#topup");
  if (tu) tu.onclick = async () => {
    try { await api("/api/topup", {}); toast("Added $1,000 to your bankroll"); route(); } catch (e) { toast(e.message); }
  };
  $("#erase").onclick = async () => {
    const b = $("#erase");
    if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = "Are you sure? Click again to erase all hands and stats"; return; }
    try { await api("/api/erase_all", {}); T.reset(); toast("Erased. Fresh start at $1,000", 3500); route(); }
    catch (e) { toast(e.message + " (restart the server if this persists)"); }
  };
  $("#hsave").onclick = async () => { await api("/api/hero_name", { name: $("#hname").value }); toast("Saved. New name applies to your next table."); };
  const pts = l.bankroll_log.map((r, i) => [i, r.balance]);
  lineChart($("#brchart"), [{ name: "Bankroll", color: "#d9b45a", pts }], { height: 170, xLabel: "event", money: true });
  $$("tr[data-sess]").forEach(tr => tr.onclick = () => location.hash = `#hands?session=${tr.dataset.sess}`);
}

function sessionsTable(sessions) {
  if (!sessions.length) return `<div class="empty">No sessions yet. Pick a table above.</div>`;
  return `<table class="list"><tr><th>Table</th><th>Started</th><th>Hands</th><th>Buy-in</th><th>Cash-out</th><th>Net</th><th>Flags</th><th></th></tr>
    ${sessions.map(s => {
      const open = s.status === "open";
      const net = (s.cashout ?? s.last_stack) - s.buyin;
      return `<tr class="click" data-sess="${s.id}"><td>${esc(s.table_name)}</td><td class="muted">${new Date(s.started).toLocaleString()}</td>
      <td class="num">${s.hands}</td><td class="num">${fmt(s.buyin)}</td><td class="num">${open ? "<span class=muted>playing</span>" : fmt(s.cashout)}</td>
      <td class="num ${cls(net)}">${sfmt(net)}</td><td>${s.mistakes ? `<span class="badge mistake">${s.mistakes} mistakes</span>` : ""}</td>
      <td><a>Review →</a></td></tr>`;
    }).join("")}</table>`;
}

/* ------------------------------------------------------------------ table renderer (shared with replayer) */
// seats are laid out around the oval; you are always at the bottom
const SEAT_POS6 = [[50, 100], [2, 68], [16, 8], [50, 0], [84, 8], [98, 68]];
let LAYOUT_SEATS = [1, 2, 3, 4, 5, 6];
function setLayout(st) { LAYOUT_SEATS = st.seats.map(s => s.seat).sort((a, b) => a - b); }
function seatPosN(d, n) {
  if (n === 6) return SEAT_POS6[d];
  const a = (90 + d * 360 / n) * Math.PI / 180;
  const x = 50 + 49 * Math.cos(a), y = 50 + 57 * Math.sin(a);
  return [x, Math.max(-1, Math.min(100, y))];
}
function seatXY(seat, heroSeat) {
  const n = LAYOUT_SEATS.length;
  const i = LAYOUT_SEATS.indexOf(seat), h = Math.max(0, LAYOUT_SEATS.indexOf(heroSeat));
  return seatPosN(((i - h) % n + n) % n, n);
}
function lerp(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; }

function renderFelt(el, st, opts = {}) {
  const heroSeat = (st.seats.find(s => s.is_hero) || st.seats[0]).seat;
  setLayout(st);
  const many = st.seats.length >= 8 ? "many" : st.seats.length === 7 ? "seven" : "";
  const center = [50, 50];
  let html = `<div class="felt-outer"><div class="felt ${many}">
    <div class="center"><div class="board">${[0, 1, 2, 3, 4].map(i => st.board[i] ? cardHTML(st.board[i]) : `<span class="card ghost"></span>`).join("")}</div>
    <div class="pot">Pot ${fmt(st.pot)}</div></div>`;
  for (const s of st.seats) {
    const p = seatXY(s.seat, heroSeat);
    const acting = st.to_act === s.seat;
    const winner = s.won > 0;
    let cards = "";
    if (s.in_hand !== false && !(s.folded && !opts.showFolded)) {
      cards = s.hole ? s.hole.map(c => cardHTML(c)).join("") : (s.in_hand ? cardHTML(null) + cardHTML(null) : "");
    } else if (s.folded && opts.showFolded && s.hole) {
      cards = s.hole.map(c => cardHTML(c)).join("");
    }
    const last = s.all_in && !s.folded ? "allin" : s.last;
    const word = { fold: "FOLD", check: "CHECK", call: "CALL", bet: "BET", raise: "RAISE", allin: "ALL-IN" }[last] || "";
    const lastTxt = word && s.bet > 0 && last !== "fold" && last !== "check" ? `${word} ${fmt(s.bet)}` : word;
    html += `<div class="seat ${s.folded ? "folded" : ""} ${acting ? "acting" : ""} ${s.is_hero ? "hero" : ""} ${winner ? "winner" : ""}" style="left:${p[0]}%;top:${p[1]}%">
      <div class="cards">${cards}</div>
      <div class="box">
        ${s.position ? `<span class="tag">${s.position}</span>` : ""}
        ${word && last !== "fold" ? `<span class="act ${last}">${word}</span>` : ""}
        <div class="name">${esc(s.name)}</div>
        <div class="stack">${s.all_in && s.stack === 0 ? "ALL-IN" : fmt(s.stack)}</div>
        ${winner ? `<div class="won">wins ${fmt(s.won)}</div>` : ""}
        ${s.desc ? `<div class="desc">${esc(s.desc)}</div>` : ""}
        ${opts.labels && s.label ? `<div class="label">${esc(s.label)}</div>` : ""}
      </div></div>`;
    if (s.bet > 0) {
      const b = betXY(s.seat, heroSeat);
      html += `<div class="betchip" data-seat="${s.seat}" style="left:${b[0]}%;top:${b[1]}%">${fmt(s.bet)}</div>`;
    }
    if (s.seat === st.button) {
      const d = dealerXY(s.seat, heroSeat);
      html += `<div class="dealer" style="left:${d[0]}%;top:${d[1]}%">D</div>`;
    }
  }
  html += `</div></div>`;
  el.innerHTML = html;
}

/* ------------------------------------------------------------------ live table */
const T = {
  frames: [], playing: false, turbo: false, analyzing: false, lastDone: null, pre: null, cur: null, log: [], pending: null, autoTimer: null, lastHand: null,
  reset() { this.frames = []; this.playing = false; this.turbo = false; this.analyzing = false; this.pre = null; this.cur = null; this.log = []; this.lastHand = null; },
};
const SPEEDS = { instant: 0, fast: 450, normal: 1000, slow: 1600 };

async function showTable() {
  let frames = T.pending;
  T.pending = null;
  if (!frames) {
    const s = await api("/api/state");
    if (!s.seated) {
      view.innerHTML = `<div class="panel empty"><h2>You're not seated</h2><p>Pick a table in the lobby.</p>
        <a href="#lobby"><button class="primary">Go to lobby</button></a></div>`;
      return;
    }
    frames = s.frames;
  }
  const speed = store.get("speed", "normal"), auto = store.get("autodeal", true);
  view.innerHTML = `
  <div class="row" style="margin-bottom:4px">
    <h1 id="tname" style="margin:0">Table</h1><span class="muted" id="tblinds"></span><span class="spacer"></span>
    <span class="muted">Session</span> <b class="num" id="snet"></b>
    <span class="muted">· hands <b class="num" id="shands"></b></span>
    <button class="danger" id="leave">Leave table</button>
  </div>
  <div class="table-wrap">
    <div>
      <div id="feltwrap" style="position:relative"><div id="felt"></div><div id="fx"></div></div>
      <div class="panel actionbar" id="actions"></div>
    </div>
    <div class="panel sidepanel">
      <div class="settings muted">
        <label><input type="checkbox" id="auto" ${auto ? "checked" : ""}> Auto-deal next hand</label>
        <label>Speed <select id="speed">${Object.keys(SPEEDS).map(k => `<option ${k === speed ? "selected" : ""}>${k}</option>`).join("")}</select></label>
        <details class="keys"><summary>Keyboard shortcuts</summary><span class="kbd">F</span> fold <span class="kbd">C</span> check/call <span class="kbd">R</span> raise <span class="kbd">Enter</span> confirm <span class="kbd">Space</span> next/speed up <span class="kbd">A</span> analyze</details>
      </div>
      <h3>Action log</h3><div class="log" id="log"></div>
      <div class="dock-toggles">
        <button id="tg-ranges" class="toggle ${store.get("dock_ranges", false) ? "on" : ""}">Preflop ranges</button>
        <button id="tg-rank" class="toggle ${store.get("dock_rank", false) ? "on" : ""}">Hand rankings</button>
      </div>
      <div id="dock-ranges" class="dock" ${store.get("dock_ranges", false) ? "" : "hidden"}></div>
      <div id="dock-rank" class="dock" ${store.get("dock_rank", false) ? "" : "hidden"}></div>
    </div>
  </div>`;
  const toggleDock = (key, btn, box, render) => {
    const on = !store.get(key, false);
    store.set(key, on);
    $(btn).classList.toggle("on", on);
    $(box).hidden = !on;
    if (on) render();
  };
  $("#tg-ranges").onclick = () => toggleDock("dock_ranges", "#tg-ranges", "#dock-ranges", renderRangesDock);
  $("#tg-rank").onclick = () => toggleDock("dock_rank", "#tg-rank", "#dock-rank", renderRankDock);
  if (store.get("dock_rank", false)) renderRankDock();
  if (store.get("dock_ranges", false)) renderRangesDock();
  $("#auto").onchange = e => store.set("autodeal", e.target.checked);
  $("#speed").onchange = e => store.set("speed", e.target.value);
  let armed = false;
  $("#leave").onclick = async () => {
    const midHand = T.cur && !T.cur.hand_over;
    if (midHand && !armed) { armed = true; $("#leave").textContent = "Fold & leave? Click again"; return; }
    clearTimeout(T.autoTimer);
    const r = await api("/api/leave", {});
    T.reset();
    toast(`Cashed out ${fmt(r.left_with)} (${sfmt(r.net)} this session)`, 4000);
    location.hash = "#lobby";
  };
  const onKey = e => {
    if ($(".modal-bg")) { if (e.key === "Escape") closeAnalysis(); return; }
    if (e.target.tagName === "INPUT" && e.key !== "Enter") return;
    const k = e.key.toLowerCase();
    const btn = id => { const b = $(id); if (b && !b.disabled) { e.preventDefault(); b.click(); } };
    if (k === "f") btn("#a-fold");
    else if (k === "c") btn("#a-call");
    else if (k === "r") { const i = $("#amt"); if (i) { e.preventDefault(); i.focus(); i.select(); } }
    else if (k === "enter") btn("#a-raise");
    else if (k === " " || k === "n") { if ($("#a-speed:not([disabled])")) btn("#a-speed"); else btn("#a-next"); }
    else if (k === "a") btn("#a-analyze");
  };
  document.addEventListener("keydown", onKey);
  cleanup = () => { document.removeEventListener("keydown", onKey); clearTimeout(T.autoTimer); closeAnalysis(false); };
  renderLog();
  if (T.cur && frames.length === 1 && !frames[0].log && T.cur.hand_id === frames[0].hand_id) {
    T.cur = frames[0]; drawTable(T.cur);
  } else {
    enqueue(frames);
  }
}

function enqueue(frames) {
  T.frames.push(...frames);
  if (!T.playing) play();
}
async function play() {
  T.playing = true;
  while (T.frames.length) {
    const f = T.frames.shift();
    if (f.hand_id && f.hand_id !== T.lastHand) {
      T.lastHand = f.hand_id;
      T.turbo = false;
      T.log.push({ sep: true, text: `Hand #${f.hand_id} · ${f.stakes ? `$${f.stakes.sb}/$${f.stakes.bb}` : ""}` });
    }
    if (f.log) f.log.forEach(t => T.log.push({ text: t, hero: T.cur && heroName() && t.startsWith(heroName()) }));
    const prev = T.cur;
    T.cur = f;
    if (f.hand_over && f.hand_id) T.lastDone = f.hand_id;
    if ($("#felt")) { renderLog(); await animateFrame(prev, f); }
    if (T.frames.length) {
      const dealt = f.log && f.log.some(t => /^(Flop|Turn|River)/.test(t));
      await frameWait(dealt ? 1.6 : 1);
    }
  }
  T.playing = false;
  if ($("#felt")) { renderLog(); drawTable(T.cur); }
  refreshBankroll();
}
const TURBO_MS = 170;
function curSpeed() { return T.turbo ? TURBO_MS : SPEEDS[store.get("speed", "normal")]; }
async function frameWait(mult) {
  // waits one action's worth of time; if "Speed up" is pressed mid-wait it finishes early
  const start = Date.now();
  while (Date.now() - start < curSpeed() * mult) await sleep(30);
}
function speedUp() {
  T.turbo = true;
  const b = $("#a-speed"); if (b) { b.disabled = true; b.textContent = "Speeding up…"; }
}
function heroName() { const h = T.cur && T.cur.seats.find(s => s.is_hero); return h ? h.name : null; }
function renderLog() {
  const el = $("#log"); if (!el) return;
  const items = T.log.slice(-300);
  el.innerHTML = items.map(x => `<div class="${x.sep ? "sep" : x.hero ? "hero" : ""}">${esc(x.text)}</div>`).join("");
  el.scrollTop = el.scrollHeight;
}

function drawTable(f, prev) {
  if (store.get("dock_ranges", false) && (!prev || prev.hand_id !== f.hand_id || f.street === "preflop")) {
    clearTimeout(drawTable._rt); drawTable._rt = setTimeout(renderRangesDock, 200);
  }
  if (!f) return;
  $("#tname").textContent = f.table_name;
  $("#tblinds").textContent = `$${f.stakes.sb.toLocaleString()}/$${f.stakes.bb.toLocaleString()} NL · ${f.n_seats || f.seats.length} players`;
  $("#snet").innerHTML = `<span class="${cls(f.session.net)}">${sfmt(f.session.net)}</span>`;
  $("#shands").textContent = f.session.hands;
  renderFelt($("#felt"), f, { prev: prev || null });
  if (prev) spawnCallouts(prev, f);
  drawActions(f);
}

function drawActions(f) {
  const el = $("#actions");
  clearTimeout(T.autoTimer);
  const busy = T.playing && T.frames.length;
  const L = !busy && !f.hand_over && !f.busted ? f.legal : null;
  const bb = f.stakes.bb, unit = f.stakes.sb;
  const hero = f.seats.find(s => s.is_hero);
  // controls row (always the same layout; disabled when it isn't your turn)
  let presets = [["½", 0], ["¾", 0], ["Pot", 0]], def = 0, minTo = 0, maxTo = 0;
  const round = x => Math.max(minTo, Math.min(maxTo, Math.round(x / unit) * unit));
  if (L && L.can_raise) {
    minTo = L.min_to; maxTo = L.max_to;
    const potTo = frac => L.current_bet === 0 ? L.pot * frac : L.current_bet + frac * (L.pot + L.to_call);
    if (f.street === "preflop" && L.current_bet <= bb) presets = [["2.5x", 2.5 * bb], ["3x", 3 * bb], ["4x", 4 * bb]];
    else if (f.street === "preflop") presets = [["3x", L.current_bet * 3], ["4x", L.current_bet * 4], ["Pot", potTo(1)]];
    else if (L.current_bet === 0) presets = [["½", potTo(0.5)], ["¾", potTo(0.75)], ["Pot", potTo(1)]];
    else presets = [["2.5x", L.current_bet * 2.5], ["3x", L.current_bet * 3], ["Pot", potTo(1)]];
    def = round(presets[f.street === "preflop" ? 0 : 1][1]);
  }
  const canRaise = !!(L && L.can_raise);
  // pre-actions: available while the hand is running, you're still in it, and it isn't your turn
  const canPre = !L && !f.hand_over && !f.busted && hero && hero.in_hand && !hero.folded && !hero.all_in;
  if (!canPre && !L) T.pre = null;
  if (L && T.pre && !busy) {
    const pre = T.pre; T.pre = null;
    if (pre === "fold") { send(L.can_check ? "check" : "fold"); return; }
    if (pre === "check" && L.can_check) { send("check"); return; }
    toast("Someone bet. Your pre-selected check was cancelled.");
  }
  const callLabel = !L ? (canPre ? "Check" : "Check / Call") : L.can_check ? "Check" : `Call ${fmt(L.to_call)}${L.to_call >= hero.stack ? " (all-in)" : ""}`;
  const raiseWord = L && L.raise_word === "bet" ? "Bet" : L ? "Raise to" : "Bet / Raise";
  // status row
  let status = "", right = "";
  if (f.busted) {
    status = `<span class="result-banner neg">You're out of chips at this table.</span>
      <button class="primary" id="bust-leave" style="margin-left:12px">Back to lobby</button>`;
  } else if (f.hand_over && !busy) {
    const net = f.result ? f.result.hero_net : 0;
    status = `<span class="result-banner ${cls(net)}">${net > 0 ? "You won " + fmt(net) : net < 0 ? "You lost " + fmt(-net) : "Hand over"}</span>
`;
  } else if (hero && hero.folded && !f.hand_over) {
    status = `<span class="muted">You folded · hand in progress…</span>`;
  } else if (L) {
    status = L.to_call ? `<span class="muted num">Pot odds ${pct(L.to_call / (L.pot + L.to_call))}</span>` : "";
  } else {
    status = canPre
      ? (T.pre ? `<span style="color:var(--gold2)">Pre-selected: <b>${T.pre === "fold" ? "Fold (checks if free)" : "Check"}</b>. Click again to cancel.</span>`
               : `<span class="muted">Waiting for other players… you can pre-select Fold or Check.</span>`)
      : `<span class="muted">Waiting for other players…</span>`;
  }
  // fixed buttons on the right: always shown, just enabled/disabled
  const canSpeed = !!(hero && hero.folded && !f.hand_over && !f.busted && !T.turbo);
  const analyzeId = f.hand_over ? f.hand_id : (T.lastDone && T.lastDone !== f.hand_id ? T.lastDone : null);
  const canNext = !!(f.hand_over && !busy && !f.busted);
  right = `<button id="a-speed" ${canSpeed ? "" : "disabled"}>${T.turbo ? "Speeding up…" : "Speed up"}</button>
    <button id="a-analyze" ${analyzeId ? "" : "disabled"}>Analyze last hand</button>
    <button class="primary" id="a-next" ${canNext ? "" : "disabled"}>Next hand</button>`;
  el.innerHTML = `
    <div class="ctrls">
      <button class="big fold ${T.pre === "fold" ? "queued" : ""}" id="a-fold" ${(L && !L.can_check) || canPre ? "" : "disabled"}>Fold</button>
      <button class="big call ${T.pre === "check" ? "queued" : ""}" id="a-call" ${L || canPre ? "" : "disabled"}>${callLabel}</button>
      <button class="big primary" id="a-raise" ${canRaise ? "" : "disabled"}>${raiseWord} <span id="rto">${canRaise ? fmt(def) : ""}</span></button>
      <div class="sizer">
        <input type="number" id="amt" min="${minTo}" max="${maxTo}" step="${unit}" value="${canRaise ? def : ""}" ${canRaise ? "" : "disabled"}>
        <input type="range" id="slider" min="${minTo}" max="${maxTo}" step="${unit}" value="${def}" ${canRaise ? "" : "disabled"}>
        ${presets.map(([n, v]) => `<button data-to="${canRaise ? round(v) : 0}" ${canRaise ? "" : "disabled"}>${n}</button>`).join("")}
        <button data-to="${maxTo}" ${canRaise ? "" : "disabled"}>All-in</button>
      </div>
    </div>
    <div class="status"><div class="st-left">${status}</div><div class="st-right">${right}</div></div>`;
  if (analyzeId) $("#a-analyze").onclick = () => openAnalysis(analyzeId);
  if (canSpeed) $("#a-speed").onclick = speedUp;
  if (canNext) $("#a-next").onclick = () => { closeAnalysis(false); nextHand(); };
  if (f.busted) { $("#bust-leave").onclick = () => $("#leave").click(); return; }
  if (f.hand_over && !busy) {
    if (store.get("autodeal", true)) T.autoTimer = setTimeout(nextHand, f.result && f.result.showdown ? 2800 : 1700);
    return;
  }
  if (canPre) {
    const toggle = which => { T.pre = T.pre === which ? null : which; drawActions(T.cur); };
    $("#a-fold").onclick = () => toggle("fold");
    $("#a-call").onclick = () => toggle("check");
    return;
  }
  if (!L) return;
  $("#a-fold").onclick = () => send("fold");
  $("#a-call").onclick = () => send(L.can_check ? "check" : "call");
  if (canRaise) {
    const amt = $("#amt"), sl = $("#slider");
    const setv = v => { v = round(+v || minTo); amt.value = v; sl.value = v; $("#rto").textContent = fmt(v) + (v >= maxTo ? " (all-in)" : ""); };
    sl.oninput = () => setv(sl.value);
    amt.oninput = () => { sl.value = amt.value; $("#rto").textContent = fmt(+amt.value || 0); };
    amt.onchange = () => setv(amt.value);
    $$("[data-to]", el).forEach(b => b.onclick = () => setv(b.dataset.to));
    $("#a-raise").onclick = () => send(L.raise_word, round(+amt.value));
  }
}

async function send(action, amount) {
  $$("#actions button").forEach(b => b.disabled = true);
  try {
    const r = await api("/api/act", { action, amount });
    enqueue(r.frames);
  } catch (e) { toast(e.message); drawActions(T.cur); }
}
async function nextHand() {
  clearTimeout(T.autoTimer);
  if (!$("#felt") || T.analyzing) return;
  try {
    const r = await api("/api/next", {});
    enqueue(r.frames);
  } catch (e) { toast(e.message); }
}



/* ------------------------------------------------------------------ action callouts (slide from the hand toward the middle) */
function spawnCallouts(prev, f) {
  const fx = $("#fx"), felt = $("#felt .felt"), wrap = $("#feltwrap");
  if (!fx || !felt || !wrap) return;
  const spd = curSpeed();
  if (!spd) return;
  const wr = wrap.getBoundingClientRect(), fr = felt.getBoundingClientRect();
  const hs = heroSeatOf(f);
  const px = xy => [fr.left - wr.left + fr.width * xy[0] / 100, fr.top - wr.top + fr.height * xy[1] / 100];
  const sameHand = prev.hand_id === f.hand_id;
  for (const s of f.seats) {
    const p = sameHand ? prev.seats.find(x => x.seat === s.seat) : null;
    const changed = s.last && ["fold", "check", "call", "bet", "raise"].includes(s.last) &&
      (!p || p.last !== s.last || p.bet !== s.bet || p.folded !== s.folded || p.stack !== s.stack);
    if (!changed) continue;
    const allin = s.all_in && !s.folded;
    const kind = allin ? "allin" : s.last;
    const word = { fold: "FOLD", check: "CHECK", call: "CALL", bet: "BET", raise: "RAISE", allin: "ALL-IN" }[kind];
    const amt = s.bet > 0 && kind !== "fold" && kind !== "check" ? " " + fmt(s.bet) : "";
    const seatP = seatXY(s.seat, hs);
    const isHero = s.seat === hs;
    const from = px(lerp([50, 50], seatP, 0.92)), to = px(isHero ? [73, 80] : lerp([50, 50], seatP, LAYOUT_SEATS.length >= 8 ? 0.8 : 0.55));
    const d = document.createElement("div");
    d.className = "callout " + kind + (LAYOUT_SEATS.length >= 8 ? " small" : "");
    d.textContent = word + amt;
    d.style.setProperty("--fx", from[0] + "px"); d.style.setProperty("--fy", from[1] + "px");
    d.style.setProperty("--tx", to[0] + "px"); d.style.setProperty("--ty", to[1] + "px");
    d.style.animationDuration = (T.turbo ? 650 : Math.max(1300, spd * 1.9)) + "ms";
    d.addEventListener("animationend", () => d.remove());
    fx.appendChild(d);
  }
}


/* ------------------------------------------------------------------ preflop range chart + hand rankings */
const ACT_STYLE = { raise: "Raise", call: "Call", check: "Check", fold: "Fold" };
async function renderRangesDock() {
  const box = $("#dock-ranges");
  if (!box || box.hidden) return;
  let r;
  try { r = await api("/api/preflop_ranges"); } catch (e) { return; }
  const key = JSON.stringify([r.pos, r.headline, r.hero_class]);
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  const R = "AKQJT98765432";
  let grid = "";
  for (let i = 0; i < 13; i++) for (let j = 0; j < 13; j++) {
    const c = i === j ? R[i] + R[j] : i < j ? R[i] + R[j] + "s" : R[j] + R[i] + "o";
    const act = r.chart[c] || "fold";
    grid += `<div class="rc ${act} ${c === r.hero_class ? "mine" : ""}" title="${c}: ${ACT_STYLE[act]}">${c}</div>`;
  }
  box.innerHTML = `
    <div class="dock-head"><b>${r.pos}</b>${r.hero_class ? ` · ${r.hero_class}` : ""} · <span>${esc(r.headline)}</span></div>
    <div class="dock-legend">${["raise", "call", "check", "fold"].filter(a => r.pct[a]).map(a => `<span><i class="rc ${a}"></i>${ACT_STYLE[a]} ${Math.round(r.pct[a])}%</span>`).join("")}</div>
    <div class="rgrid mini">${grid}</div>`;
}
const RANKINGS = [
  ["Four of a kind", "Qs Qh Qd Qc 7s", "0.17%"],
  ["Full house", "Ks Kh Kd 4c 4s", "2.6%"],
  ["Flush", "Ah Jh 8h 6h 2h", "3.0%"],
  ["Straight", "9c 8d 7s 6h 5c", "4.6%"],
  ["Three of a kind", "7c 7d 7h Ks 2d", "4.8%"],
  ["Two pair", "Jc Jd 5h 5s Ac", "23.5%"],
  ["One pair", "Ts Th Ac 8d 4s", "43.8%"],
  ["High card", "Ad Jc 9s 6h 3c", "17.4%"],
];
function renderRankDock() {
  const box = $("#dock-rank");
  if (!box) return;
  box.innerHTML = `
    <div class="dock-head">Best to worst · straight/royal flush beat all</div>
    ${RANKINGS.map(([n, cs, p], k) => `<div class="rk-mini"><span class="n">${k + 1}</span><span class="nm">${n}</span>${miniCards(cs)}<span class="p">${p}</span></div>`).join("")}`;
}

/* ------------------------------------------------------------------ chip animations */
const POT_XY = [50, 57];
function heroSeatOf(f) { return (f.seats.find(s => s.is_hero) || f.seats[0]).seat; }
// your own seat (bottom) has big cards, so its chip and dealer button sit beside them
function betXY(seat, hs) { return seat === hs ? [65, 74] : lerp([50, 50], seatXY(seat, hs), 0.58); }
function dealerXY(seat, hs) {
  if (seat === hs) return [35, 80];
  // sit the button beside the bet chip (offset sideways from the line to the centre)
  const p = seatXY(seat, hs), d = lerp([50, 50], p, 0.68);
  const vx = p[0] - 50, vy = p[1] - 50, len = Math.hypot(vx, vy) || 1;
  return [d[0] - vy / len * 6, d[1] + vx / len * 9];
}
function seatChipXY(seat, hs) { return lerp([50, 50], seatXY(seat, hs), 0.9); }
function flyChip(felt, from, to, label, dur) {
  const d = document.createElement("div");
  d.className = "betchip fly";
  d.textContent = label;
  d.style.left = from[0] + "%"; d.style.top = from[1] + "%";
  felt.appendChild(d);
  d.getBoundingClientRect();
  d.style.transition = `left ${dur}ms cubic-bezier(.3,.7,.4,1), top ${dur}ms cubic-bezier(.3,.7,.4,1)`;
  d.style.left = to[0] + "%"; d.style.top = to[1] + "%";
  return sleep(dur + 20).then(() => d.remove());
}
async function animateFrame(prev, f) {
  const spd = curSpeed();
  const felt = $("#felt .felt");
  if (!spd || !prev || !felt || prev.hand_id !== f.hand_id) {
    drawTable(f, prev);
    // new hand: slide the blinds out
    if (spd && f && !f.hand_over) await slideIn(null, f, Math.min(450, spd * 0.45));
    return;
  }
  const dur = T.turbo ? 130 : Math.min(520, Math.max(300, spd * 0.5));
  const hs = heroSeatOf(f);
  const streetEnd = prev.street !== f.street || (f.hand_over && !prev.hand_over);
  if (streetEnd) {
    // 1) money put in during this frame slides out from the seat
    const pb = Object.fromEntries(prev.seats.map(s => [s.seat, s.bet]));
    const puts = [];
    for (const s of f.seats) {
      const p = prev.seats.find(x => x.seat === s.seat);
      if (!p || s.won > 0) continue;
      const put = p.stack - s.stack;
      if (put > 0) { puts.push(s.seat); pb[s.seat] = (pb[s.seat] || 0) + put; }
    }
    if (puts.length) await Promise.all(puts.map(seat => flyChip(felt, seatChipXY(seat, hs), betXY(seat, hs), fmt(pb[seat] - (prev.seats.find(x => x.seat === seat).bet || 0)), dur)));
    // 2) all bets sweep into the pot
    $$(".betchip:not(.fly)", felt).forEach(c => c.style.visibility = "hidden");
    const sweeps = Object.entries(pb).filter(([, v]) => v > 0);
    if (sweeps.length) {
      await sleep(dur * 0.3);
      await Promise.all(sweeps.map(([seat, v]) => flyChip(felt, betXY(+seat, hs), POT_XY, fmt(v), dur)));
    }
    drawTable(f, prev);
    // 3) pot pushed to the winner(s)
    if (f.hand_over && !prev.hand_over) {
      const felt2 = $("#felt .felt");
      const winners = f.seats.filter(s => s.won > 0);
      await sleep(dur * 0.4);
      await Promise.all(winners.map(s => flyChip(felt2, POT_XY, seatChipXY(s.seat, hs), fmt(s.won), dur * 1.3)));
    }
    return;
  }
  drawTable(f, prev);
  await slideIn(prev, f, dur);
}
async function slideIn(prev, f, dur) {
  const felt = $("#felt .felt");
  if (!felt) return;
  const hs = heroSeatOf(f);
  const jobs = [];
  for (const s of f.seats) {
    const pbet = prev ? (prev.seats.find(x => x.seat === s.seat) || {}).bet || 0 : 0;
    if (s.bet > pbet) {
      const chip = $(`.betchip[data-seat="${s.seat}"]`, felt);
      if (!chip) continue;
      const to = betXY(s.seat, hs), from = seatChipXY(s.seat, hs);
      chip.style.left = from[0] + "%"; chip.style.top = from[1] + "%";
      chip.getBoundingClientRect();
      chip.style.transition = `left ${dur}ms cubic-bezier(.3,.7,.4,1), top ${dur}ms cubic-bezier(.3,.7,.4,1)`;
      chip.style.left = to[0] + "%"; chip.style.top = to[1] + "%";
      jobs.push(sleep(dur));
    }
  }
  await Promise.all(jobs);
}

/* ------------------------------------------------------------------ hands list */
async function showHands(params) {
  const [sessions] = await Promise.all([api("/api/sessions")]);
  const f = Object.fromEntries(params.entries());
  view.innerHTML = `
  <div class="row"><h1 style="margin:0">Hand history</h1><span class="spacer"></span>
    <a id="ex-ai"><button class="primary">⬇ Export for AI analysis (.zip)</button></a>
    <span class="muted">Other exports (use filters):</span>
    <a id="ex-txt"><button>PokerStars .txt</button></a>
    <a id="ex-json"><button>JSON</button></a>
    <a id="ex-csv"><button>Decisions .csv</button></a>
  </div>
  <p class="muted" style="margin-top:6px">The PokerStars file imports into PokerTracker 4, Hold'em Manager 3, Hand2Note, or GTO Wizard's hand upload. Files are also saved automatically in <code>data/hand_histories/</code>.</p>
  <div class="filters panel">
    <select id="f-stakes"><option value="">All stakes</option>${["1k", "5k", "25k", "100k"].map(s => `<option value="${s}">$${s.toUpperCase()}</option>`).join("")}</select>
    <select id="f-session"><option value="">All sessions</option>${sessions.map(s => `<option value="${s.id}">${esc(s.table_name)} · ${new Date(s.started).toLocaleDateString()}</option>`).join("")}</select>
    <select id="f-pos"><option value="">Any position</option>${["UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO", "BTN", "SB", "BB"].map(p => `<option>${p}</option>`).join("")}</select>
    <select id="f-result"><option value="">Won or lost</option><option value="won">Won</option><option value="lost">Lost</option></select>
    <select id="f-flagged"><option value="">All hands</option><option value="1">Possible mistakes</option><option value="notes">Mistakes + notes</option></select>
    <label><input type="checkbox" id="f-showdown"> Showdown</label>
    <label><input type="checkbox" id="f-bigpot"> Big pots (40bb+)</label>
    <input id="f-cards" placeholder="Cards e.g. Ah" style="width:120px">
  </div>
  <div class="panel" id="hlist"><div class="empty">Loading…</div></div>`;
  const ids = { stakes: "f-stakes", session: "f-session", pos: "f-pos", result: "f-result", flagged: "f-flagged", cards: "f-cards" };
  for (const [k, id] of Object.entries(ids)) if (f[k]) $("#" + id).value = f[k];
  if (f.showdown) $("#f-showdown").checked = true;
  if (f.bigpot) $("#f-bigpot").checked = true;
  const qs = () => {
    const p = new URLSearchParams();
    for (const [k, id] of Object.entries(ids)) if ($("#" + id).value) p.set(k, $("#" + id).value);
    if ($("#f-showdown").checked) p.set("showdown", "1");
    if ($("#f-bigpot").checked) p.set("bigpot", "1");
    return p.toString();
  };
  const load = async () => {
    const q = qs();
    history.replaceState(null, "", "#hands" + (q ? "?" + q : ""));
    $("#ex-ai").href = "/api/export/ai_pack.zip?" + q;
    $("#ex-txt").href = "/api/export/hands.txt?" + q;
    $("#ex-json").href = "/api/export/hands.json?" + q;
    $("#ex-csv").href = "/api/export/decisions.csv?" + q;
    const rows = await api("/api/hands?" + q);
    const el = $("#hlist");
    if (!rows.length) { el.innerHTML = `<div class="empty">No hands match.</div>`; return; }
    const tot = rows.reduce((a, r) => a + r.hero_net, 0);
    el.innerHTML = `<div class="muted" style="margin-bottom:8px">${rows.length} hands · net <b class="${cls(tot)}">${sfmt(tot)}</b></div>
    <table class="list"><tr><th>Hand</th><th>Time</th><th>Stakes</th><th>Pos</th><th>Cards</th><th>Board</th><th>Pot</th><th>Net</th><th>All-in EV</th><th>Review flags</th></tr>
    ${rows.map(r => `<tr class="click" data-id="${r.id}">
      <td class="num">#${r.id}</td><td class="muted">${new Date(r.ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</td>
      <td>$${r.stakes_id.toUpperCase()}</td><td>${r.hero_pos}</td><td>${miniCards(r.hero_cards)}</td><td>${miniCards(r.board)}</td>
      <td class="num">${fmt(r.pot)}</td>
      <td class="num ${cls(r.hero_net)}">${sfmt(r.hero_net)} <span class="muted">(${(r.hero_net / r.bb).toFixed(1)}bb)</span></td>
      <td class="num">${r.analyzed && r.ev_net != null && Math.round(r.ev_net) !== r.hero_net ? `<span class="${cls(r.ev_net)}">${sfmt(r.ev_net)}</span>` : ""}</td>
      <td>${!r.analyzed ? `<span class="muted">analyzing…</span>` : ""}${r.mistakes ? `<span class="badge mistake">${r.mistakes} mistake${r.mistakes > 1 ? "s" : ""}</span>` : ""}${r.notes ? `<span class="badge note">${r.notes} note${r.notes > 1 ? "s" : ""}</span>` : ""}${r.showdown ? `<span class="badge info">SD</span>` : ""}</td>
    </tr>`).join("")}</table>`;
    $$("tr[data-id]", el).forEach(tr => tr.onclick = () => location.hash = "#hand/" + tr.dataset.id);
  };
  $$(".filters select, .filters input").forEach(i => i.onchange = load);
  $("#f-cards").oninput = () => { clearTimeout(load._t); load._t = setTimeout(load, 300); };
  await load();
}


/* ------------------------------------------------------------------ shared analysis pieces */
const worst = d => d.flags.some(f => f.level === "mistake") ? "mistake" : d.flags.some(f => f.level === "note") ? "note" : d.flags.length ? d.flags[0].level : "good";
function decisionHTML(d) {
  return `
  <div class="decision" data-i="${d.i}">
    <div class="hd"><b>${d.street[0].toUpperCase() + d.street.slice(1)} · ${d.action}${d.amount && d.action !== "fold" && d.action !== "check" ? " " + fmt(d.amount) : ""}</b>
      <span>${d.board ? miniCards(d.board) : ""} ${verdictBadge(d)}</span></div>
    <div class="muted num" style="font-size:14px">Pot ${fmt(d.pot)}${d.to_call ? ` · to call ${fmt(d.to_call)} · needed ${pct(d.req)}` : ""} · ${d.opponents} opponent${d.opponents === 1 ? "" : "s"}${d.call_ev != null && ["call", "fold"].includes(d.action) ? ` · calling EV now ≈ ${sfmt(d.call_ev)}` : ""}</div>
    ${eqRow("Equity vs ranges", d.eq_range, d.req, "")}
    ${eqRow("Equity vs actual", d.eq_actual, d.req, "act")}
    ${shouldHTML(d)}
    ${d.flags.filter(f => f.level !== "mistake" && f.level !== "note").map(f => `<div class="flag"><span class="badge ${f.level}">${f.level}</span>${esc(f.text)}</div>`).join("")}
  </div>`;
}
function verdictBadge(d) {
  if (!d.should) return `<span class="badge ${worst(d)}">${worst(d) === "good" ? "OK" : worst(d)}</span>`;
  const same = ACT_GROUP(d.action) === ACT_GROUP(d.should.action);
  return same ? `<span class="badge good">Good</span>` : d.should.match ? `<span class="badge note">Close</span>` : `<span class="badge mistake">Improve</span>`;
}
const ACT_GROUP = a => (a === "bet" || a === "raise") ? "aggro" : a;
function shouldHTML(d) {
  const sh = d.should;
  if (!sh) return d.flags.map(f => `<div class="flag"><span class="badge ${f.level}">${f.level}</span>${esc(f.text)}</div>`).join("");
  const same = ACT_GROUP(d.action) === ACT_GROUP(sh.action);
  let head, kind;
  if (same) { head = "✓ Good play"; kind = "ok"; }
  else if (sh.match) { head = `≈ Close spot · suggested: ${esc(sh.label)}`; kind = "close"; }
  else { head = `✗ Better: ${esc(sh.label)}${sh.close ? " (close spot)" : ""}`; kind = "bad"; }
  return `<div class="should ${kind}"><b>${head}</b><div>${esc(sh.why)}</div></div>`;
}
function improveCount(an) {
  return an ? an.decisions.filter(d => d.should && !d.should.match).length : 0;
}
function allinHTML(an) {
  if (!an || !an.allin) return "";
  return `<div class="panel" style="margin-bottom:12px"><h3>All-in luck check</h3>
    <div>Your equity when the money went in: <b>${pct(an.allin.equity)}</b></div>
    <div class="row num" style="margin-top:6px"><span>Expected: <b class="${cls(an.allin.ev_net)}">${sfmt(an.allin.ev_net)}</b></span>
    <span>Actual: <b class="${cls(an.allin.actual_net)}">${sfmt(an.allin.actual_net)}</b></span>
    <span>Luck: <b class="${cls(an.allin.luck)}">${sfmt(an.allin.luck)}</b></span></div></div>`;
}

/* ------------------------------------------------------------------ quick "Analyze this hand" panel at the table */
function closeAnalysis(rearm = true) {
  const m = $(".modal-bg");
  if (m) m.remove();
  const was = T.analyzing;
  T.analyzing = false;
  if (rearm && was && T.cur && T.cur.hand_over && !T.playing && $("#actions")) drawActions(T.cur);
}
async function openAnalysis(id) {
  clearTimeout(T.autoTimer);
  T.analyzing = true;
  closeAnalysis(); T.analyzing = true;
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal"><div class="empty">Analyzing hand #${id}…</div></div>`;
  bg.onclick = e => { if (e.target === bg) closeAnalysis(); };
  document.body.appendChild(bg);
  let h;
  try { h = await api("/api/hand/" + id); } catch (e) { $(".modal", bg).innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const rec = h.record, an = h.analysis, hero = rec.seats.find(s => s.is_hero);
  const flags = an ? an.mistakes : 0;
  $(".modal", bg).innerHTML = `
    <div class="row" style="margin-bottom:10px">
      <h2 style="margin:0">Hand #${rec.id}</h2>
      <span class="muted">${hero.position} ${miniCards(rec.hero_cards)} ${rec.board_cards.length ? "· board " + miniCards(rec.board_cards.join(" ")) : ""}</span>
      <span class="spacer"></span>
      <b class="num ${cls(rec.hero_net)}" style="font-size:22px">${sfmt(rec.hero_net)}</b>
    </div>
    <div style="margin-bottom:10px;font-size:17px">${an ? (improveCount(an) ? `<b class="neg">${improveCount(an)} decision${improveCount(an) > 1 ? "s" : ""} to improve</b>` : `<b class="pos">You played this hand well</b>`) : ""}</div>
    <div class="panel" style="margin-bottom:12px">
      <h3>Everyone's cards</h3>
      <table class="list">${rec.seats.map(s => `<tr><td><b>${s.position}</b></td><td>${esc(s.name)}${s.is_hero ? " (you)" : ""}</td>
        <td>${miniCards(s.hole_str.join(" "))}</td><td class="muted">${s.is_hero ? "" : esc(s.archetype_label || "")}</td>
        <td class="num ${cls(s.end_stack - s.start_stack)}">${s.end_stack !== s.start_stack ? sfmt(s.end_stack - s.start_stack) : ""}</td></tr>`).join("")}</table>
    </div>
    ${allinHTML(an)}
    <h3>Your decisions</h3>
    <p class="muted" style="font-size:14px;margin:4px 0 10px"><b>Equity vs ranges</b> = what you could know at the table. <b>Equity vs actual</b> = hindsight vs their real cards. Orange line = equity needed to call.</p>
    ${an && an.decisions.length ? an.decisions.map(decisionHTML).join("") : `<div class="muted">You made no decisions this hand (blinds only, or everyone folded to you).</div>`}
    <div class="row" style="margin-top:14px">
      <button id="m-copy">Copy for AI review</button>
      <a href="#hand/${rec.id}"><button>Open full replay</button></a>
      <span class="spacer"></span>
      <button class="ghost" id="m-close">Close</button>
      ${T.cur && T.cur.hand_over && !T.cur.busted ? `<button class="primary" id="m-next">Next hand</button>` : ""}
    </div>`;
  $("#m-copy").onclick = () => copy(aiPrompt(h), "Copied. Paste it into Claude for a full review.");
  $("#m-close").onclick = closeAnalysis;
  if ($("#m-next")) $("#m-next").onclick = () => { closeAnalysis(false); nextHand(); };
  $$("a", bg).forEach(a => a.addEventListener("click", closeAnalysis));
}

/* ------------------------------------------------------------------ hand review / replayer */
function describe(a, nm) {
  const n = a.seat != null ? nm[a.seat] : "";
  const ai = a.allin ? " (all-in)" : "";
  switch (a.type) {
    case "post_sb": return `${n} posts SB ${fmt(a.amount)}`;
    case "post_bb": return `${n} posts BB ${fmt(a.amount)}`;
    case "fold": return `${n} folds`;
    case "check": return `${n} checks`;
    case "call": return `${n} calls ${fmt(a.amount)}${ai}`;
    case "bet": return `${n} bets ${fmt(a.to)}${ai}`;
    case "raise": return `${n} raises to ${fmt(a.to)}${ai}`;
    case "uncalled": return `${fmt(a.amount)} returned to ${n}`;
    case "collect": return `${n} wins ${fmt(a.amount)}`;
    case "deal": return a.board.length === 3 ? "FLOP" : a.board.length === 4 ? "TURN" : "RIVER";
  }
  return a.type;
}

function buildReplay(rec) {
  const seats = rec.seats.map(s => ({
    seat: s.seat, name: s.name, is_hero: s.is_hero, stack: s.start_stack, bet: 0, folded: false, all_in: false,
    hole: s.hole_str, position: s.position, last: null, won: 0, label: s.archetype_label, in_hand: true, desc: null,
  }));
  const by = Object.fromEntries(seats.map(s => [s.seat, s]));
  let board = [], invested = 0, collected = 0, street = "preflop";
  const states = [];
  rec.actions.forEach((a, k) => {
    const s = a.seat != null ? by[a.seat] : null;
    let put = 0;
    if (["post_sb", "post_bb", "call"].includes(a.type)) put = a.amount;
    if (["bet", "raise"].includes(a.type)) put = a.put != null ? a.put : (a.to - (a.to - (a.raise_by || a.to)));
    if (put) { s.stack -= put; s.bet += put; invested += put; s.last = a.type; if (s.stack === 0) s.all_in = true; }
    if (a.type === "fold") { s.folded = true; s.last = "fold"; }
    if (a.type === "check") s.last = "check";
    if (a.type === "uncalled") { s.stack += a.amount; s.bet -= a.amount; invested -= a.amount; if (s.stack > 0) s.all_in = false; }
    if (a.type === "deal") {
      board = a.board.map(cstr); street = ["", "", "", "flop", "turn", "river"][board.length];
      seats.forEach(x => { x.bet = 0; if (!x.folded) x.last = null; });
    }
    if (a.type === "collect") {
      seats.forEach(x => { x.bet = 0; });
      s.stack += a.amount; s.won += a.amount; collected += a.amount;
      if (rec.showdown) seats.forEach(x => { x.desc = rec.descriptions[x.seat] || null; });
    }
    let nextActor = null;
    for (let j = k + 1; j < rec.actions.length; j++) {
      const b = rec.actions[j];
      if (["fold", "check", "call", "bet", "raise"].includes(b.type)) { nextActor = b.seat; break; }
      if (b.type === "deal" || b.type === "collect" || b.type === "uncalled") break;
    }
    states.push({
      k, street, text: describe(a, Object.fromEntries(rec.seats.map(x => [x.seat, x.name]))), type: a.type, seat: a.seat,
      board: [...board], pot: invested - collected, button: rec.button_seat, to_act: nextActor,
      seats: seats.map(x => ({ ...x })),
    });
  });
  return states;
}

async function showHand(id) {
  const h = await api("/api/hand/" + id);
  const rec = h.record, an = h.analysis;
  const states = buildReplay(rec);
  const hero = rec.seats.find(s => s.is_hero);
  const decByIdx = Object.fromEntries((an ? an.decisions : []).map(d => [d.i, d]));
  const firstStep = Math.max(0, rec.actions.findIndex(a => !["post_sb", "post_bb"].includes(a.type)) - 1);
  let step = firstStep;
  let showAll = store.get("review_showall", true);
  const nm = Object.fromEntries(rec.seats.map(s => [s.seat, s.name]));

  view.innerHTML = `
  <div class="row" style="margin-bottom:10px">
    <a href="#hands">← Hands</a>
    <h1 style="margin:0 8px">Hand #${rec.id}</h1>
    <span class="muted">${esc(rec.table_name)} · $${rec.sb}/$${rec.bb} · ${new Date(rec.ts).toLocaleString()} · you: ${hero.position} ${miniCards(rec.hero_cards)}</span>
    <span class="spacer"></span>
    <b class="num ${cls(rec.hero_net)}" style="font-size:18px">${sfmt(rec.hero_net)}</b>
    <button ${h.prev_id ? "" : "disabled"} id="prevh">← Prev</button><button ${h.next_id ? "" : "disabled"} id="nexth">Next →</button>
  </div>
  <div class="review">
    <div>
      <div id="rfelt"></div>
      <div class="panel">
        <div class="steps">
          <button id="s-first">⏮</button><button id="s-prev">◀ Back</button><button id="s-next" class="primary">Next ▶</button><button id="s-last">⏭</button>
          <button data-street="flop">Flop</button><button data-street="turn">Turn</button><button data-street="river">River</button>
          <span class="spacer"></span>
          <label class="muted"><input type="checkbox" id="showall" ${showAll ? "checked" : ""}> Show all hole cards</label>
        </div>
        <div class="muted" id="steptext" style="margin-bottom:6px"></div>
        <div class="actlist" id="actlist"></div>
      </div>
    </div>
    <div>
      ${allinHTML(an)}
      <div class="panel" style="margin-bottom:12px">
        <div class="row"><h3 style="margin:0">Your decisions</h3><span class="spacer"></span>
          <button id="copyai">Copy for AI review</button><button id="copyhh">Copy hand text</button></div>
        <p class="muted" style="font-size:14px;margin:6px 0 10px">
          <b>Equity vs ranges</b> = your share of the pot against the hands opponents likely hold given their actions (what you could know at the table).
          <b>Equity vs actual</b> = against their real cards (hindsight only). The orange line is the equity you needed to call.</p>
        <div id="decs">${an ? an.decisions.map(decisionHTML).join("") : `<div class="muted">Analysis is still running. Refresh in a moment.</div>`}</div>
      </div>
      <details class="panel"><summary>PokerStars hand history</summary><pre class="hh">${esc(h.hh)}</pre></details>
    </div>
  </div>`;

  const actEl = $("#actlist");
  let html = "", lastStreet = null;
  rec.actions.forEach((a, k) => {
    const st = states[k].street;
    if (a.type === "deal") { html += `<div class="street" data-k="${k}">── ${describe(a, nm)} ${miniCards(a.board.map(cstr).join(" "))}</div>`; return; }
    if (lastStreet === null) { html += `<div class="street">── PREFLOP</div>`; lastStreet = "preflop"; }
    const d = decByIdx[k];
    const isHero = a.seat === rec.hero_seat;
    html += `<div data-k="${k}" class="${isHero ? "hero" : ""}">${esc(describe(a, nm))}${d ? ` ${verdictBadge(d)}` : ""}</div>`;
  });
  actEl.innerHTML = html;

  const draw = () => {
    const s = states[step];
    const st = { ...s, seats: s.seats.map(x => ({ ...x })) };
    const atEnd = step === states.length - 1 || states.slice(step + 1).every(x => x.type === "collect");
    st.seats.forEach(x => {
      if (!showAll && !x.is_hero && !(rec.showdown && atEnd && !x.folded)) x.hole = null;
      x.in_hand = true;
    });
    renderFelt($("#rfelt"), st, { labels: true, showFolded: showAll });
    $$("#actlist div[data-k]").forEach(d => d.classList.toggle("cur", +d.dataset.k === step));
    const cur = $(`#actlist div[data-k="${step}"]`);
    if (cur) cur.scrollIntoView({ block: "nearest" });
    const nextHeroDec = decByIdx[step + 1];
    $("#steptext").innerHTML = nextHeroDec ? `<b style="color:var(--gold2)">Your decision next:</b> you chose to <b>${nextHeroDec.action}</b>. See analysis on the right.` : `Step ${step + 1} / ${states.length}: ${esc(s.text)}`;
    $$(".decision").forEach(d => d.classList.toggle("cur", +d.dataset.i === step + 1 || +d.dataset.i === step));
  };
  const go = k => { step = Math.max(0, Math.min(states.length - 1, k)); draw(); };
  $("#s-first").onclick = () => go(firstStep);
  $("#s-prev").onclick = () => go(step - 1);
  $("#s-next").onclick = () => go(step + 1);
  $("#s-last").onclick = () => go(states.length - 1);
  $$("[data-street]").forEach(b => b.onclick = () => {
    const k = states.findIndex(s => s.type === "deal" && s.street === b.dataset.street);
    if (k >= 0) go(k); else toast("No " + b.dataset.street + " in this hand");
  });
  $$("#actlist div[data-k]").forEach(d => d.onclick = () => go(+d.dataset.k));
  $$(".decision").forEach(d => d.onclick = () => go(+d.dataset.i - 1));
  $("#showall").onchange = e => { showAll = e.target.checked; store.set("review_showall", showAll); draw(); };
  $("#prevh").onclick = () => location.hash = "#hand/" + h.prev_id;
  $("#nexth").onclick = () => location.hash = "#hand/" + h.next_id;
  $("#copyhh").onclick = () => copy(h.hh, "Hand history copied");
  $("#copyai").onclick = () => copy(aiPrompt(h), "Copied. Paste it into Claude for a full review.");
  const onKey = e => {
    if (e.target.tagName === "INPUT") return;
    if (e.key === "ArrowRight") go(step + 1);
    else if (e.key === "ArrowLeft") go(step - 1);
  };
  document.addEventListener("keydown", onKey);
  cleanup = () => document.removeEventListener("keydown", onKey);
  draw();
}

function eqRow(label, v, need, kind) {
  return `<div class="eqrow"><span class="muted">${label}</span>
    <div class="eqbar"><div class="fill ${kind}" style="width:${Math.round(v * 100)}%"></div>${need ? `<div class="need" style="left:${need * 100}%"></div>` : ""}</div>
    <span class="num">${pct(v)}</span></div>`;
}

function aiPrompt(h) {
  const rec = h.record, an = h.analysis;
  const villains = rec.seats.filter(s => !s.is_hero).map(s => `- ${s.name} (${s.position}): ${s.archetype_label}`).join("\n");
  const decs = an ? an.decisions.map(d => `- ${d.street} (${d.board || "no board"}): I ${d.action}${d.amount ? " " + fmt(d.amount) : ""}; pot ${fmt(d.pot)}, to call ${fmt(d.to_call)}, needed ${pct(d.req)}; my equity vs estimated ranges ${pct(d.eq_range)}, vs actual cards ${pct(d.eq_actual)}${d.flags.length ? "; auto-flags: " + d.flags.map(f => f.text).join(" ") : ""}`).join("\n") : "";
  return `Please review this ${rec.max_seats || rec.seats.length}-handed No-Limit Hold'em cash hand I played ($${rec.sb}/$${rec.bb}, everyone started with 100 big blinds). I am "${rec.seats.find(s => s.is_hero).name}".
Go street by street: what was good, what was a mistake, what a strong player would do instead and why (ranges, sizing, position). Be concise.

${h.hh}
Opponent player types (from the app):
${villains}

My decisions with equity numbers from the app:
${decs}
${an && an.allin ? `\nAll-in: my equity was ${pct(an.allin.equity)}; expected result ${sfmt(an.allin.ev_net)}, actual ${sfmt(an.allin.actual_net)}.` : ""}`;
}

async function copy(text, msg) {
  try { await navigator.clipboard.writeText(text); toast(msg); }
  catch (e) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast(msg); } catch (e2) { toast("Copy failed"); }
    ta.remove();
  }
}

/* ------------------------------------------------------------------ stats */
const REFS = {
  vpip: "solid reg: 22–28%", pfr: "18–24%", three_bet: "6–10%", af: "2–4", wtsd: "25–31%", wsd: "50–56%",
  cbet: "50–70%", fold_to_cbet: "35–50%",
};
async function showStats(params) {
  const sessions = await api("/api/sessions");
  view.innerHTML = `
  <div class="row"><h1 style="margin:0">Stats</h1><span class="spacer"></span>
    <a id="st-ai" href="/api/export/ai_pack.zip"><button class="primary">⬇ Export for AI analysis (.zip)</button></a>
    <select id="s-stakes"><option value="">All stakes</option>${["1k", "5k", "25k", "100k"].map(s => `<option value="${s}">$${s.toUpperCase()}</option>`).join("")}</select>
    <select id="s-session"><option value="">All sessions</option>${sessions.map(s => `<option value="${s.id}">${esc(s.table_name)} · ${new Date(s.started).toLocaleDateString()}</option>`).join("")}</select>
  </div>
  <div id="sbody" style="margin-top:14px"><div class="empty">Loading…</div></div>`;
  if (params.get("stakes")) $("#s-stakes").value = params.get("stakes");
  if (params.get("session")) $("#s-session").value = params.get("session");
  const load = async () => {
    const p = new URLSearchParams();
    if ($("#s-stakes").value) p.set("stakes", $("#s-stakes").value);
    if ($("#s-session").value) p.set("session", $("#s-session").value);
    history.replaceState(null, "", "#stats" + (p.toString() ? "?" + p : ""));
    $("#st-ai").href = "/api/export/ai_pack.zip?" + p;
    const s = await api("/api/stats?" + p);
    const o = s.overall, el = $("#sbody");
    if (!o.hands) { el.innerHTML = `<div class="panel empty">No hands yet. Go play some.</div>`; return; }
    const kpi = (k, v, ref, c = "") => `<div class="kpi"><div class="k">${k}</div><div class="v ${c}">${v ?? "—"}</div><div class="ref">${ref || "&nbsp;"}</div></div>`;
    const pc = v => v == null ? "—" : v + "%";
    el.innerHTML = `
    <div class="grid kpis">
      ${kpi("Hands", o.hands.toLocaleString())}
      ${kpi("Net won", sfmt(o.net), "", cls(o.net))}
      ${kpi("Win rate", o.bb100 == null ? "—" : o.bb100.toFixed(1) + `<small style="font-size:12px"> bb/100</small>`, "big blinds won per 100 hands", cls(o.bb100))}
      ${kpi("VPIP", pc(o.vpip), "voluntarily put $ in · " + REFS.vpip)}
      ${kpi("PFR", pc(o.pfr), "preflop raise · " + REFS.pfr)}
      ${kpi("3-bet", pc(o.three_bet), REFS.three_bet)}
      ${kpi("AF", o.af ?? "—", "aggression factor · " + REFS.af)}
      ${kpi("WTSD", pc(o.wtsd), "went to showdown · " + REFS.wtsd)}
      ${kpi("W$SD", pc(o.wsd), "won $ at showdown · " + REFS.wsd)}
      ${kpi("C-bet", pc(o.cbet), "continuation bet · " + REFS.cbet)}
      ${kpi("Fold to c-bet", pc(o.fold_to_cbet), REFS.fold_to_cbet)}
      ${kpi("Flagged mistakes", o.mistakes, s.pending_analysis ? `${s.pending_analysis} hands still analyzing` : `<a href="#hands?flagged=1">review them →</a>`, o.mistakes ? "neg" : "")}
    </div>
    <div class="panel chart" style="margin-bottom:16px"><div class="row"><h3 style="margin:0">Results over time</h3><span class="spacer"></span><span class="muted" style="font-size:14px">Click the chart to open that hand</span></div><div id="chart"></div></div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(380px,1fr))">
      <div class="panel"><h3>By position</h3>${statTable(s.by_position)}</div>
      <div class="panel"><h3>By stakes</h3>${statTable(Object.fromEntries(Object.entries(s.by_stakes).map(([k, v]) => ["$" + k.toUpperCase(), v])))}</div>
    </div>`;
    const sr = s.series;
    lineChart($("#chart"), [
      { name: "Net won", color: "#4cc38a", pts: [[0, 0], ...sr.map(r => [r[0], r[1]])] },
      { name: "All-in adjusted (EV)", color: "#d9b45a", dash: "5 4", pts: [[0, 0], ...sr.map(r => [r[0], r[2]])] },
      { name: "Showdown", color: "#6fa8ff", pts: [[0, 0], ...sr.map(r => [r[0], r[3]])], off: true },
      { name: "Non-showdown", color: "#ef6b6b", pts: [[0, 0], ...sr.map(r => [r[0], r[4]])], off: true },
    ], { height: 300, xLabel: "hands", money: true, onClick: i => { const r = sr[Math.round(i) - 1]; if (r) location.hash = "#hand/" + r[5]; } });
  };
  $("#s-stakes").onchange = load; $("#s-session").onchange = load;
  await load();
}
function statTable(m) {
  const keys = Object.keys(m);
  if (!keys.length) return `<div class="muted">—</div>`;
  return `<table class="list"><tr><th></th><th>Hands</th><th>Net</th><th>bb/100</th><th>VPIP</th><th>PFR</th><th>WTSD</th></tr>
    ${keys.map(k => { const r = m[k]; return `<tr><td><b>${k}</b></td><td class="num">${r.hands}</td><td class="num ${cls(r.net)}">${sfmt(r.net)}</td>
    <td class="num ${cls(r.bb100)}">${r.bb100}</td><td class="num">${r.vpip ?? "—"}%</td><td class="num">${r.pfr ?? "—"}%</td><td class="num">${r.wtsd ?? "—"}${r.wtsd == null ? "" : "%"}</td></tr>`; }).join("")}</table>`;
}

/* ------------------------------------------------------------------ tiny SVG line chart */
function lineChart(el, series, opt = {}) {
  const W = 900, H = opt.height || 280, P = { l: 64, r: 14, t: 12, b: 26 };
  const draw = () => {
    const vis = series.filter(s => !s.off && s.pts.length);
    const all = vis.flatMap(s => s.pts);
    if (!all.length) { el.innerHTML = `<div class="empty">No data yet</div>`; return; }
    let x0 = Math.min(...all.map(p => p[0])), x1 = Math.max(...all.map(p => p[0]));
    let y0 = Math.min(0, ...all.map(p => p[1])), y1 = Math.max(0, ...all.map(p => p[1]));
    if (x1 === x0) x1 = x0 + 1; if (y1 === y0) y1 = y0 + 1;
    const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
    const X = x => P.l + (x - x0) / (x1 - x0) * (W - P.l - P.r);
    const Y = y => H - P.b - (y - y0) / (y1 - y0) * (H - P.t - P.b);
    const ticks = 5; let g = "";
    for (let i = 0; i <= ticks; i++) {
      const v = y0 + (y1 - y0) * i / ticks;
      g += `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="#ffffff10"/>
        <text x="${P.l - 8}" y="${Y(v) + 4}" fill="#8f9b97" font-size="13" text-anchor="end">${opt.money ? fmt(v) : Math.round(v)}</text>`;
    }
    g += `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="#ffffff30"/>`;
    g += `<text x="${W - P.r}" y="${H - 6}" fill="#8f9b97" font-size="13" text-anchor="end">${opt.xLabel || ""} → ${Math.round(x1)}</text>`;
    const step = Math.max(1, Math.floor(all.length / vis.length / 1500));
    const lines = vis.map(s => {
      const d = s.pts.filter((p, i) => i % step === 0 || i === s.pts.length - 1).map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join("");
      return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round"/>`;
    }).join("");
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px">${g}${lines}
      <line id="hov" y1="${P.t}" y2="${H - P.b}" stroke="#ffffff40" visibility="hidden"/></svg>
      <div class="muted num" id="hovtxt" style="font-size:14px;min-height:16px"></div>
      ${series.length > 1 ? `<div class="legend">${series.map((s, i) => `<label><input type="checkbox" data-s="${i}" ${s.off ? "" : "checked"}><span class="sw" style="background:${s.color}"></span>${s.name}</label>`).join("")}</div>` : ""}`;
    const svg = $("svg", el);
    const toX = e => { const r = svg.getBoundingClientRect(); const px = (e.clientX - r.left) / r.width * W; return x0 + (px - P.l) / (W - P.l - P.r) * (x1 - x0); };
    svg.onmousemove = e => {
      const x = Math.max(x0, Math.min(x1, toX(e)));
      const hv = $("#hov", el); hv.setAttribute("x1", X(x)); hv.setAttribute("x2", X(x)); hv.setAttribute("visibility", "visible");
      $("#hovtxt", el).innerHTML = `${opt.xLabel || ""} ${Math.round(x)}: ` + vis.map(s => {
        const p = s.pts.reduce((a, b) => Math.abs(b[0] - x) < Math.abs(a[0] - x) ? b : a);
        return `<span style="color:${s.color}">${s.name} ${opt.money ? fmt(p[1]) : p[1]}</span>`;
      }).join(" · ");
    };
    if (opt.onClick) { svg.style.cursor = "pointer"; svg.onclick = e => opt.onClick(toX(e)); }
    $$("[data-s]", el).forEach(c => c.onchange = () => { series[+c.dataset.s].off = !c.checked; draw(); });
  };
  draw();
}

route();
