"use strict";

const SIZE = 15;
const PREMIUM_LABELS = { TW: "TRIPLE WORD", DW: "DOUBLE WORD", TL: "TRIPLE LETTER", DL: "DOUBLE LETTER", ST: "★" };

let state = null;          // latest state from the server
let rack = [];             // local rack order: [{id, letter}]
let nextTileId = 1;
const placed = new Map();  // "r,c" -> {id, letter, blank}
let selectedId = null;
let exchangeMode = false;
const exchangeSel = new Set();
let previewTimer = null;
let previewValid = null;   // tile-level marker: false when the placement breaks a rule, else null
let previewWords = [];     // [{cells, valid}] from the last preview, framed on the board
let busy = false;
let revealedAt = null;     // pass & play: history length when the current player last showed their tiles

const $ = (id) => document.getElementById(id);

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); throw new Error("logged out"); }
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong");
  return data;
}

const gameUrl = (action) => `/api/games/${encodeURIComponent(window.GAME_ID)}${action ? "/" + action : ""}`;

// ---------- state sync ----------

async function poll() {
  try {
    const since = state ? `?since=${state.version}` : "";
    const data = await api(gameUrl() + since);
    if (!data.unchanged) applyState(data);
  } catch (err) {
    if (err.message === "That game no longer exists.") location.href = "/";
  }
}

function applyState(data) {
  state = data;
  syncRack(data.rack);
  // Drop any tentative tiles whose squares were just taken by someone else.
  for (const [key, t] of placed) {
    const [r, c] = key.split(",").map(Number);
    if (state.board[r][c]) placed.delete(key);
  }
  render();
  schedulePreview();
}

function syncRack(serverRack) {
  const mine = rack.map((t) => t.letter).sort().join("");
  const theirs = [...serverRack].sort().join("");
  if (mine === theirs) return;
  rack = serverRack.map((letter) => ({ id: nextTileId++, letter }));
  placed.clear();
  selectedId = null;
  exchangeSel.clear();
}

const isMyTurn = () => state && state.status === "active" && state.my_index === state.turn_index;
const isPlayer = () => state && state.my_index !== null && state.my_index !== undefined;
const placedIds = () => new Set([...placed.values()].map((t) => t.id));

// ---------- rendering ----------

function render() {
  $("game-title").textContent = state.name;
  const pending = state.status === "pending";
  $("pending-view").hidden = !pending;
  $("play-view").hidden = pending;
  if (pending) renderPending();
  else renderPlay();
  document.title = (isMyTurn() ? "▶ Your turn · " : "") + "Scrabble at Home";
}

function renderPending() {
  const me = state.players.find((p) => p.name === window.ME);
  $("pending-players").innerHTML = state.players.map((p) => `
    <li class="${p.ready ? "ready" : ""}">
      <span>${esc(p.name)}${p.name === state.creator ? ' <span class="muted small">(host)</span>' : ""}</span>
      <span class="${p.ready ? "ok" : "muted"}">${p.ready ? "✔ Ready" : "Not ready"}</span>
    </li>`).join("") + (state.players.length < 4 ? `<li class="muted empty-slot">${4 - state.players.length} open seat${state.players.length === 3 ? "" : "s"}</li>` : "");

  $("join-btn").hidden = !!me || state.players.length >= 4;
  $("ready-btn").hidden = !me;
  $("ready-btn").textContent = me && me.ready ? "Not ready" : "I'm ready";
  $("ready-btn").classList.toggle("primary", !(me && me.ready));
  $("leave-btn").hidden = !me;

  let msg = "";
  if (state.players.length < 2) msg = "Need at least 2 players to start.";
  else if (state.players.every((p) => p.ready)) msg = "Starting…";
  else msg = "Game starts once everyone is ready.";
  $("pending-msg").textContent = msg;
}

