#!/usr/bin/env python3
"""Scrabble at Home — a small Flask server for playing Scrabble with family.

Usage:
    python3 app.py                      # prompts for the shared password
    python3 app.py --password hunter2 --port 8000
"""

import argparse
import getpass
import hashlib
import hmac
import secrets
import socket
import threading
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from waitress import serve

from dictionary import Dictionary
from scrabble import LETTER_VALUES, Game, GameError, evaluate_move, premium_board

app = Flask(__name__)
app.config["PASSWORD"] = None
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.permanent_session_lifetime = 60 * 60 * 24 * 90

lock = threading.Lock()
games = {}
dictionary = None


# ---------- auth ----------

def password_fingerprint():
    # Stored in the session so changing the password on restart logs everyone out.
    return hashlib.sha256(("pw:" + app.config["PASSWORD"]).encode()).hexdigest()[:16]


def current_user():
    if session.get("pw") != password_fingerprint():
        return None
    return session.get("user")


def login_required(api=False):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user():
                if api:
                    return jsonify({"error": "Please log in again."}), 401
                return redirect(url_for("login", next=request.path))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    username = ""
    if request.method == "POST":
        username = " ".join(request.form.get("username", "").split())
        password = request.form.get("password", "")
        if not hmac.compare_digest(password.encode(), app.config["PASSWORD"].encode()):
            error = "Wrong password."
        elif not (1 <= len(username) <= 20):
            error = "Pick a name between 1 and 20 characters."
        else:
            session.clear()
            session.permanent = True
            session["user"] = username
            session["pw"] = password_fingerprint()
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("lobby"))
    return render_template("login.html", error=error, username=username)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- pages ----------

@app.route("/")
@login_required()
def lobby():
    return render_template("lobby.html", user=current_user())


@app.route("/game/<game_id>")
@login_required()
def game_page(game_id):
    if game_id not in games:
        return redirect(url_for("lobby"))
    return render_template(
        "game.html",
        user=current_user(),
        game_id=game_id,
        premiums=premium_board(),
        letter_values=LETTER_VALUES,
        two_letter_words=dictionary.two_letter_words,
    )


# ---------- API ----------

def get_game(game_id):
    game = games.get(game_id)
    if not game:
        raise GameError("That game no longer exists.")
    return game


@app.errorhandler(GameError)
def handle_game_error(e):
    return jsonify({"error": str(e)}), 400


@app.route("/api/games", methods=["GET"])
@login_required(api=True)
def list_games():
    with lock:
        items = sorted(games.values(), key=lambda g: g.updated_at, reverse=True)
        return jsonify({"games": [g.summary() for g in items], "me": current_user()})


@app.route("/api/games", methods=["POST"])
@login_required(api=True)
def create_game():
    name = " ".join((request.get_json(silent=True) or {}).get("name", "").split())[:40]
    user = current_user()
    with lock:
        game = Game(name or f"{user}'s game", user)
        games[game.id] = game
    return jsonify({"id": game.id})


@app.route("/api/games/<game_id>", methods=["GET"])
@login_required(api=True)
def game_state(game_id):
    with lock:
        game = get_game(game_id)
        since = request.args.get("since", type=int)
        if since is not None and since == game.version:
            return jsonify({"unchanged": True, "version": game.version})
        return jsonify(game.view(current_user()))


def game_action(fn):
    """Run fn(game, user, body) under the lock and return the new state."""
    def handler(game_id):
        body = request.get_json(silent=True) or {}
        with lock:
            game = get_game(game_id)
            extra = fn(game, current_user(), body)
            state = game.view(current_user())
        if extra:
            state["result"] = extra
        return jsonify(state)
    return handler


def route(path, fn):
    endpoint = "game_" + path.rsplit("/", 1)[-1]
    app.add_url_rule(path, endpoint, login_required(api=True)(game_action(fn)), methods=["POST"])


route("/api/games/<game_id>/join", lambda g, u, b: g.add_player(u))
route("/api/games/<game_id>/leave", lambda g, u, b: g.remove_player(u))
route("/api/games/<game_id>/ready", lambda g, u, b: g.set_ready(u, b.get("ready", True)))
route("/api/games/<game_id>/play", lambda g, u, b: g.play(u, parse_placements(b), dictionary))
route("/api/games/<game_id>/exchange", lambda g, u, b: g.exchange(u, list(b.get("tiles", []))))
route("/api/games/<game_id>/pass", lambda g, u, b: g.pass_turn(u))


def parse_placements(body):
    try:
        return [
            {"r": int(p["r"]), "c": int(p["c"]), "l": str(p["l"]), "b": bool(p.get("b"))}
            for p in body.get("placements", [])
        ]
    except (KeyError, TypeError, ValueError):
        raise GameError("Bad move data.")


@app.route("/api/games/<game_id>/preview", methods=["POST"])
@login_required(api=True)
def preview(game_id):
    """Score a tentative move and check its words without committing it."""
    placements = parse_placements(request.get_json(silent=True) or {})
    with lock:
        game = get_game(game_id)
        board = [row[:] for row in game.board]
    try:
        result = evaluate_move(board, placements)
        words = [{**w, "valid": dictionary.is_valid(w["word"])} for w in result["words"]]
        return jsonify({
            "ok": True,
            "valid": all(w["valid"] for w in words),
            "score": result["score"],
            "bingo": result["bingo"],
            "words": words,
        })
    except GameError as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/games/<game_id>/delete", methods=["POST"])
@login_required(api=True)
def delete_game(game_id):
    with lock:
        game = get_game(game_id)
        if game.creator != current_user():
            raise GameError("Only the person who created the game can delete it.")
        if game.status == "active":
            raise GameError("You can't delete a game in progress.")
        del games[game_id]
    return jsonify({"ok": True})


# ---------- CLI ----------

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main():
    global dictionary
    parser = argparse.ArgumentParser(description="Host a Scrabble game for your family.")
    parser.add_argument("--password", help="Shared password everyone uses to log in (prompted if omitted)")
    parser.add_argument("--host", default="0.0.0.0", help="Interface to listen on (default: all)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    args = parser.parse_args()

    password = args.password
    while not password:
        password = getpass.getpass("Set the game password: ").strip()

    app.config["PASSWORD"] = password
    # A fresh key each run: restarting the server logs everyone out (games are in memory only).
    app.secret_key = secrets.token_hex(32)
    dictionary = Dictionary()

    print(f"Loaded {len(dictionary):,} words (TWL06).")
    print(f"Scrabble at Home is running:")
    print(f"  This computer:  http://localhost:{args.port}")
    print(f"  Your network:   http://{lan_ip()}:{args.port}")
    serve(app, host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
