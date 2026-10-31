"""Pure calculation helpers for the Arkane Bank ledger."""
from __future__ import annotations

import calendar
import math
from datetime import datetime, timedelta
from typing import Any

SAVINGS_BASE_RATES = {"topups": 0.13, "no_topups": 0.14}
SAVINGS_RATE_FLOOR = 0.05
SAVINGS_WITHDRAWAL_RATE_STEP = 0.002
DEPOSIT_TERMS = {
    "14d": {"label": "2 недели", "rate": 0.13},
    "1m": {"label": "1 месяц", "rate": 0.135},
    "1.5m": {"label": "1,5 месяца", "rate": 0.14},
    "2m": {"label": "2 месяца", "rate": 0.145},
    "3m": {"label": "3 месяца", "rate": 0.16},
}


def add_calendar_months(value: datetime, months: int) -> datetime:
    """Add calendar months, clamping to the last day when needed."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def deposit_maturity(opened_at: datetime, term: str) -> datetime:
    if term not in DEPOSIT_TERMS:
        raise ValueError("Неизвестный срок вклада.")
    if term == "14d":
        return opened_at + timedelta(days=14)
    if term == "1m":
        return add_calendar_months(opened_at, 1)
    if term == "1.5m":
        return add_calendar_months(opened_at, 1) + timedelta(days=15)
    if term == "2m":
        return add_calendar_months(opened_at, 2)
    return add_calendar_months(opened_at, 3)


def deposit_interest(principal: int, term: str) -> int:
    if principal < 1 or term not in DEPOSIT_TERMS:
        raise ValueError("Некорректная сумма или срок вклада.")
    return math.ceil(principal * DEPOSIT_TERMS[term]["rate"] - 1e-9)


def early_deposit_payout(principal: int) -> int:
    if principal < 1:
        raise ValueError("Сумма вклада должна быть положительной.")
    return math.floor(principal * 0.99 + 1e-9)


def _month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    start = _month_start(value)
    return add_calendar_months(start, 1)


def accrue_savings_account(account: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Accrue monthly interest by time-weighted balance/rate and capitalize at month boundaries.

    Interest accrues only until seven days after the last confirmed bank visit. A later
    visit restarts accrual at its timestamp; the paused interval is never compensated.
    Returns monthly capitalization events for the caller to post to the bank ledger.
    """
    if account.get("status", "active") != "active":
        return []
    last_raw = account.get("last_accrual_at") or account.get("created_at")
    if not last_raw:
        account["last_accrual_at"] = now.isoformat(timespec="seconds")
        return []
    cursor = datetime.fromisoformat(last_raw)
    if now <= cursor:
        return []
    events: list[dict[str, Any]] = []
    balance = float(account.get("balance", 0))
    monthly_interest = float(account.get("month_interest", 0.0))
    last_visit_raw = account.get("last_visit_at")
    active_until = datetime.fromisoformat(last_visit_raw) + timedelta(days=7) if last_visit_raw else cursor
    rate = float(account.get("rate", SAVINGS_BASE_RATES.get(account.get("mode", "topups"), 0.13)))

    while cursor < now:
        boundary = _next_month(cursor)
        segment_end = min(now, boundary)
        accrual_end = min(segment_end, active_until)
        if cursor < accrual_end and balance > 0:
            seconds = (accrual_end - cursor).total_seconds()
            month_seconds = (boundary - _month_start(cursor)).total_seconds()
            monthly_interest += balance * rate * seconds / month_seconds
        cursor = segment_end
        if cursor == boundary:
            payout = math.ceil(monthly_interest - 1e-9) if monthly_interest > 1e-9 else 0
            if payout:
                balance += payout
                events.append({"month": (boundary - timedelta(seconds=1)).strftime("%Y-%m"), "amount": payout})
            monthly_interest = 0.0
            # A new calendar month starts a fresh seven-day visit window only after a new visit;
            # active_until deliberately remains tied to the last actual visit.

    account["balance"] = int(round(balance))
    account["month_interest"] = round(monthly_interest, 8)
    account["last_accrual_at"] = now.isoformat(timespec="seconds")
    return events
