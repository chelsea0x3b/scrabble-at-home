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
    return `
      <a class="game-row ${g.status}" href="/game/${encodeURIComponent(g.id)}">
        <div>
          <div class="game-name">${esc(g.name)}</div>
          <div class="muted small">${STATUS_LABELS[g.status]}${detail} · ${g.players.map(esc).join(", ") || "no players"}</div>
        </div>
        <span class="btn ${action === "Your turn!" || action === "Join" ? "primary" : ""}">${action}</span>
      </a>`;
  }).join("");
}

document.getElementById("new-game").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("game-name").value;
  const local = document.getElementById("local-toggle").checked;
  const players = [...document.querySelectorAll(".player-name")].map((el) => el.value.trim()).filter(Boolean);
  try {
    const { id } = await api("/api/games", local ? { name, local, players } : { name });
    location.href = `/game/${encodeURIComponent(id)}`;
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("local-toggle").addEventListener("change", (e) => {
  document.getElementById("local-names").hidden = !e.target.checked;
});

loadGames();
setInterval(() => loadGames().catch(() => {}), 4000);
