"""Unit tests for pure credit calculations."""
import unittest
from datetime import datetime, timedelta

from credit_logic import (
    accrue_interest, build_principal_schedule, calibrated_daily_rate,
    due_offsets, weighted_principal_days,
)


class CreditScheduleTests(unittest.TestCase):
    def test_seven_day_schedule_has_seven_equal_principal_parts(self):
        issued = datetime(2026, 1, 1, 12)
        schedule = build_principal_schedule(700, 7, issued)
        self.assertEqual([row["principal"] for row in schedule], [100] * 7)
        self.assertEqual(datetime.fromisoformat(schedule[-1]["due_at"]), issued + timedelta(days=7))

    def test_monthly_schedule_uses_days_seven_fourteen_twenty_one_and_thirty(self):
        issued = datetime(2026, 1, 1, 12)
        schedule = build_principal_schedule(1001, 30, issued)
        self.assertEqual([row["principal"] for row in schedule], [250, 250, 250, 251])
        self.assertEqual([datetime.fromisoformat(row["due_at"]) - issued for row in schedule],
                         [timedelta(days=7), timedelta(days=14), timedelta(days=21), timedelta(days=30)])

    def test_fourteen_day_legacy_schedule_is_preserved(self):
        self.assertEqual(due_offsets(14), [timedelta(days=3.5), timedelta(days=7), timedelta(days=10.5), timedelta(days=14)])

    def test_daily_rate_calibration_matches_target_under_on_time_schedule(self):
        for term, target in ((7, 0.10), (14, 0.15), (30, 0.20)):
            rate = calibrated_daily_rate(term, target)
            self.assertAlmostEqual(rate * weighted_principal_days(term), target, places=12)

    def test_accrual_uses_only_whole_elapsed_days_and_outstanding_principal(self):
        loan = {"last_interest_at": "2026-01-01T12:00:00", "principal_remaining": 700,
                "daily_rate": 0.01, "interest_accrued": 2.0}
        self.assertAlmostEqual(accrue_interest(loan, datetime(2026, 1, 3, 11)), 9.0)
        self.assertEqual(loan["last_interest_at"], "2026-01-02T12:00:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