function renderPlay() {
  renderScores();
  renderBanner();
  renderBoard();
  renderRack();
  renderHistory();
  renderHandoff();
  $("bag-count").textContent = state.bag_count;

  const active = state.status === "active" && isPlayer();
  document.querySelector(".rack-area").hidden = !isPlayer();
  for (const id of ["submit-btn", "exchange-btn", "pass-btn"]) $(id).disabled = !active || !isMyTurn() || busy;
  $("shuffle-btn").disabled = $("recall-btn").disabled = !active;
  $("exchange-btn").textContent = exchangeMode ? (exchangeSel.size ? `Swap ${exchangeSel.size}` : "Cancel") : "Exchange";
  $("exchange-btn").title = state.can_exchange ? "Swap tiles with the bag" : "Fewer than 7 tiles left in the bag";
  if (!state.can_exchange && !exchangeMode) $("exchange-btn").disabled = true;
  $("submit-btn").hidden = exchangeMode;
  $("pass-btn").hidden = exchangeMode;
}

function renderScores() {
  $("scores").innerHTML = state.players.map((p, i) => {
    const turn = state.status === "active" && i === state.turn_index;
    const winner = state.status === "finished" && state.winners.includes(p.name);
    return `
      <div class="score-card ${turn ? "turn" : ""} ${winner ? "winner" : ""} ${p.name === window.ME && !state.local ? "me" : ""}">
        <div class="score-name">${winner ? "🏆 " : ""}${esc(p.name)}${p.name === window.ME && !state.local ? " (you)" : ""}</div>
        <div class="muted small">${turn ? "playing…" : `${p.tiles} tiles`}</div>
        <div class="score-value">${p.score}</div>
      </div>`;
  }).join("");
}

// Only shown at the end; whose turn it is lives in the score list.
function renderBanner() {
  const b = $("banner");
  b.hidden = state.status !== "finished";
  if (b.hidden) return;
  const w = state.winners;
  b.textContent = w.length === 1 ? `🎉 ${w[0]} wins! 🎉` : `It's a tie: ${w.join(" & ")}!`;
}

// Pass & play: cover the board between turns so nobody sees the next player's tiles.
function renderHandoff() {
  const show = state.local && state.status === "active" && isPlayer() && revealedAt !== state.history.length;
  $("handoff-modal").hidden = !show;
  if (!show) return;
  $("handoff-name").textContent = state.players[state.turn_index].name;
  const last = [...state.history].reverse().find((h) => h.player);
  $("handoff-last").textContent = last
    ? `${last.player} ${last.text}${last.kind === "play" ? ` for ${last.score} points` : ""}.`
    : "";
}

function tileHTML(letter, { blank = false, extra = "", id = null } = {}) {
  const value = blank ? "" : window.LETTER_VALUES[letter] ?? "";
  const shown = letter === "?" ? "" : letter;
  return `<div class="tile ${blank ? "blank" : ""} ${extra}" ${id !== null ? `data-id="${id}"` : ""}>
    <span class="letter">${shown}</span><span class="value">${value}</span></div>`;
}

function renderBoard() {
  const last = new Set(state.last_move.map(([r, c]) => `${r},${c}`));
  let html = "";
  for (let r = 0; r < SIZE; r++) {
    for (let c = 0; c < SIZE; c++) {
      const key = `${r},${c}`;
      const prem = window.PREMIUMS[r][c];
      const cell = state.board[r][c];
      const p = placed.get(key);
      let inner = "";
      if (cell) inner = tileHTML(cell.l, { blank: cell.b, extra: last.has(key) ? "last" : "" });
      else if (p) inner = tileHTML(p.letter, { blank: p.blank, extra: "pending draggable " + validityClass(), id: p.id });
      else if (prem) inner = `<span class="prem-label">${prem === "ST" ? "★" : prem}</span>`;
      html += `<div class="cell ${prem ? "p-" + prem : ""}" data-r="${r}" data-c="${c}" title="${cell || p ? "" : PREMIUM_LABELS[prem] || ""}">${inner}</div>`;
    }
  }
  $("board").innerHTML = html;
  renderFrames();
}

