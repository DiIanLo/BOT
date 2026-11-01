"""Smoke tests that import the real bot and its feature modules."""
import importlib
import json
from pathlib import Path


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
