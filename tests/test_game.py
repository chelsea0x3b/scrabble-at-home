"""Game-flow tests (exchange, end game) and the HTTP preview endpoint."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as server  # noqa: E402
from dictionary import Dictionary  # noqa: E402
from scrabble import Game, GameError  # noqa: E402

DICT = Dictionary()


def started_game(*names):
    game = Game("test", names[0])
    for n in names[1:]:
        game.add_player(n)
    for n in names:
        game.set_ready(n, True)
    game.turn = 0  # deterministic: first player listed goes first
    return game


class LobbyFlow(unittest.TestCase):
    def test_starts_only_when_two_or_more_players_all_ready(self):
        game = Game("t", "A")
        game.set_ready("A", True)
        self.assertEqual(game.status, "pending", "one player can't start a game")
        game.add_player("B")
        self.assertEqual(game.status, "pending")
        game.set_ready("B", True)
        self.assertEqual(game.status, "active")
        self.assertEqual([len(p["rack"]) for p in game.players], [7, 7])
        self.assertEqual(len(game.bag), 100 - 14)

    def test_max_four_players(self):
        game = Game("t", "A")
        for n in "BCD":
            game.add_player(n)
        with self.assertRaises(GameError):
            game.add_player("E")


class Exchange(unittest.TestCase):
    def test_exchange_swaps_tiles_and_keeps_tile_count(self):
        game = started_game("A", "B")
        game.players[0]["rack"] = list("QQQABCD")  # rigged rack, fine for this test
        before_bag = len(game.bag)
        game.exchange("A", ["Q", "Q"])
        rack = game.players[0]["rack"]
        self.assertEqual(len(rack), 7)
        self.assertEqual(rack[:5], list("QABCD"))
        self.assertEqual(len(game.bag), before_bag)
        self.assertEqual(game.turn, 1, "exchanging ends your turn")
        self.assertEqual(game.players[0]["score"], 0)

    def test_cannot_exchange_tiles_you_dont_have(self):
        game = started_game("A", "B")
        game.players[0]["rack"] = list("ABCDEFG")
        with self.assertRaises(GameError):
            game.exchange("A", ["Z"])

    def test_cannot_exchange_with_fewer_than_seven_in_bag(self):
        game = started_game("A", "B")
        game.bag = game.bag[:6]
        with self.assertRaises(GameError):
            game.exchange("A", [game.players[0]["rack"][0]])

    def test_cannot_exchange_out_of_turn(self):
        game = started_game("A", "B")
        with self.assertRaises(GameError):
            game.exchange("B", [game.players[1]["rack"][0]])


class EndGame(unittest.TestCase):
    def test_going_out_collects_opponents_tiles(self):
        game = started_game("A", "B", "C")
        game.bag = []
        game.players[0]["rack"] = list("QI")
        game.players[1]["rack"] = list("ZE")  # 11 points
        game.players[2]["rack"] = list("K")   # 5 points
        game.play("A", [{"r": 7, "c": 7, "l": "Q"}, {"r": 7, "c": 8, "l": "I"}], DICT)
        self.assertEqual(game.status, "finished")
        scores = {p["name"]: p["score"] for p in game.players}
        # A: QI = 22, +11 +5 from opponents' racks
        self.assertEqual(scores, {"A": 38, "B": -11, "C": -5})
        self.assertEqual(game.winners, ["A"])

    def test_emptying_rack_while_bag_has_tiles_refills_and_continues(self):
        game = started_game("A", "B")
        game.players[0]["rack"] = list("QI")
        game.play("A", [{"r": 7, "c": 7, "l": "Q"}, {"r": 7, "c": 8, "l": "I"}], DICT)
        self.assertEqual(game.status, "active")
        self.assertEqual(len(game.players[0]["rack"]), 7)

    def test_six_scoreless_turns_ends_game_with_rack_penalties(self):
        game = started_game("A", "B")
        game.players[0]["rack"] = list("QAAAAAA")  # 16
        game.players[1]["rack"] = list("EEEEEEE")  # 7
        for _ in range(5):
            game.pass_turn(game.players[game.turn]["name"])
        self.assertEqual(game.status, "active")
        game.pass_turn(game.players[game.turn]["name"])
        self.assertEqual(game.status, "finished")
        scores = {p["name"]: p["score"] for p in game.players}
        self.assertEqual(scores, {"A": -16, "B": -7})
        self.assertEqual(game.winners, ["B"])

    def test_scoring_play_resets_scoreless_counter(self):
        game = started_game("A", "B")
        for _ in range(5):
            game.pass_turn(game.players[game.turn]["name"])
        current = game.players[game.turn]
        current["rack"] = list("QIABCDE")
        game.play(current["name"], [{"r": 7, "c": 7, "l": "Q"}, {"r": 7, "c": 8, "l": "I"}], DICT)
        self.assertEqual(game.scoreless_turns, 0)
        game.pass_turn(game.players[game.turn]["name"])
        self.assertEqual(game.status, "active")

    def test_tie(self):
        game = started_game("A", "B")
        game.players[0]["rack"] = list("E")
        game.players[1]["rack"] = list("A")
        for _ in range(6):
            game.pass_turn(game.players[game.turn]["name"])
        self.assertEqual(sorted(game.winners), ["A", "B"])


class PreviewEndpoint(unittest.TestCase):
    """The live word check used by the client while placing tiles."""

    def setUp(self):
        server.app.config["PASSWORD"] = "pw"
        server.app.secret_key = "test"
        server.dictionary = DICT
        server.games.clear()

        self.client = server.app.test_client()
        self.client.post("/login", data={"username": "A", "password": "pw"})
        game = started_game("A", "B")
        # HE on the board at row 7.
        game.board[7][7] = {"l": "H", "b": False}
        game.board[7][8] = {"l": "E", "b": False}
        server.games[game.id] = game
        self.url = f"/api/games/{game.id}/preview"

    def preview(self, *placements):
        return self.client.post(self.url, json={"placements": [
            {"r": r, "c": c, "l": l, "b": False} for r, c, l in placements
        ]}).get_json()

    def test_reports_every_word_formed_with_scores(self):
        res = self.preview((8, 7, "A"), (8, 8, "T"))
        self.assertTrue(res["ok"])
        self.assertTrue(res["valid"])
        self.assertEqual(res["score"], 11)
        self.assertEqual(
            [(w["word"], w["score"], w["valid"]) for w in res["words"]],
            [("AT", 3, True), ("HA", 5, True), ("ET", 3, True)],
        )

    def test_flags_each_invalid_word_individually(self):
        res = self.preview((8, 7, "Z"), (8, 8, "A"))
        self.assertTrue(res["ok"])
        self.assertFalse(res["valid"])
        self.assertEqual(
            {w["word"]: w["valid"] for w in res["words"]},
            {"ZA": True, "HZ": False, "EA": False},
        )

    def test_rule_errors_come_back_as_not_ok(self):
        res = self.preview((2, 2, "A"), (2, 3, "T"))
        self.assertFalse(res["ok"])
        self.assertIn("connect", res["error"])

    def test_preview_does_not_change_the_game(self):
        game = next(iter(server.games.values()))
        version = game.version
        self.preview((8, 7, "A"), (8, 8, "T"))
        self.assertEqual(game.version, version)
        self.assertIsNone(game.board[8][7])


if __name__ == "__main__":
    unittest.main()
