"""Scoring and placement-rule tests for evaluate_move.

Premium squares used below (row, col), from scrabble.LAYOUT:
  (7,7) center = DW    (7,3) = DL    (8,8) = DL    (4,4) = DW
  (3,3) = DW           (11,3) = DW   (7,0) = TW    (5,1) = TL
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dictionary import Dictionary  # noqa: E402
from scrabble import SIZE, GameError, evaluate_move  # noqa: E402

DICT = Dictionary()


def board_with(*tiles):
    """tiles: (r, c, letter) or (r, c, letter, is_blank) already on the board."""
    board = [[None] * SIZE for _ in range(SIZE)]
    for t in tiles:
        r, c, letter = t[:3]
        board[r][c] = {"l": letter, "b": len(t) > 3 and t[3]}
    return board


def across(word, r, c, blanks=()):
    return [{"r": r, "c": c + i, "l": ch, "b": i in blanks} for i, ch in enumerate(word)]


def down(word, r, c, blanks=()):
    return [{"r": r + i, "c": c, "l": ch, "b": i in blanks} for i, ch in enumerate(word)]


def tiles(*placements):
    return [{"r": r, "c": c, "l": l, "b": False} for r, c, l in placements]


def words(result):
    return {w["word"]: w["score"] for w in result["words"]}


class FirstMoveScoring(unittest.TestCase):
    def test_center_square_doubles_word(self):
        # C(7,6) A(7,7 DW) T(7,8): (3+1+1) x2
        res = evaluate_move(board_with(), across("CAT", 7, 6))
        self.assertEqual(res["score"], 10)

    def test_letter_and_word_premium_combined(self):
        # H on (7,3) DL = 8, E L L = 3, O on center DW: (8+1+1+1+1) x2
        res = evaluate_move(board_with(), across("HELLO", 7, 3))
        self.assertEqual(res["score"], 24)

    def test_vertical_first_move(self):
        # Q(6,7) I(7,7 DW): (10+1) x2
        res = evaluate_move(board_with(), down("QI", 6, 7))
        self.assertEqual(words(res), {"QI": 22})


class PremiumsOnlyCountForNewTiles(unittest.TestCase):
    def test_extending_word_ignores_used_premium(self):
        # HE already covers the center DW, so HEAT gets no multiplier.
        board = board_with((7, 7, "H"), (7, 8, "E"))
        res = evaluate_move(board, tiles((7, 9, "A"), (7, 10, "T")), DICT)
        self.assertEqual(words(res), {"HEAT": 7})
        self.assertEqual(res["score"], 7)

    def test_filling_a_gap_uses_new_tiles_premium(self):
        # C _ T on the board, A placed on the center DW: (3+1+1) x2
        board = board_with((7, 6, "C"), (7, 8, "T"))
        res = evaluate_move(board, tiles((7, 7, "A")), DICT)
        self.assertEqual(words(res), {"CAT": 10})


class MultipleWordsInOneMove(unittest.TestCase):
    def test_parallel_play_scores_main_word_and_each_crossword(self):
        # HE on row 7. Playing AT directly below forms AT, HA and ET.
        # A(8,7) plain, T(8,8) DL.
        #   AT = 1 + 1x2 = 3,  HA = 4 + 1 = 5,  ET = 1 + 1x2 = 3
        board = board_with((7, 7, "H"), (7, 8, "E"))
        res = evaluate_move(board, across("AT", 8, 7), DICT)
        self.assertEqual(words(res), {"AT": 3, "HA": 5, "ET": 3})
        self.assertEqual(res["score"], 11)
        self.assertEqual(res["words"][0]["word"], "AT", "main word is listed first")

    def test_hook_scores_extended_word_and_new_word(self):
        # CAT on row 7. S(7,9) O(8,9) down makes SO and hooks CAT -> CATS.
        board = board_with((7, 6, "C"), (7, 7, "A"), (7, 8, "T"))
        res = evaluate_move(board, down("SO", 7, 9), DICT)
        self.assertEqual(words(res), {"SO": 2, "CATS": 6})
        self.assertEqual(res["score"], 8)

    def test_word_multiplier_applies_to_both_words_through_that_square(self):
        # AX at (4,5)-(4,6). M on (4,4) DW and E at (5,4) form ME down and MAX across.
        #   ME  = (3+1) x2 = 8
        #   MAX = (3+1+8) x2 = 24
        board = board_with((4, 5, "A"), (4, 6, "X"))
        res = evaluate_move(board, down("ME", 4, 4), DICT)
        self.assertEqual(words(res), {"ME": 8, "MAX": 24})
        self.assertEqual(res["score"], 32)

    def test_single_tile_forming_words_in_both_directions(self):
        # H at (7,6) and O at (6,7). I on center DW makes HI across and OI down.
        #   HI = (4+1) x2 = 10,  OI = (1+1) x2 = 4
        board = board_with((7, 6, "H"), (6, 7, "O"))
        res = evaluate_move(board, tiles((7, 7, "I")), DICT)
        self.assertEqual(words(res), {"HI": 10, "OI": 4})
        self.assertEqual(res["score"], 14)

    def test_one_bad_crossword_rejects_whole_move_and_names_it(self):
        # HE on row 7; ZA below is a valid word, but its crosswords HZ and EA aren't.
        board = board_with((7, 7, "H"), (7, 8, "E"))
        with self.assertRaises(GameError) as cm:
            evaluate_move(board, across("ZA", 8, 7), DICT)
        self.assertIn("HZ", str(cm.exception))
        self.assertIn("EA", str(cm.exception))
        self.assertNotIn("ZA", str(cm.exception))


class Bingo(unittest.TestCase):
    def test_double_double_plus_bingo(self):
        # ABANDONED down column 3, rows 3-11, with A(5,3) and N(6,3) already placed.
        # New tiles hit (3,3) DW, (7,3) DL on D, and (11,3) DW.
        #   letters: A1 B3 A1 N1 D2x2 O1 N1 E1 D2 = 15, x4 = 60, +50 bingo = 110
        board = board_with((5, 3, "A"), (6, 3, "N"))
        new = [p for p in down("ABANDONED", 3, 3) if p["r"] not in (5, 6)]
        self.assertEqual(len(new), 7)
        res = evaluate_move(board, new, DICT)
        self.assertTrue(res["bingo"])
        self.assertEqual(words(res), {"ABANDONED": 60})
        self.assertEqual(res["score"], 110)

    def test_six_tiles_is_not_a_bingo(self):
        res = evaluate_move(board_with(), across("ABATED", 7, 4))
        self.assertFalse(res["bingo"])


class BlankTiles(unittest.TestCase):
    def test_blank_scores_zero_even_on_letter_premium(self):
        # HE on row 7, AT below with a blank T on (8,8) DL.
        #   AT = 1 + 0 = 1,  HA = 5,  ET = 1 + 0 = 1
        board = board_with((7, 7, "H"), (7, 8, "E"))
        res = evaluate_move(board, across("AT", 8, 7, blanks={1}), DICT)
        self.assertEqual(words(res), {"AT": 1, "HA": 5, "ET": 1})

    def test_blank_on_word_premium_still_multiplies(self):
        # Blank A on center DW: (3+0+1) x2
        res = evaluate_move(board_with(), across("CAT", 7, 6, blanks={1}))
        self.assertEqual(res["score"], 8)

    def test_blank_already_on_board_scores_zero(self):
        board = board_with((7, 7, "H", True), (7, 8, "E"))
        res = evaluate_move(board, tiles((7, 9, "A"), (7, 10, "T")), DICT)
        self.assertEqual(words(res), {"HEAT": 3})


class PlacementRules(unittest.TestCase):
    def assertRejected(self, board, placements, fragment):
        with self.assertRaises(GameError) as cm:
            evaluate_move(board, placements)
        self.assertIn(fragment, str(cm.exception))

    def test_first_move_must_cover_center(self):
        self.assertRejected(board_with(), across("CAT", 6, 6), "center")

    def test_first_move_needs_two_letters(self):
        self.assertRejected(board_with(), tiles((7, 7, "A")), "two letters")

    def test_tiles_must_be_in_one_line(self):
        self.assertRejected(board_with(), tiles((7, 7, "A"), (8, 8, "T")), "single row or column")

    def test_no_gaps(self):
        self.assertRejected(board_with(), tiles((7, 6, "A"), (7, 8, "T")), "continuous")

    def test_must_connect_to_existing_tiles(self):
        board = board_with((7, 7, "H"), (7, 8, "E"))
        self.assertRejected(board, across("AT", 2, 2), "connect")

    def test_cannot_place_on_occupied_square(self):
        board = board_with((7, 7, "H"))
        self.assertRejected(board, tiles((7, 7, "A")), "taken")

    def test_cannot_place_two_tiles_on_one_square(self):
        self.assertRejected(board_with(), tiles((7, 7, "A"), (7, 7, "B")), "taken")

    def test_off_board(self):
        self.assertRejected(board_with(), tiles((7, 14, "A"), (7, 15, "T")), "off the board")


if __name__ == "__main__":
    unittest.main()
