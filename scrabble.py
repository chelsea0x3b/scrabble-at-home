"""Core Scrabble rules: board, tile bag, move validation, scoring, game flow."""

import random
import secrets
import time

SIZE = 15
CENTER = 7
RACK_SIZE = 7
MAX_PLAYERS = 4
MIN_PLAYERS = 2
BINGO_BONUS = 50
MAX_SCORELESS_TURNS = 6

# T = triple word, D = double word, t = triple letter, d = double letter, * = center (double word)
LAYOUT = [
    "T..d...T...d..T",
    ".D...t...t...D.",
    "..D...d.d...D..",
    "d..D...d...D..d",
    "....D.....D....",
    ".t...t...t...t.",
    "..d...d.d...d..",
    "T..d...*...d..T",
    "..d...d.d...d..",
    ".t...t...t...t.",
    "....D.....D....",
    "d..D...d...D..d",
    "..D...d.d...D..",
    ".D...t...t...D.",
    "T..d...T...d..T",
]
PREMIUM_NAMES = {"T": "TW", "D": "DW", "t": "TL", "d": "DL", "*": "ST", ".": ""}

LETTER_VALUES = {
    "A": 1, "B": 3, "C": 3, "D": 2, "E": 1, "F": 4, "G": 2, "H": 4, "I": 1,
    "J": 8, "K": 5, "L": 1, "M": 3, "N": 1, "O": 1, "P": 3, "Q": 10, "R": 1,
    "S": 1, "T": 1, "U": 1, "V": 4, "W": 4, "X": 8, "Y": 4, "Z": 10, "?": 0,
}
DISTRIBUTION = {
    "A": 9, "B": 2, "C": 2, "D": 4, "E": 12, "F": 2, "G": 3, "H": 2, "I": 9,
    "J": 1, "K": 1, "L": 4, "M": 2, "N": 6, "O": 8, "P": 2, "Q": 1, "R": 6,
    "S": 4, "T": 6, "U": 4, "V": 2, "W": 2, "X": 1, "Y": 2, "Z": 1, "?": 2,
}


class GameError(Exception):
    pass


def premium_board():
    return [[PREMIUM_NAMES[ch] for ch in row] for row in LAYOUT]


def new_bag():
    bag = [letter for letter, n in DISTRIBUTION.items() for _ in range(n)]
    random.shuffle(bag)
    return bag


def rack_value(rack):
    return sum(LETTER_VALUES[t] for t in rack)


def evaluate_move(board, placements, dictionary=None):
    """Validate a set of tile placements and score them.

    board: 15x15 grid of None or {"l": letter, "b": is_blank}
    placements: list of {"r", "c", "l", "b"} where l is the letter shown on
    the board and b is True if a blank tile is being used.

    Returns {"words": [{"word", "score"}], "score": total}.
    Raises GameError for illegal moves.
    """
    if not placements:
        raise GameError("Place at least one tile.")
    if len(placements) > RACK_SIZE:
        raise GameError("Too many tiles.")

    new = {}
    for p in placements:
        r, c, letter = p["r"], p["c"], p["l"]
        if not (0 <= r < SIZE and 0 <= c < SIZE):
            raise GameError("Tile placed off the board.")
        if board[r][c] is not None or (r, c) in new:
            raise GameError("That square is already taken.")
        if not (isinstance(letter, str) and len(letter) == 1 and letter.isalpha() and letter.isascii()):
            raise GameError("Invalid letter.")
        new[(r, c)] = {"l": letter.upper(), "b": bool(p.get("b"))}

    def at(r, c):
        if not (0 <= r < SIZE and 0 <= c < SIZE):
            return None
        return new.get((r, c)) or board[r][c]

    rows = {r for r, _ in new}
    cols = {c for _, c in new}
    if len(rows) > 1 and len(cols) > 1:
        raise GameError("Tiles must be in a single row or column.")

    if len(new) > 1:
        horizontal = len(rows) == 1
    else:
        (r, c), = new
        horizontal = bool(at(r, c - 1) or at(r, c + 1))
    dr, dc = (0, 1) if horizontal else (1, 0)

    # No gaps between placed tiles (existing tiles may fill gaps).
    positions = sorted(new)
    (r0, c0), (r1, c1) = positions[0], positions[-1]
    r, c = r0, c0
    while (r, c) != (r1, c1):
        r, c = r + dr, c + dc
        if at(r, c) is None:
            raise GameError("Tiles must form one continuous word.")

    board_empty = all(cell is None for row in board for cell in row)
    if board_empty:
        if (CENTER, CENTER) not in new:
            raise GameError("The first word must cover the center star.")
        if len(new) < 2:
            raise GameError("The first word must be at least two letters.")
    else:
        touches = False
        for (r, c) in new:
            for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if 0 <= nr < SIZE and 0 <= nc < SIZE and board[nr][nc] is not None:
                    touches = True
        if not touches:
            raise GameError("Your word must connect to tiles already on the board.")

    def word_through(r, c, dr, dc):
        while at(r - dr, c - dc):
            r, c = r - dr, c - dc
        cells = []
        while at(r, c):
            cells.append((r, c))
            r, c = r + dr, c + dc
        return cells

    def score_word(cells):
        total, mult = 0, 1
        for (r, c) in cells:
            tile = at(r, c)
            value = 0 if tile["b"] else LETTER_VALUES[tile["l"]]
            if (r, c) in new:
                prem = LAYOUT[r][c]
                if prem == "d":
                    value *= 2
                elif prem == "t":
                    value *= 3
                elif prem in "D*":
                    mult *= 2
                elif prem == "T":
                    mult *= 3
            total += value
        return total * mult

    word_cells = []
    main = word_through(r0, c0, dr, dc)
    if len(main) >= 2:
        word_cells.append(main)
    for (r, c) in positions:
        cross = word_through(r, c, dc, dr)
        if len(cross) >= 2:
            word_cells.append(cross)
    if not word_cells:
        raise GameError("Your tiles must form a word of at least two letters.")

    words = [
        {"word": "".join(at(r, c)["l"] for r, c in cells), "score": score_word(cells)}
        for cells in word_cells
    ]
    if dictionary is not None:
        invalid = [w["word"] for w in words if not dictionary.is_valid(w["word"])]
        if invalid:
            label = "is not a valid word" if len(invalid) == 1 else "are not valid words"
            raise GameError(f"{', '.join(invalid)} {label}.")

    total = sum(w["score"] for w in words)
    bingo = len(new) == RACK_SIZE
    if bingo:
        total += BINGO_BONUS
    return {"words": words, "score": total, "bingo": bingo}


