"""Tests for bank calculations that do not require discord.py or a live bot."""
import unittest
from datetime import datetime

from bank_logic import (
    DEPOSIT_TERMS,
    accrue_savings_account,
    deposit_interest,
    deposit_maturity,
    early_deposit_payout,
)


class DepositCalculationTests(unittest.TestCase):
    def test_calendar_month_clamps_to_month_end(self):
        opened = datetime(2026, 1, 31, 12, 30)
        self.assertEqual(deposit_maturity(opened, "1m"), datetime(2026, 2, 28, 12, 30))
        self.assertEqual(deposit_maturity(opened, "2m"), datetime(2026, 3, 31, 12, 30))

    def test_half_month_term_is_one_calendar_month_plus_fifteen_days(self):
        opened = datetime(2026, 1, 31, 12, 0)
        self.assertEqual(deposit_maturity(opened, "1.5m"), datetime(2026, 3, 15, 12, 0))

    def test_interest_is_for_the_entire_term_and_rounded_up_to_whole_diamonds(self):
        self.assertEqual(deposit_interest(500, "14d"), 65)
        self.assertEqual(deposit_interest(501, "1m"), 68)
        self.assertEqual(set(DEPOSIT_TERMS), {"14d", "1m", "1.5m", "2m", "3m"})

    def test_early_payout_is_99_percent_rounded_down(self):
        self.assertEqual(early_deposit_payout(500), 495)
        self.assertEqual(early_deposit_payout(501), 495)


class SavingsAccrualTests(unittest.TestCase):
    def make_account(self):
        return {
            "id": "1", "status": "active", "mode": "topups", "balance": 1000,
            "rate": 0.13, "month_interest": 0.0,
            "created_at": "2026-01-01T00:00:00",
            "last_accrual_at": "2026-01-01T00:00:00",
            "last_visit_at": "2026-01-01T00:00:00",
        }

    def test_interest_pauses_after_seven_days_without_visit(self):
        account = self.make_account()
        events = accrue_savings_account(account, datetime(2026, 1, 20, 0, 0))
        self.assertEqual(events, [])
        # Accrual is limited to the seven-day window after the last confirmed visit.
        self.assertGreater(account["month_interest"], 0)
        self.assertLess(account["month_interest"], 1000 * 0.13 * 8 / 31)

    def test_month_end_capitalizes_interest_as_whole_diamonds(self):
        account = self.make_account()
        events = accrue_savings_account(account, datetime(2026, 2, 1, 0, 0))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["month"], "2026-01")
        self.assertEqual(account["balance"], 1030)
        self.assertEqual(account["month_interest"], 0.0)

    def test_new_visit_restarts_accrual_without_compensating_pause(self):
        account = self.make_account()
        accrue_savings_account(account, datetime(2026, 1, 20, 0, 0))
        account["last_visit_at"] = "2026-01-20T00:00:00"
        account["last_accrual_at"] = "2026-01-20T00:00:00"
        old_interest = account["month_interest"]
        accrue_savings_account(account, datetime(2026, 1, 22, 0, 0))
        self.assertGreater(account["month_interest"], old_interest)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TreasuryCashMovementTests(unittest.TestCase):
    def test_incoming_cash_increases_treasury_and_is_idempotent(self):
        from bank_logic import apply_treasury_cash_movement
        treasury = {"treasury_balance": 100, "posted_sources": []}
        self.assertTrue(apply_treasury_cash_movement(treasury, "deposit:1", 500))
        self.assertEqual(treasury["treasury_balance"], 600)
        self.assertFalse(apply_treasury_cash_movement(treasury, "deposit:1", 500))
        self.assertEqual(treasury["treasury_balance"], 600)

    def test_outgoing_cash_decreases_treasury(self):
        from bank_logic import apply_treasury_cash_movement
        treasury = {"treasury_balance": 700, "posted_sources": []}
        self.assertTrue(apply_treasury_cash_movement(treasury, "payout:1", -650))
        self.assertEqual(treasury["treasury_balance"], 50)

    def test_cash_payout_cannot_make_treasury_negative(self):
        from bank_logic import apply_treasury_cash_movement
        treasury = {"treasury_balance": 100, "posted_sources": []}
        with self.assertRaises(ValueError):
            apply_treasury_cash_movement(treasury, "payout:1", -101)
        self.assertEqual(treasury["treasury_balance"], 100)
        self.assertEqual(treasury["posted_sources"], [])

    def test_invalid_or_zero_movements_are_rejected(self):
        from bank_logic import apply_treasury_cash_movement
        treasury = {"treasury_balance": 100, "posted_sources": []}
        for delta in (0, 1.5, True):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                apply_treasury_cash_movement(treasury, "bad", delta)
