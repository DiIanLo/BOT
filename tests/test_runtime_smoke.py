"""Smoke tests that import the real bot and its feature modules."""
import importlib
import json
from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_modules_import_without_a_discord_token():
    main = importlib.import_module("main")
    bank = importlib.import_module("bank_system")
    credit = importlib.import_module("credit_system")
    assert main.bot is not None
    assert callable(bank.setup_bank_system)
    assert callable(credit.setup_credit_system)


def test_root_persistent_json_files_are_valid():
    for path in ROOT.glob("*.json"):
        with path.open("r", encoding="utf-8") as stream:
            json.load(stream)


def test_no_local_runtime_environment_is_tracked():
    # These directories must stay ignored; committing a venv/cache bloats the repo
    # and can accidentally include machine-specific files.
    for name in (".cache", ".local", ".idea", ".venv", "venv"):
        assert not (ROOT / name).exists(), f"Unexpected tracked/runtime directory: {name}"


def test_bank_and_credit_commands_register_on_a_real_discord_bot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bot = commands.Bot(command_prefix=".", intents=discord.Intents.none())
    bank = importlib.import_module("bank_system")
    credit = importlib.import_module("credit_system")
    now = lambda: datetime(2026, 11, 1, 12, 0, 0)
    atomic_write = lambda path, payload: None

    bank_api = bank.setup_bank_system(
        bot=bot, data={"players": {}}, is_registered=lambda uid: True,
        leader_roles={"торговцы": 1}, rank_roles={}, atomic_write=atomic_write,
        now_msk=now,
    )
    credit.setup_credit_system(
        bot=bot, data={"players": {}}, is_registered=lambda uid: True,
        leader_roles={"торговцы": 1}, rank_roles={}, atomic_write=atomic_write,
        now_msk=now, report_channels={}, bank_api=bank_api,
    )

    registered = {command.name for command in bot.commands}
    assert {"treasury", "savings_open", "deposit_open", "credit_apply",
            "credit_approve", "credit_issue", "credit_pay"} <= registered
    assert len(registered) == len(bot.commands)