function renderRack() {
  const used = placedIds();
  $("rack").innerHTML = rack.filter((t) => !used.has(t.id)).map((t) => {
    const cls = ["draggable"];
    if (t.id === selectedId) cls.push("selected");
    if (exchangeSel.has(t.id)) cls.push("marked");
    return tileHTML(t.letter, { blank: t.letter === "?", extra: cls.join(" "), id: t.id });
  }).join("");
  $("rack").classList.toggle("exchange-mode", exchangeMode);
}

function renderHistory() {
  const el = $("history");
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
  el.innerHTML = state.history.map((h) => {
    const who = h.player ? `<b>${esc(h.player)}</b> ` : "";
    const score = h.kind === "play" || h.kind === "bonus" || h.kind === "penalty"
      ? `<span class="pts ${h.score < 0 ? "neg" : ""}">${h.score > 0 ? "+" : ""}${h.score}</span>` : "";
    return `<li class="h-${h.kind}"><span>${who}${esc(h.text)}</span>${score}</li>`;
  }).join("");
  if (atBottom) el.scrollTop = el.scrollHeight;
}

function setStatus(msg, kind = "", html = false) {
  const el = $("status");
  el[html ? "innerHTML" : "textContent"] = msg;
  el.className = "status " + kind;
}

function validityClass() {
  return previewValid === null ? "" : previewValid ? "valid" : "invalid";
}

function setPreview(tileState, words = []) {
  previewValid = tileState;
  previewWords = words;
  for (const el of document.querySelectorAll(".board .tile.pending")) {
    el.classList.remove("valid", "invalid");
    if (tileState !== null) el.classList.add(tileState ? "valid" : "invalid");
  }
  renderFrames();
}

// Outline each word the tentative play forms: solid when valid, dashed when not.
function renderFrames() {
  const board = $("board");
  board.querySelectorAll(".word-frame").forEach((el) => el.remove());
  board.insertAdjacentHTML("beforeend", previewWords.map((w) => {
    const rows = w.cells.map(([r]) => r), cols = w.cells.map(([, c]) => c);
    const area = `grid-row: ${Math.min(...rows) + 1} / ${Math.max(...rows) + 2}; grid-column: ${Math.min(...cols) + 1} / ${Math.max(...cols) + 2}`;
    return `<div class="word-frame ${w.valid ? "valid" : "invalid"}" style="${area}"></div>`;
  }).join(""));
}

// ---------- tile moves ----------

function rackTile(id) { return rack.find((t) => t.id === id); }

function findPlacedKey(id) {
  for (const [k, t] of placed) if (t.id === id) return k;
  return null;
}

function chooseBlankLetter() {
  return new Promise((resolve) => {
    const modal = $("blank-modal");
    const letters = $("blank-letters");
    letters.innerHTML = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").map((l) => `<button class="btn letter-btn">${l}</button>`).join("");
    modal.hidden = false;
    const close = (val) => { modal.hidden = true; letters.onclick = null; $("blank-cancel").onclick = null; resolve(val); };
    letters.onclick = (e) => { if (e.target.classList.contains("letter-btn")) close(e.target.textContent); };
    $("blank-cancel").onclick = () => close(null);
  });
}

async function placeTile(id, r, c) {
  if (state.status !== "active" || state.board[r][c] || exchangeMode) return;
  const key = `${r},${c}`;
  if (placed.has(key) && placed.get(key).id !== id) return;
  const fromKey = findPlacedKey(id);
  if (fromKey) {
    // Moving a tile already on the board keeps its letter choice.
    const t = placed.get(fromKey);
    placed.delete(fromKey);
    placed.set(key, t);
  } else {
    const t = rackTile(id);
    if (!t) return;
    let letter = t.letter;
    if (letter === "?") {
      letter = await chooseBlankLetter();
      if (!letter || placed.has(key)) return;
    }
    placed.set(key, { id, letter, blank: t.letter === "?" });
  }
  selectedId = null;
  render();
  schedulePreview();
}

