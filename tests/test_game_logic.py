"""Автоматические проверки чистой игровой логики из main.py без подключения к Discord."""
import ast
import re
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

SOURCE = Path(__file__).resolve().parents[1] / "main.py"

CONSTANTS = {
    "RANK_COEFFICIENTS", "RANK_POINTS_REQUIRED", "RANK_ORDER", "MAX_TASKS_PER_RANK",
    "MIN_TASKS_PER_RANK", "MIN_TASKS_PENALTY_PER_TASK", "BASE_TASK_FAIL_PENALTY",
    "PENALTY_DIFF_MULTIPLIER", "RANK_DIFF_BONUS", "ACHIEVEMENT_CATALOG", "TITLE_CATALOG",
}
FUNCTIONS = {
    "get_rank_diff", "can_take_task", "can_add_tasks", "calculate_penalty",
    "calculate_salary", "player_weekly_salary", "add_task_salary_base",
    "calculate_rank_up", "calculate_min_tasks_penalty", "parse_duration_minutes",
    "format_duration", "parse_clock", "_achievement_unlocked", "refresh_player_progress",
    "get_active_title_name", "calculate_territory_limit", "quest_reward_config",
    "parse_reward_amount", "parse_reward_pair", "quest_reward_label", "apply_quest_completion",
}


def load_logic_namespace():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & CONSTANTS:
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "re": re,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


LOGIC = load_logic_namespace()


class RankLogicTests(unittest.TestCase):
    def test_rank_thresholds_are_cumulative_and_points_are_not_spent(self):
        rank, points, count = LOGIC["calculate_rank_up"](100, "F")
        self.assertEqual((rank, points, count), ("C", 100, 3))

    def test_rank_up_does_not_demote_or_recount_existing_rank(self):
        self.assertEqual(LOGIC["calculate_rank_up"](29, "E"), ("E", 29, 0))
        self.assertEqual(LOGIC["calculate_rank_up"](2000, "S"), ("S", 2000, 0))

    def test_salary_includes_task_difficulty_and_quest_bonus(self):
        self.assertEqual(LOGIC["calculate_salary"]("F", 2, 15, 1), 6.9)

    def test_weekly_salary_uses_recorded_base(self):
        player = {"rank": "F", "completed_tasks": 2, "weekly_salary_base": 6.0, "quest_bonus": 15}
        self.assertEqual(LOGIC["player_weekly_salary"](player), 6.9)

    def test_legacy_player_salary_fallback(self):
        player = {"rank": "E", "completed_tasks": 2, "quest_bonus": 10}
        self.assertEqual(LOGIC["player_weekly_salary"](player), 11.0)

    def test_task_limit_includes_exact_boundary(self):
        can_add = LOGIC["can_add_tasks"]
        self.assertTrue(can_add("F", 9, 1))
        self.assertFalse(can_add("F", 9, 2))
        self.assertFalse(can_add("F", 0, 0))
        self.assertFalse(can_add("unknown", 0, 1))

    def test_only_same_rank_or_up_to_two_ranks_higher_can_be_taken(self):
        can_take = LOGIC["can_take_task"]
        self.assertTrue(can_take("F", "F"))
        self.assertTrue(can_take("F", "E"))
        self.assertTrue(can_take("F", "D"))
        self.assertFalse(can_take("F", "C"))
        self.assertFalse(can_take("D", "F"))
        self.assertFalse(can_take("invalid", "F"))

    def test_minimum_task_penalty(self):
        self.assertEqual(LOGIC["calculate_min_tasks_penalty"]("F", 0), 2)
        self.assertEqual(LOGIC["calculate_min_tasks_penalty"]("F", 1), 0)

    def test_failed_task_penalty_increases_with_rank_gap(self):
        penalty = LOGIC["calculate_penalty"]
        self.assertEqual(penalty("F", 0), 1)  # дробный штраф округляется до минимум 1 очка
        self.assertEqual(penalty("E", 0), 2)
        self.assertEqual(penalty("E", 1), 4)
        self.assertEqual(penalty("E", 2), 6)


