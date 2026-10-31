"""Arkane Bank: savings, fixed deposits, treasury and audit ledger.

All item transfers occur in Minecraft. Commands that change customer funds are manual
confirmations by an authorized bank employee after the physical transfer is checked.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import discord
from discord.ext import commands, tasks

from bank_logic import (
    DEPOSIT_TERMS,
    SAVINGS_BASE_RATES,
    SAVINGS_RATE_FLOOR,
    SAVINGS_WITHDRAWAL_RATE_STEP,
    accrue_savings_account,
    deposit_interest,
    deposit_maturity,
    early_deposit_payout,
)

ACCOUNTS_FILE = "bank_accounts.json"
DEPOSITS_FILE = "bank_deposits.json"
TREASURY_FILE = "treasury.json"
TRANSACTIONS_FILE = "bank_transactions.json"
AUDIT_FILE = "bank_audit.json"


def _safe_load(path: str, fallback: Any) -> Any:
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Файл {path} повреждён; банковская система остановлена без перезаписи данных: {exc}") from exc


def setup_bank_system(
    bot,
    data: dict[str, Any],
    is_registered: Callable[[str], bool],
    leader_roles: dict[str, int],
    rank_roles: Optional[dict[str, dict[str, int]]],
    atomic_write: Callable[[str, Any], None],
    now_msk: Callable[[], datetime],
):
    accounts = _safe_load(ACCOUNTS_FILE, {"accounts": {}, "next_id": 1})
    deposits = _safe_load(DEPOSITS_FILE, {"deposits": {}, "next_id": 1})
    treasury = _safe_load(TREASURY_FILE, {
        "treasury_balance": 0, "reserve_balance": 0, "staff": [], "posted_sources": [],
        "pending_expenses": {}, "next_expense_id": 1, "last_daily_check": None,
    })
    transactions = _safe_load(TRANSACTIONS_FILE, {"transactions": [], "next_id": 1})
    audit_log = _safe_load(AUDIT_FILE, {"events": []})
    if not isinstance(accounts, dict) or not isinstance(accounts.get("accounts"), dict):
        raise RuntimeError(f"Файл {ACCOUNTS_FILE} имеет неверный формат.")
    if not isinstance(deposits, dict) or not isinstance(deposits.get("deposits"), dict):
        raise RuntimeError(f"Файл {DEPOSITS_FILE} имеет неверный формат.")
    for key, value in {"treasury_balance": 0, "reserve_balance": 0, "staff": [], "posted_sources": [], "pending_expenses": {}, "next_expense_id": 1, "last_daily_check": None}.items():
        treasury.setdefault(key, value)
    for key, value in {"transactions": [], "next_id": 1}.items():
        transactions.setdefault(key, value)
    audit_log.setdefault("events", [])

    def save_accounts(): atomic_write(ACCOUNTS_FILE, accounts)
    def save_deposits(): atomic_write(DEPOSITS_FILE, deposits)
    def save_treasury(): atomic_write(TREASURY_FILE, treasury)
    def save_transactions(): atomic_write(TRANSACTIONS_FILE, transactions)
    def save_audit(): atomic_write(AUDIT_FILE, audit_log)

    def is_trader(member) -> bool:
        if getattr(member, "guild_permissions", None) and member.guild_permissions.administrator:
            return True
        player = data.get("players", {}).get(str(member.id), {})
        if str(player.get("guild", "")).strip().casefold() == "торговцы":
            return True
        roles = getattr(member, "roles", [])
        if any(discord.utils.get(roles, id=rid) for rid in (rank_roles or {}).get("торговцы", {}).values()):
            return True
        leader_role_id = leader_roles.get("торговцы")
        return bool(leader_role_id and discord.utils.get(roles, id=leader_role_id))

    def is_leader(member) -> bool:
        role_id = leader_roles.get("торговцы")
        return bool(role_id and getattr(member, "roles", None) and discord.utils.get(member.roles, id=role_id))

    def is_staff(member) -> bool:
        if getattr(member, "guild_permissions", None) and member.guild_permissions.administrator:
            return True
        return is_trader(member) and (is_leader(member) or str(member.id) in {str(x) for x in treasury.get("staff", [])})

    def audit(actor_id: Any, action: str, details: str):
        audit_log["events"].append({"at": now_msk().isoformat(timespec="seconds"), "actor_id": str(actor_id),
                                    "action": action, "details": str(details)[:1000]})
        audit_log["events"] = audit_log["events"][-10000:]
        save_audit()

    def transaction(kind: str, amount: int, actor_id: Any, details: str, owner_id: Optional[str] = None,
                    source_ref: Optional[str] = None, status: str = "confirmed"):
        if source_ref:
            existing = next((row for row in transactions["transactions"] if row.get("source_ref") == source_ref), None)
            if existing:
                return existing
        tx_id = str(transactions["next_id"])
        transactions["next_id"] += 1
        row = {"id": tx_id, "at": now_msk().isoformat(timespec="seconds"), "type": kind,
               "amount": int(amount), "actor_id": str(actor_id), "owner_id": str(owner_id) if owner_id is not None else None,
               "details": str(details)[:700], "status": status, "source_ref": source_ref}
        transactions["transactions"].append(row)
        transactions["transactions"] = transactions["transactions"][-20000:]
        save_transactions()
        audit(actor_id, "transaction:" + kind, f"Операция #{tx_id}, сумма {amount}, владелец {owner_id}; {details}")
        return row

    def member_nick(user_id: str) -> str:
        return str(data.get("players", {}).get(str(user_id), {}).get("minecraft_nick") or "ник не указан")

    def get_account(user_id: str):
        return next((a for a in accounts["accounts"].values()
                     if a.get("owner_id") == str(user_id) and a.get("status", "active") in {"active", "pending_funding"}), None)

    def accrue_account(account: dict[str, Any]):
        events = accrue_savings_account(account, now_msk())
        for event in events:
            # Monthly interest is a new bank liability, funded from the bank's free treasury.
            source_ref = f"savings-interest:{account['id']}:{event['month']}"
            already_posted = any(row.get("source_ref") == source_ref for row in transactions["transactions"])
            if not already_posted and source_ref not in treasury.get("posted_sources", []):
                treasury["treasury_balance"] = int(treasury.get("treasury_balance", 0)) - int(event["amount"])
                treasury.setdefault("posted_sources", []).append(source_ref)
                save_treasury()
            transaction("savings_interest", int(event["amount"]), "system",
                        f"Проценты за {event['month']} по накопительному счёту #{account['id']}",
                        owner_id=account["owner_id"], source_ref=source_ref)
        save_accounts()
        if events:
            save_treasury()
        return events

    def savings_liability() -> int:
        for account in accounts["accounts"].values():
            if account.get("status", "active") == "active":
                accrue_account(account)
        return sum(int(a.get("balance", 0)) for a in accounts["accounts"].values() if a.get("status", "active") == "active")

    def deposit_liability() -> int:
        total = 0
        for dep in deposits["deposits"].values():
            if dep.get("status") == "active":
                total += int(dep["principal"]) + int(dep.get("contractual_interest", 0))
        return total

    def loan_metrics() -> tuple[int, int, int]:
        raw = _safe_load("loans.json", {"loans": {}})
        principal = 0
        debt = 0
        overdue = 0
        now = now_msk()
        for loan in raw.get("loans", {}).values():
            if loan.get("status") != "active":
                continue
            p = max(0, int(float(loan.get("principal_remaining", 0))))
            principal += p
            debt += p + max(0, int(float(loan.get("interest_accrued", 0)) + 0.999999))
            for inst in loan.get("schedule", []):
                if not inst.get("paid") and now >= datetime.fromisoformat(inst["due_at"]) + timedelta(days=1):
                    overdue += 1
                    break
        return principal, debt, overdue

    def committed_expenses() -> int:
        return sum(int(e.get("amount", 0)) for e in treasury["pending_expenses"].values()
                   if e.get("status") in {"pending_leader", "approved_waiting_payment"})

    # Publicly callable, idempotent callbacks used by the credit department.
    def record_loan_issued(actor_id: Any, loan: dict[str, Any], note: str = "") -> tuple[bool, str]:
        source_ref = f"loan-issue:{loan['id']}"
        if source_ref in treasury.get("posted_sources", []) or any(row.get("source_ref") == source_ref for row in transactions["transactions"]):
            return True, "Выдача уже отражена в банковском журнале."
        amount = int(loan["principal_original"])
        available = int(treasury.get("treasury_balance", 0)) - committed_expenses()
        if available < amount:
            return False, f"В свободной казне недостаточно незарезервированных средств: доступно {max(0, available)}, требуется {amount} алмазов."
        treasury["treasury_balance"] = int(treasury.get("treasury_balance", 0)) - amount
        treasury.setdefault("posted_sources", []).append(source_ref)
        save_treasury()
        transaction("credit_issued", amount, actor_id, f"Выдача кредита #{loan['id']} заёмщику {loan['borrower_id']}; {note}",
                    owner_id=str(loan["borrower_id"]), source_ref=source_ref)
        return True, "Выдача записана."

    def record_loan_payment(actor_id: Any, loan: dict[str, Any], amount: int, principal_paid: float,
                            interest_paid: float, payment_index: int, note: str = "") -> tuple[bool, str]:
        source_ref = f"loan-payment:{loan['id']}:{payment_index}"
        if source_ref in treasury.get("posted_sources", []) or any(row.get("source_ref") == source_ref for row in transactions["transactions"]):
            return True, "Платёж уже отражён в банковском журнале."
        treasury["treasury_balance"] = int(treasury.get("treasury_balance", 0)) + int(amount)
        treasury.setdefault("posted_sources", []).append(source_ref)
        save_treasury()
        transaction("credit_repayment", amount, actor_id,
                    f"Погашение кредита #{loan['id']}; основной долг {principal_paid:.2f}, проценты {interest_paid:.2f}; {note}",
                    owner_id=str(loan["borrower_id"]), source_ref=source_ref)
        return True, "Погашение записано."

    @bot.command(name="bank_help")
    async def bank_help(ctx):
        message = (
            "**Аркейн Банк**\n"
            "`.savings_open topups|no_topups` — открыть накопительный счёт с выбранным режимом.\n"
            "`.savings_status [@участник]` — остаток, ставка и состояние начисления.\n"
            "`.deposit_status [@участник]` — посмотреть состояние срочных вкладов.\n"
        )
        if is_staff(ctx.author):
            message += (
                "**Служебные команды Торговцев**\n"
                "`.savings_deposit @участник сумма [примечание]`, `.savings_withdraw @участник сумма [примечание]`, `.savings_visit @участник`.\n"
                "`.deposit_open @участник сумма 14d|1m|1.5m|2m|3m`, `.deposit_pay ID`, `.deposit_early ID`.\n"
                "`.treasury`, `.treasury_add сумма причина`, `.treasury_expense сумма причина`, `.treasury_approve ID`, `.treasury_pay ID`.\n"
                "`.treasury_reserve сумма причина`, `.treasury_release сумма причина`, `.bank_report week|month`, `.bank_history [количество]`, `.bank_staff @участник да/нет`.\n"
            )
        message += "Все физические передачи совершаются в Minecraft. Сотрудник записывает операцию только после проверки передачи."
        await ctx.send(message)

    @bot.command(name="savings_open")
    async def savings_open(ctx, mode: str):
        uid = str(ctx.author.id)
        if not ctx.guild or not is_registered(uid):
            return await ctx.send("❌ Накопительный счёт доступен зарегистрированным участникам сервера.")
        aliases = {"topups": "topups", "пополнения": "topups", "с_пополнениями": "topups",
                   "no_topups": "no_topups", "без_пополнений": "no_topups", "безпополнений": "no_topups"}
        mode = aliases.get(mode.casefold())
        if not mode:
            return await ctx.send("Использование: `.savings_open topups` или `.savings_open no_topups`.")
        if get_account(uid):
            return await ctx.send("❌ У вас уже есть активный накопительный счёт.")
        now = now_msk()
        aid = str(accounts["next_id"])
        accounts["next_id"] += 1
        accounts["accounts"][aid] = {
            "id": aid, "owner_id": uid, "minecraft_nick": member_nick(uid), "mode": mode,
            "rate": SAVINGS_BASE_RATES[mode], "balance": 0, "month_interest": 0.0,
            "created_at": now.isoformat(timespec="seconds"), "last_accrual_at": now.isoformat(timespec="seconds"),
            "last_visit_at": None, "status": "pending_funding", "withdrawal_count": 0,
        }
        save_accounts()
        audit(uid, "savings_opened", f"Счёт #{aid}, режим {mode}, ставка {SAVINGS_BASE_RATES[mode]:.1%}")
        await ctx.send(f"✅ Открыт накопительный счёт **#{aid}**. Режим: **{'с пополнениями' if mode == 'topups' else 'без пополнений'}**, ставка {SAVINGS_BASE_RATES[mode]:.1%} в месяц. Для внесения начальной суммы обратитесь к сотруднику банка в игре.")

    @bot.command(name="savings_status")
    async def savings_status(ctx, member: Optional[discord.Member] = None):
        target = member or ctx.author
        if target.id != ctx.author.id and not is_staff(ctx.author):
            return await ctx.send("❌ Просматривать чужие счета могут только сотрудники банка.")
        account = get_account(str(target.id))
        if not account:
            return await ctx.send(f"У {target.mention} нет активного накопительного счёта.")
        accrue_account(account)
        last_visit_raw = account.get("last_visit_at")
        last_visit = datetime.fromisoformat(last_visit_raw) if last_visit_raw else None
        paused = last_visit is None or now_msk() >= last_visit + timedelta(days=7)
        if account.get("status") == "pending_funding":
            return await ctx.send(f"**Накопительный счёт #{account['id']} — {target.mention}**\nСчёт открыт и ожидает первоначального взноса от 100 алмазов. До внесения средств проценты не начисляются.")
        await ctx.send(f"**Накопительный счёт #{account['id']} — {target.mention}**\n"
                       f"Баланс: **{account['balance']} алмазов**\nСтавка: **{float(account['rate']):.2%} в месяц**\n"
                       f"Режим: **{'с пополнениями' if account['mode'] == 'topups' else 'без пополнений'}**\n"
                       f"Последнее посещение: `{account.get('last_visit_at') or 'не подтверждено'} МСК`\n"
                       f"Начисление процентов: **{'приостановлено' if paused else 'активно'}**. Минимальный остаток — 100 алмазов.")

    @bot.command(name="savings_deposit")
    async def savings_deposit(ctx, member: discord.Member, amount: int, *, note: str = ""):
        if not is_staff(ctx.author): return await ctx.send("❌ Подтвердить пополнение может только лидер или назначенный сотрудник банка.")
        if amount < 100: return await ctx.send("❌ Минимальное пополнение — 100 алмазов.")
        account = get_account(str(member.id))
        if not account: return await ctx.send("❌ У участника нет активного накопительного счёта.")
        accrue_account(account)
        if account["mode"] == "no_topups" and int(account.get("balance", 0)) > 0:
            return await ctx.send("❌ Этот счёт открыт без пополнений. После первоначального взноса дополнительные пополнения запрещены.")
        source_ref = f"savings-deposit:{account['id']}:{now_msk().isoformat(timespec='seconds')}:{ctx.author.id}"
        try:
            apply_treasury_cash_movement(treasury, source_ref, amount)
        except (TypeError, ValueError) as exc:
            return await ctx.send(f"❌ Пополнение не записано в казну: {exc}")
        account["balance"] = int(account.get("balance", 0)) + amount
        account["status"] = "active"
        account["last_visit_at"] = now_msk().isoformat(timespec="seconds")
        account["last_accrual_at"] = account["last_visit_at"]
        save_accounts()
        save_treasury()
        transaction("savings_deposit", amount, ctx.author.id, note or "Пополнение накопительного счёта после физической передачи", owner_id=str(member.id), source_ref=source_ref)
        await ctx.send(f"✅ Пополнение счёта **#{account['id']}** на {amount} алмазов записано. Новый остаток: {account['balance']}.")

    @bot.command(name="savings_withdraw")
    async def savings_withdraw(ctx, member: discord.Member, amount: int, *, note: str = ""):
        if not is_staff(ctx.author): return await ctx.send("❌ Подтвердить снятие может только лидер или назначенный сотрудник банка.")
        if amount < 50: return await ctx.send("❌ Минимальное снятие — 50 алмазов.")
        account = get_account(str(member.id))
        if not account: return await ctx.send("❌ У участника нет активного накопительного счёта.")
        accrue_account(account)
        if int(account.get("balance", 0)) - amount < 100:
            return await ctx.send("❌ После снятия на счёте должно остаться не менее 100 алмазов.")
        source_ref = f"savings-withdraw:{account['id']}:{now_msk().isoformat(timespec='seconds')}:{ctx.author.id}"
        try:
            apply_treasury_cash_movement(treasury, source_ref, -amount)
        except (TypeError, ValueError) as exc:
            return await ctx.send(f"❌ Снятие не выполнено: {exc}")
        old_rate = float(account["rate"])
        account["balance"] = int(account["balance"]) - amount
        account["rate"] = max(SAVINGS_RATE_FLOOR, round(old_rate - SAVINGS_WITHDRAWAL_RATE_STEP, 8))
        account["withdrawal_count"] = int(account.get("withdrawal_count", 0)) + 1
        account["last_visit_at"] = now_msk().isoformat(timespec="seconds")
        account["last_accrual_at"] = account["last_visit_at"]
        save_accounts()
        transaction("savings_withdrawal", amount, ctx.author.id,
                    f"Снятие; ставка снижена с {old_rate:.2%} до {account['rate']:.2%}. {note}",
                    owner_id=str(member.id), source_ref=source_ref)
        save_treasury()
        await ctx.send(f"✅ Снятие {amount} алмазов со счёта **#{account['id']}** записано. Остаток: {account['balance']}; новая ставка: {account['rate']:.2%} в месяц.")

    @bot.command(name="savings_visit")
    async def savings_visit(ctx, member: discord.Member):
        if not is_staff(ctx.author): return await ctx.send("❌ Посещение может подтвердить только сотрудник банка.")
        account = get_account(str(member.id))
        if not account: return await ctx.send("❌ У участника нет активного накопительного счёта.")
        accrue_account(account)
        now = now_msk()
        account["last_visit_at"] = now.isoformat(timespec="seconds")
        account["last_accrual_at"] = now.isoformat(timespec="seconds")
        save_accounts()
        transaction("savings_visit", 0, ctx.author.id, "Подтверждено посещение физического банка", owner_id=str(member.id), source_ref=f"savings-visit:{account['id']}:{now.isoformat(timespec='seconds')}")
        await ctx.send(f"✅ Посещение банка для {member.mention} записано. Начисление процентов возобновлено с текущего момента.")

    @bot.command(name="deposit_open")
    async def deposit_open(ctx, member: discord.Member, amount: int, term: str):
        if not is_staff(ctx.author): return await ctx.send("❌ Открывать вклад может только лидер или назначенный сотрудник банка.")
        term = term.casefold()
        if term not in DEPOSIT_TERMS:
            return await ctx.send("❌ Срок: `14d`, `1m`, `1.5m`, `2m` или `3m`.")
        if not 500 <= amount <= 5000:
            return await ctx.send("❌ Сумма срочного вклада должна быть от 500 до 5000 алмазов.")
        if not is_registered(str(member.id)):
            return await ctx.send("❌ Клиент должен быть зарегистрирован в боте.")
        now = now_msk()
        did = str(deposits["next_id"])
        deposits["next_id"] += 1
        maturity = deposit_maturity(now, term)
        interest = deposit_interest(amount, term)
        source_ref = f"deposit-open:{did}"
        try:
            apply_treasury_cash_movement(treasury, source_ref, amount)
        except (TypeError, ValueError) as exc:
            deposits["next_id"] -= 1
            return await ctx.send(f"❌ Вклад не открыт: {exc}")
        deposits["deposits"][did] = {"id": did, "owner_id": str(member.id), "minecraft_nick": member_nick(str(member.id)),
            "principal": amount, "term": term, "rate": DEPOSIT_TERMS[term]["rate"], "contractual_interest": interest,
            "opened_at": now.isoformat(timespec="seconds"), "matures_at": maturity.isoformat(timespec="seconds"),
            "status": "active", "opened_by": str(ctx.author.id)}
        save_deposits()
        transaction("fixed_deposit_opened", amount, ctx.author.id,
                    f"Открыт срочный вклад #{did}, срок {DEPOSIT_TERMS[term]['label']}, ставка {DEPOSIT_TERMS[term]['rate']:.2%}; физическое получение алмазов подтверждено",
                    owner_id=str(member.id), source_ref=source_ref)
        save_treasury()
        await ctx.send(f"✅ Срочный вклад **#{did}** оформлен для {member.mention}: **{amount} алмазов**, срок {DEPOSIT_TERMS[term]['label']}, ставка {DEPOSIT_TERMS[term]['rate']:.2%} за весь срок. Погашение: `{maturity.isoformat(timespec='seconds')} МСК`. Операция предполагает, что сотрудник уже проверил физическую передачу алмазов.")

    @bot.command(name="deposit_status")
    async def deposit_status(ctx, member: Optional[discord.Member] = None):
        target = member or ctx.author
        if target.id != ctx.author.id and not is_staff(ctx.author): return await ctx.send("❌ Просматривать чужие вклады могут только сотрудники банка.")
        rows = [d for d in deposits["deposits"].values() if d.get("owner_id") == str(target.id)]
        if not rows: return await ctx.send(f"У {target.mention} нет зарегистрированных срочных вкладов.")
        now = now_msk()
        lines = []
        for dep in rows[-8:]:
            due = datetime.fromisoformat(dep["matures_at"])
            status = dep.get("status", "active")
            payout = int(dep["principal"]) + int(dep.get("contractual_interest", 0))
            due_text = f"к выплате {payout}" if status == "active" and now >= due else f"ожидаемая выплата {payout}"
            lines.append(f"**#{dep['id']}** — {dep['principal']} алмазов, {DEPOSIT_TERMS[dep['term']]['label']}, {dep['rate']:.2%}; до `{dep['matures_at']}`; статус `{status}`; {due_text} алмазов")
        await ctx.send(f"**Срочные вклады {target.mention}**\n" + "\n".join(lines))

    @bot.command(name="deposit_pay")
    async def deposit_pay(ctx, deposit_id: str, *, note: str = ""):
        if not is_staff(ctx.author): return await ctx.send("❌ Погашать вклады может только лидер или назначенный сотрудник банка.")
        dep = deposits["deposits"].get(deposit_id)
        if not dep or dep.get("status") != "active": return await ctx.send("❌ Активный вклад с таким ID не найден.")
        if now_msk() < datetime.fromisoformat(dep["matures_at"]): return await ctx.send("❌ Срок вклада ещё не завершился. Для досрочного закрытия используйте `.deposit_early ID`.")
        payout = int(dep["principal"]) + int(dep.get("contractual_interest", 0))
        interest = int(dep.get("contractual_interest", 0))
        source_ref = f"deposit-payout:{deposit_id}"
        try:
            apply_treasury_cash_movement(treasury, source_ref, -payout)
        except (TypeError, ValueError) as exc:
            return await ctx.send(f"❌ Выплата не выполнена: {exc} Казна должна покрывать всю сумму, включая возвращаемый основной капитал.")
        dep.update({"status": "paid", "paid_at": now_msk().isoformat(timespec="seconds"), "paid_by": str(ctx.author.id), "payout": payout})
        save_deposits(); save_treasury()
        transaction("fixed_deposit_payout", payout, ctx.author.id, f"Погашен вклад #{deposit_id}; проценты {interest}; {note}", owner_id=dep["owner_id"], source_ref=source_ref)
        await ctx.send(f"✅ Выплата по вкладу **#{deposit_id}** на сумму {payout} алмазов записана после подтверждения физической передачи. Из них проценты: {interest} алмазов.")

    @bot.command(name="deposit_early")
    async def deposit_early(ctx, deposit_id: str, *, note: str = ""):
        if not is_staff(ctx.author): return await ctx.send("❌ Досрочно закрывать вклады может только лидер или назначенный сотрудник банка.")
        dep = deposits["deposits"].get(deposit_id)
        if not dep or dep.get("status") != "active": return await ctx.send("❌ Активный вклад с таким ID не найден.")
        if now_msk() >= datetime.fromisoformat(dep["matures_at"]): return await ctx.send("❌ Срок уже завершён. Используйте `.deposit_pay ID`.")
        payout = early_deposit_payout(int(dep["principal"]))
        retained = int(dep["principal"]) - payout
        source_ref = f"deposit-early:{deposit_id}"
        try:
            apply_treasury_cash_movement(treasury, source_ref, -payout)
        except (TypeError, ValueError) as exc:
            return await ctx.send(f"❌ Досрочная выплата не выполнена: {exc}")
        dep.update({"status": "early_closed", "closed_at": now_msk().isoformat(timespec="seconds"), "closed_by": str(ctx.author.id), "payout": payout, "retained_amount": retained})
        save_deposits(); save_treasury()
        transaction("fixed_deposit_early_payout", payout, ctx.author.id, f"Досрочное закрытие вклада #{deposit_id}; удержано {retained}; {note}", owner_id=dep["owner_id"], source_ref=source_ref)
        await ctx.send(f"✅ Досрочное закрытие вклада **#{deposit_id}** записано. Выплата: {payout} алмазов; удержано: {retained} алмазов; проценты не выплачиваются.")

    @bot.command(name="treasury")
    async def treasury_status(ctx):
        if not is_staff(ctx.author): return await ctx.send("❌ Сводка казны доступна только лидеру и назначенным сотрудникам банка.")
        sav = savings_liability(); dep = deposit_liability(); loan_principal, loan_debt, overdue = loan_metrics()
        pending = committed_expenses()
        await ctx.send("**Аркейн Банк — балансы**\n"
            f"Свободная казна: **{treasury.get('treasury_balance', 0)}** алмазов\n"
            f"Резерв: **{treasury.get('reserve_balance', 0)}** алмазов\n"
            f"Средства на накопительных счетах: **{sav}** алмазов\n"
            f"Обязательства по срочным вкладам (с договорными процентами): **{dep}** алмазов\n"
            f"Основной долг по выданным кредитам: **{loan_principal}** алмазов\n"
            f"Общая задолженность заёмщиков с начисленными процентами: **{loan_debt}** алмазов\n"
            f"Кредиты с просроченными платежами: **{overdue}**\n"
            f"Зарезервировано под незавершённые расходы: **{pending}** алмазов")

    @bot.command(name="treasury_add")
    async def treasury_add(ctx, amount: int, *, reason: str):
        if not is_staff(ctx.author): return await ctx.send("❌ Пополнять казну может только лидер или назначенный сотрудник банка.")
        if amount < 1: return await ctx.send("❌ Сумма должна быть положительной.")
        treasury["treasury_balance"] = int(treasury.get("treasury_balance", 0)) + amount
        save_treasury()
        transaction("treasury_topup", amount, ctx.author.id, f"{reason}; физическое поступление подтверждено", source_ref=f"treasury-add:{now_msk().isoformat(timespec='seconds')}:{ctx.author.id}")
        await ctx.send(f"✅ Казна пополнена на {amount} алмазов. Свободный баланс: {treasury['treasury_balance']}.")

    @bot.command(name="treasury_expense")
    async def treasury_expense(ctx, amount: int, *, reason: str):
        if not is_staff(ctx.author): return await ctx.send("❌ Запрашивать расходы могут только лидер и назначенные сотрудники банка.")
        if amount < 1: return await ctx.send("❌ Сумма должна быть положительной.")
        available = int(treasury.get("treasury_balance", 0)) - committed_expenses()
        if amount > available: return await ctx.send(f"❌ Недостаточно свободных средств с учётом уже заявленных расходов. Доступно: {max(0, available)}.")
        eid = str(treasury["next_expense_id"]); treasury["next_expense_id"] += 1
        needs_leader = amount >= 500 and not is_leader(ctx.author)
        treasury["pending_expenses"][eid] = {"id": eid, "amount": amount, "reason": reason[:500], "created_by": str(ctx.author.id),
            "created_at": now_msk().isoformat(timespec="seconds"), "status": "pending_leader" if needs_leader else "approved_waiting_payment",
            "approved_by": str(ctx.author.id) if not needs_leader else None}
        save_treasury(); audit(ctx.author.id, "expense_requested", f"Расход #{eid}, {amount}, статус {treasury['pending_expenses'][eid]['status']}; {reason}")
        status = "ожидает подтверждения лидера" if needs_leader else "одобрен, ожидает физической выплаты и команды подтверждения"
        await ctx.send(f"🧾 Запрос расхода **#{eid}** на {amount} алмазов создан: {status}. После физической передачи средств используйте `.treasury_pay {eid}`.")

    @bot.command(name="treasury_approve")
    async def treasury_approve(ctx, expense_id: str):
        if not is_leader(ctx.author): return await ctx.send("❌ Подтвердить крупный расход может только лидер гильдии торговцев.")
        expense = treasury["pending_expenses"].get(expense_id)
        if not expense or expense.get("status") != "pending_leader": return await ctx.send("❌ Запрос расхода не найден или уже обработан.")
        other_committed = sum(int(e.get("amount", 0)) for key, e in treasury["pending_expenses"].items()
                              if key != expense_id and e.get("status") in {"pending_leader", "approved_waiting_payment"})
        if int(treasury.get("treasury_balance", 0)) - other_committed < int(expense["amount"]):
            return await ctx.send("❌ В казне больше недостаточно свободных средств с учётом других запросов.")
        expense["status"] = "approved_waiting_payment"; expense["approved_by"] = str(ctx.author.id); expense["approved_at"] = now_msk().isoformat(timespec="seconds")
        save_treasury(); audit(ctx.author.id, "expense_approved", f"Расход #{expense_id} одобрен лидером")
        await ctx.send(f"✅ Расход **#{expense_id}** одобрен. После физической передачи алмазов уполномоченный сотрудник должен выполнить `.treasury_pay {expense_id}`.")

    @bot.command(name="treasury_pay")
    async def treasury_pay(ctx, expense_id: str, *, note: str = ""):
        if not is_staff(ctx.author): return await ctx.send("❌ Подтвердить расход может только сотрудник банка.")
        expense = treasury["pending_expenses"].get(expense_id)
        if not expense or expense.get("status") != "approved_waiting_payment": return await ctx.send("❌ Расход не одобрен или уже обработан.")
        amount = int(expense["amount"])
        other_committed = sum(int(e.get("amount", 0)) for key, e in treasury["pending_expenses"].items()
                              if key != expense_id and e.get("status") in {"pending_leader", "approved_waiting_payment"})
        if int(treasury.get("treasury_balance", 0)) - other_committed < amount:
            return await ctx.send("❌ В казне недостаточно незарезервированных средств на момент выплаты.")
        treasury["treasury_balance"] = int(treasury.get("treasury_balance", 0)) - amount
        expense.update({"status": "paid", "paid_by": str(ctx.author.id), "paid_at": now_msk().isoformat(timespec="seconds"), "payment_note": note[:500]})
        save_treasury()
        transaction("treasury_expense", amount, ctx.author.id, f"Расход #{expense_id}: {expense['reason']}; {note}", source_ref=f"treasury-expense:{expense_id}")
        await ctx.send(f"✅ Расход **#{expense_id}** на {amount} алмазов подтверждён и записан. Остаток казны: {treasury['treasury_balance']}.")

    async def move_to_reserve(ctx, amount: int, reason: str, direction: str):
        if not is_staff(ctx.author): return await ctx.send("❌ Управлять резервом могут только сотрудники банка.")
        if amount < 1: return await ctx.send("❌ Сумма должна быть положительной.")
        if direction == "reserve":
            if amount > int(treasury.get("treasury_balance", 0)): return await ctx.send("❌ В казне недостаточно средств.")
            treasury["treasury_balance"] = int(treasury["treasury_balance"]) - amount
            treasury["reserve_balance"] = int(treasury.get("reserve_balance", 0)) + amount
            kind = "treasury_to_reserve"
        else:
            if amount > int(treasury.get("reserve_balance", 0)): return await ctx.send("❌ В резерве недостаточно средств.")
            treasury["reserve_balance"] = int(treasury["reserve_balance"]) - amount
            treasury["treasury_balance"] = int(treasury.get("treasury_balance", 0)) + amount
            kind = "reserve_to_treasury"
        save_treasury()
        transaction(kind, amount, ctx.author.id, reason, source_ref=f"{kind}:{now_msk().isoformat(timespec='seconds')}:{ctx.author.id}")
        await ctx.send(f"✅ Перевод {amount} алмазов записан. Казна: {treasury['treasury_balance']}; резерв: {treasury['reserve_balance']}.")

    @bot.command(name="treasury_reserve")
    async def treasury_reserve(ctx, amount: int, *, reason: str):
        await move_to_reserve(ctx, amount, reason, "reserve")

    @bot.command(name="treasury_release")
    async def treasury_release(ctx, amount: int, *, reason: str):
        await move_to_reserve(ctx, amount, reason, "release")

    @bot.command(name="bank_report")
    async def bank_report(ctx, period: str = "month"):
        if not is_staff(ctx.author): return await ctx.send("❌ Отчёты доступны только сотрудникам банка.")
        if period not in {"week", "month"}: return await ctx.send("Использование: `.bank_report week` или `.bank_report month`.")
        now = now_msk()
        since = now - timedelta(days=7) if period == "week" else now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = [r for r in transactions["transactions"] if datetime.fromisoformat(r["at"]) >= since and r.get("status") == "confirmed"]
        incoming = sum(int(r["amount"]) for r in rows if r["type"] in {"treasury_topup", "credit_repayment"})
        expenses = sum(int(r["amount"]) for r in rows if r["type"] in {"treasury_expense", "credit_issued"})
        interest_paid = sum(int(r["amount"]) for r in rows if r["type"] == "savings_interest")
        await ctx.send(f"**Отчёт за {'7 дней' if period == 'week' else '30 дней'}**\n"
            f"Поступления в казну и погашения кредитов: {incoming} алмазов\n"
            f"Расходы и выданные кредиты: {expenses} алмазов\n"
            f"Начислено процентов по накопительным счетам: {interest_paid} алмазов\n"
            f"Текущая свободная казна: {treasury.get('treasury_balance', 0)}; резерв: {treasury.get('reserve_balance', 0)}.")

    @bot.command(name="bank_history")
    async def bank_history(ctx, count: int = 10):
        if not is_staff(ctx.author): return await ctx.send("❌ История доступна только сотрудникам банка.")
        count = max(1, min(count, 8))
        rows = transactions["transactions"][-count:]
        if not rows: return await ctx.send("Журнал операций пуст.")
        lines = [f"`#{r['id']}` `{r['at']}` — **{r['type']}**, {r['amount']} алмазов; <@{r['actor_id']}>; {str(r['details'])[:100]}" for r in reversed(rows)]
        await ctx.send("**Последние операции банка**\n" + "\n".join(lines))

    @bot.command(name="bank_staff")
    async def bank_staff(ctx, member: discord.Member, status: str):
        if not is_leader(ctx.author): return await ctx.send("❌ Назначать сотрудников банка может только лидер гильдии торговцев.")
        if status.casefold() not in {"да", "нет", "yes", "no", "on", "off"}:
            return await ctx.send("Использование: `.bank_staff @участник да/нет`.")
        ids = {str(x) for x in treasury.get("staff", [])}
        target = str(member.id)
        if status.casefold() in {"да", "yes", "on"}:
            if not is_trader(member):
                return await ctx.send("❌ Назначать сотрудником банка можно только участника гильдии Торговцев.")
            ids.add(target)
        else: ids.discard(target)
        treasury["staff"] = sorted(ids); save_treasury()
        audit(ctx.author.id, "bank_staff_access", f"Пользователь {target}: {target in ids}")
        await ctx.send(f"✅ Доступ сотрудника банка для {member.mention}: {'выдан' if target in ids else 'снят'}.")

    @tasks.loop(minutes=1)
    async def bank_daily_checker():
        now = now_msk()
        if (now.hour, now.minute) < (12, 0): return
        if treasury.get("last_daily_check") == now.date().isoformat(): return
        treasury["last_daily_check"] = now.date().isoformat()
        # Processing at least once per day ensures month-boundary interest is capitalized
        # even if no customer invokes a bank command around month end.
        for account in accounts["accounts"].values():
            if account.get("status", "active") == "active":
                accrue_account(account)
        save_treasury()

    return {"daily_checker": bank_daily_checker, "record_loan_issued": record_loan_issued,
            "record_loan_payment": record_loan_payment}
