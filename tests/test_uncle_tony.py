import tempfile
import unittest

from pokerapp.game import Game


class UncleTony(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.game = Game(self.dir.name)

    def broke(self, amount):
        self.game.db.change_bankroll(amount - self.game.db.bankroll(), "cashout", "test")

    def test_not_available_at_a_full_bankroll(self):
        self.assertFalse(self.game.lobby()["can_cry"])
        with self.assertRaises(ValueError):
            self.game.cry_to_tony()
        self.assertEqual(self.game.db.bankroll(), 1000)

    def test_available_just_under_the_cheapest_table(self):
        self.broke(999)
        self.assertTrue(self.game.lobby()["can_cry"])
        self.assertFalse(self.game.lobby()["can_topup"])

    def test_loan_adds_money_and_debt_and_unlocks_a_table(self):
        self.broke(400)
        lobby = self.game.cry_to_tony()
        self.assertEqual((lobby["bankroll"], lobby["tony_debt"]), (1400, 1000))
        self.assertFalse(lobby["can_cry"])
        self.assertFalse(lobby["stakes"][0]["locked"])
        self.assertEqual(lobby["bankroll_log"][-1]["kind"], "tony")

    def test_debt_adds_up_and_survives_a_restart(self):
        self.broke(400)
        self.game.cry_to_tony()
        self.broke(100)
        self.game.cry_to_tony()
        self.game.db.conn.close()
        self.assertEqual(Game(self.dir.name).lobby()["tony_debt"], 2000)

    def test_a_loan_keeps_hands_and_sessions(self):
        self.game.db.x("INSERT INTO hands(id, hero_net) VALUES (1, -600)")
        self.broke(400)
        self.game.cry_to_tony()
        self.assertEqual(len(self.game.db.q("SELECT id FROM hands")), 1)

    def test_erase_clears_the_debt(self):
        self.broke(400)
        self.game.cry_to_tony()
        self.assertEqual(self.game.erase_all()["tony_debt"], 0)

    def test_paying_back_part_then_all(self):
        self.broke(400)
        self.game.cry_to_tony()
        lobby = self.game.pay_tony(300)
        self.assertEqual((lobby["bankroll"], lobby["tony_debt"]), (1100, 700))
        lobby = self.game.pay_tony(700)
        self.assertEqual((lobby["bankroll"], lobby["tony_debt"]), (400, 0))
        self.assertEqual(lobby["bankroll_log"][-1]["kind"], "tony_repay")

    def test_bad_payments_change_nothing(self):
        with self.assertRaises(ValueError):
            self.game.pay_tony(100)  # no debt yet
        self.broke(400)
        self.game.cry_to_tony()
        for amount in (0, -50, 1001, 5000):
            with self.assertRaises(ValueError):
                self.game.pay_tony(amount)
        lobby = self.game.lobby()
        self.assertEqual((lobby["bankroll"], lobby["tony_debt"]), (1400, 1000))

    def test_cannot_pay_more_than_the_bankroll(self):
        self.broke(400)
        self.game.cry_to_tony()
        self.broke(100)
        with self.assertRaises(ValueError):
            self.game.pay_tony(101)
        self.assertEqual(self.game.pay_tony(100)["tony_debt"], 900)


if __name__ == "__main__":
    unittest.main()