function returnTile(id, beforeId = null) {
  const key = findPlacedKey(id);
  if (key) placed.delete(key);
  if (beforeId !== null && beforeId !== id) {
    const tile = rackTile(id);
    rack = rack.filter((t) => t.id !== id);
    const idx = rack.findIndex((t) => t.id === beforeId);
    rack.splice(idx < 0 ? rack.length : idx, 0, tile);
  }
  selectedId = null;
  render();
  schedulePreview();
}

function recallAll() {
  placed.clear();
  selectedId = null;
  render();
  schedulePreview();
}

function shuffleRack() {
  for (let i = rack.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [rack[i], rack[j]] = [rack[j], rack[i]];
  }
  render();
}

// ---------- preview & actions ----------

function schedulePreview() {
  clearTimeout(previewTimer);
  setPreview(null);
  if (!state || state.status !== "active" || !placed.size) {
    if (state && state.status === "active" && !exchangeMode) setStatus(isMyTurn() ? "Place tiles on the board, then Submit." : `Waiting for ${state.players[state.turn_index].name}…`);
    return;
  }
  previewTimer = setTimeout(async () => {
    try {
      const sent = JSON.stringify(placementList());
      const res = await api(gameUrl("preview"), { placements: placementList() });
      if (!placed.size || JSON.stringify(placementList()) !== sent) return;  // stale
      if (!res.ok) {
        setPreview(false);
        return setStatus(res.error, "warn");
      }
      setPreview(null, res.words);
      const chips = res.words.map((w) =>
        `<span class="word-chip ${w.valid ? "valid" : "invalid"}" title="${w.valid ? "Valid word" : "Not in the dictionary"}">${w.valid ? "✓" : "✗"} ${esc(w.word)} <small>${w.score}</small></span>`
      ).join(" ");
      const summary = res.valid
        ? `<b>${res.score} points</b>${res.bingo ? " — BINGO!" : ""}${isMyTurn() ? "" : " <span class=\"muted\">(not your turn yet)</span>"}`
        : `<b class="bad">Not a valid play</b>`;
      setStatus(`${chips} ${summary}`, "preview", true);
    } catch (_) { /* ignore */ }
  }, 200);
}

function placementList() {
  return [...placed].map(([key, t]) => {
    const [r, c] = key.split(",").map(Number);
    return { r, c, l: t.letter, b: t.blank };
  });
}

async function act(action, body, confirmMsg) {
  if (busy) return;
  if (confirmMsg && !confirm(confirmMsg)) return;
  busy = true;
  render();
  try {
    const data = await api(gameUrl(action), body || {});
    if (action === "play") placed.clear();
    if (action === "exchange") { exchangeMode = false; exchangeSel.clear(); }
    busy = false;
    applyState(data);
    if (action === "play") {
      const r = data.result;
      setStatus(`Nice! +${r.score} points${r.bingo ? " — BINGO!" : ""}`, "ok");
    }
  } catch (err) {
    busy = false;
    render();
    setStatus(err.message, "error");
  }
}

function toggleExchange() {
  if (!exchangeMode) {
    recallAll();
    exchangeMode = true;
    exchangeSel.clear();
    setStatus("Tap the tiles you want to swap, then press Swap.");
    render();
  } else if (exchangeSel.size) {
    const tiles = rack.filter((t) => exchangeSel.has(t.id)).map((t) => t.letter);
    act("exchange", { tiles }, `Swap ${tiles.length} tile(s) and end your turn?`);
  } else {
    exchangeMode = false;
    render();
    schedulePreview();
  }
}

// ---------- pointer interaction (click + drag, mouse & touch) ----------

let drag = null;

function onPointerDown(e) {
  const tile = e.target.closest(".tile.draggable");
  if (!tile || e.button > 0) return;
  drag = { id: Number(tile.dataset.id), el: tile, x: e.clientX, y: e.clientY, ghost: null };
  tile.setPointerCapture?.(e.pointerId);
}

