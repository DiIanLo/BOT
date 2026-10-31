"""Credit ledger for the Discord bot. Transfers are recorded manually after confirmation."""
from __future__ import annotations
import json
import os
import math
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional
from discord.ext import commands, tasks
import discord

TERMS = {7: {"min": 448, "max": 700, "target_rate": 0.10},
         14: {"min": 896, "max": 3200, "target_rate": 0.15},
         30: {"min": 4480, "max": None, "target_rate": 0.20}}
CREDITORS_FILE = "creditors.json"
LOANS_FILE = "loans.json"


def setup_credit_system(bot, data, is_registered: Callable[[str], bool], leader_roles: Dict[str, int],
                        rank_roles: Optional[Dict[str, Dict[str, int]]], atomic_write: Callable[[str, Any], None], now_msk: Callable[[], datetime],
                        report_channels: Dict[str, int], bank_api: Optional[Dict[str, Any]] = None):
    creditors = _safe_load(CREDITORS_FILE, {"users": {}, "staff": [], "service_channel_id": None,
                                             "limits": {str(k): {"min": v["min"], "max": v["max"]}
                                                        for k, v in TERMS.items()}, "audit": []})
    loans = _safe_load(LOANS_FILE, {"applications": {}, "loans": {}, "next_application_id": 1,
                                     "next_loan_id": 1, "last_daily_check": None})
    if not isinstance(creditors, dict): creditors = {"users": {}, "staff": [], "service_channel_id": None, "limits": {}, "audit": []}
    if not isinstance(loans, dict): loans = {"applications": {}, "loans": {}, "next_application_id": 1, "next_loan_id": 1, "last_daily_check": None}
    for k, v in {"users": {}, "staff": [], "service_channel_id": None, "limits": {}, "audit": []}.items(): creditors.setdefault(k, v)
    for k, v in {"applications": {}, "loans": {}, "next_application_id": 1, "next_loan_id": 1, "last_daily_check": None}.items(): loans.setdefault(k, v)

    def save_creditors(): atomic_write(CREDITORS_FILE, creditors)
    def save_loans(): atomic_write(LOANS_FILE, loans)
    def audit(actor_id, action, details):
        creditors["audit"].append({"at": now_msk().isoformat(timespec="seconds"), "actor_id": str(actor_id),
                                   "action": action, "details": str(details)[:1000]})
        creditors["audit"] = creditors["audit"][-5000:]
        save_creditors()

    def is_trader(member):
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

    def is_leader(member):
        role_id = leader_roles.get("торговцы")
        return bool(role_id and getattr(member, "roles", None) and
                    discord.utils.get(member.roles, id=role_id))

    def is_staff(member):
        if getattr(member, "guild_permissions", None) and member.guild_permissions.administrator:
            return True
        return is_trader(member) and (is_leader(member) or str(member.id) in {str(x) for x in creditors.get("staff", [])})

    def can_lead(member): return is_leader(member)

    def service_channel(guild):
        channel_id = creditors.get("service_channel_id")
        return guild.get_channel(int(channel_id)) if guild and channel_id else None

    async def send_service(guild, content):
        ch = service_channel(guild)
        if ch:
            try:
                await ch.send(content)
            except (discord.Forbidden, discord.HTTPException):
                pass

    def get_active_loan(user_id):
        return next((l for l in loans["loans"].values() if l.get("borrower_id") == str(user_id)
                     and l.get("status") in {"active", "pending_issue"}), None)

    def limits_for(term):
        return creditors["limits"].get(str(term), {"min": TERMS[term]["min"], "max": TERMS[term]["max"]})

    def due_offsets(term):
        if term == 7: return [timedelta(hours=24 * i) for i in range(1, 8)]
        if term == 14: return [timedelta(hours=84 * i) for i in range(1, 5)]
        return [timedelta(days=7), timedelta(days=14), timedelta(days=21), timedelta(days=30)]

    def weighted_principal_days(term):
        # Calibrate the daily rate against equal principal installments and the agreed schedule.
        offsets = due_offsets(term)
        prev = 0.0
        bal_fraction = 1.0
        total = 0.0
        principal_fraction = 1.0 / len(offsets)
        for off in offsets:
            day = off.total_seconds() / 86400.0
            interval_days = day - prev
            total += bal_fraction * interval_days
            bal_fraction = max(0.0, bal_fraction - principal_fraction)
            prev = day
        return max(total, 1.0)

    def calibrated_rate(term):
        return TERMS[term]["target_rate"] / weighted_principal_days(term)

    def accrue(loan, at):
        last = datetime.fromisoformat(loan["last_interest_at"])
        elapsed_days = int((at - last).total_seconds() // 86400)
        if elapsed_days > 0 and loan.get("principal_remaining", 0) > 0:
            loan["interest_accrued"] = round(float(loan.get("interest_accrued", 0)) +
                float(loan["principal_remaining"]) * float(loan["daily_rate"]) * elapsed_days, 6)
            loan["last_interest_at"] = (last + timedelta(days=elapsed_days)).isoformat(timespec="seconds")

    def next_due(loan):
        idx = int(loan.get("installments_paid", 0))
        schedule = loan.get("schedule", [])
        return schedule[idx] if idx < len(schedule) else None

    def scheduled_amount(loan):
        due = next_due(loan)
        if not due: return 0
        return math.ceil(float(due.get("principal", 0)) + float(loan.get("interest_accrued", 0)))

    async def notify_user(guild, user_id, message):
        try:
            user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
            await user.send(message)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
        await send_service(guild, f"<@{user_id}> — {message}")

    @bot.command(name="credit_apply")
    async def credit_apply(ctx, amount: int, term: int):
        uid = str(ctx.author.id)
        if not ctx.guild or not is_registered(uid):
            return await ctx.send("❌ Подать заявку может только зарегистрированный участник сервера.")
        if term not in TERMS:
            return await ctx.send("❌ Срок должен быть 7, 14 или 30 дней.")
        if get_active_loan(uid):
            return await ctx.send("❌ У вас уже есть активный кредит.")
        if any(a.get("borrower_id") == uid and a.get("status") == "pending" for a in loans["applications"].values()):
            return await ctx.send("❌ У вас уже есть заявка на рассмотрении.")
        profile = data.get("players", {}).get(uid, {})
        nick = profile.get("minecraft_nick")
        if not nick:
            return await ctx.send("❌ Не удалось найти ваш Minecraft-ник в регистрации.")
        passport = creditors["users"].get(uid, {})
        if not passport.get("passport_verified"):
            return await ctx.send("❌ Паспорт ещё не подтверждён гильдией торговцев. Обратитесь к её лидеру или назначенному сотруднику.")
        limits = limits_for(term)
        if amount < int(limits.get("min", TERMS[term]["min"])):
            return await ctx.send(f"❌ Минимальная сумма для срока {term} дней: {limits.get('min')} алмазов.")
        maximum = limits.get("max")
        above_limit = maximum is not None and amount > int(maximum)
        app_id = str(loans["next_application_id"]); loans["next_application_id"] += 1
        loans["applications"][app_id] = {"id": app_id, "borrower_id": uid, "minecraft_nick": nick,
            "amount": int(amount), "term_days": term, "status": "pending", "created_at": now_msk().isoformat(timespec="seconds"),
            "requires_limit_exception": bool(above_limit)}
        creditors["users"].setdefault(uid, {}).update({"discord_id": uid, "minecraft_nick": nick})
        save_creditors(); save_loans()
        limit_note = " ⚠️ Сумма выше базового лимита: одобрить её может только лидер торговцев." if above_limit else ""
        await ctx.send(f"✅ Заявка **#{app_id}** создана: **{amount} алмазов**, срок **{term} дней**. Ожидайте решения гильдии торговцев.{limit_note}")
        await send_service(ctx.guild, f"📨 Новая заявка **#{app_id}** от <@{uid}> (`{nick}`): **{amount} алмазов**, срок {term} дней. Рассмотрение: `.credit_requests`. {limit_note}")

    @bot.command(name="credit_requests")
    async def credit_requests(ctx):
        if not is_staff(ctx.author): return await ctx.send("❌ Команда доступна только лидеру и назначенным сотрудникам гильдии торговцев.")
        pending = [a for a in loans["applications"].values() if a.get("status") == "pending"]
        if not pending: return await ctx.send("📭 Заявок на рассмотрении нет.")
        lines = [f"**#{a['id']}** — <@{a['borrower_id']}> (`{a['minecraft_nick']}`), {a['amount']} алмазов / {a['term_days']} дней" for a in pending[:25]]
        await ctx.send("📨 **Заявки на кредит**\n" + "\n".join(lines) + "\nОдобрить: `.credit_approve ID`; отклонить: `.credit_reject ID причина`. Исключение по лимиту одобряет только лидер.")

    @bot.command(name="credit_approve")
    async def credit_approve(ctx, app_id: str):
        if not is_staff(ctx.author): return await ctx.send("❌ Недостаточно прав.")
        app = loans["applications"].get(app_id)
        if not app or app.get("status") != "pending": return await ctx.send("❌ Активная заявка с таким ID не найдена.")
        uid = app["borrower_id"]; term = int(app["term_days"]); amount = int(app["amount"]); limits = limits_for(term)
        maximum = limits.get("max")
        if amount < int(limits.get("min", TERMS[term]["min"])): return await ctx.send("❌ Сумма ниже действующего минимального лимита.")
        if maximum is not None and amount > int(maximum) and not can_lead(ctx.author):
            return await ctx.send("❌ Исключение за пределами лимита может одобрить только лидер торговцев.")
        if get_active_loan(uid): return await ctx.send("❌ У заёмщика уже есть активный кредит.")
        if not creditors["users"].get(uid, {}).get("passport_verified"):
            return await ctx.send("❌ Паспорт больше не подтверждён; заявку нельзя одобрить.")
        created = now_msk(); offsets = due_offsets(term); n = len(offsets)
        base_part = amount // n; rem = amount - base_part * n
        schedule = []
        for i, offset in enumerate(offsets):
            principal_part = base_part + (rem if i == n - 1 else 0)
            schedule.append({"due_at": (created + offset).isoformat(timespec="seconds"), "principal": principal_part, "paid": False})
        loan_id = str(loans["next_loan_id"]); loans["next_loan_id"] += 1
        loans["loans"][loan_id] = {"id": loan_id, "application_id": app_id, "borrower_id": uid,
            "minecraft_nick": app["minecraft_nick"], "principal_original": amount, "principal_remaining": amount,
            "interest_accrued": 0.0, "daily_rate": calibrated_rate(term), "target_rate": TERMS[term]["target_rate"],
            "term_days": term, "issued_at": created.isoformat(timespec="seconds"), "last_interest_at": created.isoformat(timespec="seconds"),
            "schedule": schedule, "installments_paid": 0, "total_paid": 0, "status": "pending_issue", "payments": []}
        app["status"] = "approved"; app["loan_id"] = loan_id; app["reviewed_by"] = str(ctx.author.id); app["reviewed_at"] = created.isoformat(timespec="seconds")
        save_loans(); audit(ctx.author.id, "loan_approved", f"Заявка #{app_id}, кредит #{loan_id}, сумма {amount}, срок {term}; ставка {calibrated_rate(term):.8%}/день")
        await ctx.send(f"✅ Кредит **#{loan_id}** одобрен: {amount} алмазов на {term} дней. Дневная ставка: **{calibrated_rate(term):.5%}**. Кредит начнёт действовать после фактической передачи и команды `.credit_issue {loan_id}`.")
        await notify_user(ctx.guild, uid, f"Кредит #{loan_id} одобрен: {amount} алмазов на {term} дней. После фактической передачи алмазов сотрудник подтвердит выдачу командой `.credit_issue {loan_id}`. Сроки и проценты начнут отсчитываться после подтверждения выдачи.")

    @bot.command(name="credit_issue")
    async def credit_issue(ctx, loan_id: str, *, note: str = ""):
        """Confirm the physical loan payout; interest and deadlines start only now."""
        if not is_staff(ctx.author):
            return await ctx.send("❌ Подтвердить выдачу кредита может только лидер или назначенный сотрудник торговцев.")
        loan = loans["loans"].get(loan_id)
        if not loan or loan.get("status") != "pending_issue":
            return await ctx.send("❌ Одобренный кредит, ожидающий выдачи, не найден.")
        if bank_api and callable(bank_api.get("record_loan_issued")):
            ok, message = bank_api["record_loan_issued"](ctx.author.id, loan, note)
            if not ok:
                return await ctx.send("❌ Выдача не записана: " + message)
        elif bank_api is not None:
            return await ctx.send("❌ Не удалось подключить учёт казны; выдача не подтверждена.")
        issued = now_msk()
        term = int(loan["term_days"])
        offsets = due_offsets(term)
        n = len(offsets)
        principal = int(loan["principal_original"])
        base_part = principal // n
        rem = principal - base_part * n
        loan["schedule"] = []
        for i, offset in enumerate(offsets):
            principal_part = base_part + (rem if i == n - 1 else 0)
            loan["schedule"].append({"due_at": (issued + offset).isoformat(timespec="seconds"),
                                     "principal": principal_part, "paid": False})
        loan["issued_at"] = issued.isoformat(timespec="seconds")
        loan["last_interest_at"] = issued.isoformat(timespec="seconds")
        loan["status"] = "active"
        loan["issued_by"] = str(ctx.author.id)
        loan["issue_note"] = note[:500]
        save_loans()
        audit(ctx.author.id, "loan_issued", f"Кредит #{loan_id}, физическая выдача подтверждена; {note}")
        await ctx.send(f"✅ Выдача кредита **#{loan_id}** на {loan['principal_original']} алмазов подтверждена. Первый платёж: `{loan['schedule'][0]['due_at']}` МСК.")
        await notify_user(ctx.guild, loan["borrower_id"], f"Кредит #{loan_id} выдан. Проценты и график отсчитываются с {loan['issued_at']} МСК. Первый платёж: {loan['schedule'][0]['due_at']} МСК.")

    @bot.command(name="credit_reject")
    async def credit_reject(ctx, app_id: str, *, reason: str = "причина не указана"):
        if not is_staff(ctx.author): return await ctx.send("❌ Недостаточно прав.")
        app = loans["applications"].get(app_id)
        if not app or app.get("status") != "pending": return await ctx.send("❌ Активная заявка с таким ID не найдена.")
        app["status"] = "rejected"; app["reviewed_by"] = str(ctx.author.id); app["reviewed_at"] = now_msk().isoformat(timespec="seconds"); app["reason"] = reason[:500]
        save_loans(); audit(ctx.author.id, "application_rejected", f"Заявка #{app_id}: {reason}")
        await ctx.send(f"Заявка **#{app_id}** отклонена.")
        await notify_user(ctx.guild, app["borrower_id"], f"Заявка на кредит #{app_id} отклонена. Причина: {reason}")

    @bot.command(name="credit_passport")
    async def credit_passport(ctx, member: discord.Member, status: str):
        if not is_staff(ctx.author): return await ctx.send("❌ Недостаточно прав.")
        if status.casefold() not in {"да", "нет", "yes", "no", "on", "off"}:
            return await ctx.send("Использование: `.credit_passport @участник да/нет`.")
        verified = status.casefold() in {"да", "yes", "on"}
        record = creditors["users"].setdefault(str(member.id), {})
        record.update({"discord_id": str(member.id), "passport_verified": verified,
                       "passport_checked_by": str(ctx.author.id), "passport_checked_at": now_msk().isoformat(timespec="seconds")})
        save_creditors(); audit(ctx.author.id, "passport_status", f"Пользователь {member.id}: {verified}")
        await ctx.send(f"✅ Паспорт для {member.mention}: {'подтверждён' if verified else 'не подтверждён'}.")

    @bot.command(name="credit_staff")
    async def credit_staff(ctx, member: discord.Member, status: str):
        if not can_lead(ctx.author): return await ctx.send("❌ Назначать сотрудников может только лидер торговцев.")
        if status.casefold() not in {"да", "нет", "on", "off", "yes", "no"}:
            return await ctx.send("Использование: `.credit_staff @участник да/нет`.")
        ids = {str(x) for x in creditors["staff"]}; target = str(member.id)
        if status.casefold() in {"да", "on", "yes"}:
            if not is_trader(member):
                return await ctx.send("❌ Назначать сотрудником кредитного отдела можно только участника гильдии Торговцев.")
            ids.add(target)
        else: ids.discard(target)
        creditors["staff"] = sorted(ids); save_creditors(); audit(ctx.author.id, "staff_access", f"Пользователь {target}: {target in ids}")
        await ctx.send(f"✅ Доступ сотрудника для {member.mention}: {'выдан' if target in ids else 'снят'}.")

    @bot.command(name="credit_limits")
    async def credit_limits(ctx, term: Optional[int] = None, minimum: Optional[int] = None, maximum: Optional[int] = None):
        if not ctx.author.guild_permissions.administrator: return await ctx.send("❌ Изменять базовые лимиты может только администратор сервера.")
        if term is None:
            lines = []
            for t in (7, 14, 30):
                lim = limits_for(t); lines.append(f"{t} дней: {lim.get('min')}–{lim.get('max') if lim.get('max') is not None else 'без максимума'} алмазов")
            return await ctx.send("**Базовые лимиты**\n" + "\n".join(lines) + "\nИзменение: `.credit_limits срок минимум максимум`; для отсутствующего максимума укажите `0`.")
        if term not in TERMS or minimum is None or maximum is None or minimum < 1 or maximum < 0 or (maximum and maximum < minimum):
            return await ctx.send("Использование: `.credit_limits 7|14|30 минимум максимум`; максимум `0` означает без ограничения.")
        creditors["limits"][str(term)] = {"min": minimum, "max": maximum or None}
        save_creditors(); audit(ctx.author.id, "limits_changed", f"Срок {term}: min={minimum}, max={maximum or None}")
        await ctx.send(f"✅ Лимиты на {term} дней обновлены: минимум {minimum}, максимум {maximum or 'не установлен'} алмазов.")

    @bot.command(name="credit_service_channel")
    async def credit_service_channel(ctx, channel: discord.TextChannel):
        if not can_lead(ctx.author): return await ctx.send("❌ Настроить служебный канал может только лидер торговцев.")
        creditors["service_channel_id"] = channel.id; save_creditors(); audit(ctx.author.id, "service_channel_changed", f"Канал {channel.id}")
        await ctx.send(f"✅ Служебный канал кредитной системы: {channel.mention}.")

    @bot.command(name="creditors")
    async def creditors_list(ctx):
        if not is_staff(ctx.author): return await ctx.send("❌ Список доступен только лидеру и назначенным сотрудникам торговцев.")
        users = creditors.get("users", {})
        if not users: return await ctx.send("📭 В реестре пока нет участников кредитной системы.")
        lines = []
        for uid, record in list(users.items())[:40]:
            nick = record.get("minecraft_nick") or "ник не записан"
            passport = "паспорт подтверждён" if record.get("passport_verified") else "паспорт не подтверждён"
            lines.append(f"<@{uid}> — `{nick}`; {passport}")
        await ctx.send("**Реестр кредитной системы**\n" + "\n".join(lines))

    @bot.command(name="credit_status")
    async def credit_status(ctx, member: Optional[discord.Member] = None):
        target = member or ctx.author; uid = str(target.id)
        if target.id != ctx.author.id and not is_staff(ctx.author): return await ctx.send("❌ Просматривать чужой кредит могут только сотрудники торговцев.")
        active = get_active_loan(uid)
        pending = next((a for a in loans["applications"].values() if a.get("borrower_id") == uid and a.get("status") == "pending"), None)
        if not active:
            return await ctx.send(f"У {target.mention}: активного кредита нет." + (f" Заявка #{pending['id']} ожидает рассмотрения." if pending else ""))
        if active.get("status") == "pending_issue":
            return await ctx.send(f"**Кредит #{active['id']} — {target.mention}**\nСтатус: одобрен, ожидает фактической передачи алмазов. Проценты и график начнутся после подтверждения командой `.credit_issue {active['id']}`.")
        accrue(active, now_msk()); save_loans()
        due = next_due(active)
        due_text = f"Следующий платёж: {due['due_at']} МСК; ориентировочная сумма: {scheduled_amount(active)} алмазов." if due else "График платежей завершён."
        await ctx.send(f"**Кредит #{active['id']} — {target.mention}**\nОстаток основного долга: {active['principal_remaining']} алмазов\nНачисленные проценты: {active['interest_accrued']:.2f}\nСтатус: {active['status']}\n{due_text}")

    @bot.command(name="credit_pay")
    async def credit_pay(ctx, loan_id: str, amount: int, *, note: str = ""):
        if not is_staff(ctx.author): return await ctx.send("❌ Подтвердить передачу алмазов может кредитор/сотрудник торговцев.")
        loan = loans["loans"].get(loan_id)
        if not loan or loan.get("status") != "active": return await ctx.send("❌ Активный кредит с таким ID не найден.")
        if amount < 1: return await ctx.send("❌ Сумма подтверждённого платежа должна быть положительной.")
        at = now_msk(); accrue(loan, at)
        balance_before = float(loan["principal_remaining"]) + float(loan["interest_accrued"])
        if amount > math.ceil(balance_before + 0.000001):
            return await ctx.send(f"❌ Сумма превышает допустимый окончательный платёж ({math.ceil(balance_before)} алмазов).")
        applied_amount = min(float(amount), balance_before)
        rounding_excess = round(max(0.0, float(amount) - balance_before), 6)
        interest_paid = min(float(loan["interest_accrued"]), applied_amount)
        loan["interest_accrued"] = round(float(loan["interest_accrued"]) - interest_paid, 6)
        principal_paid = min(float(loan["principal_remaining"]), applied_amount - interest_paid)
        loan["principal_remaining"] = round(float(loan["principal_remaining"]) - principal_paid, 6)
        loan["total_paid"] = int(loan.get("total_paid", 0)) + amount
        loan["payments"].append({"at": at.isoformat(timespec="seconds"), "amount": amount, "interest_paid": round(interest_paid, 6),
                                 "principal_paid": round(principal_paid, 6), "rounding_excess": rounding_excess,
                                 "confirmed_by": str(ctx.author.id), "note": note[:500]})
        # Advance all installment dates that have been covered by the recorded principal repayment.
        while loan.get("installments_paid", 0) < len(loan["schedule"]):
            due = loan["schedule"][loan["installments_paid"]]
            target_principal = float(due["principal"])
            expected_cumulative = float(loan["principal_original"]) - sum(float(x["principal"]) for x in loan["schedule"][:loan["installments_paid"] + 1])
            if float(loan["principal_remaining"]) <= expected_cumulative + 0.000001:
                due["paid"] = True; due["paid_at"] = at.isoformat(timespec="seconds"); loan["installments_paid"] += 1
            else: break
        if loan["principal_remaining"] <= 0.000001 and loan["interest_accrued"] <= 0.000001:
            loan["principal_remaining"] = 0; loan["interest_accrued"] = 0; loan["status"] = "closed"; loan["closed_at"] = at.isoformat(timespec="seconds")
        save_loans()
        bank_sync_note = ""
        if bank_api and callable(bank_api.get("record_loan_payment")):
            try:
                ok, bank_message = bank_api["record_loan_payment"](ctx.author.id, loan, amount, principal_paid,
                                                                     interest_paid, len(loan["payments"]), note)
                if not ok:
                    bank_sync_note = " ⚠️ Не удалось обновить казну: " + str(bank_message)
            except Exception as exc:
                bank_sync_note = f" ⚠️ Платёж записан в кредитах, но синхронизация казны завершилась ошибкой ({type(exc).__name__}). Проверьте банковский журнал."
        audit(ctx.author.id, "payment_confirmed", f"Кредит #{loan_id}, сумма {amount}, проценты {interest_paid:.6f}, основной долг {principal_paid:.6f}, {note}")
        rounding_note = f" Разница округления: {rounding_excess:.2f} алмаза." if rounding_excess > 0 else ""
        await ctx.send(f"✅ Платёж {amount} алмазов по кредиту **#{loan_id}** записан. В основной долг зачтено {principal_paid:.2f}, в проценты — {interest_paid:.2f}. Остаток: {loan['principal_remaining'] + loan['interest_accrued']:.2f} алмазов.{rounding_note}{bank_sync_note}")
        await notify_user(ctx.guild, loan["borrower_id"], f"Платёж {amount} алмазов по кредиту #{loan_id} подтверждён. Остаток долга: {loan['principal_remaining'] + loan['interest_accrued']:.2f} алмазов.")

    @bot.command(name="credit_edit")
    async def credit_edit(ctx, loan_id: str, field: str, value: str, *, reason: str):
        if not can_lead(ctx.author): return await ctx.send("❌ Исправлять кредиты может только лидер торговцев.")
        loan = loans["loans"].get(loan_id)
        if not loan: return await ctx.send("❌ Кредит не найден.")
        if field not in {"principal_remaining", "interest_accrued", "status"}:
            return await ctx.send("Разрешённые поля: `principal_remaining`, `interest_accrued`, `status`.")
        old = loan.get(field)
        if field == "status" and value not in {"active", "pending_issue", "closed", "cancelled"}: return await ctx.send("Статус: active, pending_issue, closed или cancelled.")
        if field != "status":
            try: numeric = float(value)
            except ValueError: return await ctx.send("Значение должно быть числом.")
            if numeric < 0: return await ctx.send("Значение не может быть отрицательным.")
            loan[field] = round(numeric, 6)
        else: loan[field] = value
        save_loans(); audit(ctx.author.id, "loan_corrected", f"Кредит #{loan_id}: {field} {old!r} -> {value!r}; причина: {reason}")
        await ctx.send(f"✅ Кредит #{loan_id} исправлен. Изменение записано в журнал.")

    @bot.command(name="credit_audit")
    async def credit_audit(ctx, count: int = 10):
        if not can_lead(ctx.author): return await ctx.send("❌ Журнал доступен только лидеру торговцев.")
        count = max(1, min(count, 20)); rows = creditors.get("audit", [])[-count:]
        if not rows: return await ctx.send("Журнал пуст.")
        await ctx.send("**Журнал действий**\n" + "\n".join(f"`{r['at']}` <@{r['actor_id']}> — {r['action']}: {r['details']}" for r in rows))

    @bot.command(name="credit_help")
    async def credit_help(ctx):
        message = (
            "**Кредиты**\n"
            "`.credit_apply сумма 7|14|30` — подать заявку (нужна регистрация и подтверждённый паспорт).\n"
            "`.credit_status` — проверить свой кредит.\n"
        )
        if is_staff(ctx.author):
            message += (
                "**Служебные команды Торговцев**\n"
                "`.creditors`, `.credit_requests`, `.credit_approve ID`, `.credit_reject ID причина`.\n"
                "`.credit_issue ID [примечание]` — подтвердить фактическую выдачу после передачи алмазов; `.credit_pay ID сумма [примечание]` — подтвердить полученный платёж.\n"
                "`.credit_passport @участник да/нет` — проверить паспорт. Для лидера: `.credit_staff @участник да/нет`, `.credit_edit ID поле значение причина`, `.credit_audit [количество]`, `.credit_service_channel #канал`.\n"
            )
        if getattr(ctx.author, "guild_permissions", None) and ctx.author.guild_permissions.administrator:
            message += "Администратор: `.credit_limits [срок минимум максимум]`.\n"
        await ctx.send(message)

    @tasks.loop(minutes=1)
    async def credit_daily_checker():
        now = now_msk()
        if (now.hour, now.minute) < (12, 0): return
        today = now.date().isoformat()
        if loans.get("last_daily_check") == today: return
        loans["last_daily_check"] = today
        save_loans()
        for loan in loans["loans"].values():
            if loan.get("status") != "active": continue
            guild = bot.guilds[0] if bot.guilds else None
            for idx, installment in enumerate(loan.get("schedule", [])):
                if installment.get("paid"): continue
                due = datetime.fromisoformat(installment["due_at"])
                # Reminder on the due calendar day at 12:00 Moscow time.
                if due.date() == now.date() and not installment.get("reminded"):
                    accrue(loan, now); installment["reminded"] = True; save_loans()
                    await notify_user(guild, loan["borrower_id"], f"Сегодня срок платежа по кредиту #{loan['id']}. Ориентировочная сумма: {scheduled_amount(loan)} алмазов. Подтвердите передачу через сотрудника торговцев.")
                # Mark overdue at noon on the day after the exact deadline.
                if now >= due + timedelta(days=1) and not installment.get("overdue_notified"):
                    installment["overdue_notified"] = True; save_loans()
                    await notify_user(guild, loan["borrower_id"], f"Просрочка по кредиту #{loan['id']}: платёж по графику не подтверждён. Новые кредиты заблокированы до погашения просрочки.")
    return credit_daily_checker


def _safe_load(path, fallback):
    if not os.path.exists(path): return fallback
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Файл {path} повреждён; остановка кредитной системы без перезаписи данных: {exc}") from exc
