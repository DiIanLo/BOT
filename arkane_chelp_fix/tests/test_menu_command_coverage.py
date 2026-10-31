import ast
from pathlib import Path


def _decorated_commands(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    result = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            try:
                parsed = ast.parse(ast.unparse(decorator), mode="eval").body
            except Exception:
                continue
            if not isinstance(parsed, ast.Call) or not ast.unparse(parsed.func).endswith(".command"):
                continue
            for keyword in parsed.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    result.add(keyword.value.value)
    return result


def test_every_registered_command_is_in_a_menu_or_is_a_root_entry():
    root = Path(__file__).resolve().parents[1]
    registered = set()
    for filename in ("main.py", "bank_system.py", "credit_system.py"):
        registered |= _decorated_commands(root / filename)
    tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    groups_node = next(node for node in tree.body if isinstance(node, ast.Assign) and
                       any(isinstance(target, ast.Name) and target.id == "MENU_COMMAND_GROUPS"
                           for target in node.targets))
    groups = ast.literal_eval(groups_node.value)
    mapped = {command for commands in groups.values() for command in commands}
    root_entries = {"menu", "chelp"}
    assert mapped.isdisjoint(root_entries)
    assert registered - mapped == root_entries
    assert mapped <= registered
    assert len(mapped) == len(set(mapped))


def test_every_menu_command_has_a_description_and_all_guild_guides_exist():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"MENU_COMMAND_GROUPS", "MENU_ACTION_HELP", "GUILD_GUIDES"}:
                    assignments[target.id] = ast.literal_eval(node.value)
    commands_in_menu = {name for names in assignments["MENU_COMMAND_GROUPS"].values() for name in names}
    assert commands_in_menu == set(assignments["MENU_ACTION_HELP"])
    assert set(assignments["GUILD_GUIDES"]) == {"шахтёры", "архитекторы", "торговцы", "СОБР"}
    assert all(len(title) > 0 and len(body) > 300 for title, body in assignments["GUILD_GUIDES"].values())