class CabinetAndTitleTests(unittest.TestCase):
    def test_first_task_unlocks_achievement_and_title_once(self):
        player = {"rank": "F", "lifetime_tasks_total": 1, "rank_points": 0}
        refresh = LOGIC["refresh_player_progress"]
        self.assertEqual(refresh(player), ["first_task"])
        self.assertIn("pioneer", player["unlocked_titles"])
        self.assertEqual(refresh(player), [])
        self.assertEqual(player["achievements"].count("first_task"), 1)

    def test_rank_achievement_uses_rank_order(self):
        unlocked = LOGIC["_achievement_unlocked"]
        self.assertFalse(unlocked({"rank": "D"}, "rank_c"))
        self.assertTrue(unlocked({"rank": "C"}, "rank_c"))
        self.assertTrue(unlocked({"rank": "S"}, "rank_c"))

    def test_title_selection_and_area_bonus_are_safe_by_default(self):
        player = {"rank": "F", "lifetime_tasks_total": 1, "rank_points": 0}
        refresh = LOGIC["refresh_player_progress"]
        refresh(player)
        player["active_title"] = "pioneer"
        self.assertEqual(LOGIC["get_active_title_name"](player), "Первопроходец")
        self.assertEqual(LOGIC["calculate_territory_limit"](100, player), 100)

    def test_area_limit_rejects_invalid_base(self):
        with self.assertRaises(ValueError):
            LOGIC["calculate_territory_limit"]("not-a-number", {})


class QuestRewardTests(unittest.TestCase):
    def test_zero_reward_keeps_salary_bonus_but_has_no_item_reward(self):
        player = {"quest_bonus": 5, "lifetime_quests_completed": 2}
        quest = {"bonus": 10, "reward_diamonds": 0, "reward_xp": 0}
        participant = {"status": "taken"}
        reward = LOGIC["apply_quest_completion"](player, quest, participant, 123, "2026-10-22T10:00:00+03:00")
        self.assertEqual(player["quest_bonus"], 15)
        self.assertEqual(player["lifetime_quests_completed"], 3)
        self.assertEqual(reward["reward_type"], "salary_only")
        self.assertEqual(participant["reward_status"], "not_required")

    def test_reward_quest_records_pending_diamonds_and_xp(self):
        player = {"quest_bonus": 0, "lifetime_quests_completed": 0}
        quest = {"bonus": 8, "reward_diamonds": 64, "reward_xp": 120}
        participant = {"status": "taken"}
        reward = LOGIC["apply_quest_completion"](player, quest, participant, 123, "2026-10-22T10:00:00+03:00")
        self.assertEqual(reward["reward_type"], "diamonds_xp")
        self.assertEqual(participant["reward_status"], "pending")
        self.assertEqual(participant["reward_diamonds"], 64)
        self.assertEqual(participant["reward_xp"], 120)
        self.assertEqual(player["quest_bonus"], 8)

    def test_reward_pair_validation(self):
        parse = LOGIC["parse_reward_pair"]
        self.assertEqual(parse("100, 50")["reward_diamonds"], 100)
        self.assertEqual(parse("100; 50")["reward_xp"], 50)
        self.assertEqual(parse("0,0")["reward_type"], "salary_only")
        for value in ("100", "-1,2", "1,1000001", "abc,5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse(value)


class DurationAndScheduleTests(unittest.TestCase):
    def test_duration_accepts_legacy_minutes_and_compound_units(self):
        parse = LOGIC["parse_duration_minutes"]
        self.assertEqual(parse("90"), 90)
        self.assertEqual(parse("1д 2ч 30м"), 1590)
        self.assertEqual(parse("1d 2h 30m"), 1590)
        self.assertEqual(parse("0"), 0)

    def test_duration_rejects_invalid_or_excessive_values(self):
        parse = LOGIC["parse_duration_minutes"]
        for value in ("", "tomorrow", "1w", "525601"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse(value)

    def test_duration_format_can_be_read_back(self):
        parse = LOGIC["parse_duration_minutes"]
        fmt = LOGIC["format_duration"]
        self.assertEqual(parse(fmt(1590)), 1590)
        self.assertEqual(fmt(0), "∞ (без ограничения)")

    def test_clock_parser_checks_format_and_range(self):
        parse = LOGIC["parse_clock"]
        self.assertEqual(parse("08:30"), (8, 30))
        for value in ("24:00", "10:60", "8.30", "abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
