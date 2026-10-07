"use strict";

const STATUS_LABELS = { pending: "Waiting for players", active: "In progress", finished: "Finished" };

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
  if (res.status === 401) { location.href = "/login"; throw new Error("logged out"); }
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong");
  return data;
}

async function loadGames() {
  const { games, me } = await api("/api/games");
  const el = document.getElementById("games");
  if (!games.length) {
    el.innerHTML = '<p class="muted">No games yet — start one!</p>';
    return;
  }
  el.innerHTML = games.map((g) => {
    const mine = g.players.includes(me);
    let action = "View";
    if (g.status === "pending") action = mine ? "Open" : (g.players.length < 4 ? "Join" : "View");
    else if (g.status === "active" && g.local) action = g.creator === me ? "Play" : "View";
    else if (g.status === "active" && mine) action = g.turn === me ? "Your turn!" : "Play";
    const detail = (g.local ? " · Pass & play" : "") + (g.status === "active" ? ` · ${esc(g.turn)}'s turn` : "");
    const people = g.players.map((p) =>
      `<span class="player-chip ${p === me ? "me" : ""}">${esc(p)}</span>`
    ).join("");
    return `
      <a class="game-row ${g.status}" href="/game/${encodeURIComponent(g.id)}">
        <div>
          <div class="game-name">${esc(g.name)}</div>
          <div class="muted small">${STATUS_LABELS[g.status]}${detail}</div>
          <div class="player-chips">${people}</div>
        </div>
        <span class="btn ${action === "Your turn!" || action === "Join" ? "primary" : ""}">${action}</span>
      </a>`;
  }).join("");
}

async function newGame(body) {
  try {
    const { id } = await api("/api/games", body);
    location.href = `/game/${encodeURIComponent(id)}`;
  } catch (err) {
    alert(err.message);
  }
}

document.getElementById("new-game").addEventListener("click", () => newGame({}));
document.getElementById("new-local").addEventListener("click", () => newGame({ local: true }));

loadGames();
setInterval(() => loadGames().catch(() => {}), 4000);
