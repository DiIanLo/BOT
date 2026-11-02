"""Pure, independently tested calculations for the credit system."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def due_offsets(term: int) -> list[timedelta]:
    """Return the current contractual installment offsets for a loan term."""
    if term == 7:
        return [timedelta(days=i) for i in range(1, 8)]
    if term == 14:
        return [timedelta(hours=84 * i) for i in range(1, 5)]
    if term == 30:
        return [timedelta(days=7), timedelta(days=14), timedelta(days=21), timedelta(days=30)]
    raise ValueError("Срок кредита должен быть 7, 14 или 30 дней.")


def weighted_principal_days(term: int) -> float:
    """Principal-days assuming equal principal installments paid on their due dates."""
    offsets = due_offsets(term)
    previous_day = 0.0
    balance_fraction = 1.0
    total = 0.0
    principal_fraction = 1.0 / len(offsets)
    for offset in offsets:
        day = offset.total_seconds() / 86400.0
        total += balance_fraction * (day - previous_day)
        balance_fraction = max(0.0, balance_fraction - principal_fraction)
        previous_day = day
    return max(total, 1.0)


def calibrated_daily_rate(term: int, target_total_rate: float) -> float:
    if not isinstance(target_total_rate, (int, float)) or target_total_rate <= 0:
        raise ValueError("Целевая ставка должна быть положительной.")
    return float(target_total_rate) / weighted_principal_days(term)


def build_principal_schedule(principal: int, term: int, issued_at: datetime) -> list[dict[str, Any]]:
    if isinstance(principal, bool) or not isinstance(principal, int) or principal < 1:
        raise ValueError("Основной долг должен быть положительным целым числом.")
    offsets = due_offsets(term)
    base_part, remainder = divmod(principal, len(offsets))
    return [
        {
            "due_at": (issued_at + offset).isoformat(timespec="seconds"),
            "principal": base_part + (remainder if index == len(offsets) - 1 else 0),
            "paid": False,
        }
        for index, offset in enumerate(offsets)
    ]


def accrue_interest(loan: dict[str, Any], at: datetime) -> float:
    """Accrue whole elapsed days on outstanding principal, preserving legacy semantics."""
    last = datetime.fromisoformat(loan["last_interest_at"])
    elapsed_days = int((at - last).total_seconds() // 86400)
    if elapsed_days > 0 and float(loan.get("principal_remaining", 0)) > 0:
        added = float(loan["principal_remaining"]) * float(loan["daily_rate"]) * elapsed_days
        loan["interest_accrued"] = round(float(loan.get("interest_accrued", 0)) + added, 6)
        loan["last_interest_at"] = (last + timedelta(days=elapsed_days)).isoformat(timespec="seconds")
    return float(loan.get("interest_accrued", 0))
