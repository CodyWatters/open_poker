import random
import unittest

from pokerapp.analysis import _true_runout, luck_check
from pokerapp.cards import parse_card as P


def cards(s):
    return [P(c) for c in s.split()]


def hand(hero, villain, board, net=-10, deck_left=None, fold_board_len=0):
    rec = {"id": 1, "hero_seat": 1, "hero_net": net, "board": cards(board),
           "seats": [{"seat": 1, "name": "Hero", "hole": cards(hero)}, {"seat": 2, "name": "Bob", "hole": cards(villain)}],
           "actions": [{"seat": 1, "type": "fold", "board_len": fold_board_len, "to_call": 10}]}
    if deck_left:
        rec["deck_left"] = deck_left
    return rec


def graded(action, match):
    return {"decisions": [{"i": 0, "street": "preflop", "action": action, "should": {"match": match}}]}


def check(rec, an):
    return luck_check(rec, an, rng=random.Random(1))


class Folds(unittest.TestCase):
    BOARD = "2c 3d 9h Js Qd"

    def test_right_fold_that_would_have_won_is_called_luck_not_a_mistake(self):
        r = check(hand("Ks Kd", "7c 8d", self.BOARD), graded("fold", True))
        self.assertEqual((r["would"], r["kind"]), ("win", "unlucky"))

    def test_right_fold_that_would_have_lost(self):
        r = check(hand("7c 8d", "Ks Kd", self.BOARD), graded("fold", True))
        self.assertEqual((r["would"], r["kind"]), ("lose", "earned"))

    def test_wrong_fold_that_would_have_won(self):
        r = check(hand("Ks Kd", "7c 8d", self.BOARD), graded("fold", False))
        self.assertEqual((r["would"], r["kind"]), ("win", "costly"))

    def test_wrong_fold_that_would_have_lost_is_still_wrong(self):
        r = check(hand("7c 8d", "Ks Kd", self.BOARD), graded("fold", False))
        self.assertEqual((r["would"], r["kind"]), ("lose", "lucky"))

    def test_old_hand_without_the_deck_invents_no_outcome(self):
        r = check(hand("Ks Kd", "7c 8d", ""), graded("fold", True))
        self.assertIsNone(r["would"])
        self.assertIsNone(r["board"])
        self.assertGreater(r["chance"], 0.7)

    def test_saved_deck_gives_the_real_cards_with_burns(self):
        order = cards("2h 2c 3d 9h 3h Js 4h Qd")  # burn, flop x3, burn, turn, burn, river
        self.assertEqual(_true_runout([], list(reversed(order))), cards("2c 3d 9h Js Qd"))
        self.assertEqual(_true_runout(cards("2c 3d 9h"), list(reversed(cards("3h Js 4h Qd")))), cards("2c 3d 9h Js Qd"))

    def test_saved_deck_is_used_when_the_hand_ended_early(self):
        deck = list(reversed(cards("2h 2c 3d 9h 3h Js 4h Qd")))
        r = check(hand("Ks Kd", "7c 8d", "", deck_left=deck), graded("fold", True))
        self.assertEqual(r["would"], "win")


class PlayedHands(unittest.TestCase):
    def kind(self, match, net):
        rec = hand("Ks Kd", "7c 8d", "2c 3d 9h Js Qd", net=net)
        return check(rec, graded("call", match))["kind"]

    def test_all_four_outcomes(self):
        self.assertEqual(self.kind(True, 50), "earned")
        self.assertEqual(self.kind(True, -50), "unlucky")
        self.assertEqual(self.kind(False, 50), "lucky")
        self.assertEqual(self.kind(False, -50), "costly")

    def test_no_decisions_means_no_verdict(self):
        self.assertIsNone(check(hand("Ks Kd", "7c 8d", ""), {"decisions": []}))


if __name__ == "__main__":
    unittest.main()
