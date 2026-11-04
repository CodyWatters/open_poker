"""Run from the repo root: python3 -m unittest discover tests"""
import random
import unittest

from pokerapp.analysis import live_decision
from pokerapp.cards import parse_card


def grade(hand, action, pos="UTG"):
    positions = dict(zip(range(1, 7), ["UTG", "HJ", "CO", "BTN", "SB", "BB"]))
    hero = next(s for s, p in positions.items() if p == pos)
    view = {"positions": positions, "actions": [], "board": [], "bb": 2}
    opps = [s for s in positions if s != hero]
    return live_decision(view, [parse_card(c) for c in hand.split()], pos, opps, "preflop", 2, 3, samples=200,
                         rng=random.Random(1), hero_action=action)["should"]


class CoachGrades(unittest.TestCase):
    def test_folding_trash_is_good(self):
        self.assertTrue(grade("7d 2c", "fold")["match"])

    def test_raising_trash_is_flagged(self):
        self.assertFalse(grade("7d 2c", "raise")["match"])

    def test_folding_aces_is_flagged(self):
        self.assertFalse(grade("Ad Ac", "fold")["match"])

    def test_raising_aces_is_good(self):
        self.assertTrue(grade("Ad Ac", "raise")["match"])

    def test_same_hand_changes_with_seat(self):
        self.assertEqual(grade("Kd 9c", "fold", "UTG")["action"], "fold")
        self.assertEqual(grade("Kd 9c", "fold", "BTN")["action"], "raise")


class CompanionNumbers(unittest.TestCase):
    def spot(self, pos):
        positions = dict(zip(range(1, 7), ["UTG", "HJ", "CO", "BTN", "SB", "BB"]))
        hero = next(s for s, p in positions.items() if p == pos)
        view = {"positions": positions, "actions": [], "board": [], "bb": 2}
        return live_decision(view, [parse_card("Kd"), parse_card("9c")], pos, [s for s in positions if s != hero],
                             "preflop", 2, 3, samples=200, rng=random.Random(1))

    def test_later_seats_have_fewer_players_left_and_wider_ranges(self):
        utg, btn = self.spot("UTG"), self.spot("BTN")
        self.assertEqual((utg["left"], btn["left"]), (5, 2))
        self.assertLess(utg["play_pct"], btn["play_pct"])

    def test_inside_the_range_means_the_book_plays_it(self):
        for pos in ("UTG", "HJ", "CO", "BTN", "SB"):
            r = self.spot(pos)
            self.assertEqual(r["hand_pct"] < r["play_pct"], r["should"]["action"] == "raise", pos)


if __name__ == "__main__":
    unittest.main()
