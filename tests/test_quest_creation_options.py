from pathlib import Path


def test_one_time_quest_option_is_available():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "label='🎯 Единоразовый'" in source
    assert "self.quest_type not in ('daily', 'weekly', 'once')" in source
    assert "'once': '🎯 Разовый'" in source


def test_auto_quest_template_creation_is_available_from_schedule_menu():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "class AutoQuestTemplateTypeView" in source
    assert "label='➕ Создать шаблон автоквеста'" in source
    assert "self.template_type, 'mode': 'individual'" in source


def test_quest_ids_are_published_and_available_in_management_menu():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "def generate_quest_id()" in source
    assert source.count("ID квеста: `{qid}`") >= 3  # ручное создание, шаблон и автоквест
    assert "class QuestIdMenuView" in source
    assert "label='🆔 Список квестов и ID'" in source


def test_pending_reward_menu_includes_one_time_quests():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    pending_select = source.split("class PendingRewardSelect", 1)[1].split("class PendingRewardConfirmView", 1)[0]
    assert "quest.get('type')" not in pending_select or "once" in pending_select
    assert "participant.get('reward_status') == 'pending'" in pending_select
    assert "pending_by_type['once']" in source


def test_closed_quests_cannot_be_confirmed_and_taken_entries_are_cancelled():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "Этот квест уже закрыт. Подтверждение выполнения больше недоступно." in source
    assert "participant.update({'status': 'cancelled'" in source
