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


def test_main_menu_reuses_existing_message_and_removes_duplicate_panels():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    upsert = functions["_upsert_main_menu"]
    source = ast.get_source_segment((root / "main.py").read_text(encoding="utf-8"), upsert)
    assert "ctx.channel.history(limit=100)" in source
    assert "primary.edit" in source
    assert "duplicate.delete()" in source
    menu = functions["main_menu"]
    menu_source = ast.get_source_segment((root / "main.py").read_text(encoding="utf-8"), menu)
    assert "_upsert_main_menu(ctx)" in menu_source
    assert "ctx.send(embed=build_main_menu_embed" not in menu_source


def test_main_menu_view_does_not_add_legacy_placeholder_controls():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    view = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainMenuView")
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_item"
        for node in ast.walk(view)
    )


def test_menu_context_proxy_does_not_mix_embed_and_embeds_keywords():
    root = Path(__file__).resolve().parents[1]
    source = (root / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    proxy = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_MenuContextProxy")
    send = next(node for node in proxy.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "send")
    segment = ast.get_source_segment(source, send)
    assert 'payload["embed"] = embed' in segment
    assert 'payload["embeds"] = embeds' in segment
    assert "send_message(**payload)" in segment
    assert "followup.send(**payload)" in segment
    assert "embed=embed, embeds=embeds" not in segment