class Game:
    def __init__(self, name, creator):
        self.id = secrets.token_urlsafe(6)
        self.name = name
        self.creator = creator
        self.created_at = time.time()
        self.status = "pending"  # pending -> active -> finished
        self.players = []  # list of {"name", "ready", "score", "rack"}
        self.board = [[None] * SIZE for _ in range(SIZE)]
        self.bag = []
        self.turn = 0
        self.history = []
        self.scoreless_turns = 0
        self.last_move = []
        self.version = 0
        self.updated_at = time.time()
        self.add_player(creator)

    # ---- persistence ----
    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data):
        game = cls.__new__(cls)
        game.__dict__.update(data)
        return game

    def touch(self):
        self.version += 1
        self.updated_at = time.time()

    # ---- lobby ----
    def player(self, name):
        for i, p in enumerate(self.players):
            if p["name"] == name:
                return i, p
        return None, None

    def add_player(self, name):
        if self.status != "pending":
            raise GameError("This game has already started.")
        if self.player(name)[1]:
            return
        if len(self.players) >= MAX_PLAYERS:
            raise GameError("This game is full.")
        self.players.append({"name": name, "ready": False, "score": 0, "rack": []})
        self.touch()

    def remove_player(self, name):
        if self.status != "pending":
            raise GameError("You can't leave a game that has started.")
        i, _ = self.player(name)
        if i is not None:
            self.players.pop(i)
            self.touch()

    def set_ready(self, name, ready):
        if self.status != "pending":
            raise GameError("This game has already started.")
        _, p = self.player(name)
        if not p:
            raise GameError("You're not in this game.")
        p["ready"] = bool(ready)
        self.touch()
        if len(self.players) >= MIN_PLAYERS and all(pl["ready"] for pl in self.players):
            self.start()

    def start(self):
        self.status = "active"
        self.bag = new_bag()
        for p in self.players:
            p["rack"] = self.draw(RACK_SIZE)
        self.turn = random.randrange(len(self.players))
        self.log(None, "start", f"Game started. {self.players[self.turn]['name']} goes first!")
        self.touch()

    # ---- play ----
    def draw(self, n):
        n = min(n, len(self.bag))
        tiles, self.bag = self.bag[:n], self.bag[n:]
        return tiles

    def log(self, player, kind, text, score=0, words=None):
        self.history.append({
            "player": player, "kind": kind, "text": text, "score": score,
            "words": words or [], "t": time.time(),
        })

    def _require_turn(self, name):
        if self.status != "active":
            raise GameError("The game isn't in progress.")
        i, p = self.player(name)
        if p is None:
            raise GameError("You're not playing in this game.")
        if i != self.turn:
            raise GameError(f"It's {self.players[self.turn]['name']}'s turn.")
        return p

    def _advance(self):
        self.turn = (self.turn + 1) % len(self.players)

    def _remove_from_rack(self, rack, tiles):
        remaining = list(rack)
        for t in tiles:
            if t not in remaining:
                raise GameError("Those tiles aren't on your rack.")
            remaining.remove(t)
        return remaining

    def play(self, name, placements, dictionary):
        p = self._require_turn(name)
        result = evaluate_move(self.board, placements, dictionary)
        used = ["?" if pl.get("b") else pl["l"].upper() for pl in placements]
        rack = self._remove_from_rack(p["rack"], used)

        for pl in placements:
            self.board[pl["r"]][pl["c"]] = {"l": pl["l"].upper(), "b": bool(pl.get("b"))}
        self.last_move = [[pl["r"], pl["c"]] for pl in placements]
        p["score"] += result["score"]
        p["rack"] = rack + self.draw(RACK_SIZE - len(rack))
        self.scoreless_turns = 0 if result["score"] > 0 else self.scoreless_turns + 1

        main = result["words"][0]["word"]
        text = f"played {main}"
        if len(result["words"]) > 1:
            text += " (" + ", ".join(w["word"] for w in result["words"][1:]) + ")"
        if result["bingo"]:
            text += " — BINGO!"
        self.log(name, "play", text, result["score"], result["words"])

        if not p["rack"] and not self.bag:
            self._finish(went_out=p)
        else:
            self._advance()
            self._check_scoreless()
        self.touch()
        return result

    def exchange(self, name, tiles):
        p = self._require_turn(name)
        if not tiles:
            raise GameError("Choose at least one tile to exchange.")
        if len(self.bag) < RACK_SIZE:
            raise GameError("You can only exchange when at least 7 tiles are left in the bag.")
        tiles = [t.upper() for t in tiles]
        rack = self._remove_from_rack(p["rack"], tiles)
        drawn = self.draw(len(tiles))
        self.bag.extend(tiles)
        random.shuffle(self.bag)
        p["rack"] = rack + drawn
        self.last_move = []
        self.scoreless_turns += 1
        self.log(name, "exchange", f"exchanged {len(tiles)} tile{'s' if len(tiles) != 1 else ''}")
        self._advance()
        self._check_scoreless()
        self.touch()

    def pass_turn(self, name):
        self._require_turn(name)
        self.last_move = []
        self.scoreless_turns += 1
        self.log(name, "pass", "passed")
        self._advance()
        self._check_scoreless()
        self.touch()

    def _check_scoreless(self):
        if self.status == "active" and self.scoreless_turns >= MAX_SCORELESS_TURNS:
            self.log(None, "info", f"{MAX_SCORELESS_TURNS} scoreless turns in a row.")
            self._finish(went_out=None)

    def _finish(self, went_out):
        self.status = "finished"
        bonus = 0
        for p in self.players:
            if p is went_out:
                continue
            v = rack_value(p["rack"])
            if v:
                p["score"] -= v
                bonus += v
                self.log(p["name"], "penalty", f"loses {v} for tiles left ({''.join(p['rack'])})", -v)
        if went_out is not None and bonus:
            went_out["score"] += bonus
            self.log(went_out["name"], "bonus", f"went out and gains {bonus}", bonus)
        best = max(p["score"] for p in self.players)
        winners = [p["name"] for p in self.players if p["score"] == best]
        if len(winners) == 1:
            self.log(None, "end", f"Game over — {winners[0]} wins with {best}!")
        else:
            self.log(None, "end", f"Game over — tie between {' & '.join(winners)} at {best}!")
        self.winners = winners

    # ---- views ----
    def summary(self):
        return {
            "id": self.id,
            "name": self.name,
            "creator": self.creator,
            "status": self.status,
            "players": [p["name"] for p in self.players],
            "turn": self.players[self.turn]["name"] if self.status == "active" else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def view(self, viewer):
        idx, me = self.player(viewer)
        return {
            **self.summary(),
            "version": self.version,
            "me": viewer,
            "my_index": idx,
            "rack": me["rack"] if me else [],
            "players": [
                {"name": p["name"], "ready": p["ready"], "score": p["score"], "tiles": len(p["rack"])}
                for p in self.players
            ],
            "turn_index": self.turn,
            "board": self.board,
            "bag_count": len(self.bag),
            "history": self.history,
            "last_move": self.last_move,
            "winners": getattr(self, "winners", []),
            "can_exchange": len(self.bag) >= RACK_SIZE,
        }