function onPointerMove(e) {
  if (!drag) return;
  if (!drag.ghost) {
    if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6 || exchangeMode || state.status !== "active") return;
    const rect = drag.el.getBoundingClientRect();
    drag.ghost = drag.el.cloneNode(true);
    drag.ghost.classList.add("ghost");
    drag.ghost.style.width = rect.width + "px";
    drag.ghost.style.height = rect.height + "px";
    document.body.appendChild(drag.ghost);
    drag.el.classList.add("dragging");
  }
  drag.ghost.style.left = e.clientX + "px";
  drag.ghost.style.top = e.clientY + "px";
  e.preventDefault();
}

function onPointerUp(e) {
  if (!drag) return;
  const d = drag;
  drag = null;
  if (!d.ghost) return onTileClick(d.id, d.el);
  d.ghost.remove();
  d.el.classList.remove("dragging");
  const target = document.elementFromPoint(e.clientX, e.clientY);
  const cell = target && target.closest(".cell");
  if (cell) return placeTile(d.id, Number(cell.dataset.r), Number(cell.dataset.c));
  const rackTarget = target && target.closest(".rack, .rack-area");
  if (rackTarget) {
    const over = target.closest(".rack .tile");
    return returnTile(d.id, over ? Number(over.dataset.id) : (findPlacedKey(d.id) ? null : -1));
  }
}

function onTileClick(id, el) {
  if (el.closest(".board")) return returnTile(id);
  if (exchangeMode) {
    exchangeSel.has(id) ? exchangeSel.delete(id) : exchangeSel.add(id);
    return render();
  }
  if (selectedId !== null && selectedId !== id) {
    // Tapping a second rack tile swaps the two — handy for rearranging.
    const a = rack.findIndex((t) => t.id === selectedId);
    const b = rack.findIndex((t) => t.id === id);
    if (a >= 0 && b >= 0) [rack[a], rack[b]] = [rack[b], rack[a]];
    selectedId = null;
    return render();
  }
  selectedId = selectedId === id ? null : id;
  render();
}

function onBoardClick(e) {
  const cell = e.target.closest(".cell");
  if (!cell || e.target.closest(".tile.pending")) return;
  if (selectedId !== null) placeTile(selectedId, Number(cell.dataset.r), Number(cell.dataset.c));
}

// ---------- wiring ----------

document.addEventListener("pointerdown", onPointerDown);
document.addEventListener("pointermove", onPointerMove, { passive: false });
document.addEventListener("pointerup", onPointerUp);
document.addEventListener("pointercancel", () => { if (drag?.ghost) { drag.ghost.remove(); drag.el.classList.remove("dragging"); } drag = null; });
$("board").addEventListener("click", onBoardClick);

$("shuffle-btn").onclick = shuffleRack;
$("recall-btn").onclick = () => { exchangeMode = false; exchangeSel.clear(); recallAll(); };
$("submit-btn").onclick = () => {
  if (!placed.size) return setStatus("Place some tiles on the board first.", "warn");
  act("play", { placements: placementList() });
};
$("exchange-btn").onclick = toggleExchange;
$("pass-btn").onclick = () => act("pass", {}, "Pass your turn?");

$("handoff-btn").onclick = () => {
  revealedAt = state.history.length;
  placed.clear();
  selectedId = null;
  render();
  schedulePreview();
};

$("join-btn").onclick = () => act("join");
$("leave-btn").onclick = () => act("leave").then(() => { location.href = "/"; });
$("ready-btn").onclick = () => {
  const me = state.players.find((p) => p.name === window.ME);
  act("ready", { ready: !(me && me.ready) });
};

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { selectedId = null; if (state) render(); }
  if (e.key === "Enter" && isMyTurn() && placed.size && !busy && $("blank-modal").hidden && $("handoff-modal").hidden) $("submit-btn").click();
});

poll();
setInterval(poll, 2000);
