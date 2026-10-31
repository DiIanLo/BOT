import discord
from discord.ext import commands, tasks
import json
import os
import random
import string
import secrets
import shutil
import tempfile
import asyncio
import re
import inspect
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List


MOSCOW_TZ = ZoneInfo('Europe/Moscow')

def now_msk() -> datetime:
    """Текущее московское время без tzinfo для совместимости с сохранёнными датами бота."""
    return datetime.now(MOSCOW_TZ).replace(tzinfo=None)

TOKEN = os.getenv("DISCORD_TOKEN")

# Включаем только необходимые Gateway Intents. Presence, typing и voice-state
# события бот не использует; их отключение уменьшает поток событий и нагрузку.
intents = discord.Intents.default()
intents.members = True          # список участников и роли для проверок доступа
intents.message_content = True  # префиксные команды и регистрация в ЛС
intents.guild_reactions = True  # реакции на квестах и подтверждение регистрации
intents.dm_reactions = True
intents.presences = False
intents.typing = False
intents.guild_typing = False
intents.dm_typing = False
intents.voice_states = False
bot = commands.Bot(command_prefix='.', intents=intents)

# === НАСТРОЙКИ ===

RANK_COEFFICIENTS = {'F': 2.0, 'E': 5.0, 'D': 10.0, 'C': 20.0, 'B': 40.0, 'A': 60.0, 'S': 80.0}
RANK_POINTS_REQUIRED = {'F': 0, 'E': 10, 'D': 30, 'C': 100, 'B': 200, 'A': 500, 'S': 1000}
MAX_TASKS_PER_RANK = {'F': 10, 'E': 8, 'D': 5, 'C': 3, 'B': 100, 'A': 100, 'S': 100}
MIN_TASKS_PER_RANK = {'F': 1, 'E': 2, 'D': 2, 'C': 3, 'B': 3, 'A': 4, 'S': 5}
MIN_TASKS_PENALTY_PER_TASK = {'F': 2, 'E': 5, 'D': 10, 'C': 25, 'B': 50, 'A': 100, 'S': 200}

MAX_BONUS_PER_RANK = {'F': 20, 'E': 30, 'D': 32, 'C': 40, 'B': 48, 'A': 50, 'S': 55}
RANK_DIFF_BONUS = {0: 0, 1: 50, 2: 80}
BASE_TASK_FAIL_PENALTY = {'F': 0.5, 'E': 2, 'D': 3, 'C': 12, 'B': 25, 'A': 75, 'S': 150}
PENALTY_DIFF_MULTIPLIER = {0: 1.0, 1: 2.0, 2: 3.0}

QUEST_TAKE_REACTION = '✋'
QUEST_CONFIRM_REACTION = '✅'

VACATION_COOLDOWN_DAYS = 14
INVITE_CODE_TTL_HOURS = 24

GUILD_LEADER_ROLES = {
    'шахтёры': 1543957261238403082,
    'архитекторы': 1543958583346077747,
    'торговцы': 1543958540463513661,
    'СОБР': 1543958512382648341
}

RANK_ROLES = {
    'шахтёры': {'F': 1543961246792028230, 'E': 1543961299296456854, 'D': 1543961321748299837,
                'C': 1543957372773605526, 'B': 1543957352217059518, 'A': 1543957310383325184, 'S': 1543957299020693515},
    'архитекторы': {'F': 1543969717796995212, 'E': 1543969155802206300, 'D': 1543967903299407872,
                    'C': 1543967523500986408, 'B': 1543967042053341264, 'A': 1543966125698711572,
                    'S': 1543965596364972074},
    'торговцы': {'F': 1543982197462278284, 'E': 1543981699531284621, 'D': 1543980799194431518,
                 'C': 1543980298910302359, 'B': 1543979826677809222, 'A': 1543979268424470680,
                 'S': 1543978951901454456},
    'СОБР': {'F': 1543987560576192515, 'E': 1543987259374575706, 'D': 1543986865470709994,
             'C': 1543986350116569209, 'B': 1543986100438310962, 'A': 1543985766227509418, 'S': 1543985428334379059}
}

GUILD_CATEGORIES = {
    'шахтёры': 1543986476587683860,
    'архитекторы': 1543986994311336037,
    'торговцы': 1543987089379688601,
    'СОБР': 1543987133092724736
}

GUILD_REPORT_CHANNELS = {
    'шахтёры': 1545144250109264062,
    'архитекторы': 1545143820163883078,
    'торговцы': 1545143871325995038,
    'СОБР': 1545144227787317318
}

GUILD_QUEST_BOARDS = {'шахтёры': 1547610184887836693, 'архитекторы': 1547578745093890058,
                      'торговцы': 1547598571405049876, 'СОБР': 1547626299844206663}

GUILD_NAMES = ['шахтёры', 'архитекторы', 'торговцы', 'СОБР']
GUILD_EMOJIS = {'шахтёры': '⛏️', 'архитекторы': '🏛️', 'торговцы': '💰', 'СОБР': '🛡️'}
RANK_ORDER = ['F', 'E', 'D', 'C', 'B', 'A', 'S']
RANK_ORDER_REV = RANK_ORDER[::-1]

DATA_FILE = 'guild_data.json'
TEMPLATES_FILE = 'quest_templates.json'

DEFAULT_TEMPLATES = {
    'mining_diamond': {'name': '💎 Добыть 64 алмаза', 'description': 'Добудьте 64 алмаза в шахте', 'bonus': 15,
                       'time_limit': 1440, 'category': '⛏️ Добыча', 'type': 'weekly'},
    'mining_iron': {'name': '⛏️ Добыть 128 железа', 'description': 'Добудьте 128 железной руды', 'bonus': 10,
                    'time_limit': 720, 'category': '⛏️ Добыча', 'type': 'weekly'},
    'build_house': {'name': '🏠 Построить дом', 'description': 'Постройте дом размером минимум 10x10', 'bonus': 20,
                    'time_limit': 2880, 'category': '🏗️ Строительство', 'type': 'weekly'},
    'build_farm': {'name': '🌾 Построить ферму', 'description': 'Постройте автоматическую ферму', 'bonus': 25,
                   'time_limit': 2880, 'category': '🏗️ Строительство', 'type': 'weekly'},
    'kill_mobs': {'name': '⚔️ Убить 50 мобов', 'description': 'Убейте 50 враждебных мобов', 'bonus': 10,
                  'time_limit': 720, 'category': '⚔️ Бой', 'type': 'daily'},
    'kill_boss': {'name': '🐉 Убить босса', 'description': 'Убейте дракона Края или Иссушителя', 'bonus': 30,
                  'time_limit': 1440, 'category': '⚔️ Бой', 'type': 'weekly'},
    'explore_village': {'name': '🧭 Найти деревню', 'description': 'Найдите и отметьте координаты деревни', 'bonus': 8,
                        'time_limit': 360, 'category': '🧭 Исследование', 'type': 'daily'},
    'explore_biome': {'name': '🗺️ Найти биом', 'description': 'Найдите редкий биом (грибной остров, багровый лес)',
                      'bonus': 12, 'time_limit': 720, 'category': '🧭 Исследование', 'type': 'weekly'},
    'trade_items': {'name': '💰 Продать 100 предметов', 'description': 'Продайте 100 любых предметов торговцу',
                    'bonus': 8, 'time_limit': 720, 'category': '💰 Торговля', 'type': 'weekly'},
    'craft_armor': {'name': '🛡️ Скрафтить алмазную броню', 'description': 'Создайте полный сет алмазной брони',
                    'bonus': 20, 'time_limit': 1440, 'category': '🛠️ Крафт', 'type': 'weekly'},
    'guard_patrol': {'name': '🛡️ Патруль территории', 'description': 'Патрулируйте территорию города 30 минут',
                     'bonus': 10, 'time_limit': 60, 'category': '🛡️ СОБР', 'type': 'daily'},
    'guard_catch': {'name': '🚔 Поймать нарушителя', 'description': 'Поймайте нарушителя порядка на территории',
                    'bonus': 20, 'time_limit': 1440, 'category': '🛡️ СОБР', 'type': 'weekly'},
}


def _atomic_write_json(path: str, payload: Any) -> None:
    """Сохраняет JSON атомарно; перед заменой оставляет резервную копию."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='.bot-save-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            backup_path = path + '.bak'
            shutil.copy2(path, backup_path)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _load_json_safely(path: str, fallback: Any) -> Any:
    if not os.path.exists(path):
        backup_path = path + '.bak'
        if os.path.exists(backup_path):
            try:
                with open(backup_path, 'r', encoding='utf-8') as f:
                    restored = json.load(f)
                shutil.copy2(backup_path, path)
                print(f'⚠️ Основной файл {path} отсутствует; восстановлена резервная копия.')
                return restored
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f'Не удалось прочитать резервную копию {backup_path}: {exc}') from exc
        return fallback
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        backup_path = path + '.bak'
        if os.path.exists(backup_path):
            try:
                with open(backup_path, 'r', encoding='utf-8') as f:
                    restored = json.load(f)
                shutil.copy2(backup_path, path)
                print(f'⚠️ {path} повреждён; восстановлена резервная копия {backup_path}: {exc}')
                return restored
            except (OSError, json.JSONDecodeError) as backup_exc:
                raise RuntimeError(f'Не удалось прочитать {path} и резервную копию: {backup_exc}') from exc
        # Не заменяем повреждённый файл пустыми данными: это может уничтожить прогресс.
        raise RuntimeError(f'Файл {path} повреждён, резервной копии нет. Исправьте файл или восстановите копию: {exc}') from exc


def load_data() -> Dict[str, Any]:
    return _load_json_safely(DATA_FILE, {
        'players': {}, 'registered_users': [], 'selection_messages': {},
        'temp_nick': {}, 'temp_code': {}, 'temp_individual_registration': {}, 'invite_codes': {},
        'quests': {}, 'player_quests': {}, 'weekly_history': {},
        'vacations': {}, 'vacation_cooldowns': {}, 'last_reset_week': None
    })


def load_templates() -> Dict[str, Any]:
    loaded = _load_json_safely(TEMPLATES_FILE, DEFAULT_TEMPLATES.copy())
    if not isinstance(loaded, dict):
        raise RuntimeError(f'Файл {TEMPLATES_FILE} должен содержать JSON-объект.')
    if not os.path.exists(TEMPLATES_FILE):
        _atomic_write_json(TEMPLATES_FILE, loaded)
    return loaded


def save_data() -> None:
    try:
        _atomic_write_json(DATA_FILE, data)
    except Exception as e:
        print(f'❌ Ошибка сохранения данных: {e}')
        raise


def save_templates() -> None:
    _atomic_write_json(TEMPLATES_FILE, quest_templates)


def save_config():
    cfg = {'categories': GUILD_CATEGORIES, 'report_channels': GUILD_REPORT_CHANNELS, 'quest_boards': GUILD_QUEST_BOARDS}
    try:
        _atomic_write_json('guild_categories_config.json', cfg)
    except Exception as e:
        print(f'⚠️ Ошибка конфига: {e}')


data = load_data()
quest_templates = load_templates()
QUEST_SCHEDULE_FILE = 'quest_schedule_config.json'
quest_schedules = _load_json_safely(QUEST_SCHEDULE_FILE, {})
if not isinstance(quest_schedules, dict):
    quest_schedules = {}
weekly_reset_lock = asyncio.Lock()

# Банковские модули подключаются после загрузки конфигурации Discord.
credit_daily_checker = None
bank_daily_checker = None
bank_api = None

_DICT_DEFAULTS = {
    'players': {}, 'selection_messages': {}, 'temp_nick': {}, 'temp_code': {}, 'temp_individual_registration': {}, 'invite_codes': {},
    'quests': {}, 'player_quests': {}, 'weekly_history': {}, 'vacations': {}, 'vacation_cooldowns': {}
}
for _key, _default in _DICT_DEFAULTS.items():
    if not isinstance(data.get(_key), dict):
        data[_key] = _default.copy()
data.setdefault('temp_individual_registration', {})
if not isinstance(data.get('temp_individual_registration'), dict):
    data['temp_individual_registration'] = {}
if not isinstance(data.get('registered_users'), list):
    data['registered_users'] = [int(uid) if str(uid).isdigit() else uid for uid in data.get('players', {}).keys()]
data.setdefault('last_reset_week', None)




# === ЛИЧНЫЙ КАБИНЕТ, ДОСТИЖЕНИЯ И ТИТУЛЫ ===
# area_bonus задаётся в дополнительных блоках территории (условных единицах площади).
# Все значения по умолчанию равны 0: конкретные бонусы намеренно не настроены.
ACHIEVEMENT_CATALOG = {
    'first_task': {'name': 'Первое дело', 'description': 'Выполнить первое задание', 'metric': 'lifetime_tasks_total', 'threshold': 1, 'title_id': 'pioneer'},
    'tasks_10': {'name': 'Надёжный исполнитель', 'description': 'Выполнить 10 заданий за всё время', 'metric': 'lifetime_tasks_total', 'threshold': 10, 'title_id': 'executor'},
    'points_100': {'name': 'Первые высоты', 'description': 'Набрать 100 очков ранга', 'metric': 'rank_points', 'threshold': 100, 'title_id': 'climber'},
    'rank_c': {'name': 'Профессионал', 'description': 'Достичь ранга C или выше', 'metric': 'rank', 'threshold': 'C', 'title_id': 'professional'},
    'quests_5': {'name': 'Мастер квестов', 'description': 'Завершить 5 квестов', 'metric': 'lifetime_quests_completed', 'threshold': 5, 'title_id': 'quest_master'},
}
TITLE_CATALOG = {
    'pioneer': {'name': 'Первопроходец', 'description': 'За первое выполненное задание', 'achievement_id': 'first_task', 'area_bonus': 0},
    'executor': {'name': 'Исполнитель', 'description': 'За 10 выполненных заданий', 'achievement_id': 'tasks_10', 'area_bonus': 0},
    'climber': {'name': 'Покоритель высот', 'description': 'За 100 очков ранга', 'achievement_id': 'points_100', 'area_bonus': 0},
    'professional': {'name': 'Профессионал', 'description': 'За достижение ранга C', 'achievement_id': 'rank_c', 'area_bonus': 0},
    'quest_master': {'name': 'Мастер квестов', 'description': 'За 5 завершённых квестов', 'achievement_id': 'quests_5', 'area_bonus': 0},
}

def _achievement_unlocked(player: Dict[str, Any], achievement_id: str) -> bool:
    spec = ACHIEVEMENT_CATALOG.get(achievement_id)
    if not spec:
        return False
    metric = spec['metric']
    if metric == 'rank':
        rank = str(player.get('rank', 'F')).upper()
        return rank in RANK_ORDER and RANK_ORDER.index(rank) >= RANK_ORDER.index(spec['threshold'])
    try:
        return float(player.get(metric, 0) or 0) >= float(spec['threshold'])
    except (TypeError, ValueError):
        return False

def refresh_player_progress(player: Dict[str, Any]) -> List[str]:
    """Открывает новые достижения/титулы идемпотентно и возвращает новые достижения."""
    achievements = player.setdefault('achievements', [])
    titles = player.setdefault('unlocked_titles', [])
    if not isinstance(achievements, list):
        achievements = player['achievements'] = []
    if not isinstance(titles, list):
        titles = player['unlocked_titles'] = []
    newly_unlocked = []
    for achievement_id, spec in ACHIEVEMENT_CATALOG.items():
        if _achievement_unlocked(player, achievement_id) and achievement_id not in achievements:
            achievements.append(achievement_id)
            newly_unlocked.append(achievement_id)
        if achievement_id in achievements:
            title_id = spec.get('title_id')
            if title_id in TITLE_CATALOG and title_id not in titles:
                titles.append(title_id)
    active = player.get('active_title')
    if active not in titles:
        player['active_title'] = titles[0] if titles else None
    return newly_unlocked

def get_active_title_name(player: Dict[str, Any]) -> str:
    refresh_player_progress(player)
    title_id = player.get('active_title')
    return TITLE_CATALOG.get(title_id, {}).get('name', 'Без титула')

def calculate_territory_limit(base_area: float, player: Dict[str, Any]) -> float:
    """Базовая площадь + бонус активного титула; по умолчанию бонусы не настроены."""
    try:
        base = max(0.0, float(base_area))
    except (TypeError, ValueError):
        raise ValueError('Базовая площадь должна быть числом.')
    refresh_player_progress(player)
    title = TITLE_CATALOG.get(player.get('active_title'), {})
    bonus = max(0.0, float(title.get('area_bonus', 0) or 0))
    result = base + bonus
    return int(result) if result.is_integer() else round(result, 2)


def normalize_guild_name(value: str) -> Optional[str]:
    """Возвращает каноническое имя гильдии независимо от регистра и пробелов."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return next((name for name in GUILD_NAMES if name.casefold() == normalized), None)


def interaction_can_manage_guild(interaction: discord.Interaction, guild_name: str,
                                 creator_id: Optional[int] = None) -> bool:
    """Повторная проверка автора меню и прав при каждом UI-взаимодействии."""
    if creator_id is not None and interaction.user.id != creator_id:
        return False
    if not interaction.guild or not hasattr(interaction.user, 'roles'):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    canonical = normalize_guild_name(guild_name)
    role_id = GUILD_LEADER_ROLES.get(canonical) if canonical else None
    return bool(role_id and discord.utils.get(interaction.user.roles, id=role_id))


def interaction_can_manage_any_guild(interaction: discord.Interaction, creator_id: Optional[int] = None) -> bool:
    if creator_id is not None and interaction.user.id != creator_id:
        return False
    if not interaction.guild or not hasattr(interaction.user, 'roles'):
        return False
    return bool(interaction.user.guild_permissions.administrator or any(
        discord.utils.get(interaction.user.roles, id=role_id) for role_id in GUILD_LEADER_ROLES.values()))

class AuthorizedView(discord.ui.View):
    """UI-панель, доступная только её создателю с актуальными правами."""
    def __init__(self, *, creator_id: int, guild_name: Optional[str] = None,
                 any_guild: bool = False, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.creator_id = creator_id
        self.guild_name = guild_name
        self.any_guild = any_guild

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        allowed = (interaction_can_manage_any_guild(interaction, self.creator_id) if self.any_guild
                   else interaction_can_manage_guild(interaction, self.guild_name or '', self.creator_id))
        if not allowed:
            try:
                await interaction.response.send_message(
                    '❌ Это меню доступно только создавшему его уполномоченному пользователю.', ephemeral=True)
            except discord.InteractionResponded:
                await interaction.followup.send('❌ Недостаточно прав для этого действия.', ephemeral=True)
        return allowed


def get_current_week_key() -> str:
    iso = now_msk().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def get_week_start_datetime() -> datetime:
    now = now_msk()
    start = now - timedelta(days=now.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def get_next_week_start() -> datetime:
    return get_week_start_datetime() + timedelta(days=7)


def get_time_until_next_week() -> timedelta:
    return get_next_week_start() - now_msk()


def generate_random_code(length: int = 5) -> str:
    chars = string.digits + string.ascii_uppercase
    chars = chars.replace('0', '').replace('O', '').replace('1', '').replace('I', '')
    return ''.join(secrets.choice(chars) for _ in range(length))


def get_points_to_next_rank(points: int, current_rank: str) -> int:
    if current_rank == RANK_ORDER[-1]: return 0
    return max(0, RANK_POINTS_REQUIRED[RANK_ORDER[RANK_ORDER.index(current_rank) + 1]] - points)


def get_next_rank(current_rank: str) -> Optional[str]:
    idx = RANK_ORDER.index(current_rank)
    return RANK_ORDER[idx + 1] if idx < len(RANK_ORDER) - 1 else None


def get_rank_diff(player_rank: str, task_rank: str) -> int:
    return max(0, RANK_ORDER.index(task_rank) - RANK_ORDER.index(player_rank))


def can_take_task(player_rank: str, task_rank: str) -> bool:
    return player_rank in RANK_ORDER and task_rank in RANK_ORDER and get_rank_diff(player_rank, task_rank) <= 2


def can_add_tasks(rank: str, completed: int, requested: int) -> bool:
    """Проверяет недельный лимит, включая пакетное начисление."""
    if rank not in MAX_TASKS_PER_RANK or requested < 1 or completed < 0:
        return False
    return completed + requested <= MAX_TASKS_PER_RANK[rank]


def calculate_penalty(task_rank: str, rank_diff: int) -> int:
    return max(1, round(BASE_TASK_FAIL_PENALTY.get(task_rank, 5) * PENALTY_DIFF_MULTIPLIER.get(rank_diff, 1.0)))


def calculate_salary(rank: str, tasks: int, quest_bonus: float, rank_diff: int = 0) -> float:
    """Расчёт зарплаты для одной группы одинаковых заданий."""
    base = RANK_COEFFICIENTS.get(rank, 1.0) * max(0, tasks)
    base *= 1 + RANK_DIFF_BONUS.get(rank_diff, 0) / 100
    return round(base * (1 + max(0.0, quest_bonus) / 100), 2)


def player_weekly_salary(player: Dict[str, Any]) -> float:
    """Единый расчёт недельной зарплаты по накопленной базе начислений."""
    base = player.get('weekly_salary_base')
    if base is None:
        base = RANK_COEFFICIENTS.get(player.get('rank', 'F'), 1.0) * max(0, player.get('completed_tasks', 0))
    bonus = max(0.0, float(player.get('quest_bonus', 0.0) or 0.0))
    return round(float(base) * (1 + bonus / 100), 2)


def add_task_salary_base(player: Dict[str, Any], tasks: int, task_rank_diff: int = 0) -> None:
    rank = player.get('rank', 'F')
    diff_bonus = RANK_DIFF_BONUS.get(task_rank_diff, 0)
    base = RANK_COEFFICIENTS.get(rank, 1.0) * max(0, tasks) * (1 + diff_bonus / 100)
    player['weekly_salary_base'] = float(player.get('weekly_salary_base',
        RANK_COEFFICIENTS.get(rank, 1.0) * max(0, player.get('completed_tasks', 0) - tasks))) + base


def calculate_rank_up(points: int, current_rank: str) -> tuple:
    """Проверяет общие накопленные пороги. Очки не расходуются при повышении."""
    if current_rank not in RANK_ORDER:
        current_rank = 'F'
    points = max(0, int(points))
    current_index = RANK_ORDER.index(current_rank)
    new_index = current_index
    for index in range(current_index + 1, len(RANK_ORDER)):
        if points >= RANK_POINTS_REQUIRED[RANK_ORDER[index]]:
            new_index = index
        else:
            break
    new_rank = RANK_ORDER[new_index]
    return new_rank, points, new_index - current_index


def calculate_min_tasks_penalty(rank: str, completed: int) -> int:
    minimum = MIN_TASKS_PER_RANK.get(rank, 1)
    if completed >= minimum: return 0
    return (minimum - completed) * MIN_TASKS_PENALTY_PER_TASK.get(rank, 5)


def is_on_vacation(user_id: str) -> bool:
    vac = data.get('vacations', {}).get(user_id)
    if not vac: return False
    try:
        end_date = datetime.fromisoformat(vac['end_date'])
    except (ValueError, KeyError):
        data['vacations'].pop(user_id, None)
        return False
    if now_msk() > end_date:
        data['vacations'].pop(user_id, None)
        return False
    return True


def get_vacation_info(user_id: str) -> Optional[Dict]:
    return data.get('vacations', {}).get(user_id) if is_on_vacation(user_id) else None


def can_take_vacation(user_id: str) -> tuple:
    if is_on_vacation(user_id):
        vac = data['vacations'][user_id]
        try:
            end_date = datetime.fromisoformat(vac['end_date'])
        except:
            return False, '❌ Ошибка данных отпуска.'
        return False, f'Вы уже в отпуске до **{end_date.strftime("%d.%m.%Y %H:%M")}**'

    last = data.get('vacation_cooldowns', {}).get(user_id)
    if last:
        try:
            last_end = datetime.fromisoformat(last['end_date'])
        except:
            return True, None
        cooldown_end = last_end + timedelta(days=VACATION_COOLDOWN_DAYS)
        if now_msk() < cooldown_end:
            remaining = cooldown_end - now_msk()
            return False, f'Следующий отпуск через **{remaining.days}д {remaining.seconds // 3600}ч**\n📅 Дата: **{cooldown_end.strftime("%d.%m.%Y %H:%M")}**'
    return True, None


def record_vacation_end(user_id: str, end_date: datetime) -> None:
    data.setdefault('vacation_cooldowns', {})[user_id] = {
        'end_date': end_date.isoformat(),
        'recorded_at': now_msk().isoformat()
    }
    save_data()


async def update_rank_roles(member: Optional[discord.Member], new_rank: str, guild_name: str) -> bool:
    if not member or not member.guild:
        return False
    canonical = normalize_guild_name(guild_name)
    if not canonical or new_rank not in RANK_ORDER:
        return False
    guild_roles = RANK_ROLES.get(canonical, {})
    new_role_id = guild_roles.get(new_rank)
    new_role = member.guild.get_role(new_role_id) if new_role_id else None
    if not new_role:
        print(f'⚠️ Не найдена роль ранга {new_rank} для гильдии {canonical}')
        return False
    try:
        # Сначала назначаем новую роль, чтобы при ошибке не оставить игрока без ранга.
        if new_role not in member.roles:
            await member.add_roles(new_role, reason='Синхронизация ранга RPG-бота')
        stale_roles = [role for role_id in guild_roles.values()
                       if (role := member.guild.get_role(role_id)) and role != new_role and role in member.roles]
        if stale_roles:
            await member.remove_roles(*stale_roles, reason='Удаление устаревших ролей ранга RPG-бота')
        return True
    except discord.Forbidden:
        print(f'❌ Недостаточно прав для изменения ранга пользователя {member.id} в {canonical}')
    except discord.HTTPException as exc:
        print(f'❌ Discord API не смог обновить ранг пользователя {member.id}: {exc}')
    return False


async def remove_all_rank_roles(member: discord.Member, guild_name: str) -> None:
    if not member or not member.guild:
        return
    canonical = normalize_guild_name(guild_name)
    if not canonical:
        return
    roles = [role for role_id in RANK_ROLES.get(canonical, {}).values()
             if (role := member.guild.get_role(role_id)) and role in member.roles]
    if not roles:
        return
    try:
        await member.remove_roles(*roles, reason='Удаление ролей ранга RPG-бота')
    except discord.Forbidden:
        print(f'❌ Недостаточно прав для удаления ролей ранга пользователя {member.id}')
    except discord.HTTPException as exc:
        print(f'❌ Discord API не смог удалить роли ранга пользователя {member.id}: {exc}')


def get_guild_from_category(ctx: commands.Context) -> Optional[str]:
    if not ctx.guild or not hasattr(ctx.channel, 'category') or not ctx.channel.category: return None
    for guild, category_id in GUILD_CATEGORIES.items():
        if ctx.channel.category.id == category_id:
            return guild
    return None


def get_user_role(ctx: commands.Context) -> str:
    if ctx.author.guild_permissions.administrator: return 'admin'
    if hasattr(ctx.author, 'roles'):
        for role_id in GUILD_LEADER_ROLES.values():
            if discord.utils.get(ctx.author.roles, id=role_id): return 'leader'
    return 'player' if str(ctx.author.id) in data.get('players', {}) else 'none'


def get_leader_guild(ctx: commands.Context) -> Optional[str]:
    if not hasattr(ctx.author, 'roles'): return None
    for guild, role_id in GUILD_LEADER_ROLES.items():
        if discord.utils.get(ctx.author.roles, id=role_id): return guild
    return None


def is_registered(user_id: str) -> bool:
    return user_id in data.get('players', {})


def find_player_by_nick(nick: str, guild: str) -> tuple:
    for uid, p in data.get('players', {}).items():
        if p.get('minecraft_nick', '').casefold() == nick.strip().casefold() and normalize_guild_name(p.get('guild', '')) == normalize_guild_name(guild):
            return uid, p
    return None, None


def get_quest_by_thread_or_message(message_id: int) -> Optional[Dict]:
    for qid, q in data.get('quests', {}).items():
        if q.get('message_id') == message_id:
            return {'id': qid, **q}
    return None

def generate_quest_id() -> str:
    """Генерирует уникальный короткий ID квеста."""
    qid = generate_random_code(6).upper()
    while qid in data.setdefault('quests', {}):
        qid = generate_random_code(6).upper()
    return qid


def get_player_quest(quest_id: str, user_id: str) -> Optional[Dict]:
    return data.get('player_quests', {}).get(quest_id, {}).get(user_id)


def parse_duration_minutes(value: str) -> int:
    """Принимает минуты (старый формат) или сочетания 1д 2ч 30м / 1d 2h 30m."""
    raw = str(value or '').strip().lower().replace(',', ' ')
    if not raw:
        raise ValueError('Укажите срок или 0 для бесконечного срока.')
    if raw.isdigit():
        minutes = int(raw)
    else:
        aliases = {'д': 1440, 'дн': 1440, 'дн.': 1440, 'день': 1440, 'дня': 1440, 'дней': 1440,
                   'd': 1440, 'day': 1440, 'days': 1440,
                   'ч': 60, 'ч.': 60, 'час': 60, 'часа': 60, 'часов': 60,
                   'h': 60, 'hr': 60, 'hrs': 60, 'hour': 60, 'hours': 60,
                   'м': 1, 'мин': 1, 'мин.': 1, 'минута': 1, 'минуты': 1, 'минут': 1,
                   'm': 1, 'min': 1, 'mins': 1, 'minute': 1, 'minutes': 1}
        tokens = re.findall(r'(\d+)\s*([a-zа-яё.]+)', raw)
        residue = re.sub(r'(\d+)\s*([a-zа-яё.]+)', '', raw).strip()
        if not tokens or residue:
            raise ValueError('Используйте минуты (например 90) или формат 1д 2ч 30м.')
        minutes = 0
        for amount, unit in tokens:
            if unit not in aliases:
                raise ValueError(f'Неизвестная единица времени: {unit}')
            minutes += int(amount) * aliases[unit]
    if not 0 <= minutes <= 525600:
        raise ValueError('Срок должен быть от 0 до 525600 минут (365 дней).')
    return minutes


def format_duration(minutes: int) -> str:
    minutes = int(minutes or 0)
    if minutes <= 0:
        return '∞ (без ограничения)'
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    parts = []
    if days: parts.append(f'{days} дн.')
    if hours: parts.append(f'{hours} ч.')
    if mins: parts.append(f'{mins} мин.')
    return ' '.join(parts)


def parse_clock(value: str) -> tuple[int, int]:
    match = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*', value or '')
    if not match:
        raise ValueError('Время укажите в формате ЧЧ:ММ, например 08:30.')
    hour, minute = map(int, match.groups())
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError('Время должно быть в пределах 00:00–23:59.')
    return hour, minute


WEEKDAY_ALIASES = {'mon': 0, 'monday': 0, 'пн': 0, 'понедельник': 0,
                   'tue': 1, 'tuesday': 1, 'вт': 1, 'вторник': 1,
                   'wed': 2, 'wednesday': 2, 'ср': 2, 'среда': 2,
                   'thu': 3, 'thursday': 3, 'чт': 3, 'четверг': 3,
                   'fri': 4, 'friday': 4, 'пт': 4, 'пятница': 4,
                   'sat': 5, 'saturday': 5, 'сб': 5, 'суббота': 5,
                   'sun': 6, 'sunday': 6, 'вс': 6, 'воскресенье': 6}
WEEKDAY_NAMES = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']


def save_quest_schedules() -> None:
    _atomic_write_json(QUEST_SCHEDULE_FILE, quest_schedules)


def get_templates_by_category(category: str = None) -> List[Dict]:
    return [{'id': tid, **t} for tid, t in quest_templates.items() if not category or t.get('category') == category]


def get_template_categories() -> List[str]:
    return sorted(list(set(t['category'] for t in quest_templates.values() if 'category' in t)))


def get_template(template_id: str) -> Optional[Dict]:
    return quest_templates.get(template_id)


def quest_reward_config(source: Dict[str, Any]) -> Dict[str, Any]:
    """Нормализует награду; старые квесты по умолчанию остаются без предметной награды."""
    diamonds = max(0, int(source.get('reward_diamonds', 0) or 0))
    xp = max(0, int(source.get('reward_xp', 0) or 0))
    reward_type = 'diamonds_xp' if (diamonds > 0 or xp > 0) else 'salary_only'
    return {'reward_type': reward_type, 'reward_diamonds': diamonds, 'reward_xp': xp}


def parse_reward_amount(value: str) -> int:
    amount = int(str(value or '').strip())
    if amount < 0 or amount > 1000000:
        raise ValueError('Награда должна быть целым числом от 0 до 1000000.')
    return amount


def parse_reward_pair(value: str) -> Dict[str, Any]:
    """Читает пару «алмазы, XP»; нули означают отсутствие соответствующей награды."""
    parts = [part.strip() for part in str(value or '').replace(';', ',').split(',')]
    if len(parts) != 2:
        parts = str(value or '').split()
    if len(parts) != 2:
        raise ValueError('Введите два целых числа через запятую: алмазы, XP (например 100, 50).')
    reward = {'reward_diamonds': parse_reward_amount(parts[0]), 'reward_xp': parse_reward_amount(parts[1])}
    return {**reward, **quest_reward_config(reward)}


def quest_reward_label(source: Dict[str, Any]) -> str:
    reward = quest_reward_config(source)
    if reward['reward_type'] == 'salary_only':
        return '🎁 Дополнительной награды нет; бонус к зарплате сохраняется'
    return f"💎 **Награда:** {reward['reward_diamonds']} алмазов · ✨ **Опыт:** {reward['reward_xp']} XP"


def apply_quest_completion(player: Dict[str, Any], quest: Dict[str, Any], participant: Dict[str, Any],
                           confirmed_by: int, confirmed_at: str) -> Dict[str, Any]:
    """Выдаёт процентный бонус всегда, а предметную награду только регистрирует к выдаче."""
    player['quest_bonus'] = float(player.get('quest_bonus', 0.0)) + float(quest.get('bonus', 0.0))
    player['lifetime_quests_completed'] = int(player.get('lifetime_quests_completed', 0) or 0) + 1
    reward = quest_reward_config(quest)
    participant.update({'status': 'confirmed', 'confirmed_at': confirmed_at, 'confirmed_by': confirmed_by})
    participant['reward_type'] = reward['reward_type']
    participant['reward_diamonds'] = reward['reward_diamonds']
    participant['reward_xp'] = reward['reward_xp']
    participant['reward_status'] = 'pending' if reward['reward_type'] == 'diamonds_xp' else 'not_required'
    if reward['reward_type'] == 'diamonds_xp':
        participant['reward_pending_at'] = confirmed_at
    return reward


async def perform_weekly_reset():
    async with weekly_reset_lock:
        await _perform_weekly_reset_locked()


async def _perform_weekly_reset_locked():
    now = now_msk()
    current_week_key = get_current_week_key()
    week_key = f"{(now - timedelta(days=7)).isocalendar().year}-W{(now - timedelta(days=7)).isocalendar().week:02d}"
    promotions, role_updates, min_penalties = {}, [], {}
    weekly_snapshot = {'week': week_key, 'date': now.strftime('%d.%m.%Y'), 'players': {}}

    for uid, p in data.get('players', {}).items():
        old_rank = p.get('rank', 'F')
        points = p.get('rank_points', 0)
        tasks = p.get('completed_tasks', 0)
        quest_bonus = p.get('quest_bonus', 0.0)
        on_vacation = is_on_vacation(uid)

        if not on_vacation:
            penalty = calculate_min_tasks_penalty(old_rank, tasks)
            if penalty > 0:
                points = max(0, points - penalty)
                p['rank_points'] = points
                min_penalties[uid] = {'rank': old_rank, 'completed': tasks,
                                      'required': MIN_TASKS_PER_RANK.get(old_rank, 1), 'penalty': penalty,
                                      'nick': p.get('minecraft_nick', '?')}

        weekly_snapshot['players'][uid] = {'nick': p.get('minecraft_nick', '?'), 'guild': p.get('guild'),
                                           'rank': old_rank, 'points': points, 'tasks': tasks,
                                           'quest_bonus': quest_bonus,
                                           'salary': player_weekly_salary(p),
                                           'on_vacation': on_vacation}

        new_rank, remaining, count = calculate_rank_up(points, old_rank)
        if count:
            p['rank'] = new_rank
            p['rank_points'] = remaining
            promotions[uid] = {'old': old_rank, 'new': new_rank, 'count': count, 'remaining': remaining,
                               'nick': p.get('minecraft_nick', '?'), 'guild': p.get('guild'),
                               'discord_id': p.get('discord_id')}
            role_updates.append((uid, new_rank, p.get('guild')))

    data['weekly_history'][week_key] = weekly_snapshot
    if len(data['weekly_history']) > 12:
        del data['weekly_history'][sorted(data['weekly_history'].keys())[0]]

    # Сначала фиксируем завершение расчёта и сброс состояния. Если процесс упадёт
    # при отправке Discord-отчётов, повторный запуск не применит штрафы второй раз.
    for player in data.get('players', {}).values():
        player['completed_tasks'] = 0
        player['quest_bonus'] = 0.0
        player['weekly_salary_base'] = 0.0
    for quest in data.get('quests', {}).values():
        if quest.get('thread_id'):
            try:
                thread = bot.get_channel(quest['thread_id'])
                if thread and isinstance(thread, discord.Thread):
                    await thread.edit(locked=True, archived=True, reason='Сброс недели')
            except (discord.HTTPException, discord.Forbidden) as exc:
                print(f'⚠️ Не удалось архивировать квест {quest.get("name", "?")}: {exc}')
    data['quests'], data['player_quests'] = {}, {}
    data['last_reset_week'] = current_week_key
    save_data()

    for uid, new_rank, guild in role_updates:
        player = data['players'].get(uid, {})
        role_id = RANK_ROLES.get(guild, {}).get(new_rank)
        for discord_guild in bot.guilds:
            member = discord_guild.get_member(player.get('discord_id'))
            if member and role_id and discord_guild.get_role(role_id):
                await update_rank_roles(member, new_rank, guild)
                break

    for guild in GUILD_NAMES:
        players = []
        for uid, snap in weekly_snapshot['players'].items():
            live_player = data.get('players', {}).get(uid, {})
            if snap.get('guild') != guild:
                continue
            players.append({'uid': uid, 'nick': snap.get('nick', '?'), 'tasks': snap.get('tasks', 0),
                            'points': snap.get('points', 0), 'rank': snap.get('rank', 'F'),
                            'salary': snap.get('salary', 0.0), 'bonus': snap.get('quest_bonus', 0.0),
                            'discord_id': live_player.get('discord_id')})

        if not players: continue

        channel_id = GUILD_REPORT_CHANNELS.get(guild)
        if channel_id:
            channel = bot.get_channel(channel_id)
            if channel:
                embed = discord.Embed(title=f'📊 Отчёт {guild.capitalize()}',
                                      description=f'📅 Неделя: **{week_key}** ({now.strftime("%d.%m.%Y")})',
                                      color=discord.Color.gold())
                promo_text = [f"🎮 **{p['nick']}** | {p['old']} → {p['new']} (+{p['count']})" for p in
                              promotions.values() if p.get('guild') == guild]
                if promo_text: embed.add_field(name='🎉 Повышения!', value='\n'.join(promo_text[:10]), inline=False)
                pen_text = [f"⚠️ **{p['nick']}** ({p['rank']}): {p['completed']}/{p['required']} → -{p['penalty']}" for
                            uid, p in min_penalties.items() if data['players'].get(uid, {}).get('guild') == guild]
                if pen_text: embed.add_field(name='⚠️ Штрафы', value='\n'.join(pen_text[:10]), inline=False)

                lines, total = [], 0
                for p in sorted(players, key=lambda x: RANK_ORDER_REV.index(x['rank'])):
                    total += p['salary']
                    lines.append(
                        f"🎮 **{p['nick']}** | {p['rank']} | ⭐ {p['points']} | 📊 {p['tasks']} | 💰 {p['salary']}")
                embed.add_field(name=f'👥 Игроки ({len(players)})', value='\n'.join(lines[:25]), inline=False)
                embed.add_field(name='💰 Всего', value=f'{total} алмазов', inline=False)
                try:
                    await channel.send(embed=embed)
                except:
                    pass

        for p in players:
            if p.get('discord_id'):
                try:
                    user = await bot.fetch_user(p['discord_id'])
                    if user: await send_weekly_dm(user, p, guild, week_key, promotions.get(p['uid']),
                                                  min_penalties.get(p['uid']))
                except:
                    pass

    print(f'[{now}] ✅ Сброс недели {week_key}')


async def send_weekly_dm(user: discord.User, player: Dict, guild: str, week_key: str, promotion: Optional[Dict],
                         min_penalty: Optional[Dict]):
    history = data.get('weekly_history', {})
    weeks = sorted(history.keys())
    prev_week = next((weeks[i - 1] for i, w in enumerate(weeks) if w == week_key and i > 0), None)

    embed = discord.Embed(title=f'📊 Отчёт за неделю {week_key}', description=f'Гильдия: **{guild.capitalize()}**',
                          color=discord.Color.blue())
    embed.add_field(name='🎮 Ник', value=player['nick'], inline=True)
    embed.add_field(name='🔰 Ранг', value=f'**{player["rank"]}**', inline=True)
    embed.add_field(name='💎 Бонус', value=f'+{player["bonus"]}%', inline=True)
    embed.add_field(name='📊 Заданий', value=f'{player["tasks"]}', inline=True)
    embed.add_field(name='⭐ Очки', value=f'{player["points"]}', inline=True)
    embed.add_field(name='💰 Зарплата', value=f'{player["salary"]}', inline=True)

    if prev_week and prev_week in history:
        prev_data = history[prev_week]['players'].get(player['uid'])
        if prev_data and prev_data.get('salary', 0) > 0:
            diff = player['salary'] - prev_data['salary']
            percent = round((diff / prev_data['salary']) * 100, 1)
            embed.add_field(name='📈 Прошлая неделя', value=f'**{diff:+}** ({percent:+}%) 🎉' if diff > 0 else (
                f'**{diff}** ({percent}%)' if diff < 0 else 'Без изменений'), inline=False)

    if promotion: embed.add_field(name='🎉 ПОВЫШЕНИЕ!',
                                  value=f'**{promotion["old"]}** → **{promotion["new"]}** (осталось {promotion["remaining"]})',
                                  inline=False)
    if min_penalty: embed.add_field(name='⚠️ Штраф за минимум',
                                    value=f'{min_penalty["completed"]}/{min_penalty["required"]} → -{min_penalty["penalty"]} очков',
                                    inline=False)
    if player['rank'] != 'S' and (nr := get_next_rank(player['rank'])): embed.add_field(name='🎯 Цель',
                                                                                        value=f'**{nr}** — нужно {RANK_POINTS_REQUIRED[nr]} очков',
                                                                                        inline=False)

    embed.set_footer(text='Ждём вас на следующей неделе 🚀')
    try:
        await user.send(embed=embed)
    except:
        pass


async def _resolve_channel(channel_id: int):
    channel = bot.get_channel(int(channel_id))
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(int(channel_id))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def _close_scheduled_quests(guild_name: str, quest_type: str, period_key: str) -> int:
    closed = 0
    for qid, quest in list(data.get('quests', {}).items()):
        if (quest.get('guild') != guild_name or quest.get('type') != quest_type
                or quest.get('status') != 'active' or not quest.get('scheduled_auto')):
            continue
        quest['status'] = 'closed'
        quest['closed_at'] = now_msk().isoformat()
        quest['closed_period'] = period_key
        closed += 1
        # Закрытие расписания завершает попытки: подтверждённые участники не затрагиваются.
        for uid, participant in data.get('player_quests', {}).get(qid, {}).items():
            if participant.get('status') != 'taken':
                continue
            penalty = max(0.0, float(quest.get('bonus', 0) or 0) / 2)
            player = data.get('players', {}).get(uid)
            if player:
                player['quest_bonus'] = max(0.0, float(player.get('quest_bonus', 0.0)) - penalty)
            participant.update({'status': 'overdue', 'penalty_applied': penalty,
                                'overdue_at': now_msk().isoformat(), 'closed_by_schedule': True})
        thread = await _resolve_channel(quest.get('thread_id', 0)) if quest.get('thread_id') else None
        if isinstance(thread, discord.Thread):
            try:
                await thread.edit(locked=True, archived=True)
            except discord.HTTPException:
                pass
    if closed:
        save_data()
    return closed


async def _publish_scheduled_quests(guild_name: str, quest_type: str, count: int, period_key: str) -> int:
    board_id = GUILD_QUEST_BOARDS.get(guild_name)
    board = await _resolve_channel(board_id) if board_id else None
    if not isinstance(board, discord.ForumChannel):
        print(f'⚠️ Автоквесты: доска для {guild_name} не настроена или недоступна.')
        return 0
    templates = [(tid, t) for tid, t in quest_templates.items()
                 if str(t.get('type', 'weekly')).lower() == quest_type and t.get('name') and t.get('description')]
    if not templates:
        print(f'⚠️ Автоквесты: нет шаблонов типа {quest_type}.')
        return 0
    chosen = random.sample(templates, min(count, len(templates)))
    created = 0
    for template_id, template in chosen:
        try:
            bonus = min(100.0, max(0.0, float(template.get('bonus', 0))))
            limit = parse_duration_minutes(str(template.get('time_limit', 0)))
            mode = template.get('mode', 'individual')
            if mode not in ('individual', 'group'):
                mode = 'individual'
            qid = generate_quest_id()
            title = f"{'📅 Еженед.' if quest_type == 'weekly' else '📆 Ежедн.'} | {template['name']}"
            body = (f"🆔 **ID квеста: `{qid}`**\n\n🎯 **{template['name']}**\n\n{template['description']}\n\n"
                    f"💎 **Бонус:** +{bonus:g}%\n⏰ **Срок:** {format_duration(limit)}\n"
                    f"📂 **Категория:** {template.get('category', '—')}\n"
                    f"{quest_reward_label(template)}\n\n"
                    f"**Поставьте {QUEST_TAKE_REACTION}, чтобы взять!**")
            thread, message = await create_forum_post(board, title, body)
            data['quests'][qid] = {
                'guild': guild_name, 'name': str(template['name']), 'description': str(template['description']),
                'type': quest_type, 'bonus': bonus, 'time_limit_minutes': limit, 'creator_id': 0,
                'created_at': now_msk().isoformat(), 'thread_id': thread.id, 'message_id': message.id,
                'status': 'active', 'mode': mode, 'template_id': template_id, 'scheduled_auto': True,
                'schedule_period': period_key, **quest_reward_config(template),
            }
            save_data()
            for reaction in (QUEST_TAKE_REACTION, QUEST_CONFIRM_REACTION):
                try:
                    await message.add_reaction(reaction)
                except discord.HTTPException as reaction_error:
                    print(f'⚠️ Не удалось добавить реакцию {reaction} к автоквесту {qid}: {reaction_error}')
            created += 1
        except (discord.HTTPException, ValueError, TypeError, KeyError) as exc:
            print(f'❌ Не удалось опубликовать автоквест {template_id} ({guild_name}): {exc}')
    if created:
        save_data()
    return created


async def process_quest_schedules(now: Optional[datetime] = None) -> None:
    """Проверяет расписания по московскому времени (Europe/Moscow, UTC+3)."""
    # Автоквесты всегда ориентируются на Москву, независимо от часового пояса хостинга.
    # Параметр now оставлен для тестирования расписания с заданной датой/временем.
    now = now or now_msk()
    minute = now.strftime('%H:%M')
    for guild_name, configs in quest_schedules.items():
        if not isinstance(configs, dict) or guild_name not in GUILD_NAMES:
            continue
        for quest_type in ('daily', 'weekly'):
            cfg = configs.get(quest_type)
            if not isinstance(cfg, dict) or not cfg.get('enabled', True):
                continue
            publish_day = cfg.get('publish_day', 'daily' if quest_type == 'daily' else 'mon')
            close_day = cfg.get('close_day', 'daily' if quest_type == 'daily' else 'sun')
            pub_time, close_time = cfg.get('publish_time'), cfg.get('close_time')
            period_key = now.strftime('%Y-%m-%d') if quest_type == 'daily' else now.strftime('%G-W%V')
            day_token = 'daily' if quest_type == 'daily' else now.strftime('%a').lower()
            if minute == pub_time and (publish_day == 'daily' or publish_day == day_token):
                if cfg.get('last_publish_period') != period_key:
                    count = max(1, min(10, int(cfg.get('count', 3))))
                    created = await _publish_scheduled_quests(guild_name, quest_type, count, period_key)
                    if created:
                        cfg['last_publish_period'] = period_key
                        save_quest_schedules()
            if minute == close_time and (close_day == 'daily' or close_day == day_token):
                close_key = period_key
                if cfg.get('last_close_period') != close_key:
                    closed = await _close_scheduled_quests(guild_name, quest_type, close_key)
                    # Mark even if zero: avoids repeated work/logs every minute.
                    cfg['last_close_period'] = close_key
                    save_quest_schedules()
                    if closed:
                        print(f'🔒 Автоквесты: закрыто {closed} ({guild_name}, {quest_type}).')


@tasks.loop(minutes=1)
async def quest_schedule_checker():
    try:
        await process_quest_schedules()
    except Exception as exc:
        print(f'❌ Ошибка расписания квестов: {exc}')


@quest_schedule_checker.before_loop
async def before_quest_schedule_checker():
    await bot.wait_until_ready()


@tasks.loop(minutes=1)
async def weekly_reset_checker():
    current_week = get_current_week_key()
    if data.get('last_reset_week') != current_week:
        print(f'🔄 Новая неделя: {current_week}')
        try:
            await perform_weekly_reset()
        except Exception as exc:
            print(f'❌ Еженедельный сброс не завершён; повторим позже: {exc}')
            return
        data['last_reset_week'] = current_week
        save_data()


@weekly_reset_checker.before_loop
async def before_weekly_reset_checker(): await bot.wait_until_ready()


@tasks.loop(minutes=5)
async def check_overdue_quests():
    now, changed = now_msk(), False
    for quest_id, quest_data in data.get('quests', {}).items():
        if quest_data.get('status') == 'closed' or not quest_data.get('time_limit_minutes'): continue
        for user_id, pq in data.get('player_quests', {}).get(quest_id, {}).items():
            if pq.get('status') != 'taken': continue
            try:
                taken_at = datetime.fromisoformat(pq['taken_at'])
            except:
                continue
            if now > taken_at + timedelta(minutes=quest_data['time_limit_minutes']):
                penalty = max(0.0, float(quest_data.get('bonus', 0) or 0)) / 2
                player = data.get('players', {}).get(user_id)
                if player:
                    player['quest_bonus'] = max(0, player.get('quest_bonus', 0.0) - penalty)
                    pq['status'], pq['penalty_applied'], pq['overdue_at'] = 'overdue', penalty, now.isoformat()
                    changed = True
                    try:
                        if u := await bot.fetch_user(int(user_id)): await u.send(
                            f'⏰ **Квест просрочен!**\n**{quest_data["name"]}**\nШтраф: -{penalty}%')
                    except:
                        pass
    if changed: save_data()


@check_overdue_quests.before_loop
async def before_check_overdue_quests(): await bot.wait_until_ready()



# === СЛУЖЕБНЫЕ ОТЧЁТЫ СОБР ===
SOBR_REPORTS_FILE = 'sobr_reports.json'
SOBR_PRIVATE_CHANNEL_NAME = 'закрытые-отчёты-собр'
SOBR_CREATE_MIN_RANK = 'D'
SOBR_CONFIRM_MIN_RANK = 'B'
SOBR_WEEKLY_HOUR = 10  # понедельник, Europe/Moscow
sobr_reports_data = _load_json_safely(SOBR_REPORTS_FILE, {
    'next_report_id': 1, 'next_violation_id': 1, 'next_fine_id': 1,
    'reports': {}, 'dossiers': {}, 'violations': {}, 'fines': {},
    'inventory_latest': {}, 'weekly_passport_reports': [], 'last_passport_report_week': None,
    'private_channel_id': None
})
for _k, _v in {
    'next_report_id': 1, 'next_violation_id': 1, 'next_fine_id': 1,
    'reports': {}, 'dossiers': {}, 'violations': {}, 'fines': {},
    'inventory_latest': {}, 'weekly_passport_reports': [], 'last_passport_report_week': None,
    'private_channel_id': None
}.items():
    sobr_reports_data.setdefault(_k, _v.copy() if isinstance(_v, (dict, list)) else _v)


def save_sobr_reports():
    _atomic_write_json(SOBR_REPORTS_FILE, sobr_reports_data)


def _sobr_member_rank(member: discord.Member) -> Optional[str]:
    """Returns the member's registered СОБР rank, with Discord rank roles as fallback."""
    player = data.get('players', {}).get(str(member.id))
    if player and normalize_guild_name(player.get('guild', '')) == 'СОБР':
        rank = str(player.get('rank', '')).upper()
        if rank in RANK_ORDER:
            return rank
    for rank in RANK_ORDER_REV:
        role_id = RANK_ROLES.get('СОБР', {}).get(rank)
        if role_id and discord.utils.get(getattr(member, 'roles', []), id=role_id):
            return rank
    if discord.utils.get(getattr(member, 'roles', []), id=GUILD_LEADER_ROLES['СОБР']):
        return 'S'
    return None


def _sobr_has_min_rank(member: discord.Member, minimum: str) -> bool:
    if getattr(member, 'guild_permissions', None) and member.guild_permissions.administrator:
        return True
    rank = _sobr_member_rank(member)
    return bool(rank and RANK_ORDER.index(rank) >= RANK_ORDER.index(minimum))


def _member_in_guild(member: discord.Member, guild_name: str) -> bool:
    """Проверяет членство в гильдии по регистрации, ранговой или лидерской роли."""
    if getattr(member, 'guild_permissions', None) and member.guild_permissions.administrator:
        return True
    player = data.get('players', {}).get(str(member.id), {})
    if normalize_guild_name(player.get('guild', '')) == guild_name:
        return True
    rank_roles = RANK_ROLES.get(guild_name, {})
    if any(discord.utils.get(getattr(member, 'roles', []), id=role_id) for role_id in rank_roles.values()):
        return True
    leader_role_id = GUILD_LEADER_ROLES.get(guild_name)
    return bool(leader_role_id and discord.utils.get(getattr(member, 'roles', []), id=leader_role_id))


def _sobr_report_channel(guild: discord.Guild):
    channel_id = sobr_reports_data.get('private_channel_id')
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if channel:
        return channel
    return discord.utils.get(guild.text_channels, name=SOBR_PRIVATE_CHANNEL_NAME)


async def ensure_sobr_private_channel(guild: discord.Guild):
    channel = _sobr_report_channel(guild)
    if channel:
        # Не записываем тот же ID на диск при каждом повторном вызове.
        if sobr_reports_data.get('private_channel_id') != channel.id:
            sobr_reports_data['private_channel_id'] = channel.id
            save_sobr_reports()
        return channel
    category = guild.get_channel(GUILD_CATEGORIES['СОБР'])
    if category is None:
        # Не создаём канал СОБР на сторонних Discord-серверах, где нет категории гильдии.
        return None
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    bot_member = guild.me
    if bot_member:
        overwrites[bot_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                              read_message_history=True, manage_channels=True)
    # В закрытом канале могут читать отчёты сотрудники ранга D и выше; утверждать нарушения — B и выше.
    for rank in ('D', 'C', 'B', 'A', 'S'):
        role_id = RANK_ROLES['СОБР'].get(rank)
        role = guild.get_role(role_id) if role_id else None
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                           read_message_history=True)
    leader_role = guild.get_role(GUILD_LEADER_ROLES['СОБР'])
    if leader_role:
        overwrites[leader_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                               read_message_history=True)
    try:
        channel = await guild.create_text_channel(SOBR_PRIVATE_CHANNEL_NAME, category=category,
                                                  overwrites=overwrites,
                                                  topic='Закрытый канал служебных отчётов СОБР. Доступ по рангу.')
        sobr_reports_data['private_channel_id'] = channel.id
        save_sobr_reports()
        await channel.send('🛡️ Закрытый канал служебных отчётов СОБР создан. Исходные отчёты сохраняются без перезаписи; исправления добавляются отдельными записями.')
        return channel
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(f'❌ Не удалось создать закрытый канал отчётов СОБР: {exc}')
        return None


def _sobr_parse_people(raw: str, guild: discord.Guild) -> list:
    people = []
    seen_ids = set()
    tokens = [t.strip() for t in re.split(r'[,;\n]+', raw or '') if t.strip()]
    for token in tokens:
        match = re.fullmatch(r'<@!?(\d+)>', token) or re.fullmatch(r'(\d{15,22})', token)
        member = guild.get_member(int(match.group(1))) if match else None
        if not member and not match:
            # Нарушителем может быть любой зарегистрированный игрок, не только сотрудник СОБР.
            for uid, player_record in data.get('players', {}).items():
                if player_record.get('minecraft_nick', '').casefold() == token.casefold():
                    member = guild.get_member(int(uid))
                    if member:
                        break
        if member and str(member.id) not in seen_ids:
            member_id = str(member.id)
            seen_ids.add(member_id)
            player = data.get('players', {}).get(member_id, {})
            people.append({'discord_id': member_id, 'minecraft_nick': player.get('minecraft_nick', member.display_name),
                           'display_name': member.display_name})
    return people


def _sobr_add_to_dossier(user_id: str, entry: dict):
    dossier = sobr_reports_data['dossiers'].setdefault(str(user_id), [])
    if not any(x.get('entry_id') == entry.get('entry_id') for x in dossier):
        dossier.append(entry)


def _sobr_parse_inventory(content: str) -> tuple:
    building = None
    resources = {}
    for line in content.splitlines():
        if line.lower().startswith(('здание:', 'объект:')):
            building = line.split(':', 1)[1].strip()
        elif line.lower().startswith(('ресурсы:', 'остатки:')):
            raw = line.split(':', 1)[1]
            for item in re.split(r'[,;]+', raw):
                if '=' not in item and ':' not in item:
                    continue
                name, amount = re.split(r'[=:]', item, maxsplit=1)
                name = name.strip()
                try:
                    number = int(amount.strip().replace(' ', ''))
                except ValueError:
                    continue
                if name and number >= 0:
                    resources[name] = number
    return building, resources


class SobrReportModal(discord.ui.Modal):
    def __init__(self, report_type: str):
        super().__init__(title=f'Новый отчёт СОБР: {report_type[:35]}')
        self.report_type = report_type
        self.grounds = discord.ui.TextInput(label='Основание и цель отчёта', placeholder='Почему составляется отчёт и что он фиксирует', max_length=700)
        self.people = discord.ui.TextInput(label='Участники / проверяемые лица', placeholder='Упоминания @игроков, ID или Minecraft-ники через запятую', max_length=800, required=False)
        self.content = discord.ui.TextInput(label='Содержание отчёта', placeholder='Для инвентаризации: Здание: ...\nРесурсы: алмазы=10, железо=20', style=discord.TextStyle.paragraph, max_length=3500)
        self.completed_at = discord.ui.TextInput(label='Время выполнения (необязательно)', placeholder='ДД.ММ.ГГГГ ЧЧ:ММ; пусто = сейчас, время МСК', max_length=25, required=False)
        self.offender = discord.ui.TextInput(label='Нарушитель (только для правонарушения)', placeholder='@игрок, ID или Minecraft-ник СОБР', max_length=100, required=False)
        for item in (self.grounds, self.people, self.content, self.completed_at, self.offender):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message('Создание отчётов доступно только на сервере.', ephemeral=True)
        if not _sobr_has_min_rank(interaction.user, SOBR_CREATE_MIN_RANK):
            return await interaction.response.send_message('❌ Создавать отчёты могут сотрудники СОБР ранга D и выше.', ephemeral=True)
        people = _sobr_parse_people(str(self.people.value), interaction.guild)
        offender_people = _sobr_parse_people(str(self.offender.value), interaction.guild) if self.offender.value.strip() else []
        if self.report_type == 'Правонарушение' and not offender_people:
            return await interaction.response.send_message('Для отчёта о правонарушении обязательно укажите нарушителя (упоминание, Discord ID или Minecraft-ник из СОБР).', ephemeral=True)
        completed_raw = self.completed_at.value.strip()
        if completed_raw:
            try:
                completed = datetime.strptime(completed_raw, '%d.%m.%Y %H:%M')
            except ValueError:
                return await interaction.response.send_message('Неверное время. Используйте формат `ДД.ММ.ГГГГ ЧЧ:ММ` по Москве или оставьте поле пустым.', ephemeral=True)
        else:
            completed = now_msk()
        report_id = str(sobr_reports_data['next_report_id'])
        sobr_reports_data['next_report_id'] += 1
        author_player = data.get('players', {}).get(str(interaction.user.id), {})
        report = {
            'id': report_id, 'type': self.report_type, 'grounds': str(self.grounds.value).strip(),
            'content': str(self.content.value).strip(), 'author_id': str(interaction.user.id),
            'author_name': interaction.user.display_name, 'author_rank': _sobr_member_rank(interaction.user) or '?',
            'created_at': now_msk().isoformat(timespec='seconds'), 'completed_at': completed.isoformat(timespec='minutes'),
            'participants': people, 'offenders': offender_people, 'status': 'ожидает подтверждения' if self.report_type == 'Правонарушение' else 'зафиксирован',
            'corrections': [], 'inventory': None
        }
        if self.report_type == 'Инвентаризация ресурсов':
            building, resources = _sobr_parse_inventory(report['content'])
            if not building or not resources:
                return await interaction.response.send_message('Для инвентаризации добавьте в содержание строки `Здание: название` и `Ресурсы: алмазы=10, железо=20` (числа — неотрицательные целые).', ephemeral=True)
            previous = sobr_reports_data['inventory_latest'].get(building.casefold())
            delta = {}
            if previous:
                for name in sorted(set(previous.get('resources', {})) | set(resources)):
                    delta[name] = resources.get(name, 0) - previous.get('resources', {}).get(name, 0)
            report['inventory'] = {'building': building, 'resources': resources, 'previous_report_id': previous.get('report_id') if previous else None, 'delta': delta}
            sobr_reports_data['inventory_latest'][building.casefold()] = {'report_id': report_id, 'building': building, 'resources': resources, 'at': completed.isoformat(timespec='minutes')}
        sobr_reports_data['reports'][report_id] = report
        entry = {'entry_id': f'report:{report_id}', 'kind': 'report', 'report_id': report_id,
                 'type': self.report_type, 'grounds': report['grounds'], 'created_at': report['created_at'],
                 'completed_at': report['completed_at'], 'status': report['status']}
        for person in people:
            _sobr_add_to_dossier(person['discord_id'], dict(entry))
        # For a violation, the named offender is also included in the report dossier even if not repeated in participants.
        for person in offender_people:
            _sobr_add_to_dossier(person['discord_id'], dict(entry))
        save_sobr_reports()
        channel = await ensure_sobr_private_channel(interaction.guild)
        if channel:
            embed = discord.Embed(title=f'🛡️ Служебный отчёт СОБР №{report_id} — {self.report_type}', color=discord.Color.dark_blue())
            embed.add_field(name='Основание и цель', value=report['grounds'][:1024], inline=False)
            embed.add_field(name='Время выполнения (МСК)', value=report['completed_at'], inline=True)
            embed.add_field(name='Автор', value=f"{interaction.user.mention} · ранг {report['author_rank']}", inline=True)
            if people:
                embed.add_field(name='Участники / проверяемые лица', value=', '.join(f"<@{x['discord_id']}>" for x in people)[:1024], inline=False)
            if offender_people:
                embed.add_field(name='Указанный нарушитель', value=', '.join(f"<@{x['discord_id']}>" for x in offender_people)[:1024], inline=False)
            if report['inventory']:
                inv = report['inventory']
                inv_text = '\n'.join(f'• {name}: {amount}' for name, amount in inv['resources'].items())
                if inv['previous_report_id']:
                    inv_text += '\n**Изменение к отчёту №' + inv['previous_report_id'] + ':**\n' + '\n'.join(f'• {k}: {v:+d}' for k, v in inv['delta'].items())
                else:
                    inv_text += '\nПервичная фиксация — следующая инвентаризация станет сравнительной.'
                embed.add_field(name=f"Инвентаризация: {inv['building']}", value=inv_text[:1024], inline=False)
            embed.add_field(name='Содержание', value=report['content'][:1024], inline=False)
            embed.add_field(name='Статус', value=report['status'], inline=False)
            await channel.send(embed=embed)
        await interaction.response.send_message(f'✅ Отчёт СОБР №{report_id} сохранён. Запись добавлена в личные дела указанных лиц.' + (f' Закрытый канал: {channel.mention}.' if channel else ' ⚠️ Не удалось открыть закрытый канал; запись сохранена в файле данных.'), ephemeral=True)


class SobrReportTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
    async def _open(self, interaction: discord.Interaction, report_type: str):
        if not isinstance(interaction.user, discord.Member) or not _sobr_has_min_rank(interaction.user, SOBR_CREATE_MIN_RANK):
            return await interaction.response.send_message('❌ Нужен ранг СОБР D или выше.', ephemeral=True)
        await interaction.response.send_modal(SobrReportModal(report_type))
    @discord.ui.button(label='Правонарушение', style=discord.ButtonStyle.danger, emoji='⚖️')
    async def violation(self, interaction: discord.Interaction, button: discord.ui.Button): await self._open(interaction, 'Правонарушение')
    @discord.ui.button(label='Инвентаризация', style=discord.ButtonStyle.primary, emoji='📦')
    async def inventory(self, interaction: discord.Interaction, button: discord.ui.Button): await self._open(interaction, 'Инвентаризация ресурсов')
    @discord.ui.button(label='Проверка паспортов', style=discord.ButtonStyle.secondary, emoji='🪪')
    async def passports(self, interaction: discord.Interaction, button: discord.ui.Button): await self._open(interaction, 'Проверка паспортов')
    @discord.ui.button(label='Прочий служебный', style=discord.ButtonStyle.secondary, emoji='📄')
    async def general(self, interaction: discord.Interaction, button: discord.ui.Button): await self._open(interaction, 'Прочий служебный')


@bot.command(name='sobr_report', aliases=['собр_отчёт', 'собр_отчет'])
async def sobr_report_command(ctx):
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return await ctx.send('Команда доступна только на Discord-сервере.')
    if not _sobr_has_min_rank(ctx.author, SOBR_CREATE_MIN_RANK):
        return await ctx.send('❌ Создавать отчёты могут сотрудники СОБР ранга D и выше.')
    await ctx.send('Выберите тип служебного отчёта. Для инвентаризации укажите в содержании `Здание: название` и `Ресурсы: алмазы=10, железо=20`.', view=SobrReportTypeView())


@bot.command(name='sobr_reports', aliases=['собр_отчёты', 'собр_отчеты'])
async def sobr_reports_list(ctx, status: str = 'все'):
    if not ctx.guild or not isinstance(ctx.author, discord.Member) or not _sobr_has_min_rank(ctx.author, SOBR_CREATE_MIN_RANK):
        return await ctx.send('❌ Просматривать служебные отчёты могут сотрудники СОБР ранга D и выше.')
    reports = sorted(sobr_reports_data['reports'].values(), key=lambda r: r.get('id', '0'), reverse=True)
    if status.casefold() in {'ожидает', 'ожидающие', 'pending'}:
        reports = [r for r in reports if r.get('status') == 'ожидает подтверждения']
    elif status.casefold() not in {'все', 'all'}:
        reports = [r for r in reports if status.casefold() in r.get('status', '').casefold()]
    if not reports:
        return await ctx.send('📄 Отчётов по заданному фильтру нет.')
    lines = [f"• №{r['id']} · {r.get('type', 'отчёт')} · {r.get('status', 'зафиксирован')} · {r.get('created_at', '?')} · {r.get('grounds', '')[:100]}" for r in reports[:15]]
    await ctx.send(embed=discord.Embed(title='🛡️ Последние отчёты СОБР', description='\n'.join(lines)[:4000], color=discord.Color.dark_blue()))


@bot.command(name='sobr_dossier', aliases=['собр_дело'])
async def sobr_dossier_command(ctx, member: Optional[discord.Member] = None):
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return await ctx.send('Команда доступна только на сервере.')
    target = member or ctx.author
    if not _member_in_guild(ctx.author, 'СОБР'):
        return await ctx.send('❌ Команда доступна только сотрудникам СОБР.')
    if target.id != ctx.author.id and not _sobr_has_min_rank(ctx.author, SOBR_CONFIRM_MIN_RANK):
        return await ctx.send('❌ Чужие личные дела доступны сотрудникам СОБР ранга B и выше.')
    entries = sobr_reports_data['dossiers'].get(str(target.id), [])
    if not entries:
        return await ctx.send(f'📁 У {target.mention} пока нет записей в деле СОБР.')
    lines = []
    for e in entries[-15:]:
        lines.append(f"• **{e.get('kind', 'record')}** · отчёт №{e.get('report_id', '?')} · {e.get('type', 'запись')} · {e.get('status', 'зафиксирован')} · {e.get('created_at', '?')}")
    await ctx.send(embed=discord.Embed(title=f'📁 Личное дело: {target.display_name}', description='\n'.join(lines)[:4000], color=discord.Color.blurple()))


@bot.command(name='sobr_violation_confirm', aliases=['собр_нарушение_подтвердить'])
async def sobr_violation_confirm(ctx, report_id: str, *, decision: str = 'Нарушение подтверждено'):
    if not ctx.guild or not isinstance(ctx.author, discord.Member) or not _sobr_has_min_rank(ctx.author, SOBR_CONFIRM_MIN_RANK):
        return await ctx.send('❌ Подтверждать нарушения могут сотрудники СОБР ранга B и выше.')
    report = sobr_reports_data['reports'].get(str(report_id))
    if not report or report.get('type') != 'Правонарушение':
        return await ctx.send('❌ Отчёт о правонарушении с таким номером не найден.')
    if report.get('status') != 'ожидает подтверждения':
        return await ctx.send('ℹ️ Этот отчёт уже обработан; повторное подтверждение невозможно.')
    offenders = report.get('offenders', [])
    if not offenders:
        return await ctx.send('❌ В отчёте не указан нарушитель.')
    report['status'] = 'нарушение подтверждено'
    report['decision'] = decision[:500]
    report['decided_by'] = str(ctx.author.id)
    report['decided_at'] = now_msk().isoformat(timespec='seconds')
    new_fines = []
    for offender in offenders:
        uid = str(offender['discord_id'])
        violation_id = str(sobr_reports_data['next_violation_id'])
        sobr_reports_data['next_violation_id'] += 1
        violations = [v for v in sobr_reports_data['violations'].values() if v.get('offender_id') == uid and v.get('status') == 'подтверждено']
        violation = {'id': violation_id, 'report_id': str(report_id), 'offender_id': uid,
                     'offender_name': offender.get('display_name', offender.get('minecraft_nick', uid)),
                     'status': 'подтверждено', 'confirmed_by': str(ctx.author.id),
                     'confirmed_at': now_msk().isoformat(timespec='seconds'), 'decision': decision[:500]}
        sobr_reports_data['violations'][violation_id] = violation
        _sobr_add_to_dossier(uid, {'entry_id': f'violation:{violation_id}', 'kind': 'правонарушение',
                                  'report_id': str(report_id), 'violation_id': violation_id,
                                  'type': 'Подтверждённое правонарушение', 'status': 'подтверждено',
                                  'created_at': violation['confirmed_at'], 'decision': decision[:500]})
        # Штраф создаётся за каждую вторую подтверждённую запись; штрафы не объединяются и не начисляются повторно.
        if (len(violations) + 1) % 2 == 0:
            fine_id = str(sobr_reports_data['next_fine_id'])
            sobr_reports_data['next_fine_id'] += 1
            fine = {'id': fine_id, 'offender_id': uid, 'amount': 200, 'status': 'не оплачен',
                    'violation_ids': [violations[-1]['id'], violation_id], 'created_at': now_msk().isoformat(timespec='seconds')}
            sobr_reports_data['fines'][fine_id] = fine
            _sobr_add_to_dossier(uid, {'entry_id': f'fine:{fine_id}', 'kind': 'штраф', 'report_id': str(report_id),
                                      'fine_id': fine_id, 'type': 'Штраф 200 алмазов', 'status': 'не оплачен',
                                      'created_at': fine['created_at']})
            new_fines.append((offender, fine_id))
    save_sobr_reports()
    channel = _sobr_report_channel(ctx.guild)
    if channel:
        await channel.send(f'⚖️ Отчёт №{report_id}: нарушение подтверждено сотрудником {ctx.author.mention}. Решение: {decision[:500]}')
        for offender, fine_id in new_fines:
            await channel.send(f"💎 <@{offender['discord_id']}>: создан штраф №{fine_id} на 200 алмазов за два подтверждённых нарушения. Передача физическая; бот только фиксирует оплату.")
    fined_ids = {str(offender['discord_id']): fine_id for offender, fine_id in new_fines}
    for offender in offenders:
        try:
            user = await bot.fetch_user(int(offender['discord_id']))
            fine_id = fined_ids.get(str(offender['discord_id']))
            message = f'⚖️ СОБР подтвердил правонарушение по отчёту №{report_id}. Решение: {decision[:500]}.'
            if fine_id:
                message += f' Создан штраф №{fine_id}: 200 алмазов за два подтверждённых нарушения. Передайте алмазы уполномоченному сотруднику в Minecraft; оплата будет отмечена в боте после проверки.'
            else:
                message += ' Штраф создаётся за каждые два подтверждённых правонарушения.'
            await user.send(message)
        except (discord.Forbidden, discord.HTTPException):
            pass
    await ctx.send(f'✅ Нарушение из отчёта №{report_id} подтверждено. В личное дело нарушителя добавлена запись.' + (f' Созданы штрафы: {", ".join(x[1] for x in new_fines)}.' if new_fines else ' Новый штраф не требуется.'))


@bot.command(name='sobr_fines', aliases=['собр_штрафы'])
async def sobr_fines(ctx, member: Optional[discord.Member] = None):
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return await ctx.send('Команда доступна только на сервере.')
    if not _member_in_guild(ctx.author, 'СОБР'):
        return await ctx.send('❌ Команда доступна только сотрудникам СОБР.')
    if member and member.id != ctx.author.id and not _sobr_has_min_rank(ctx.author, SOBR_CONFIRM_MIN_RANK):
        return await ctx.send('❌ Смотреть чужие штрафы могут сотрудники СОБР ранга B и выше.')
    target_id = str((member or ctx.author).id)
    fines = [f for f in sobr_reports_data['fines'].values() if f.get('offender_id') == target_id]
    if not fines:
        return await ctx.send('💎 Штрафов в реестре нет.')
    lines = [f"№{f['id']} — {f['amount']} алмазов · {f['status']}" for f in fines]
    await ctx.send(embed=discord.Embed(title=f'💎 Штрафы: {(member or ctx.author).display_name}', description='\n'.join(lines), color=discord.Color.gold()))


@bot.command(name='sobr_fine_paid', aliases=['собр_штраф_оплачен'])
async def sobr_fine_paid(ctx, member: discord.Member, fine_id: str, *, note: str = 'Физическая передача подтверждена'):
    if not ctx.guild or not isinstance(ctx.author, discord.Member) or not _sobr_has_min_rank(ctx.author, SOBR_CONFIRM_MIN_RANK):
        return await ctx.send('❌ Подтверждать оплату могут сотрудники СОБР ранга B и выше.')
    fine = sobr_reports_data['fines'].get(str(fine_id))
    if not fine or fine.get('offender_id') != str(member.id):
        return await ctx.send('❌ Штраф не найден или не принадлежит указанному игроку.')
    if fine.get('status') == 'оплачен':
        return await ctx.send('ℹ️ Этот штраф уже отмечен оплаченным.')
    fine.update({'status': 'оплачен', 'paid_by': str(ctx.author.id), 'paid_at': now_msk().isoformat(timespec='seconds'), 'payment_note': note[:500]})
    _sobr_add_to_dossier(str(member.id), {'entry_id': f'fine-paid:{fine_id}', 'kind': 'оплата штрафа',
                                          'fine_id': str(fine_id), 'type': 'Штраф 200 алмазов', 'status': 'оплачен',
                                          'created_at': fine['paid_at'], 'note': note[:500]})
    save_sobr_reports()
    channel = _sobr_report_channel(ctx.guild)
    if channel:
        await channel.send(f'✅ Штраф №{fine_id} для {member.mention} отмечен оплаченным сотрудником {ctx.author.mention}. Примечание: {note[:500]}')
    await ctx.send(f'✅ Штраф №{fine_id} отмечен оплаченным. Убедитесь, что 200 алмазов действительно переданы в Minecraft.')


@bot.command(name='sobr_report_correct', aliases=['собр_исправление'])
async def sobr_report_correct(ctx, report_id: str, *, correction: str):
    if not ctx.guild or not isinstance(ctx.author, discord.Member) or not _sobr_has_min_rank(ctx.author, SOBR_CREATE_MIN_RANK):
        return await ctx.send('❌ Добавлять исправления могут сотрудники СОБР ранга D и выше.')
    report = sobr_reports_data['reports'].get(str(report_id))
    if not report:
        return await ctx.send('❌ Отчёт не найден.')
    entry = {'author_id': str(ctx.author.id), 'author_name': ctx.author.display_name,
             'created_at': now_msk().isoformat(timespec='seconds'), 'text': correction[:2000]}
    report.setdefault('corrections', []).append(entry)
    for person in report.get('participants', []) + report.get('offenders', []):
        _sobr_add_to_dossier(str(person['discord_id']), {'entry_id': f"correction:{report_id}:{entry['created_at']}:{person['discord_id']}",
                            'kind': 'исправление', 'report_id': str(report_id), 'type': 'Исправление к отчёту',
                            'status': 'добавлено', 'created_at': entry['created_at'], 'note': correction[:2000]})
    save_sobr_reports()
    channel = _sobr_report_channel(ctx.guild)
    if channel:
        await channel.send(f'📝 Исправление к отчёту №{report_id} от {ctx.author.mention} ({entry["created_at"]} МСК):\n{correction[:1800]}')
    await ctx.send(f'✅ Исправление добавлено к отчёту №{report_id}. Исходный текст не изменён.')


def _sobr_week_bounds(now: datetime):
    # По понедельникам формируем отчёт за последнюю полностью завершённую неделю.
    end = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=7)
    return start, end


async def generate_sobr_weekly_passport_report(guild: discord.Guild, force: bool = False):
    now = now_msk()
    week_start, week_end = _sobr_week_bounds(now)
    week_key = week_start.strftime('%Y-%m-%d')
    if sobr_reports_data.get('last_passport_report_week') == week_key:
        return False
    if not force and (now.weekday() != 0 or now.hour < SOBR_WEEKLY_HOUR):
        return False
    channel = await ensure_sobr_private_channel(guild)
    if not channel:
        return False
    registered = sorted(data.get('players', {}).items(), key=lambda pair: pair[1].get('minecraft_nick', '').casefold())
    creditors_path = 'creditors.json'
    creditors_data = _load_json_safely(creditors_path, {'users': {}})
    creditor_users = creditors_data.get('users', {}) if isinstance(creditors_data, dict) else {}
    checked = []
    for uid, record in creditor_users.items():
        checked_at = record.get('passport_checked_at')
        if not checked_at:
            continue
        try:
            checked_dt = datetime.fromisoformat(checked_at)
        except (TypeError, ValueError):
            continue
        if week_start <= checked_dt < week_end:
            checked.append((str(uid), record, checked_dt))
    embed = discord.Embed(title=f'🪪 Еженедельный отчёт СОБР о паспортах · неделя с {week_start:%d.%m.%Y}',
                          description=f'Зарегистрированных игроков на момент формирования: **{len(registered)}**.\nПроверок паспортов за неделю: **{len(checked)}**.\nПериод: {week_start:%d.%m.%Y}–{(week_end - timedelta(days=1)):%d.%m.%Y} (МСК).',
                          color=discord.Color.blue())
    roster = []
    for uid, player in registered:
        roster.append(f"• {player.get('minecraft_nick', '?')} — <@{uid}>")
    embed.add_field(name='Все зарегистрированные игроки', value='\n'.join(roster)[:1024] if roster else 'Нет зарегистрированных игроков.', inline=False)
    checked_lines = []
    for uid, record, checked_dt in sorted(checked, key=lambda x: x[2]):
        checked_lines.append(f"• {record.get('minecraft_nick', data.get('players', {}).get(uid, {}).get('minecraft_nick', '?'))} — {'паспорт подтверждён' if record.get('passport_verified') else 'паспорт не подтверждён'}; проверка {checked_dt:%d.%m %H:%M}; сотрудник <@{record.get('passport_checked_by', '?')}>")
    embed.add_field(name='Паспорта, проверенные за неделю', value='\n'.join(checked_lines)[:1024] if checked_lines else 'На этой неделе проверок паспортов не зарегистрировано.', inline=False)
    await channel.send(embed=embed)
    report_id = str(sobr_reports_data['next_report_id'])
    sobr_reports_data['next_report_id'] += 1
    report = {'id': report_id, 'type': 'Еженедельный отчёт о паспортах', 'grounds': 'Еженедельная сверка регистраций и проверок паспортов',
              'content': f'Зарегистрированных: {len(registered)}; проверок за неделю: {len(checked)}.',
              'author_id': 'system', 'author_name': 'Автоматизация СОБР', 'author_rank': 'system',
              'created_at': now.isoformat(timespec='seconds'), 'completed_at': now.isoformat(timespec='minutes'),
              'participants': [{'discord_id': str(uid), 'minecraft_nick': player.get('minecraft_nick', '?'), 'display_name': player.get('minecraft_nick', '?')} for uid, player in registered],
              'offenders': [], 'status': 'зафиксирован', 'corrections': [], 'inventory': None,
              'passport_week': week_key, 'registered_count': len(registered), 'checked_passports_count': len(checked)}
    sobr_reports_data['reports'][report_id] = report
    for uid, player in registered:
        _sobr_add_to_dossier(str(uid), {'entry_id': f'report:{report_id}', 'kind': 'report', 'report_id': report_id,
                                        'type': report['type'], 'grounds': report['grounds'], 'created_at': report['created_at'],
                                        'completed_at': report['completed_at'], 'status': report['status']})
    sobr_reports_data['last_passport_report_week'] = week_key
    sobr_reports_data['weekly_passport_reports'].append({'report_id': report_id, 'week': week_key, 'created_at': report['created_at']})
    sobr_reports_data['weekly_passport_reports'] = sobr_reports_data['weekly_passport_reports'][-100:]
    save_sobr_reports()
    return True


@tasks.loop(minutes=1)
async def sobr_weekly_passport_checker():
    now = now_msk()
    if now.weekday() != 0 or now.hour < SOBR_WEEKLY_HOUR:
        return
    for guild in bot.guilds:
        try:
            if await generate_sobr_weekly_passport_report(guild):
                print(f'🪪 Сформирован еженедельный отчёт СОБР о паспортах для сервера {guild.id}.')
        except Exception as exc:
            print(f'❌ Не удалось сформировать недельный отчёт СОБР: {exc}')


@bot.command(name='sobr_passport_report', aliases=['собр_паспорта_отчёт', 'собр_паспорта_отчет'])
async def sobr_passport_report(ctx):
    if not ctx.guild or not isinstance(ctx.author, discord.Member) or not _sobr_has_min_rank(ctx.author, SOBR_CONFIRM_MIN_RANK):
        return await ctx.send('❌ Формировать отчёт о паспортах вручную могут сотрудники СОБР ранга B и выше.')
    result = await generate_sobr_weekly_passport_report(ctx.guild, force=True)
    await ctx.send('✅ Отчёт о паспортах сформирован в закрытом канале.' if result else '❌ Не удалось сформировать отчёт: проверьте права бота на создание/отправку сообщений в закрытом канале.')


# === КОМАНДЫ ===

@bot.command(name='week')
async def show_week(ctx):
    tl = get_time_until_next_week()
    embed = discord.Embed(title='🗓️ Неделя', color=discord.Color.blue()).add_field(name='📅 Текущая',
                                                                                   value=get_current_week_key(),
                                                                                   inline=True).add_field(
        name='⏰ До сброса', value=f'{tl.days}д {tl.seconds // 3600}ч {(tl.seconds % 3600) // 60}м', inline=True)
    await ctx.send(embed=embed)


@bot.command(name='stats')
async def stats(ctx):
    uid = str(ctx.author.id)
    p = data.get('players', {}).get(uid)
    if not p: return await ctx.send('❌ Не зарегистрированы!')

    rank, tasks, qb = p.get('rank', 'F'), p.get('completed_tasks', 0), p.get('quest_bonus', 0.0)
    min_status = '✅' if tasks >= MIN_TASKS_PER_RANK.get(rank, 1) else f'⚠️ нужно {MIN_TASKS_PER_RANK.get(rank, 1)}'

    embed = discord.Embed(title=f'📊 {p["minecraft_nick"]}', description=f'📅 {get_current_week_key()}',
                          color=discord.Color.blue())
    embed.add_field(name='🏛️', value=p.get('guild', '?').capitalize(), inline=True)
    embed.add_field(name='🔰', value=rank, inline=True)
    embed.add_field(name='💎 Квесты', value=f'+{qb}%', inline=True)
    embed.add_field(name='📊 Заданий', value=f'{tasks}/{MAX_TASKS_PER_RANK.get(rank, 5)} {min_status}', inline=True)
    embed.add_field(name='⭐ Очки', value=p.get('rank_points', 0), inline=True)
    embed.add_field(name='💰', value=f'{player_weekly_salary(p)} алмазов', inline=True)

    if is_on_vacation(uid):
        if vac := get_vacation_info(uid): embed.add_field(name='🌴 Отпуск',
                                                          value=f'До **{datetime.fromisoformat(vac["end_date"]).strftime("%d.%m.%Y %H:%M")}**',
                                                          inline=False)
    elif last := data.get('vacation_cooldowns', {}).get(uid):
        try:
            cd = datetime.fromisoformat(last['end_date']) + timedelta(days=VACATION_COOLDOWN_DAYS)
            if now_msk() < cd: embed.add_field(name='⏳ Кулдаун отпуска',
                                                    value=f'Следующий через **{(cd - now_msk()).days}д**\n(с **{cd.strftime("%d.%m.%Y")}**)',
                                                    inline=False)
        except:
            pass
    await ctx.send(embed=embed)


@bot.command(name='cabinet', aliases=['profile', 'личный_кабинет'])
async def personal_cabinet(ctx, member: Optional[discord.Member] = None):
    """Личный кабинет: статистика, титул, достижения и открытые титулы."""
    target_member = member or ctx.author
    uid = str(target_member.id)
    player = data.get('players', {}).get(uid)
    if not player:
        return await ctx.send('❌ Этот пользователь не зарегистрирован в системе гильдий.')
    new_achievements = refresh_player_progress(player)
    if new_achievements:
        save_data()
    achievements = player.get('achievements', [])
    titles = player.get('unlocked_titles', [])
    completed = [ACHIEVEMENT_CATALOG[a]['name'] for a in achievements if a in ACHIEVEMENT_CATALOG]
    title_lines = [f"{'⭐' if t == player.get('active_title') else '🏷️'} **{TITLE_CATALOG[t]['name']}** (`{t}`)" for t in titles if t in TITLE_CATALOG]
    embed = discord.Embed(title=f"🪪 Личный кабинет — {player.get('minecraft_nick', 'Игрок')}",
                          description=f"{GUILD_EMOJIS.get(player.get('guild'), '🏛️')} **{player.get('guild', '—').capitalize()}** · ранг **{player.get('rank', 'F')}**",
                          color=discord.Color.gold())
    embed.add_field(name='⭐ Очки ранга', value=str(player.get('rank_points', 0)), inline=True)
    embed.add_field(name='📋 Заданий за неделю', value=str(player.get('completed_tasks', 0)), inline=True)
    embed.add_field(name='📚 Заданий за всё время', value=str(player.get('lifetime_tasks_total', player.get('completed_tasks', 0))), inline=True)
    embed.add_field(name='🎯 Завершено квестов', value=str(player.get('lifetime_quests_completed', 0)), inline=True)
    embed.add_field(name='🏷️ Активный титул', value=get_active_title_name(player), inline=True)
    embed.add_field(name=f'🏆 Достижения ({len(achievements)}/{len(ACHIEVEMENT_CATALOG)})', value='\n'.join(f'✅ {name}' for name in completed) or 'Пока нет — выполни первое задание!', inline=False)
    embed.add_field(name=f'🎖️ Открытые титулы ({len(titles)}/{len(TITLE_CATALOG)})', value='\n'.join(title_lines) or 'Пока титулов нет.', inline=False)
    await ctx.send(embed=embed)


@bot.command(name='achievements', aliases=['достижения'])
async def show_achievements(ctx):
    player = data.get('players', {}).get(str(ctx.author.id))
    if not player:
        return await ctx.send('❌ Сначала зарегистрируйся в системе гильдий.')
    newly = refresh_player_progress(player)
    if newly:
        save_data()
    unlocked = set(player.get('achievements', []))
    lines = [f"{'✅' if aid in unlocked else '🔒'} **{spec['name']}** — {spec['description']}" for aid, spec in ACHIEVEMENT_CATALOG.items()]
    await ctx.send(embed=discord.Embed(title='🏆 Достижения', description='\n'.join(lines), color=discord.Color.gold()))


@bot.command(name='titles', aliases=['титулы'])
async def show_titles(ctx):
    player = data.get('players', {}).get(str(ctx.author.id))
    if not player:
        return await ctx.send('❌ Сначала зарегистрируйся в системе гильдий.')
    refresh_player_progress(player)
    save_data()
    unlocked = set(player.get('unlocked_titles', []))
    lines = []
    for title_id, spec in TITLE_CATALOG.items():
        status = '⭐ активный' if player.get('active_title') == title_id else ('✅ открыт' if title_id in unlocked else '🔒 закрыт')
        lines.append(f"**{spec['name']}** (`{title_id}`) — {status}\n{spec['description']} · бонус территории: +{spec['area_bonus']}")
    await ctx.send(embed=discord.Embed(title='🎖️ Коллекция титулов', description='\n\n'.join(lines), color=discord.Color.gold()))


@bot.command(name='title_set', aliases=['титул'])
async def set_active_title(ctx, title_id: str):
    player = data.get('players', {}).get(str(ctx.author.id))
    if not player:
        return await ctx.send('❌ Сначала зарегистрируйся в системе гильдий.')
    title_id = title_id.strip().casefold()
    refresh_player_progress(player)
    if title_id not in TITLE_CATALOG:
        return await ctx.send('❌ Неизвестный ID титула. Используй `.titles`.')
    if title_id not in player.get('unlocked_titles', []):
        return await ctx.send('🔒 Этот титул ещё не открыт. Посмотри условия командой `.achievements`.')
    player['active_title'] = title_id
    save_data()
    await ctx.send(f"✅ Активный титул изменён: **{TITLE_CATALOG[title_id]['name']}**.")


@bot.command(name='territory_limit')
async def territory_limit(ctx, base_area: float = 100.0):
    """Показывает расчёт максимальной площади с учётом активного титула."""
    player = data.get('players', {}).get(str(ctx.author.id))
    if not player:
        return await ctx.send('❌ Сначала зарегистрируйся в системе гильдий.')
    try:
        limit = calculate_territory_limit(base_area, player)
    except ValueError as exc:
        return await ctx.send(f'❌ {exc}')
    title = TITLE_CATALOG.get(player.get('active_title'), {})
    await ctx.send(f"📐 Базовая площадь: **{base_area:g}**\n🏷️ Титул: **{get_active_title_name(player)}** (+{title.get('area_bonus', 0)})\n🏙️ Максимальная площадь по текущей конфигурации: **{limit}**.\n_Бонусы титулов пока равны 0; их значения можно настроить отдельно._")


@bot.command(name='rank_info')
async def rank_info(ctx, rank: str = None):
    rank = rank.upper() if rank else data.get('players', {}).get(str(ctx.author.id), {}).get('rank', 'F')
    if rank not in RANK_POINTS_REQUIRED: return await ctx.send(f'❌ Ранги: {", ".join(RANK_ORDER)}')
    embed = discord.Embed(title=f'📋 Ранг {rank}', color=discord.Color.blue())
    embed.add_field(name='⭐ Очков', value=RANK_POINTS_REQUIRED[rank], inline=True).add_field(name='📊 Макс.',
                                                                                             value=MAX_TASKS_PER_RANK.get(
                                                                                                 rank, 5),
                                                                                             inline=True).add_field(
        name='📉 Мин.', value=MIN_TASKS_PER_RANK.get(rank, 1), inline=True).add_field(name='💰 Коэф.',
                                                                                     value=RANK_COEFFICIENTS.get(rank,
                                                                                                                 1.0),
                                                                                     inline=True)
    if nr := get_next_rank(rank): embed.add_field(name='⬆️ Следующий',
                                                  value=f'**{nr}** ({RANK_POINTS_REQUIRED[nr]} очков)', inline=False)
    await ctx.send(embed=embed)


@bot.command(name='compare')
async def compare_weeks(ctx):
    uid = str(ctx.author.id)
    if not is_registered(uid): return await ctx.send('❌ Не зарегистрированы!')
    weeks = sorted(data.get('weekly_history', {}).keys())
    if len(weeks) < 2: return await ctx.send('📭 Нужно 2 недели данных.')
    w1, w2 = weeks[-2], weeks[-1]
    p1, p2 = data['weekly_history'][w1]['players'].get(uid), data['weekly_history'][w2]['players'].get(uid)
    if not p1 or not p2: return await ctx.send('❌ Нет данных.')

    embed = discord.Embed(title='📊 Сравнение', description=f'{w1} vs {w2}', color=discord.Color.blue())
    for label, key in [('Задания', 'tasks'), ('Очки', 'points')]:
        d = p2.get(key, 0) - p1.get(key, 0)
        embed.add_field(name=f'{"📈" if d > 0 else ("📉" if d < 0 else "➡️")} {label}',
                        value=f'{p1.get(key, 0)} → {p2.get(key, 0)} ({d:+d})', inline=True)
    s1, s2 = p1.get('salary', 0), p2.get('salary', 0)
    ds = s2 - s1
    embed.add_field(name=f'{"📈" if ds > 0 else ("📉" if ds < 0 else "➡️")} Зарплата',
                    value=f'{s1} → {s2} ({ds:+.1f}, {round((ds / s1 * 100) if s1 > 0 else 0, 1):+.1f}%)', inline=True)
    await ctx.send(embed=embed)


@bot.command(name='history')
async def show_history(ctx):
    uid = str(ctx.author.id)
    if not is_registered(uid): return await ctx.send('❌ Не зарегистрированы!')
    weeks = sorted(data.get('weekly_history', {}).keys())[-10:]
    if not weeks: return await ctx.send('📭 История пуста.')
    embed = discord.Embed(title='📅 История', color=discord.Color.blue())
    for week in weeks:
        if p := data['weekly_history'][week]['players'].get(uid): embed.add_field(name=f'📆 {week}',
                                                                                  value=f'{p["rank"]} | ⭐ {p["points"]} | 📊 {p["tasks"]} | 💰 {p["salary"]}',
                                                                                  inline=False)
    await ctx.send(embed=embed)


@bot.command(name='my_quests')
async def my_quests(ctx):
    uid = str(ctx.author.id)
    p = data.get('players', {}).get(uid)
    if not p: return await ctx.send('❌ Не зарегистрированы!')
    embed = discord.Embed(title=f'🎯 Квесты {p["minecraft_nick"]}', color=discord.Color.blue()).add_field(name='💎 Бонус',
                                                                                                         value=f'+{p.get("quest_bonus", 0.0)}%',
                                                                                                         inline=False)
    taken, confirmed, overdue = [], [], []
    for qid, users in data.get('player_quests', {}).items():
        if uid not in users or not (quest := data.get('quests', {}).get(qid)): continue
        pq = users[uid]
        line = f"**{quest['name']}** (+{quest['bonus']}%)"
        if pq.get('reward_type', quest.get('reward_type', 'salary_only')) == 'diamonds_xp':
            reward_state = {'pending': '⏳ награда ожидает выдачи', 'paid': '🎁 награда выдана'}.get(pq.get('reward_status'), '🎁 награда предусмотрена')
            line += f" — 💎 {pq.get('reward_diamonds', quest.get('reward_diamonds', 0))}, ✨ {pq.get('reward_xp', quest.get('reward_xp', 0))} XP ({reward_state})"
        if pq['status'] == 'taken':
            taken.append(line)
        elif pq['status'] == 'confirmed':
            confirmed.append(line + ' ✅')
        elif pq['status'] == 'overdue':
            overdue.append(line + f' ⏰')

    if taken: embed.add_field(name=f'🟡 В процессе ({len(taken)})', value='\n'.join(taken[:10]), inline=False)
    if confirmed: embed.add_field(name=f'✅ Подтверждены ({len(confirmed)})', value='\n'.join(confirmed[:10]),
                                  inline=False)
    if overdue: embed.add_field(name=f'⏰ Просрочены ({len(overdue)})', value='\n'.join(overdue[:10]), inline=False)
    if not (taken or confirmed or overdue): embed.add_field(name='📭 Квестов нет', value='Возьмите квест на доске!',
                                                            inline=False)
    await ctx.send(embed=embed)


@bot.command(name='vacation')
async def vacation_cmd(ctx, days: int = 7):
    uid = str(ctx.author.id)
    if not is_registered(uid): return await ctx.send('❌ Не зарегистрированы!')
    if not (1 <= days <= 14): return await ctx.send('❌ Отпуск может быть от 1 до 14 дней!')
    can_take, reason = can_take_vacation(uid)
    if not can_take: return await ctx.send(
        embed=discord.Embed(title='❌ Отпуск недоступен', description=reason, color=discord.Color.red()).add_field(
            name='📌 Правило', value='Отпуск можно брать **не чаще, чем раз в 2 недели**.', inline=False))

    end_date = now_msk() + timedelta(days=days)
    data['vacations'][uid] = {'start_date': now_msk().isoformat(), 'end_date': end_date.isoformat(), 'days': days}
    record_vacation_end(uid, end_date)

    embed = discord.Embed(title='🌴 Вы в отпуске!',
                          description=f'Длительность: **{days}** дней\nДо: **{end_date.strftime("%d.%m.%Y %H:%M")}**',
                          color=discord.Color.green())
    embed.add_field(name='📌 Что это значит?',
                    value='• Штрафы за невыполнение минимума заданий не применяются\n• Вы не получаете новые задания\n• Ваш ранг и очки сохраняются',
                    inline=False)
    embed.add_field(name='⏳ Следующий отпуск',
                    value=f'Не раньше **{(end_date + timedelta(days=VACATION_COOLDOWN_DAYS)).strftime("%d.%m.%Y %H:%M")}**',
                    inline=False)
    await ctx.send(embed=embed)


@bot.command(name='vacation_cancel')
async def vacation_cancel(ctx):
    uid = str(ctx.author.id)
    if not is_on_vacation(uid): return await ctx.send('❌ Вы не в отпуске.')
    data['vacations'].pop(uid, None)
    save_data()
    await ctx.send('✅ Отпуск прерван.\n⚠️ **Важно:** кулдаун 14 дней сохраняется.')


@bot.command(name='vacation_list')
async def vacation_list(ctx):
    lg = get_leader_guild(ctx)
    if not lg: return await ctx.send('❌ Только для глав!')
    on_vac, cooldowns = [], []
    for uid, p in data['players'].items():
        if p.get('guild') != lg: continue
        if is_on_vacation(uid):
            on_vac.append(
                f'🌴 **{p["minecraft_nick"]}** — до {datetime.fromisoformat(data["vacations"][uid]["end_date"]).strftime("%d.%m.%Y")}')
        elif last := data.get('vacation_cooldowns', {}).get(uid):
            try:
                cd = datetime.fromisoformat(last['end_date']) + timedelta(days=VACATION_COOLDOWN_DAYS)
                if now_msk() < cd: cooldowns.append(
                    f'⏳ **{p["minecraft_nick"]}** — через {(cd - now_msk()).days}д (до {cd.strftime("%d.%m.%Y")})')
            except:
                pass

    embed = discord.Embed(title=f'🌴 Отпуска {lg.capitalize()}', color=discord.Color.green())
    if on_vac: embed.add_field(name=f'🌴 В отпуске ({len(on_vac)})', value='\n'.join(on_vac), inline=False)
    if cooldowns: embed.add_field(name=f'⏳ На кулдауне ({len(cooldowns)})', value='\n'.join(cooldowns[:10]),
                                  inline=False)
    if not on_vac and not cooldowns: embed.description = '📭 Нет игроков в отпуске или на кулдауне.'
    await ctx.send(embed=embed)


@bot.command(name='analytics')
async def analytics(ctx):
    lg = get_leader_guild(ctx)
    if not lg: return await ctx.send('❌ Только для глав!')
    players = [{'nick': p.get('minecraft_nick', '?'), 'rank': p.get('rank', 'F'), 'tasks': p.get('completed_tasks', 0),
                'salary': player_weekly_salary(p),
                'on_vacation': is_on_vacation(uid)} for uid, p in data['players'].items() if p.get('guild') == lg]
    if not players: return await ctx.send('📭 Нет игроков.')

    top3 = sorted(players, key=lambda x: RANK_ORDER_REV.index(x['rank']))[:3]
    worst3 = sorted(players, key=lambda x: x['tasks'])[:3]
    avg_salary = sum(p['salary'] for p in players) / len(players)
    avg_tasks = sum(p['tasks'] for p in players) / len(players)

    embed = discord.Embed(title=f'📊 Аналитика {lg.capitalize()}', description=f'📅 {get_current_week_key()}',
                          color=discord.Color.blue())
    embed.add_field(name='🏆 Топ-3', value='\n'.join(
        [f'{["🥇", "🥈", "🥉"][i]} **{p["nick"]}** — {p["rank"]} | {p["tasks"]} | {p["salary"]}' for i, p in
         enumerate(top3)]), inline=False)
    embed.add_field(name='📉 Внимание', value='\n'.join([f'🌴 **{p["nick"]}** — отпуск' if (
                p['tasks'] == 0 and p['on_vacation']) else f'⚠️ **{p["nick"]}** — {p["tasks"]} | {p["salary"]}' for p in
                                                        worst3]), inline=False)
    embed.add_field(name='📈 Средние', value=f'💰 {round(avg_salary, 1)} | 📊 {round(avg_tasks, 1)}', inline=False)
    await ctx.send(embed=embed)


# === МАСТЕР КВЕСТОВ (UI) ===


async def create_forum_post(board: discord.ForumChannel, name: str, content: str):
    """Совместимость с discord.py: create_thread может вернуть ThreadWithMessage."""
    created = await board.create_thread(name=name[:100], content=content)
    thread = getattr(created, 'thread', created)
    message = getattr(created, 'message', None)
    if message is None:
        message = await thread.fetch_message(thread.id)
    return thread, message


class TemplateCreateModal(discord.ui.Modal, title='Создание квеста из шаблона'):
    bonus_input = discord.ui.TextInput(label='Бонус к зарплате (%)', default='10', required=True, max_length=6)
    time_input = discord.ui.TextInput(label='Срок (например 1д 2ч 30м; 0 = без)', default='1д', required=True, max_length=40)
    type_input = discord.ui.TextInput(label='Периодичность (weekly/daily/once)', default='weekly', required=True, max_length=10)
    mode_input = discord.ui.TextInput(label='Режим (individual / group)', default='individual', required=True, max_length=10)
    reward_input = discord.ui.TextInput(label='Награда: алмазы, XP (0,0 = без)', default='0, 0', required=True, max_length=20)

    def __init__(self, template_id: str, template: Dict, guild: str, creator_id: int, reward_enabled: bool = True):
        super().__init__()
        self.template_id, self.template, self.guild, self.creator_id = template_id, template, guild, creator_id
        self.reward_enabled = reward_enabled
        self.bonus_input.default = str(template.get('bonus', 10))[:6]
        self.time_input.default = (format_duration(int(template.get('time_limit', 1440))) if int(template.get('time_limit', 1440)) > 0 else '0')
        self.type_input.default = template.get('type', 'weekly')
        self.mode_input.default = template.get('mode', 'individual')
        self.reward_input.default = (f"{int(template.get('reward_diamonds', 0) or 0)}, {int(template.get('reward_xp', 0) or 0)}" if reward_enabled else '0, 0')

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction_can_manage_guild(interaction, self.guild, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав или это меню создал другой пользователь.', ephemeral=True)
        try:
            bonus, time_limit = float(self.bonus_input.value.replace('%', '')), parse_duration_minutes(self.time_input.value)
            quest_type, mode = self.type_input.value.strip().lower(), self.mode_input.value.strip().lower()
            reward = parse_reward_pair(self.reward_input.value) if self.reward_enabled else parse_reward_pair('0, 0')
        except ValueError as exc:
            return await interaction.response.send_message(f'❌ Проверьте поля: {exc}', ephemeral=True)
        if self.reward_enabled and reward['reward_type'] != 'diamonds_xp':
            return await interaction.response.send_message('❌ Для типа «с наградой» укажите хотя бы одно положительное значение алмазов или XP.', ephemeral=True)
        if quest_type not in ('weekly', 'daily', 'once') or mode not in ('individual', 'group'):
            return await interaction.response.send_message('❌ Периодичность: weekly/daily/once; режим: individual/group.', ephemeral=True)
        if not (0 <= bonus <= 100 and 0 <= time_limit <= 525600):
            return await interaction.response.send_message('❌ Бонус должен быть 0–100%, срок — 0–525600 минут.', ephemeral=True)
        board_id = GUILD_QUEST_BOARDS.get(self.guild)
        board = await _resolve_channel(board_id) if board_id else None
        if not isinstance(board, discord.ForumChannel):
            return await interaction.response.send_message('❌ Доска не настроена или канал не является форумом!', ephemeral=True)
        payload = {'guild': self.guild, 'name': self.template['name'], 'description': self.template['description'],
                   'bonus': bonus, 'time_limit_minutes': time_limit, 'type': quest_type, 'mode': mode,
                   'creator_id': self.creator_id, 'template_id': self.template_id, **reward}
        try:
            qid = generate_quest_id()
            type_label = {'weekly': '📅 Еженед.', 'daily': '📆 Ежедн.', 'once': '🎯 Разовый'}[quest_type]
            title = f"{type_label} | {payload['name']}"
            body = (f"🆔 **ID квеста: `{qid}`**\n\n🎯 **{payload['name']}**\n\n{payload['description']}\n\n"
                    f"💼 **Бонус к зарплате:** +{bonus:g}%\n⏰ **Срок:** {format_duration(time_limit)}\n"
                    f"{quest_reward_label(reward)}\n\nПоставьте {QUEST_TAKE_REACTION}, чтобы взять!")
            thread, msg = await create_forum_post(board, title, body)
            data['quests'][qid] = {**payload, 'created_at': now_msk().isoformat(), 'thread_id': thread.id,
                                   'message_id': msg.id, 'status': 'active'}
            save_data()
            for reaction in (QUEST_TAKE_REACTION, QUEST_CONFIRM_REACTION):
                try:
                    await msg.add_reaction(reaction)
                except discord.HTTPException as reaction_error:
                    print(f'⚠️ Не удалось добавить реакцию {reaction} к квесту {qid}: {reaction_error}')
            await interaction.response.send_message(embed=discord.Embed(title='✅ Квест создан!', description=f'{thread.mention}\n🆔 ID квеста: `{qid}`\n{quest_reward_label(reward)}', color=discord.Color.green()), ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(f'❌ Ошибка создания квеста: {exc}', ephemeral=True)


class TemplatePreviewView(AuthorizedView):
    def __init__(self, template_id: str, template: Dict, guild: str, creator_id: int):
        super().__init__(creator_id=creator_id, guild_name=guild, timeout=180)
        self.template_id, self.template, self.guild, self.creator_id = template_id, template, guild, creator_id

    @discord.ui.button(label='🎁 Создать с наградой', style=discord.ButtonStyle.success, row=0)
    async def create_rewarded(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            TemplateCreateModal(self.template_id, self.template, self.guild, self.creator_id, reward_enabled=True))

    @discord.ui.button(label='📋 Создать без награды', style=discord.ButtonStyle.secondary, row=0)
    async def create_no_reward(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            TemplateCreateModal(self.template_id, self.template, self.guild, self.creator_id, reward_enabled=False))

    @discord.ui.button(label='↩️ Назад', style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, view = build_template_browser(self.guild, self.creator_id)
        await interaction.response.edit_message(embed=embed, view=view)


class TemplateSelect(discord.ui.Select):
    def __init__(self, templates: List[Dict], guild: str, creator_id: int):
        self.guild, self.creator_id = guild, creator_id
        options = [discord.SelectOption(label=t['name'][:100], description=f"+{t['bonus']}% | {t.get('category', '—')}",
                                        value=t['id']) for t in templates[:25]]
        super().__init__(placeholder='Выберите шаблон...', options=options)

    async def callback(self, interaction: discord.Interaction):
        if not interaction_can_manage_guild(interaction, self.guild, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав или это меню создал другой пользователь.', ephemeral=True)
        if not (template := get_template(self.values[0])): return await interaction.response.send_message(
            '❌ Не найден!', ephemeral=True)
        embed = discord.Embed(title=f"📋 {template['name']}", description=template['description'],
                              color=discord.Color.blue())
        embed.add_field(name='💎 Бонус', value=f"+{template['bonus']}%", inline=True).add_field(name='⏰ Время',
                                                                                               value=format_duration(int(template.get('time_limit', 0))),
                                                                                               inline=True).add_field(
            name='🎯 Тип', value={'weekly': '📅 Еженед.', 'daily': '📆 Ежедн.', 'once': '🎯 Разовый'}.get(template.get('type'), '📆 Ежедн.'), inline=True)
        await interaction.response.edit_message(embed=embed,
                                                view=TemplatePreviewView(self.values[0], template, self.guild,
                                                                         self.creator_id))


class TemplateCategoryView(AuthorizedView):
    def __init__(self, guild: str, creator_id: int):
        super().__init__(creator_id=creator_id, guild_name=guild, timeout=180)
        self.guild, self.creator_id = guild, creator_id
        options = [
            discord.SelectOption(label=cat, description=f'{len(get_templates_by_category(cat))} шаблонов', value=cat)
            for cat in get_template_categories()]
        options.append(discord.SelectOption(label='📚 Все шаблоны', value='__all__'))
        select = discord.ui.Select(placeholder='Выберите категорию...', options=options[:25])
        select.callback = self.category_callback
        self.add_item(select)
        back_btn = discord.ui.Button(label='↩️ Назад', style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self.back_callback
        self.add_item(back_btn)

    async def category_callback(self, interaction: discord.Interaction, *args):
        cat = interaction.data['values'][0]
        templates = get_templates_by_category() if cat == '__all__' else get_templates_by_category(cat)
        embed = discord.Embed(title='📚 Все шаблоны' if cat == '__all__' else f'📂 {cat}',
                              description=f'Шаблонов: **{len(templates)}**', color=discord.Color.blue())
        view = discord.ui.View(timeout=180)
        view.add_item(TemplateSelect(templates, self.guild, self.creator_id))
        back_btn = discord.ui.Button(label='↩️ Категории', style=discord.ButtonStyle.secondary)
        back_btn.callback = self.back_callback
        view.add_item(back_btn)
        await interaction.response.edit_message(embed=embed, view=view)

    async def back_callback(self, interaction: discord.Interaction, *args):
        embed, view = build_template_browser(self.guild, self.creator_id)
        await interaction.response.edit_message(embed=embed, view=view)


def build_template_browser(guild: str, creator_id: int) -> tuple:
    embed = discord.Embed(title='🎯 Мастер квестов',
                          description=f'📋 Шаблонов: **{len(quest_templates)}**\nВыберите категорию ниже. Для создания и изменения наград используйте меню управления квестами.',
                          color=discord.Color.blue())
    for cat in get_template_categories(): embed.add_field(name=cat, value=f'{len(get_templates_by_category(cat))}',
                                                          inline=True)
    return embed, TemplateCategoryView(guild, creator_id)


class CreateTemplateModal(discord.ui.Modal, title='Создание шаблона'):
    name_input = discord.ui.TextInput(label='Название', required=True, max_length=80)
    description_input = discord.ui.TextInput(label='Описание', style=discord.TextStyle.paragraph, required=True, max_length=300)
    bonus_input = discord.ui.TextInput(label='Бонус к зарплате (%)', default='10', required=True, max_length=6)
    time_input = discord.ui.TextInput(label='Срок (например 1д 2ч 30м; 0 = без)', default='1д', required=True, max_length=40)
    category_reward_input = discord.ui.TextInput(label='Категория | алмазы, XP', default='📋 Свои | 0, 0', required=True, max_length=60)

    def __init__(self, creator_id: int, template_type: str = 'weekly'):
        super().__init__()
        self.creator_id = creator_id
        self.template_type = template_type if template_type in ('daily', 'weekly') else 'weekly'

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction_can_manage_any_guild(interaction, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав или это меню создал другой пользователь.', ephemeral=True)
        try:
            bonus, time_limit = float(self.bonus_input.value.replace('%', '')), parse_duration_minutes(self.time_input.value)
            category, reward_text = self.category_reward_input.value.rsplit('|', 1)
            category = category.strip() or '📋 Свои'
            reward = parse_reward_pair(reward_text.strip())
        except ValueError as exc:
            return await interaction.response.send_message(f'❌ Проверьте поля: {exc}', ephemeral=True)
        if not (0 <= bonus <= 100 and 0 <= time_limit <= 525600):
            return await interaction.response.send_message('❌ Бонус должен быть 0–100%, срок — 0–525600 минут.', ephemeral=True)
        template_id = 'custom_' + generate_random_code(6)
        while template_id in quest_templates:
            template_id = 'custom_' + generate_random_code(6)
        quest_templates[template_id] = {'name': self.name_input.value, 'description': self.description_input.value,
                                        'bonus': bonus, 'time_limit': time_limit, 'category': category,
                                        'type': self.template_type, 'mode': 'individual', **reward,
                                        'creator_id': self.creator_id, 'created_at': now_msk().isoformat(),
                                        'is_custom': True}
        save_templates()
        await interaction.response.send_message(embed=discord.Embed(
            title='✅ Шаблон создан!', description=f"**{self.name_input.value}**\nID: `{template_id}`\n{quest_reward_label(reward)}",
            color=discord.Color.green()), ephemeral=True)


class CreateQuestModal(discord.ui.Modal, title='Создание квеста'):
    name_input = discord.ui.TextInput(label='Название', required=True, max_length=80)
    description_input = discord.ui.TextInput(label='Описание', style=discord.TextStyle.paragraph, required=True, max_length=300)
    bonus_input = discord.ui.TextInput(label='Бонус к зарплате (%)', default='10', required=True, max_length=6)
    time_input = discord.ui.TextInput(label='Срок (например 1д 2ч 30м; 0 = без)', default='1д', required=True, max_length=40)
    reward_input = discord.ui.TextInput(label='Награда: алмазы, XP (0,0 = без)', default='0, 0', required=True, max_length=20)

    def __init__(self, guild_name: str, quest_type: str, creator_id: int, mode: str = 'individual', reward_enabled: bool = True):
        super().__init__()
        self.guild_name, self.quest_type, self.creator_id, self.mode = guild_name, quest_type, creator_id, mode
        self.reward_enabled = reward_enabled
        if not reward_enabled:
            self.reward_input.default = '0, 0'

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction_can_manage_guild(interaction, self.guild_name, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав или это меню создал другой пользователь.', ephemeral=True)
        try:
            bonus, time_limit = float(self.bonus_input.value.replace('%', '')), parse_duration_minutes(self.time_input.value)
            reward = parse_reward_pair(self.reward_input.value) if self.reward_enabled else parse_reward_pair('0, 0')
        except ValueError as exc:
            return await interaction.response.send_message(f'❌ Проверьте поля: {exc}', ephemeral=True)
        if self.reward_enabled and reward['reward_type'] != 'diamonds_xp':
            return await interaction.response.send_message('❌ Для типа «с наградой» укажите хотя бы одно положительное значение алмазов или XP.', ephemeral=True)
        if not (0 <= bonus <= 100 and 0 <= time_limit <= 525600):
            return await interaction.response.send_message('❌ Бонус должен быть 0–100%, срок — 0–525600 минут.', ephemeral=True)
        if self.quest_type not in ('daily', 'weekly', 'once'):
            return await interaction.response.send_message('❌ Неизвестная периодичность квеста.', ephemeral=True)
        if self.mode not in ('individual', 'group'):
            return await interaction.response.send_message('❌ Неизвестный режим квеста.', ephemeral=True)
        board_id = GUILD_QUEST_BOARDS.get(self.guild_name)
        board = await _resolve_channel(board_id) if board_id else None
        if not isinstance(board, discord.ForumChannel):
            return await interaction.response.send_message('❌ Доска не настроена или канал не является форумом!', ephemeral=True)
        payload = {'guild': self.guild_name, 'name': self.name_input.value, 'description': self.description_input.value,
                   'type': self.quest_type, 'bonus': bonus, 'time_limit_minutes': time_limit,
                   'creator_id': self.creator_id, 'mode': self.mode, **reward}
        try:
            qid = generate_quest_id()
            type_label = {'weekly': '📅 Еженед.', 'daily': '📆 Ежедн.', 'once': '🎯 Разовый'}[self.quest_type]
            title = f"{type_label} | {self.name_input.value}"
            body = (f"🆔 **ID квеста: `{qid}`**\n\n🎯 **{self.name_input.value}**\n\n{self.description_input.value}\n\n"
                    f"💼 **Бонус к зарплате:** +{bonus:g}%\n⏰ **Срок:** {format_duration(time_limit)}\n"
                    f"{quest_reward_label(reward)}\n\nПоставьте {QUEST_TAKE_REACTION}, чтобы взять!")
            thread, msg = await create_forum_post(board, title, body)
            data['quests'][qid] = {**payload, 'created_at': now_msk().isoformat(), 'thread_id': thread.id,
                                   'message_id': msg.id, 'status': 'active'}
            save_data()
            for reaction in (QUEST_TAKE_REACTION, QUEST_CONFIRM_REACTION):
                try:
                    await msg.add_reaction(reaction)
                except discord.HTTPException as reaction_error:
                    print(f'⚠️ Не удалось добавить реакцию {reaction} к квесту {qid}: {reaction_error}')
            await interaction.response.send_message(embed=discord.Embed(title='✅ Квест создан!', description=f'{thread.mention}\n🆔 ID квеста: `{qid}`\n{quest_reward_label(reward)}', color=discord.Color.green()), ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(f'❌ Ошибка создания квеста: {exc}', ephemeral=True)


class QuestRewardTypeView(AuthorizedView):
    """Явный выбор типа квеста в меню до выбора индивидуального/группового режима."""
    def __init__(self, guild_name: str, quest_type: str, creator_id: int):
        super().__init__(creator_id=creator_id, guild_name=guild_name, timeout=180)
        self.guild_name, self.quest_type, self.creator_id = guild_name, quest_type, creator_id

    @discord.ui.button(label='💎 С наградой', style=discord.ButtonStyle.success, row=0)
    async def rewarded(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(title='👥 Режим выполнения', description='Квест будет выдавать указанные алмазы и XP, а процентный бонус к зарплате сохранится. Выберите режим.', color=discord.Color.green()),
            view=QuestModeView(self.guild_name, self.quest_type, self.creator_id, reward_enabled=True))

    @discord.ui.button(label='📋 Без награды', style=discord.ButtonStyle.secondary, row=0)
    async def no_reward(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(title='👥 Режим выполнения', description='Алмазы и XP не выдаются; процентный бонус к зарплате сохраняется. Выберите режим.', color=discord.Color.blue()),
            view=QuestModeView(self.guild_name, self.quest_type, self.creator_id, reward_enabled=False))

    @discord.ui.button(label='↩️ Назад', style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=discord.Embed(title='🎯 Создание квеста', description='Выберите способ создания.', color=discord.Color.blue()), view=QuestCreateMenuView(self.guild_name, self.creator_id))


class QuestModeView(AuthorizedView):
    def __init__(self, guild_name: str, quest_type: str, creator_id: int, reward_enabled: bool = True):
        super().__init__(creator_id=creator_id, guild_name=guild_name, timeout=120)
        self.guild_name, self.quest_type, self.creator_id = guild_name, quest_type, creator_id
        self.reward_enabled = reward_enabled

    @discord.ui.button(label='👤 Индивидуальный', style=discord.ButtonStyle.primary)
    async def individual(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction_can_manage_guild(interaction, self.guild_name, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
        await interaction.response.send_modal(CreateQuestModal(self.guild_name, self.quest_type, self.creator_id, 'individual', self.reward_enabled))

    @discord.ui.button(label='👥 Групповой', style=discord.ButtonStyle.success)
    async def group(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction_can_manage_guild(interaction, self.guild_name, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
        await interaction.response.send_modal(CreateQuestModal(self.guild_name, self.quest_type, self.creator_id, 'group', self.reward_enabled))


# === UI КОМАНДЫ ===

@bot.command(name='template_add')
async def template_add(ctx):
    if not ctx.guild: return await ctx.send('❌ Команда доступна только на сервере Discord.')
    if not get_leader_guild(ctx) and not ctx.author.guild_permissions.administrator: return await ctx.send(
        '❌ Только для глав/админов!')
    view = AuthorizedView(creator_id=ctx.author.id, any_guild=True, timeout=120)
    btn = discord.ui.Button(label='➕ Создать шаблон', style=discord.ButtonStyle.success)

    async def on_click(interaction: discord.Interaction, *args):
        await interaction.response.send_modal(CreateTemplateModal(ctx.author.id))

    btn.callback = on_click
    view.add_item(btn)
    await ctx.send(
        embed=discord.Embed(title='➕ Создание шаблона', description='Нажмите кнопку', color=discord.Color.green()),
        view=view)


@bot.command(name='template_list')
async def template_list(ctx):
    embed = discord.Embed(title='📋 Все шаблоны', description=f'Всего: **{len(quest_templates)}**',
                          color=discord.Color.blue())
    for cat in get_template_categories():
        lines = [f"`{t['id'][:12]}` **{t['name']}** (+{t['bonus']}%){' 🆕' if t.get('is_custom') else ''}" for t in
                 get_templates_by_category(cat)[:10]]
        if lines: embed.add_field(name=f'📂 {cat} ({len(get_templates_by_category(cat))})', value='\n'.join(lines),
                                  inline=False)
    await ctx.send(embed=embed)


@bot.command(name='template_reward')
async def template_reward(ctx, template_id: str, diamonds: str, xp: str):
    """Настраивает предметную награду шаблона, в том числе для автоквестов."""
    if not ctx.guild:
        return await ctx.send('❌ Команда доступна только на сервере Discord.')
    if not ctx.author.guild_permissions.administrator and not get_leader_guild(ctx):
        return await ctx.send('❌ Только для глав/админов!')
    resolved_id = next((tid for tid in quest_templates if tid.casefold() == template_id.casefold()), None)
    if not resolved_id:
        return await ctx.send('❌ Шаблон не найден. Используйте `.template_list`.')
    try:
        reward = parse_reward_pair(f'{diamonds}, {xp}')
    except ValueError as exc:
        return await ctx.send(f'❌ {exc}')
    quest_templates[resolved_id].update(reward)
    save_templates()
    await ctx.send(f'✅ Награда шаблона **{quest_templates[resolved_id]["name"]}** обновлена: {quest_reward_label(reward)}')


@bot.command(name='template_delete')
async def template_delete(ctx, template_id: str = None):
    if not ctx.guild: return await ctx.send('❌ Команда доступна только на сервере Discord.')
    if not ctx.author.guild_permissions.administrator and not get_leader_guild(ctx): return await ctx.send(
        '❌ Только для глав/админов!')
    if template_id:
        t = get_template(template_id)
        if not t: return await ctx.send('❌ Не найден.')
        if not t.get('is_custom'): return await ctx.send('❌ Нельзя удалить базовый шаблон!')
        quest_templates.pop(template_id, None)
        save_templates()
        return await ctx.send(f'✅ Шаблон **{t["name"]}** удалён.')
    custom = [{'id': tid, **t} for tid, t in quest_templates.items() if t.get('is_custom')]
    if not custom: return await ctx.send('📭 Нет своих шаблонов.')
    await ctx.send(embed=discord.Embed(title='🗑️ Удаление шаблона', description='.template_delete ID\n\n' + '\n'.join(
        [f"`{t['id']}` — {t['name']}" for t in custom[:20]]), color=discord.Color.red()))




class TemplateRewardModal(discord.ui.Modal, title='Настройка награды шаблона'):
    diamonds_input = discord.ui.TextInput(label='Алмазы (0–1000000)', default='0', required=True, max_length=8)
    xp_input = discord.ui.TextInput(label='Опыт XP (0–1000000)', default='0', required=True, max_length=8)

    def __init__(self, template_id: str, creator_id: int):
        super().__init__()
        self.template_id = template_id
        self.creator_id = creator_id
        template = quest_templates.get(template_id, {})
        self.diamonds_input.default = str(int(template.get('reward_diamonds', 0) or 0))
        self.xp_input.default = str(int(template.get('reward_xp', 0) or 0))

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.creator_id or not interaction_can_manage_any_guild(interaction, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав или меню создано другим пользователем.', ephemeral=True)
        template = quest_templates.get(self.template_id)
        if not template:
            return await interaction.response.send_message('❌ Шаблон больше не существует.', ephemeral=True)
        try:
            reward = parse_reward_pair(f'{self.diamonds_input.value}, {self.xp_input.value}')
        except ValueError as exc:
            return await interaction.response.send_message(f'❌ {exc}', ephemeral=True)
        template.update(reward)
        save_templates()
        await interaction.response.send_message(
            f'✅ Награда шаблона **{template["name"]}** обновлена: {quest_reward_label(reward)}', ephemeral=True)


class TemplateRewardSelect(discord.ui.Select):
    def __init__(self, creator_id: int):
        self.creator_id = creator_id
        templates = list(quest_templates.items())[:25]
        options = [discord.SelectOption(
            label=str(t.get('name', tid))[:100],
            description=f"{tid[:30]} · 💎 {int(t.get('reward_diamonds', 0) or 0)} · XP {int(t.get('reward_xp', 0) or 0)}"[:100],
            value=tid) for tid, t in templates]
        if not options:
            options = [discord.SelectOption(label='Нет доступных шаблонов', value='__none__')]
        super().__init__(placeholder='Выберите шаблон для настройки награды...', options=options, disabled=not quest_templates)

    async def callback(self, interaction: discord.Interaction):
        if not interaction_can_manage_any_guild(interaction, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
        await interaction.response.send_modal(TemplateRewardModal(self.values[0], self.creator_id))


class TemplateRewardMenuView(AuthorizedView):
    def __init__(self, creator_id: int):
        super().__init__(creator_id=creator_id, any_guild=True, timeout=180)
        self.add_item(TemplateRewardSelect(creator_id))
        back = discord.ui.Button(label='↩️ Главное меню', style=discord.ButtonStyle.secondary, row=1)
        async def back_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=build_main_menu_embed(interaction.user), view=build_main_menu_view(interaction.user))
        back.callback = back_cb
        self.add_item(back)


class PendingRewardSelect(discord.ui.Select):
    def __init__(self, creator_id: int, guild_name: Optional[str]):
        self.creator_id = creator_id
        self.guild_name = guild_name
        self.selected_key = None
        pending = []
        for qid, quest in data.get('quests', {}).items():
            if guild_name and quest.get('guild') != guild_name:
                continue
            for uid, participant in data.get('player_quests', {}).get(qid, {}).items():
                if participant.get('status') == 'confirmed' and participant.get('reward_status') == 'pending':
                    player = data.get('players', {}).get(str(uid), {})
                    nick = player.get('minecraft_nick', str(uid))
                    type_label = {'once': 'разовый', 'daily': 'ежедневный', 'weekly': 'еженедельный'}.get(quest.get('type'), 'квест')
                    label = f"[{type_label}] {quest.get('name', qid)} · {nick}"
                    desc = f"ID {qid} · 💎 {participant.get('reward_diamonds', 0)} · XP {participant.get('reward_xp', 0)}"
                    pending.append((qid, str(uid), label[:100], desc[:100]))
        self.pending_map = {f'{qid}|{uid}': (qid, uid) for qid, uid, _, _ in pending[:25]}
        options = [discord.SelectOption(label=label, description=desc, value=f'{qid}|{uid}')
                   for qid, uid, label, desc in pending[:25]]
        if not options:
            options = [discord.SelectOption(label='Нет ожидающих наград', value='__none__')]
        super().__init__(placeholder='Выберите участника с ожидающей наградой...', options=options,
                         disabled=not pending)

    async def callback(self, interaction: discord.Interaction):
        if not interaction_can_manage_any_guild(interaction, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
        self.selected_key = self.values[0]
        if self.selected_key not in self.pending_map:
            return await interaction.response.send_message('ℹ️ Сейчас нет ожидающих наград.', ephemeral=True)
        qid, uid = self.pending_map[self.selected_key]
        quest = data.get('quests', {}).get(qid, {})
        player = data.get('players', {}).get(uid, {})
        participant = data.get('player_quests', {}).get(qid, {}).get(uid, {})
        embed = discord.Embed(title='🎁 Подтверждение выдачи награды',
            description=f"**Квест:** {quest.get('name', qid)} (`{qid}`)\n**Тип:** {quest.get('type', '—')}\n**Игрок:** {player.get('minecraft_nick', uid)}\n"
                        f"**Награда:** 💎 {participant.get('reward_diamonds', 0)} · ✨ {participant.get('reward_xp', 0)} XP\n\n"
                        'Нажимайте подтверждение только после фактической передачи награды в Minecraft.',
            color=discord.Color.orange())
        await interaction.response.edit_message(embed=embed, view=PendingRewardConfirmView(self.creator_id, self.guild_name, qid, uid))


class PendingRewardConfirmView(AuthorizedView):
    def __init__(self, creator_id: int, guild_name: Optional[str], quest_id: str, user_id: str):
        super().__init__(creator_id=creator_id, guild_name=guild_name, any_guild=guild_name is None, timeout=180)
        self.quest_id, self.user_id = quest_id, user_id
        confirm = discord.ui.Button(label='✅ Награда выдана', style=discord.ButtonStyle.success)
        async def confirm_cb(interaction: discord.Interaction):
            quest = data.get('quests', {}).get(self.quest_id)
            participant = data.get('player_quests', {}).get(self.quest_id, {}).get(self.user_id)
            player = data.get('players', {}).get(self.user_id, {})
            if not quest or not participant or participant.get('status') != 'confirmed' or participant.get('reward_status') != 'pending':
                return await interaction.response.send_message('ℹ️ Эта награда уже обработана или больше не ожидает выдачи.', ephemeral=True)
            if quest.get('guild') != self.guild_name and self.guild_name is not None:
                return await interaction.response.send_message('❌ Награда относится к другой гильдии.', ephemeral=True)
            participant.update({'reward_status': 'paid', 'reward_paid_at': now_msk().isoformat(), 'reward_paid_by': interaction.user.id})
            save_data()
            await interaction.response.edit_message(embed=discord.Embed(title='✅ Выдача отмечена',
                description=f"Награда за **{quest.get('name', self.quest_id)}** для **{player.get('minecraft_nick', self.user_id)}** отмечена как выданная.\n"
                            f"💎 {participant.get('reward_diamonds', 0)} алмазов · ✨ {participant.get('reward_xp', 0)} XP",
                color=discord.Color.green()), view=None)
        confirm.callback = confirm_cb
        self.add_item(confirm)
        back = discord.ui.Button(label='↩️ К списку', style=discord.ButtonStyle.secondary)
        async def back_cb(interaction: discord.Interaction):
            view = PendingRewardMenuView(self.creator_id, self.guild_name)
            await interaction.response.edit_message(embed=view.make_embed(), view=view)
        back.callback = back_cb
        self.add_item(back)


class PendingRewardMenuView(AuthorizedView):
    def __init__(self, creator_id: int, guild_name: Optional[str]):
        super().__init__(creator_id=creator_id, guild_name=guild_name, any_guild=guild_name is None, timeout=180)
        self.add_item(PendingRewardSelect(creator_id, guild_name))
        back = discord.ui.Button(label='↩️ Главное меню', style=discord.ButtonStyle.secondary, row=1)
        async def back_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=build_main_menu_embed(interaction.user), view=build_main_menu_view(interaction.user))
        back.callback = back_cb
        self.add_item(back)

    def make_embed(self):
        guild_name = self.guild_name
        pending_by_type = {'once': 0, 'daily': 0, 'weekly': 0}
        count = 0
        for qid, quest in data.get('quests', {}).items():
            if guild_name and quest.get('guild') != guild_name:
                continue
            for part in data.get('player_quests', {}).get(qid, {}).values():
                if part.get('status') == 'confirmed' and part.get('reward_status') == 'pending':
                    count += 1
                    qtype = quest.get('type')
                    if qtype in pending_by_type:
                        pending_by_type[qtype] += 1
        note = '\nПоказаны первые 25 записей.' if count > 25 else ''
        type_summary = f"\n🎯 Разовые: **{pending_by_type['once']}** · 📆 Ежедневные: **{pending_by_type['daily']}** · 📅 Еженедельные: **{pending_by_type['weekly']}**"
        return discord.Embed(title='🎁 Ожидающие награды', description=f'Наград ожидают выдачи: **{count}**.{type_summary}{note}\nВыберите участника в списке ниже.', color=discord.Color.orange())


class TemplateDeleteSelect(discord.ui.Select):
    def __init__(self, creator_id: int):
        self.creator_id = creator_id
        custom = [(tid, t) for tid, t in quest_templates.items() if t.get('is_custom')][:25]
        options = [discord.SelectOption(label=str(t.get('name', tid))[:100], description=f'ID: {tid}'[:100], value=tid) for tid, t in custom]
        if not options:
            options = [discord.SelectOption(label='Нет пользовательских шаблонов', value='__none__')]
        super().__init__(placeholder='Выберите пользовательский шаблон для удаления...', options=options, disabled=not custom)

    async def callback(self, interaction: discord.Interaction):
        if not interaction_can_manage_any_guild(interaction, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
        tid = self.values[0]
        if tid == '__none__':
            return await interaction.response.send_message('ℹ️ Нет пользовательских шаблонов для удаления.', ephemeral=True)
        template = quest_templates.get(tid)
        if not template or not template.get('is_custom'):
            return await interaction.response.send_message('❌ Можно удалить только пользовательские шаблоны.', ephemeral=True)
        quest_templates.pop(tid, None)
        save_templates()
        await interaction.response.edit_message(embed=discord.Embed(title='🗑️ Шаблон удалён', description=template.get('name', tid), color=discord.Color.green()), view=TemplateManagementView(self.creator_id))


class TemplateManagementView(AuthorizedView):
    def __init__(self, creator_id: int):
        super().__init__(creator_id=creator_id, any_guild=True, timeout=180)
        create_btn = discord.ui.Button(label='➕ Создать шаблон', style=discord.ButtonStyle.success, row=0)
        async def create_cb(interaction: discord.Interaction):
            await interaction.response.send_modal(CreateTemplateModal(self.creator_id))
        create_btn.callback = create_cb
        self.add_item(create_btn)
        reward_btn = discord.ui.Button(label='💎 Настроить награду', style=discord.ButtonStyle.primary, row=0)
        async def reward_cb(interaction: discord.Interaction):
            view = TemplateRewardMenuView(self.creator_id)
            await interaction.response.edit_message(embed=discord.Embed(title='💎 Награда шаблона', description='Выберите шаблон. Награда 0 алмазов и 0 XP означает квест без дополнительной награды; бонус к зарплате сохраняется.', color=discord.Color.blue()), view=view)
        reward_btn.callback = reward_cb
        self.add_item(reward_btn)
        delete_btn = discord.ui.Button(label='🗑️ Удалить свой шаблон', style=discord.ButtonStyle.danger, row=1)
        async def delete_cb(interaction: discord.Interaction):
            view = discord.ui.View(timeout=180)
            view.add_item(TemplateDeleteSelect(self.creator_id))
            back = discord.ui.Button(label='↩️ К шаблонам', style=discord.ButtonStyle.secondary, row=1)
            async def back_cb(interaction2: discord.Interaction):
                await interaction2.response.edit_message(embed=discord.Embed(title='📋 Управление шаблонами', description='Выберите действие.', color=discord.Color.blue()), view=TemplateManagementView(self.creator_id))
            back.callback = back_cb
            view.add_item(back)
            await interaction.response.edit_message(embed=discord.Embed(title='🗑️ Удаление шаблона', description='Можно удалить только пользовательские шаблоны.', color=discord.Color.red()), view=view)
        delete_btn.callback = delete_cb
        self.add_item(delete_btn)
        list_btn = discord.ui.Button(label='📚 Показать шаблоны', style=discord.ButtonStyle.secondary, row=1)
        async def list_cb(interaction: discord.Interaction):
            embed = discord.Embed(title='📚 Шаблоны квестов', description=f'Всего: **{len(quest_templates)}**', color=discord.Color.blue())
            for cat in get_template_categories():
                lines = [f"`{tid}` — {t.get('name', 'Без названия')} · +{t.get('bonus', 0)}% · 💎 {t.get('reward_diamonds', 0)} · XP {t.get('reward_xp', 0)}"
                         for tid, t in quest_templates.items() if t.get('category') == cat][:8]
                if lines: embed.add_field(name=cat, value='\n'.join(lines)[:1024], inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
        list_btn.callback = list_cb
        self.add_item(list_btn)
        back = discord.ui.Button(label='↩️ Главное меню', style=discord.ButtonStyle.secondary, row=3)
        async def back_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=build_main_menu_embed(interaction.user), view=build_main_menu_view(interaction.user))
        back.callback = back_cb
        self.add_item(back)


class QuestCreateMenuView(AuthorizedView):
    def __init__(self, guild_name: str, creator_id: int):
        super().__init__(creator_id=creator_id, guild_name=guild_name, timeout=180)
        self.guild_name = guild_name
        template_btn = discord.ui.Button(label='📋 Из шаблона', style=discord.ButtonStyle.primary)
        async def template_cb(interaction: discord.Interaction):
            embed, view = build_template_browser(self.guild_name, self.creator_id)
            await interaction.response.edit_message(embed=embed, view=view)
        template_btn.callback = template_cb
        self.add_item(template_btn)
        weekly_btn = discord.ui.Button(label='📅 Еженедельный', style=discord.ButtonStyle.success)
        async def weekly_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=discord.Embed(title='Режим квеста', description='Выберите, кто выполняет квест.', color=discord.Color.blue()), view=QuestRewardTypeView(self.guild_name, 'weekly', self.creator_id))
        weekly_btn.callback = weekly_cb
        self.add_item(weekly_btn)
        daily_btn = discord.ui.Button(label='📆 Ежедневный', style=discord.ButtonStyle.secondary)
        async def daily_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=discord.Embed(title='Режим квеста', description='Выберите, кто выполняет квест.', color=discord.Color.blue()), view=QuestRewardTypeView(self.guild_name, 'daily', self.creator_id))
        daily_btn.callback = daily_cb
        self.add_item(daily_btn)
        once_btn = discord.ui.Button(label='🎯 Единоразовый', style=discord.ButtonStyle.primary, row=1)
        async def once_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(
                embed=discord.Embed(title='Режим единоразового квеста', description='Квест будет опубликован один раз и не будет повторяться по расписанию. Выберите, кто выполняет квест.', color=discord.Color.blue()),
                view=QuestRewardTypeView(self.guild_name, 'once', self.creator_id))
        once_btn.callback = once_cb
        self.add_item(once_btn)
        back = discord.ui.Button(label='↩️ Главное меню', style=discord.ButtonStyle.secondary, row=3)
        async def back_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=build_main_menu_embed(interaction.user), view=build_main_menu_view(interaction.user))
        back.callback = back_cb
        self.add_item(back)


class QuestIdSelect(discord.ui.Select):
    def __init__(self, creator_id: int, guild_name: Optional[str], status_filter: str = 'all'):
        self.creator_id, self.guild_name = creator_id, guild_name
        quests = [(qid, q) for qid, q in data.get('quests', {}).items()
                  if (not guild_name or q.get('guild') == guild_name)
                  and (status_filter == 'all' or q.get('status') == status_filter)]
        quests.sort(key=lambda item: item[1].get('created_at', ''), reverse=True)
        self.quest_map = {qid: q for qid, q in quests[:25]}
        options = [discord.SelectOption(
            label=str(q.get('name', qid))[:100],
            description=f"ID {qid} · {q.get('type', '—')} · {q.get('status', '—')}"[:100],
            value=qid) for qid, q in quests[:25]]
        if not options:
            options = [discord.SelectOption(label='Квестов пока нет', value='__none__')]
        super().__init__(placeholder='Выберите квест, чтобы увидеть его ID и детали...', options=options, disabled=not quests)

    async def callback(self, interaction: discord.Interaction):
        if not interaction_can_manage_any_guild(interaction, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
        qid = self.values[0]
        quest = self.quest_map.get(qid)
        if not quest:
            return await interaction.response.send_message('Квест не найден.', ephemeral=True)
        if not interaction_can_manage_guild(interaction, quest.get('guild', ''), self.creator_id):
            return await interaction.response.send_message('❌ Нет прав для этой гильдии.', ephemeral=True)
        embed = discord.Embed(title=f"🎯 {quest.get('name', qid)}", description=f"🆔 **ID:** `{qid}`\n🏛️ **Гильдия:** {quest.get('guild', '—')}\n📌 **Статус:** {quest.get('status', '—')}\n🔁 **Тип:** {quest.get('type', '—')}\n👥 **Режим:** {quest.get('mode', '—')}\n💼 **Бонус:** +{quest.get('bonus', 0)}%\n{quest_reward_label(quest)}", color=discord.Color.blue())
        if quest.get('thread_id'):
            embed.add_field(name='Публикация', value=f"https://discord.com/channels/{interaction.guild_id}/{quest.get('thread_id')}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class QuestIdMenuView(AuthorizedView):
    def __init__(self, creator_id: int, guild_name: Optional[str]):
        super().__init__(creator_id=creator_id, guild_name=guild_name, any_guild=guild_name is None, timeout=180)
        self.add_item(QuestIdSelect(creator_id, guild_name))
        back = discord.ui.Button(label='↩️ К управлению квестами', style=discord.ButtonStyle.secondary, row=1)
        async def back_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=discord.Embed(title='🎯 Управление квестами', description='Выберите действие.', color=discord.Color.blue()), view=QuestHubView(self.creator_id, self.guild_name))
        back.callback = back_cb
        self.add_item(back)


class QuestHubView(AuthorizedView):
    def __init__(self, creator_id: int, guild_name: Optional[str]):
        super().__init__(creator_id=creator_id, guild_name=guild_name, any_guild=guild_name is None, timeout=180)
        self.guild_name = guild_name
        create_btn = discord.ui.Button(label='➕ Создать квест', style=discord.ButtonStyle.success, row=0)
        async def create_cb(interaction: discord.Interaction):
            guild = self.guild_name or get_leader_guild_from_member(interaction.user) or GUILD_NAMES[0]
            if not interaction_can_manage_guild(interaction, guild, self.creator_id):
                return await interaction.response.send_message('❌ Выберите свою гильдию или используйте меню из её категории.', ephemeral=True)
            if not GUILD_QUEST_BOARDS.get(guild):
                return await interaction.response.send_message(f'❌ Доска квестов не настроена для **{guild}**.', ephemeral=True)
            await interaction.response.edit_message(embed=discord.Embed(title='🎯 Создание квеста', description='Выберите способ создания.', color=discord.Color.blue()), view=QuestCreateMenuView(guild, self.creator_id))
        create_btn.callback = create_cb
        self.add_item(create_btn)
        templates_btn = discord.ui.Button(label='📚 Шаблоны и награды', style=discord.ButtonStyle.primary, row=0)
        async def templates_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=discord.Embed(title='📋 Управление шаблонами', description='Создавайте шаблоны, смотрите их и меняйте награды кнопками.', color=discord.Color.blue()), view=TemplateManagementView(self.creator_id))
        templates_btn.callback = templates_cb
        self.add_item(templates_btn)
        ids_btn = discord.ui.Button(label='🆔 Список квестов и ID', style=discord.ButtonStyle.secondary, row=1)
        async def ids_cb(interaction: discord.Interaction):
            view = QuestIdMenuView(self.creator_id, self.guild_name)
            await interaction.response.edit_message(embed=discord.Embed(title='🆔 Квесты и их ID', description='Выберите квест, чтобы посмотреть его ID, статус и параметры. Последние 25 квестов.', color=discord.Color.blue()), view=view)
        ids_btn.callback = ids_cb
        self.add_item(ids_btn)
        rewards_btn = discord.ui.Button(label='🎁 Выдать награду', style=discord.ButtonStyle.primary, row=1)
        async def rewards_cb(interaction: discord.Interaction):
            view = PendingRewardMenuView(self.creator_id, self.guild_name)
            await interaction.response.edit_message(embed=view.make_embed(), view=view)
        rewards_btn.callback = rewards_cb
        self.add_item(rewards_btn)
        close_btn = discord.ui.Button(label='🔒 Закрыть квест', style=discord.ButtonStyle.secondary, row=2)
        async def close_cb(interaction: discord.Interaction):
            guild = self.guild_name
            active = [(qid, q) for qid, q in data.get('quests', {}).items() if q.get('status') == 'active' and (not guild or q.get('guild') == guild)]
            options = [discord.SelectOption(label=str(q.get('name', qid))[:100], description=f"{qid} · {q.get('guild', '')}"[:100], value=qid) for qid, q in active[:25]]
            view = discord.ui.View(timeout=180)
            select = discord.ui.Select(placeholder='Выберите активный квест для закрытия...', options=options, disabled=not options)
            async def select_cb(interaction2: discord.Interaction):
                qid = select.values[0]
                q = data.get('quests', {}).get(qid)
                if not q or q.get('status') != 'active':
                    return await interaction2.response.send_message('Квест уже закрыт или удалён.', ephemeral=True)
                if not interaction_can_manage_guild(interaction2, q.get('guild', ''), self.creator_id):
                    return await interaction2.response.send_message('❌ Нет прав для этой гильдии.', ephemeral=True)
                q['status'] = 'closed'
                q['closed_at'] = now_msk().isoformat()
                for participant in data.get('player_quests', {}).get(qid, {}).values():
                    if participant.get('status') == 'taken':
                        participant.update({'status': 'cancelled', 'cancelled_at': q['closed_at'], 'closed_by_leader': True})
                save_data()
                thread = await _resolve_channel(q.get('thread_id')) if q.get('thread_id') else None
                if isinstance(thread, discord.Thread):
                    try: await thread.edit(locked=True, archived=True, reason='Квест закрыт через меню')
                    except discord.HTTPException: pass
                await interaction2.response.edit_message(embed=discord.Embed(title='🔒 Квест закрыт', description=f"**{q.get('name', qid)}** (`{qid}`)", color=discord.Color.green()), view=None)
            select.callback = select_cb
            view.add_item(select)
            back = discord.ui.Button(label='↩️ Назад', style=discord.ButtonStyle.secondary, row=1)
            async def back_cb(interaction2: discord.Interaction):
                await interaction2.response.edit_message(embed=discord.Embed(title='🎯 Управление квестами', description='Выберите действие.', color=discord.Color.blue()), view=QuestHubView(self.creator_id, self.guild_name))
            back.callback = back_cb; view.add_item(back)
            await interaction.response.edit_message(embed=discord.Embed(title='🔒 Закрытие квеста', description=f'Активных квестов: {len(active)}. Выберите квест из списка.', color=discord.Color.orange()), view=view)
        close_btn.callback = close_cb
        self.add_item(close_btn)
        schedule_btn = discord.ui.Button(label='⚙️ Автоквесты', style=discord.ButtonStyle.secondary, row=3)
        async def schedule_cb(interaction: discord.Interaction):
            guild = self.guild_name or get_leader_guild_from_member(interaction.user) or GUILD_NAMES[0]
            view = QuestScheduleMenu(self.creator_id, guild)
            await interaction.response.edit_message(embed=view.make_embed(), view=view)
        schedule_btn.callback = schedule_cb
        self.add_item(schedule_btn)
        back = discord.ui.Button(label='↩️ Главное меню', style=discord.ButtonStyle.secondary, row=3)
        async def back_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=build_main_menu_embed(interaction.user), view=build_main_menu_view(interaction.user))
        back.callback = back_cb
        self.add_item(back)


def get_leader_guild_from_member(member) -> Optional[str]:
    if not hasattr(member, 'roles'):
        return None
    for guild, role_id in GUILD_LEADER_ROLES.items():
        if discord.utils.get(member.roles, id=role_id):
            return guild
    return None


class AdminGuildSelectView(discord.ui.View):
    """Администратор выбирает конкретную гильдию перед управлением её квестами."""
    def __init__(self, creator_id: int, mode: str):
        super().__init__(timeout=180)
        self.creator_id = creator_id
        self.mode = mode
        select = discord.ui.Select(placeholder='Выберите гильдию…', options=[
            discord.SelectOption(label=f"{GUILD_EMOJIS[g]} {g}", value=g) for g in GUILD_NAMES])
        async def select_callback(interaction: discord.Interaction):
            if interaction.user.id != self.creator_id:
                return await interaction.response.send_message('Это меню создано другим пользователем.', ephemeral=True)
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message('Выбор всех гильдий доступен только администратору.', ephemeral=True)
            guild_name = select.values[0]
            if self.mode == 'schedule':
                menu = QuestScheduleMenu(self.creator_id, guild_name)
                await interaction.response.edit_message(embed=menu.make_embed(), view=menu)
            else:
                menu = QuestHubView(self.creator_id, guild_name)
                await interaction.response.edit_message(embed=discord.Embed(
                    title=f'🎯 Управление квестами · {guild_name}',
                    description='Создание, шаблоны, награды, закрытие и автоквесты.', color=discord.Color.blue()), view=menu)
        select.callback = select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.creator_id:
            await interaction.response.send_message('Это меню создано другим пользователем.', ephemeral=True)
            return False
        return True


class MainMenuView(discord.ui.View):
    def __init__(self, creator_id: int):
        super().__init__(timeout=300)
        self.creator_id = creator_id
        # All controls are created exactly once by build_main_menu_view().

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.creator_id:
            await interaction.response.send_message('❌ Это меню создано другим пользователем. Вызовите `.menu` для своего меню.', ephemeral=True)
            return False
        return True


def build_main_menu_embed(member) -> discord.Embed:
    role = 'администратор' if getattr(getattr(member, 'guild_permissions', None), 'administrator', False) else (
        f'глава гильдии: {get_leader_guild_from_member(member)}' if get_leader_guild_from_member(member) else
        ('игрок' if str(member.id) in data.get('players', {}) else 'не зарегистрирован'))
    return discord.Embed(title='🧭 Главное меню RPG-бота', description=f'Пользователь: **{member.display_name}**\nРоль: **{role}**\n\nВыберите действие кнопками ниже. Команды по-прежнему доступны для совместимости.', color=discord.Color.blurple())


def build_main_menu_view(member) -> discord.ui.View:
    view = MainMenuView(member.id)
    cabinet = discord.ui.Button(label='👤 Личный кабинет', style=discord.ButtonStyle.secondary, row=0)
    async def cabinet_cb(interaction: discord.Interaction):
        player = data.get('players', {}).get(str(interaction.user.id))
        if not player:
            return await interaction.response.send_message('❌ Вы ещё не зарегистрированы.', ephemeral=True)
        embed = discord.Embed(title=f"👤 Кабинет: {player.get('minecraft_nick', 'Игрок')}", color=discord.Color.blue())
        embed.add_field(name='🏅 Ранг', value=str(player.get('rank', '—')), inline=True)
        embed.add_field(name='⭐ Очки', value=str(player.get('points', 0)), inline=True)
        embed.add_field(name='💰 Зарплата', value=str(player.get('salary', 0)), inline=True)
        embed.add_field(name='🎯 Бонус к зарплате', value=f"+{player.get('quest_bonus', 0)}%", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    cabinet.callback = cabinet_cb; view.add_item(cabinet)
    myq = discord.ui.Button(label='🎯 Мои квесты', style=discord.ButtonStyle.secondary, row=0)
    async def myq_cb(interaction: discord.Interaction):
        uid = str(interaction.user.id); player = data.get('players', {}).get(uid)
        if not player: return await interaction.response.send_message('❌ Вы ещё не зарегистрированы.', ephemeral=True)
        embed = discord.Embed(title=f"🎯 Квесты {player.get('minecraft_nick', 'Игрок')}", color=discord.Color.blue())
        entries = []
        for qid, users in data.get('player_quests', {}).items():
            if uid not in users: continue
            quest = data.get('quests', {}).get(qid, {}); part = users[uid]
            state = {'taken':'🟡 в процессе','confirmed':'✅ подтверждён','overdue':'⏰ просрочен','cancelled':'🚫 отменён'}.get(part.get('status'), part.get('status','—'))
            reward_state = ' · 🎁 награда ожидает выдачи' if part.get('reward_status') == 'pending' else (' · ✅ награда выдана' if part.get('reward_status') == 'paid' else '')
            entries.append(f"**{quest.get('name', qid)}** (`{qid}`) — {state} (+{quest.get('bonus', 0)}%){reward_state}")
        embed.description = '\n'.join(entries[:20]) if entries else 'Активных и завершённых квестов пока нет.'
        await interaction.response.send_message(embed=embed, ephemeral=True)
    myq.callback = myq_cb; view.add_item(myq)
    member_guild = get_leader_guild_from_member(member)
    is_admin = getattr(getattr(member, 'guild_permissions', None), 'administrator', False)
    if member_guild or is_admin:
        quests = discord.ui.Button(label='🛠️ Управление квестами', style=discord.ButtonStyle.primary, row=1)
        async def quests_cb(interaction: discord.Interaction):
            guild = get_leader_guild_from_member(interaction.user)
            if interaction.user.guild_permissions.administrator and not guild:
                return await interaction.response.edit_message(
                    embed=discord.Embed(title='🎯 Выбор гильдии', description='Администратор может управлять квестами каждой гильдии. Выберите нужную.', color=discord.Color.blue()),
                    view=AdminGuildSelectView(interaction.user.id, 'quests'))
            hub = QuestHubView(interaction.user.id, guild)
            await interaction.response.edit_message(embed=discord.Embed(title='🎯 Управление квестами', description='Создание квестов, шаблоны, награды, закрытие и автоквесты собраны здесь.', color=discord.Color.blue()), view=hub)
        quests.callback = quests_cb; view.add_item(quests)
        schedules = discord.ui.Button(label='⚙️ Расписание автоквестов', style=discord.ButtonStyle.secondary, row=1)
        async def schedules_cb(interaction: discord.Interaction):
            guild = get_leader_guild_from_member(interaction.user)
            if interaction.user.guild_permissions.administrator and not guild:
                return await interaction.response.edit_message(
                    embed=discord.Embed(title='⚙️ Выбор гильдии', description='Выберите гильдию для настройки автоквестов.', color=discord.Color.blue()),
                    view=AdminGuildSelectView(interaction.user.id, 'schedule'))
            v = QuestScheduleMenu(interaction.user.id, guild or GUILD_NAMES[0])
            await interaction.response.edit_message(embed=v.make_embed(), view=v)
        schedules.callback = schedules_cb; view.add_item(schedules)
    help_btn = discord.ui.Button(label='📚 Справка', style=discord.ButtonStyle.secondary, row=2)
    async def help_cb(interaction: discord.Interaction):
        await interaction.response.send_message('Используйте `.chelp` для полного справочника команд. Управление квестами доступно через это меню.', ephemeral=True)
    help_btn.callback = help_cb; view.add_item(help_btn)
    guide_btn = discord.ui.Button(label='📖 Гайды гильдий', style=discord.ButtonStyle.secondary, row=2)
    async def guide_cb(interaction: discord.Interaction):
        allowed = [g for g in GUILD_NAMES if _member_in_guild(interaction.user, g)]
        if interaction.user.guild_permissions.administrator:
            allowed = list(GUILD_NAMES)
        if not allowed:
            return await interaction.response.send_message('Сначала вступите в гильдию, чтобы открыть её гайд.', ephemeral=True)
        opts = [discord.SelectOption(label=GUILD_GUIDES[g][0][:100], value=g) for g in allowed]
        v = discord.ui.View(timeout=180)
        sel = discord.ui.Select(placeholder='Выберите гильдию для подробного гайда', options=opts)
        async def guide_select(i: discord.Interaction):
            guild_name = sel.values[0]
            if not i.user.guild_permissions.administrator and not _member_in_guild(i.user, guild_name):
                return await i.response.send_message('❌ Гайд доступен участникам этой гильдии.', ephemeral=True)
            title, body = GUILD_GUIDES[guild_name]
            emb = discord.Embed(title=title, description=body, color=discord.Color.blurple())
            emb.set_footer(text='Откройте .menu для перехода к функциям гильдии.')
            await i.response.send_message(embed=emb, ephemeral=True)
        sel.callback = guide_select; v.add_item(sel)
        await interaction.response.send_message('Выберите гильдию:', view=v, ephemeral=True)
    guide_btn.callback = guide_cb; view.add_item(guide_btn)
    # Категории каталога: игрокам доступны личный кабинет, банк и кредиты;
    # управленческие разделы показываются по роли и повторно проверяются в callback.
    add_directory_button(view, member, '👤 Личный кабинет', 2)
    add_directory_button(view, member, '🏦 Банк', 3)
    add_directory_button(view, member, '💳 Кредиты', 3)
    if is_admin or any(_member_in_guild(member, g) for g in GUILD_NAMES):
        add_directory_button(view, member, '🏛️ Гильдия', 4)
    if member_guild or is_admin:
        add_directory_button(view, member, '🎯 Квесты', 4)
    if _member_in_guild(member, 'СОБР') or is_admin:
        add_directory_button(view, member, '🛡️ СОБР', 4)
    if is_admin:
        add_directory_button(view, member, '⚙️ Администрирование', 4)
    return view


# Полный каталог команд: интерфейс меню скрывает длинный список команд,
# но сохраняет каждый исходный обработчик и его аргументы/проверки доступа.
MENU_COMMAND_GROUPS = {
    '👤 Личный кабинет': [
        'register', 'cancel_registration', 'cabinet', 'stats', 'week', 'achievements',
        'titles', 'title_set', 'territory_limit', 'rank_info', 'compare', 'history',
        'my_quests', 'vacation', 'vacation_cancel',
    ],
    '🏛️ Гильдия': [
        'list', 'add', 'add_batch', 'remove', 'generate', 'codes', 'revoke',
        'analytics', 'vacation_list',
    ],
    '🎯 Квесты': [
        'quest_create', 'quest_confirm', 'quest_reward_paid', 'quest_delete',
        'template_add', 'template_list', 'template_reward', 'template_delete', 'quest_schedule',
    ],
    '🛡️ СОБР': [
        'sobr_report', 'sobr_reports', 'sobr_dossier', 'sobr_violation_confirm',
        'sobr_fines', 'sobr_fine_paid', 'sobr_report_correct', 'sobr_passport_report',
    ],
    '🏦 Банк': [
        'bank_help', 'savings_open', 'savings_status', 'savings_deposit', 'savings_withdraw',
        'savings_visit', 'deposit_open', 'deposit_status', 'deposit_pay', 'deposit_early',
        'treasury', 'treasury_add', 'treasury_expense', 'treasury_approve', 'treasury_pay',
        'treasury_reserve', 'treasury_release', 'bank_report', 'bank_history', 'bank_staff',
    ],
    '💳 Кредиты': [
        'credit_apply', 'credit_requests', 'credit_approve', 'credit_issue', 'credit_reject',
        'credit_passport', 'credit_staff', 'credit_limits', 'credit_service_channel',
        'creditors', 'credit_status', 'credit_pay', 'credit_edit', 'credit_audit', 'credit_help',
    ],
    '⚙️ Администрирование': [
        'set_quest_board', 'set_category', 'set_report_channel', 'show_settings',
        'force_reset', 'sync_roles', 'reset_vacation_cooldown',
    ],
}


MENU_ACTION_HELP = {
    'register': 'Начинает регистрацию Minecraft-профиля. Введите игровой ник и подтвердите его реакцией в личных сообщениях бота.',
    'cancel_registration': 'Отменяет незавершённую регистрацию, не затрагивая уже созданный профиль.',
    'cabinet': 'Показывает ваш Minecraft-ник, гильдию, ранг, очки, зарплату и бонусы.',
    'stats': 'Показывает текущий ранг, очки, задания и состояние прогресса участника.',
    'week': 'Показывает состояние текущей недели и время до недельного сброса.',
    'achievements': 'Показывает полученные достижения и условия дальнейшего прогресса.',
    'titles': 'Показывает доступные титулы профиля.',
    'title_set': 'Устанавливает выбранный титул, если он уже открыт игроку.',
    'territory_limit': 'Показывает или рассчитывает лимит территории по рангу и заданной базовой площади.',
    'rank_info': 'Показывает пороги очков, требования и особенности выбранного ранга.',
    'compare': 'Сравнивает недельные результаты и динамику игрока.',
    'history': 'Показывает историю прогресса и изменений показателей.',
    'my_quests': 'Показывает личные задания, статусы, сроки и ожидающие награды.',
    'vacation': 'Оформляет отпуск на указанное число дней с учётом ограничений и кулдауна.',
    'vacation_cancel': 'Досрочно завершает действующий отпуск.',
    'vacation_list': 'Показывает участников, находящихся в отпуске.',
    'analytics': 'Формирует сводную аналитику по гильдии и её участникам.',
    'list': 'Показывает состав гильдии и игровые ранги участников.',
    'add': 'Добавляет участнику задания/прогресс и при необходимости задаёт ранг через штатную форму команды.',
    'add_batch': 'Массово добавляет прогресс указанным участникам.',
    'remove': 'Удаляет участника из учёта гильдии согласно исходным проверкам доступа.',
    'generate': 'Создаёт новый код приглашения в гильдию.',
    'codes': 'Показывает действующие коды приглашения и сроки их действия.',
    'revoke': 'Отзывает указанный код приглашения.',
    'quest_create': 'Открывает интерактивный мастер создания индивидуального или группового квеста.',
    'quest_confirm': 'Подтверждает выполнение квеста конкретным участником после проверки доказательств.',
    'quest_reward_paid': 'Отмечает предметную награду выданной после фактической передачи в Minecraft.',
    'quest_delete': 'Удаляет выбранный квест с применением исходных ограничений.',
    'template_add': 'Создаёт пользовательский шаблон квеста с описанием, категорией, сроком и наградой.',
    'template_list': 'Показывает доступные шаблоны квестов.',
    'template_reward': 'Изменяет алмазную и XP-награду выбранного шаблона.',
    'template_delete': 'Удаляет пользовательский шаблон квеста.',
    'quest_schedule': 'Открывает настройки автоматической публикации ежедневных и еженедельных квестов.',
    'sobr_report': 'Открывает форму служебного отчёта СОБР: правонарушение, инвентаризация, паспортная проверка или прочее.',
    'sobr_reports': 'Показывает последние служебные отчёты или записи, ожидающие рассмотрения.',
    'sobr_dossier': 'Открывает личное дело участника и связанные с ним отчёты; доступ к чужим делам ограничен рангом.',
    'sobr_violation_confirm': 'Фиксирует итог рассмотрения отчёта о нарушении. Только подтверждённые записи учитываются в статистике.',
    'sobr_fines': 'Показывает назначенные штрафы и их статус.',
    'sobr_fine_paid': 'Отмечает штраф погашенным после фактической передачи алмазов.',
    'sobr_report_correct': 'Добавляет отдельную запись-исправление, сохраняя первоначальный отчёт без изменений.',
    'sobr_passport_report': 'Формирует недельную сводку паспортных проверок.',
    'bank_help': 'Показывает правила банка, ставки, условия счетов, вкладов, казны и аудита.',
    'savings_open': 'Открывает накопительный счёт в режиме с пополнениями или без них.',
    'savings_status': 'Показывает состояние накопительного счёта, баланс, ставку и начисления.',
    'savings_deposit': 'Сотрудник регистрирует фактически полученный взнос на накопительный счёт.',
    'savings_withdraw': 'Сотрудник регистрирует фактическую выплату со счёта с проверкой минимального остатка.',
    'savings_visit': 'Подтверждает посещение физического банка для возобновления начисления процентов.',
    'deposit_open': 'Сотрудник регистрирует срочный вклад после фактического получения алмазов.',
    'deposit_status': 'Показывает активные и завершённые срочные вклады.',
    'deposit_pay': 'Подтверждает выплату по завершившемуся срочному вкладу.',
    'deposit_early': 'Оформляет досрочное закрытие вклада по правилам досрочной выплаты.',
    'treasury': 'Показывает свободную казну, резерв, обязательства и незавершённые расходы.',
    'treasury_add': 'Записывает физически подтверждённое поступление алмазов в свободную казну.',
    'treasury_expense': 'Создаёт запрос на расход из казны; крупные расходы требуют одобрения лидера.',
    'treasury_approve': 'Одобряет запрос крупного расхода от имени лидера торговцев.',
    'treasury_pay': 'Подтверждает расход только после фактической передачи алмазов.',
    'treasury_reserve': 'Переводит указанную сумму из свободной казны в резерв.',
    'treasury_release': 'Возвращает указанную сумму из резерва в свободную казну.',
    'bank_report': 'Формирует отчёт о банковских операциях за неделю или календарный месяц.',
    'bank_history': 'Показывает последние подтверждённые банковские операции.',
    'bank_staff': 'Назначает или снимает сотрудника банка; доступно лидеру торговцев.',
    'credit_apply': 'Подаёт заявку на кредит на 7, 14 или 30 дней. Нужны регистрация и подтверждённый паспорт.',
    'credit_requests': 'Показывает заявки, ожидающие решения сотрудников кредитного отдела.',
    'credit_approve': 'Одобряет заявку и создаёт кредит, ожидающий фактической выдачи.',
    'credit_issue': 'Подтверждает фактическую выдачу одобренного кредита; только после этого начинаются проценты и график.',
    'credit_reject': 'Отклоняет заявку с указанием причины.',
    'credit_passport': 'Подтверждает или отклоняет паспорт заёмщика.',
    'credit_staff': 'Назначает или снимает сотрудника кредитного отдела; доступно лидеру торговцев.',
    'credit_limits': 'Показывает или изменяет лимиты сумм для сроков кредитования.',
    'credit_service_channel': 'Задаёт служебный канал уведомлений кредитного отдела.',
    'creditors': 'Показывает реестр участников кредитного отдела.',
    'credit_status': 'Показывает текущий кредит, график платежей и задолженность участника.',
    'credit_pay': 'Фиксирует фактически полученный платёж по кредиту.',
    'credit_edit': 'Исправляет запись кредита с обязательной причиной и записью в аудит.',
    'credit_audit': 'Показывает журнал действий кредитного отдела.',
    'credit_help': 'Показывает подробные условия кредитования, ставки, сроки и правила выдачи.',
    'set_quest_board': 'Назначает форумную доску квестов для указанной гильдии.',
    'set_category': 'Назначает Discord-категорию гильдии.',
    'set_report_channel': 'Назначает канал отчётов гильдии.',
    'show_settings': 'Показывает текущие настройки категорий, каналов и досок квестов.',
    'force_reset': 'Запускает принудительный недельный сброс; используйте только при необходимости.',
    'sync_roles': 'Синхронизирует Discord-роли участников с данными рангов RPG.',
    'reset_vacation_cooldown': 'Сбрасывает кулдаун отпуска выбранного участника.',
}


class _MenuContextProxy:
    """Минимальный Context-адаптер: существующий callback выполняется из UI без дублирования бизнес-логики."""
    def __init__(self, interaction: discord.Interaction, command):
        self.interaction = interaction
        self.author = interaction.user
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.bot = bot
        self.command = command
        self.prefix = '.'
        self.invoked_with = command.name
        self.message = interaction.message

    async def send(self, content=None, *, embed=None, embeds=None, view=None, ephemeral=True, **kwargs):
        kwargs.pop('delete_after', None)
        kwargs.pop('reference', None)
        kwargs.pop('mention_author', None)
        if not self.interaction.response.is_done():
            return await self.interaction.response.send_message(content=content, embed=embed, embeds=embeds,
                view=view, ephemeral=ephemeral, **kwargs)
        return await self.interaction.followup.send(content=content, embed=embed, embeds=embeds,
            view=view, ephemeral=ephemeral, **kwargs)


GUILD_GUIDES = {
    'шахтёры': ('⛏️ Гайд гильдии шахтёров',
        '**Назначение:** добыча ресурсов, обеспечение города материалами и выполнение шахтёрских квестов.\n\n'
        '**Ежедневная работа:** откройте «Мои квесты», выберите доступное задание на добычу/исследование, '
        'выполните его в Minecraft и отправьте результат в теме квеста. Не берите задание, если не успеете до срока.\n\n'
        '**Подтверждение:** глава проверяет доказательства и подтверждает выполнение. Бонус к зарплате начисляется системой; '
        'алмазная/XP-награда требует отдельной физической передачи и отметки выдачи.\n\n'
        '**Ранги:** очки копятся за подтверждённые задания; повышение выполняется при недельном сбросе. '
        'Следите за минимальным количеством задач своего ранга и сроками отпуска.\n\n'
        '**Командные функции:** список участников, статистика, история, сравнение недель, отпуск и лимит территории доступны в личном кабинете/гильдии. '
        'Управление составом, приглашениями и квестами доступно главе и администраторам.'),
    'архитекторы': ('🏛️ Гайд гильдии архитекторов',
        '**Назначение:** строительство, развитие территории и поддержание инфраструктуры города.\n\n'
        '**Как выполнять задания:** внимательно читайте размеры, материалы и критерии квеста. До начала строительства согласуйте место и проект с руководством, '
        'если задание затрагивает общую территорию. Делайте скриншоты этапов и готового результата.\n\n'
        '**Сдача:** отправьте доказательства в теме соответствующего квеста. Глава проверит соответствие условиям и подтвердит выполнение. '
        'Не заменяйте материалы или размеры без согласования.\n\n'
        '**Прогресс:** очки и бонусы учитываются автоматически после подтверждения; ранги обновляются на недельном сбросе. '
        'Предметные награды выдаются отдельно после фактической передачи.\n\n'
        '**Руководство:** глава может создавать/закрывать задания, управлять шаблонами и участниками; обычным участникам доступны личная статистика, квесты и гайды.'),
    'торговцы': ('💰 Гайд гильдии торговцев, банка и кредитного отдела',
        '**Назначение:** торговля, финансовый учёт, накопительные счета, срочные вклады, казна и кредитование.\n\n'
        '**Обычный участник:** используйте меню банка для просмотра доступных счетов и статуса. Для кредита нужна регистрация и подтверждённый паспорт. '
        'Подайте заявку, выбрав сумму и срок 7/14/30 дней; дождитесь решения сотрудников. Одобрение ещё не означает выдачу: проценты и график начинаются '
        'только после того, как сотрудник подтвердит фактическую передачу алмазов.\n\n'
        '**Сотрудник банка/кредитного отдела:** записывайте операции только после физической передачи алмазов в Minecraft. '
        'Проверяйте получателя, сумму и ID операции. Не отмечайте выплату/пополнение заранее. Все действия попадают в аудит.\n\n'
        '**Накопительный счёт:** режим с пополнениями или без них выбирается при открытии; минимальный стартовый взнос — 100 алмазов. '
        'Для начисления процентов требуется подтверждённое посещение банка; после 7 дней без посещения начисление приостанавливается.\n\n'
        '**Срочный вклад:** сумма 500–5000 алмазов, срок выбирается при открытии. Досрочное закрытие возвращает 99% первоначального вклада без процентов.\n\n'
        '**Казна:** свободные средства и резерв учитываются отдельно от денег клиентов. Расходы от 500 алмазов требуют одобрения лидера. '
        'Лидер торговцев управляет сотрудниками, лимитами и служебным каналом. Администратор Discord имеет административный обход, но физические операции всё равно должны быть подтверждены.'),
    'СОБР': ('🛡️ Гайд СОБР: отчёты, дела и штрафы',
        '**Назначение:** служебные проверки, фиксация событий, паспорта и контроль нарушений.\n\n'
        '**Ранги и доступ:** создание отчётов доступно сотрудникам ранга D и выше. Просмотр чужих личных дел, подтверждение нарушений, отметка штрафов и ручной недельный отчёт '
        'о паспортах требуют ранга B и выше. Администратор Discord имеет обход проверок.\n\n'
        '**Создание отчёта:** выберите тип — правонарушение, инвентаризация ресурсов, проверка паспортов или прочий служебный отчёт. '
        'Укажите основание, цель, участников, факты и время (МСК). Пишите нейтрально и отделяйте наблюдаемые факты от предположений.\n\n'
        '**Личные дела:** отчёты привязываются к указанным лицам. Исправления добавляются отдельной записью — исходный отчёт не переписывается.\n\n'
        '**Нарушения и штрафы:** запись учитывается только после подтверждения уполномоченным сотрудником. Каждые два подтверждённых нарушения формируют штраф 200 алмазов. '
        'Отметку об оплате делайте только после фактической передачи алмазов в Minecraft.\n\n'
        '**Паспорта:** недельная сводка автоматически публикуется по понедельникам в 10:00 МСК; ручная генерация доступна рангу B+. '
        'Не публикуйте материалы закрытых дел вне служебного канала.'),
}


def _menu_convert_value(ctx, parameter, raw):
    """Преобразует строку формы в тип параметра; Member/Role/Channel ищутся на текущем сервере."""
    import typing
    annotation = parameter.annotation
    if isinstance(annotation, str):
        simple = annotation.replace('typing.', '').replace('Optional[', '').replace(']', '').strip()
        annotation = {'int': int, 'float': float, 'str': str, 'bool': bool,
                      'discord.Member': discord.Member, 'Member': discord.Member,
                      'discord.TextChannel': discord.TextChannel, 'TextChannel': discord.TextChannel}.get(simple, str)
    if annotation is inspect.Parameter.empty or annotation is str or annotation is None:
        return raw
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Union and type(None) in args:
        annotation = next((a for a in args if a is not type(None)), str)
    if annotation is int: return int(raw)
    if annotation is float: return float(raw)
    if annotation is bool: return raw.strip().lower() in {'1','да','yes','true','on'}
    if annotation is discord.Member:
        token = raw.strip().strip('<@!>').strip()
        member = ctx.guild.get_member(int(token)) if token.isdigit() and ctx.guild else None
        if member: return member
        raise ValueError('Укажите участника через @упоминание или ID.')
    if annotation is discord.TextChannel:
        token = raw.strip().strip('<#>').strip()
        channel = ctx.guild.get_channel(int(token)) if token.isdigit() and ctx.guild else None
        if channel: return channel
        raise ValueError('Укажите текстовый канал через #канал или ID.')
    return raw


class CommandActionModal(discord.ui.Modal):
    def __init__(self, interaction: discord.Interaction, command):
        super().__init__(title=f'Выполнить: {command.name}'[:45], timeout=300)
        self.creator_id = interaction.user.id
        self.command = command
        self.fields_by_name = {}
        params = list(command.clean_params.items())
        if len(params) > 5:
            raise ValueError('У этой команды слишком много параметров для одной формы. Используйте подробную инструкцию раздела.')
        for name, parameter in params:
            default = parameter.default
            required = default is inspect.Parameter.empty
            label = name.replace('_', ' ').capitalize()[:45]
            placeholder = f'Тип: {parameter.annotation}'[:100] if parameter.annotation is not inspect.Parameter.empty else 'Введите значение'
            field = discord.ui.TextInput(label=label, placeholder=placeholder,
                required=required, max_length=1000, style=discord.TextStyle.paragraph if parameter.kind == inspect.Parameter.KEYWORD_ONLY else discord.TextStyle.short)
            self.fields_by_name[name] = field
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.creator_id:
            return await interaction.response.send_message('Это форма другого пользователя.', ephemeral=True)
        ctx = _MenuContextProxy(interaction, self.command)
        args, kwargs = [], {}
        try:
            for name, parameter in self.command.clean_params.items():
                raw = str(self.fields_by_name[name].value).strip()
                if not raw:
                    continue
                value = _menu_convert_value(ctx, parameter, raw)
                kwargs[name] = value
            # Запускаем штатные checks команды, затем тот же callback с теми же данными.
            if not await self.command.can_run(ctx):
                return await interaction.response.send_message('❌ Команда недоступна вашей роли или правам.', ephemeral=True)
            await self.command.callback(ctx, *args, **kwargs)
        except commands.CommandError as exc:
            await ctx.send(f'❌ Проверка команды не пройдена: {exc}')
        except (ValueError, TypeError) as exc:
            await ctx.send(f'❌ Проверьте введённые значения: {exc}')
        except Exception as exc:
            print(f'[MENU] Ошибка запуска .{self.command.name}: {exc!r}')
            await ctx.send('❌ Не удалось выполнить действие через меню. Исходная команда и данные сохранены; обратитесь к администратору.')


def _menu_visible_commands(member, group_name: str):
    names = list(MENU_COMMAND_GROUPS[group_name])
    is_admin = bool(getattr(getattr(member, 'guild_permissions', None), 'administrator', False))
    if is_admin:
        return names
    is_trader = _member_in_guild(member, 'торговцы')
    is_trader_leader = bool(discord.utils.get(getattr(member, 'roles', []), id=GUILD_LEADER_ROLES['торговцы']))
    uid = str(member.id)
    def staff_ids(path):
        try:
            with open(path, 'r', encoding='utf-8') as stream:
                payload = json.load(stream)
            return {str(x) for x in payload.get('staff', [])}
        except (OSError, json.JSONDecodeError, AttributeError):
            return set()
    bank_staff = is_trader_leader or uid in staff_ids('treasury.json')
    credit_staff = is_trader_leader or uid in staff_ids('creditors.json')
    if group_name == '🏦 Банк':
        if not is_trader:
            public = {'bank_help', 'savings_open', 'savings_status', 'deposit_status'}
            return [name for name in names if name in public]
        if not bank_staff:
            public = {'bank_help', 'savings_open', 'savings_status', 'deposit_status'}
            return [name for name in names if name in public]
    if group_name == '💳 Кредиты':
        if not is_trader:
            public = {'credit_apply', 'credit_status', 'credit_help'}
            return [name for name in names if name in public]
        if not credit_staff:
            public = {'credit_apply', 'credit_status', 'credit_help'}
            return [name for name in names if name in public]
        names = [name for name in names if name != 'credit_limits']
    if group_name == '🏛️ Гильдия' and not get_leader_guild_from_member(member):
        leader_only = {'add', 'add_batch', 'remove', 'generate', 'codes', 'revoke', 'analytics'}
        return [name for name in names if name not in leader_only]
    if group_name == '🛡️ СОБР':
        rank = _sobr_member_rank(member)
        if not rank or RANK_ORDER.index(rank) < RANK_ORDER.index('D'):
            names = [name for name in names if name not in {'sobr_report', 'sobr_reports', 'sobr_report_correct'}]
        if not rank or RANK_ORDER.index(rank) < RANK_ORDER.index('B'):
            names = [name for name in names if name not in {'sobr_violation_confirm', 'sobr_fine_paid', 'sobr_passport_report'}]
    return names


class CommandDirectoryView(discord.ui.View):
    """Каталог действий раздела; каждый пункт запускает штатный callback после проверки прав."""
    def __init__(self, member, group_name: str):
        super().__init__(timeout=300)
        self.creator_id = member.id
        self.group_name = group_name
        names = _menu_visible_commands(member, group_name)
        options = []
        for name in names:
            command = bot.get_command(name)
            if command is None:
                # Модули банка/кредитов регистрируют команды при запуске; каталог
                # всё равно сохраняет пункт, даже если меню открыли до регистрации.
                label = name
                description = 'Команда будет доступна после запуска соответствующего модуля.'
            else:
                label = command.name
                description = (command.short_doc or command.help or 'Открыть инструкцию по использованию.')
            options.append(discord.SelectOption(label=label[:100], description=description[:100], value=name))
        if not options:
            options = [discord.SelectOption(label='Нет доступных действий', value='__empty__', description='Вашей роли пока нечего выполнять в этом разделе.')]
        select = discord.ui.Select(placeholder='Выберите действие раздела…', min_values=1, max_values=1, options=options)

        async def select_callback(interaction: discord.Interaction):
            command_name = select.values[0]
            if command_name == '__empty__':
                return await interaction.response.send_message('Для вашей роли в этом разделе нет доступных действий.', ephemeral=True)
            command = bot.get_command(command_name)
            if command is None:
                return await interaction.response.send_message(
                    f'Команда `.{command_name}` ещё не зарегистрирована. Перезапустите бота и откройте меню снова.',
                    ephemeral=True)
            signature = f' {command.signature}' if command.signature else ''
            aliases = ', '.join(f'`.{alias}`' for alias in command.aliases) or 'нет'
            description = MENU_ACTION_HELP.get(command.name) or command.help or command.short_doc or 'Подробное описание доступно в гайде соответствующего раздела.'
            embed = discord.Embed(title=f'{self.group_name} · {command.name}',
                description=f'{description}\n\n**Формат:** `.{command.name}{signature}`\n**Алиасы:** {aliases}',
                color=discord.Color.blurple())
            action_view = discord.ui.View(timeout=180)
            action_btn = discord.ui.Button(label='▶️ Выполнить через меню', style=discord.ButtonStyle.success)
            async def action_callback(i: discord.Interaction):
                if i.user.id != self.creator_id:
                    return await i.response.send_message('❌ Это меню создано другим пользователем.', ephemeral=True)
                # Повторная проверка прав выполняется самим штатным обработчиком.
                if command.clean_params:
                    try:
                        await i.response.send_modal(CommandActionModal(i, command))
                    except ValueError as exc:
                        await i.response.send_message(f'❌ {exc}', ephemeral=True)
                else:
                    proxy = _MenuContextProxy(i, command)
                    try:
                        if not await command.can_run(proxy):
                            return await i.response.send_message('❌ Команда недоступна вашей роли или правам.', ephemeral=True)
                        await command.callback(proxy)
                    except commands.CommandError as exc:
                        await proxy.send(f'❌ Команда недоступна: {exc}')
                    except Exception as exc:
                        print(f'[MENU] Ошибка запуска .{command.name}: {exc!r}')
                        await proxy.send('❌ Не удалось выполнить действие через меню. Обратитесь к администратору.')
            action_btn.callback = action_callback
            action_view.add_item(action_btn)
            await interaction.response.send_message(embed=embed, view=action_view, ephemeral=True)

        select.callback = select_callback
        self.add_item(select)
        back = discord.ui.Button(label='↩️ Главное меню', style=discord.ButtonStyle.secondary, row=1)

        async def back_callback(interaction: discord.Interaction):
            await interaction.response.edit_message(
                embed=build_main_menu_embed(interaction.user),
                view=build_main_menu_view(interaction.user))

        back.callback = back_callback
        self.add_item(back)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.creator_id:
            await interaction.response.send_message(
                '❌ Это меню создано другим пользователем. Вызовите `.menu` для своего меню.', ephemeral=True)
            return False
        return True


def add_directory_button(view: discord.ui.View, member, group_name: str, row: int):
    button = discord.ui.Button(label=group_name, style=discord.ButtonStyle.primary, row=row)

    async def callback(interaction: discord.Interaction):
        # Проверяем актуальные права повторно, а не полагаемся на скрытие кнопки.
        if interaction.user.id != member.id:
            return await interaction.response.send_message(
                '❌ Это меню создано другим пользователем. Вызовите `.menu` для себя.', ephemeral=True)
        if group_name == '⚙️ Администрирование' and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message('❌ Раздел доступен только администраторам.', ephemeral=True)
        if group_name == '🏛️ Гильдия' and not (
            interaction.user.guild_permissions.administrator or any(_member_in_guild(interaction.user, g) for g in GUILD_NAMES)):
            return await interaction.response.send_message('❌ Раздел доступен участникам гильдий и администраторам.', ephemeral=True)
        if group_name == '🎯 Квесты' and not (
            interaction.user.guild_permissions.administrator or get_leader_guild_from_member(interaction.user)):
            return await interaction.response.send_message('❌ Управление квестами доступно главам гильдий и администраторам.', ephemeral=True)
        if group_name == '🛡️ СОБР' and not _member_in_guild(interaction.user, 'СОБР'):
            return await interaction.response.send_message('❌ Раздел доступен участникам СОБР.', ephemeral=True)
        if group_name in ('🏦 Банк', '💳 Кредиты') and not (
            interaction.user.guild_permissions.administrator or _member_in_guild(interaction.user, 'торговцы') or
            str(interaction.user.id) in data.get('players', {})):
            return await interaction.response.send_message('❌ Раздел доступен участникам сервера.', ephemeral=True)
        await interaction.response.edit_message(
            embed=discord.Embed(title=group_name, description='Выберите нужную функцию в списке ниже.',
                                color=discord.Color.blurple()),
            view=CommandDirectoryView(interaction.user, group_name))

    button.callback = callback
    view.add_item(button)


@bot.command(name='quest_create')
async def quest_create(ctx):
    lg = get_leader_guild(ctx)
    if not lg: return await ctx.send('❌ Только для глав!')
    if gfc := get_guild_from_category(ctx):
        if lg != gfc: return await ctx.send(f'❌ Вы в категории **{gfc.capitalize()}**, но вы глава **{lg.capitalize()}**!')
    if not GUILD_QUEST_BOARDS.get(lg): return await ctx.send(f'❌ Доска квестов не настроена для **{lg.capitalize()}**!')
    await ctx.send(embed=discord.Embed(title='🎯 Создание квеста', description='Выберите способ создания.', color=discord.Color.blue()),
                   view=QuestCreateMenuView(lg, ctx.author.id))


@bot.command(name='quest_confirm')
async def quest_confirm(ctx, quest_id: str, nick: str):
    quest_id = quest_id.strip().upper()
    quest = data.get('quests', {}).get(quest_id)
    if not quest:
        return await ctx.send('❌ Квест не найден.')
    leader_guild = get_leader_guild(ctx)
    if not leader_guild or leader_guild != quest.get('guild'):
        return await ctx.send('❌ Подтверждать квест может только глава соответствующей гильдии.')
    if quest.get('status') != 'active':
        return await ctx.send('❌ Этот квест уже закрыт. Подтверждение выполнения больше недоступно.')
    if quest.get('mode', 'group') != 'individual':
        return await ctx.send('❌ Эта команда предназначена для индивидуальных квестов.')
    uid, player = find_player_by_nick(nick, quest['guild'])
    if not player:
        return await ctx.send('❌ Игрок не найден в этой гильдии.')
    participant = data.get('player_quests', {}).get(quest_id, {}).get(uid)
    if not participant or participant.get('status') != 'taken':
        return await ctx.send('❌ Игрок не взял этот квест или он уже обработан.')
    if quest.get('time_limit_minutes'):
        try:
            deadline = datetime.fromisoformat(participant['taken_at']) + timedelta(minutes=int(quest['time_limit_minutes']))
        except (KeyError, ValueError, TypeError):
            return await ctx.send('❌ Не удалось проверить срок квеста. Проверьте данные.')
        if now_msk() > deadline:
            penalty = max(0.0, float(quest.get('bonus', 0) or 0)) / 2
            player['quest_bonus'] = max(0.0, float(player.get('quest_bonus', 0.0)) - penalty)
            participant.update({'status': 'overdue', 'penalty_applied': penalty, 'overdue_at': now_msk().isoformat()})
            save_data()
            return await ctx.send(f'⏰ Срок квеста истёк. Игрок **{player["minecraft_nick"]}** отмечен как просрочивший; штраф: −{penalty:g}% к бонусу.')
    # Статус меняется до сохранения бонуса, повторная команда не сможет начислить награду.
    now_iso = now_msk().isoformat()
    reward = apply_quest_completion(player, quest, participant, ctx.author.id, now_iso)
    new_achievements = refresh_player_progress(player)
    save_data()
    unlocked_note = ''
    if new_achievements:
        unlocked_note = '\n🏆 Новые достижения: ' + ', '.join(ACHIEVEMENT_CATALOG[a]['name'] for a in new_achievements)
    reward_note = f'\n{quest_reward_label(reward)}'
    if reward['reward_type'] == 'diamonds_xp':
        reward_note += '\n⏳ После физической выдачи награды откройте `.menu` → «Управление квестами» → «Выдать награду».'
    await ctx.send(f'✅ Квест **{quest["name"]}** (`{quest_id}`) подтверждён для **{player["minecraft_nick"]}**: +{quest["bonus"]}% к зарплате.{reward_note}{unlocked_note}')
    try:
        user = await bot.fetch_user(int(uid))
        await user.send(f'✅ Квест **{quest["name"]}** подтверждён! +{quest["bonus"]}% к зарплате.\n{quest_reward_label(reward)}' + ('\nНаграда ожидает выдачи в Minecraft.' if reward['reward_type'] == 'diamonds_xp' else ''))
    except (discord.HTTPException, ValueError):
        pass


@bot.command(name='quest_reward_paid')
async def quest_reward_paid(ctx, quest_id: str, nick: str):
    """Отмечает физическую выдачу игровой награды после подтверждения в Minecraft."""
    quest_id = quest_id.strip().upper()
    quest = data.get('quests', {}).get(quest_id)
    if not quest:
        return await ctx.send('❌ Квест не найден.')
    if get_leader_guild(ctx) != quest.get('guild'):
        return await ctx.send('❌ Отмечать выдачу награды может только глава соответствующей гильдии.')
    uid, player = find_player_by_nick(nick, quest['guild'])
    participant = data.get('player_quests', {}).get(quest_id, {}).get(uid) if uid else None
    if not player or not participant or participant.get('status') != 'confirmed':
        return await ctx.send('❌ Участник не найден или квест ещё не подтверждён.')
    if participant.get('reward_status') != 'pending':
        return await ctx.send('ℹ️ Для этого участника нет ожидающей выдачи награды или она уже отмечена.')
    participant.update({'reward_status': 'paid', 'reward_paid_at': now_msk().isoformat(),
                        'reward_paid_by': ctx.author.id})
    save_data()
    await ctx.send(f'✅ Награда за **{quest["name"]}** для **{player["minecraft_nick"]}** отмечена как выданная: '
                   f'{participant.get("reward_diamonds", 0)} алмазов, {participant.get("reward_xp", 0)} XP.')


@bot.command(name='quest_delete')
async def quest_delete(ctx, quest_id: str = None):
    lg = get_leader_guild(ctx)
    if not lg: return await ctx.send('❌ Только для глав!')
    if quest_id:
        quest_id = quest_id.strip().upper()
        if (q := data['quests'].get(quest_id)) and q.get('guild') == lg:
            q['status'] = 'closed'
            q['closed_at'] = now_msk().isoformat()
            for participant in data.get('player_quests', {}).get(quest_id, {}).values():
                if participant.get('status') == 'taken':
                    participant.update({'status': 'cancelled', 'cancelled_at': q['closed_at'], 'closed_by_leader': True})
            save_data()
            thread = await _resolve_channel(q.get('thread_id')) if q.get('thread_id') else None
            if isinstance(thread, discord.Thread):
                try:
                    await thread.edit(locked=True, archived=True, reason='Квест закрыт главой')
                except discord.HTTPException as exc:
                    print(f'⚠️ Не удалось архивировать квест {quest_id}: {exc}')
            return await ctx.send('✅ Квест закрыт.')
        return await ctx.send('❌ Не найден.')
    active = [(qid, q) for qid, q in data['quests'].items() if q.get('guild') == lg and q.get('status') == 'active']
    if not active: return await ctx.send('📭 Нет активных квестов.')
    await ctx.send(embed=discord.Embed(title='🗑️ Удаление', description='.quest_delete ID\n\n' + '\n'.join(
        [f"`{qid}` — {q['name']}" for qid, q in active[:20]]), color=discord.Color.red()))


# === РЕАКЦИИ И РЕГИСТРАЦИЯ ===

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if bot.user and payload.user_id == bot.user.id: return
    if not (quest := get_quest_by_thread_or_message(payload.message_id)): return

    if str(payload.emoji) == QUEST_TAKE_REACTION:
        expected_board = GUILD_QUEST_BOARDS.get(quest.get('guild'))
        if expected_board and payload.channel_id != expected_board:
            channel = bot.get_channel(payload.channel_id)
            if not isinstance(channel, discord.Thread) or channel.parent_id != expected_board:
                return
        if quest.get('status') != 'active' or not (
        player := data.get('players', {}).get(str(payload.user_id))) or player.get('guild') != quest[
            'guild'] or get_player_quest(quest['id'], str(payload.user_id)): return
        if is_on_vacation(str(payload.user_id)):
            try:
                channel = bot.get_channel(payload.channel_id)
                if channel:
                    await channel.send(f'🌴 <@{payload.user_id}>, во время отпуска нельзя брать новые квесты.')
            except discord.HTTPException:
                pass
            return
        data['player_quests'].setdefault(quest['id'], {})[str(payload.user_id)] = {
            'taken_at': now_msk().isoformat(), 'status': 'taken'}
        save_data()
        try:
            if channel := bot.get_channel(payload.channel_id):
                deadline = f' ⏰ до **{(now_msk() + timedelta(minutes=quest["time_limit_minutes"])).strftime("%d.%m %H:%M")}**' if quest.get(
                    'time_limit_minutes') else ''
                await channel.send(f'✅ <@{payload.user_id}> взял **{quest["name"]}**!{deadline}')
        except:
            pass
        return

    if str(payload.emoji) == QUEST_CONFIRM_REACTION:
        guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
        if not guild or not (member := guild.get_member(payload.user_id)): return
        expected_board = GUILD_QUEST_BOARDS.get(quest.get('guild'))
        if expected_board and payload.channel_id != expected_board:
            # Форумные реакции приходят с ID дочерней темы, поэтому допускаем тему из ожидаемой доски ниже.
            channel = bot.get_channel(payload.channel_id)
            if not isinstance(channel, discord.Thread) or channel.parent_id != expected_board:
                return
        if not (lg := next((g for g, rid in GUILD_LEADER_ROLES.items() if discord.utils.get(member.roles, id=rid)),
                           None)) or lg != quest['guild']: return
        if quest.get('mode', 'group') != 'group':
            try:
                channel = bot.get_channel(payload.channel_id)
                if channel:
                    await channel.send('ℹ️ Это индивидуальный квест. Глава должен подтвердить конкретного игрока командой `.quest_confirm ID_КВЕСТА Ник`.')
            except discord.HTTPException:
                pass
            return
        if quest.get('status') != 'active':
            return
        # Закрываем квест до начисления: повторное событие не выдаст бонус второй раз.
        data['quests'][quest['id']]['status'] = 'closed'
        confirmed = []
        now = now_msk()
        for uid, pq in list(data.get('player_quests', {}).get(quest['id'], {}).items()):
            if pq.get('status') != 'taken' or not (p := data.get('players', {}).get(uid)): continue
            try:
                taken_at = datetime.fromisoformat(pq['taken_at'])
            except (KeyError, ValueError, TypeError):
                continue
            limit = quest.get('time_limit_minutes')
            if limit and now > taken_at + timedelta(minutes=int(limit)):
                penalty = float(quest.get('bonus', 0)) / 2
                p['quest_bonus'] = max(0.0, float(p.get('quest_bonus', 0.0)) - penalty)
                pq.update({'status': 'overdue', 'penalty_applied': penalty, 'overdue_at': now.isoformat()})
                continue
            reward = apply_quest_completion(p, quest, pq, payload.user_id, now.isoformat())
            newly = refresh_player_progress(p)
            confirmed.append(p.get('minecraft_nick', uid))
            if newly:
                pq['new_achievements'] = newly
            try:
                if u := await bot.fetch_user(int(uid)):
                    pending_note = '\nНаграда ожидает выдачи в Minecraft.' if reward['reward_type'] == 'diamonds_xp' else ''
                    await u.send(f'✅ Квест **{quest["name"]}** подтверждён! +{quest["bonus"]}% к зарплате.\n{quest_reward_label(reward)}{pending_note}')
            except:
                pass
        if not confirmed:
            data['quests'][quest['id']]['status'] = 'active'
            save_data()  # сохраняем статусы просрочки, даже если никто не получил бонус
            return
        save_data()
        try:
            if channel := bot.get_channel(payload.channel_id):
                await channel.send(f'✅ **Квест подтверждён!** +{quest["bonus"]}% к зарплате для: {", ".join(confirmed)}\n{quest_reward_label(quest)}' + ('\n⏳ Физическую выдачу отметьте через `.menu` → «Управление квестами» → «Выдать награду».' if quest_reward_config(quest)['reward_type'] == 'diamonds_xp' else ''))
                if isinstance(channel, discord.Thread): await channel.edit(locked=True, archived=True)
        except:
            pass


class AddTaskModal(discord.ui.Modal, title='Добавление задания'):
    tasks_input = discord.ui.TextInput(label='Количество заданий', default='1', required=True, max_length=3)
    points_input = discord.ui.TextInput(label='Очки для ранга', default='0', required=True, max_length=6)

    def __init__(self, nick: str, leader_guild: str, player_rank: str, creator_id: int):
        super().__init__()
        self.nick, self.leader_guild, self.player_rank, self.creator_id = nick, leader_guild, player_rank, creator_id

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction_can_manage_guild(interaction, self.leader_guild, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
        try:
            tasks, points = int(self.tasks_input.value), int(self.points_input.value)
        except ValueError:
            return await interaction.response.send_message('❌ Неверный формат!', ephemeral=True)
        if not (1 <= tasks <= 100 and 0 <= points <= 100000):
            return await interaction.response.send_message('❌ Заданий: 1–100, очки: 0–100000.', ephemeral=True)
        await interaction.response.send_message(embed=discord.Embed(title='📋 Шаг 2: Ранг',
                                                                    description=f'Игрок: **{self.nick}** ({self.player_rank})\nЗаданий: **{tasks}** | Очки: **{points}**',
                                                                    color=discord.Color.blue()),
                                                view=RankSelectView(self.nick, self.leader_guild, self.player_rank,
                                                                    tasks, points, self.creator_id), ephemeral=True)


class RankSelectView(AuthorizedView):
    def __init__(self, nick, leader_guild, rank, tasks, points, creator_id):
        super().__init__(creator_id=creator_id, guild_name=leader_guild, timeout=120)
        self.nick, self.leader_guild, self.player_rank, self.tasks, self.points = nick, leader_guild, rank, tasks, points
        self.creator_id = creator_id
        for i in range(RANK_ORDER.index(rank), min(RANK_ORDER.index(rank) + 3, len(RANK_ORDER))):
            diff = i - RANK_ORDER.index(rank)
            btn = discord.ui.Button(label=f'{RANK_ORDER[i]} ({"свой" if diff == 0 else f"+{RANK_DIFF_BONUS[diff]}%"})',
                                    style=[discord.ButtonStyle.secondary, discord.ButtonStyle.primary,
                                           discord.ButtonStyle.success][diff])
            btn.callback = self._cb(RANK_ORDER[i])
            self.add_item(btn)

    def _cb(self, task_rank):
        async def cb(interaction: discord.Interaction, *args):
            await interaction.response.edit_message(
                embed=discord.Embed(title='📋 Статус', description=f'Ранг: **{task_rank}**\nВыполнено?',
                                    color=discord.Color.gold()),
                view=StatusView(self.nick, self.leader_guild, self.player_rank, self.tasks, self.points, task_rank, self.creator_id))

        return cb


class StatusView(AuthorizedView):
    def __init__(self, nick, leader_guild, rank, tasks, points, task_rank, creator_id):
        super().__init__(creator_id=creator_id, guild_name=leader_guild, timeout=120)
        self.nick, self.leader_guild, self.player_rank, self.tasks, self.points, self.task_rank = nick, leader_guild, rank, tasks, points, task_rank
        self.creator_id = creator_id

    @discord.ui.button(label='✅ Выполнено', style=discord.ButtonStyle.success)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process(interaction, True)

    @discord.ui.button(label='❌ Не выполнено', style=discord.ButtonStyle.danger)
    async def fail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process(interaction, False)

    async def _process(self, interaction, success):
        uid, target = find_player_by_nick(self.nick, self.leader_guild)
        if not target: return await interaction.response.send_message('❌ Не найден!', ephemeral=True)
        current_rank = target.get('rank', 'F')
        if is_on_vacation(uid):
            return await interaction.response.send_message('🌴 Игрок в отпуске: начислять новые задания нельзя.', ephemeral=True)
        if not can_take_task(current_rank, self.task_rank):
            return await interaction.response.send_message('❌ Текущий ранг игрока больше не позволяет это задание.', ephemeral=True)
        rd = get_rank_diff(current_rank, self.task_rank)
        if success:
            max_tasks = MAX_TASKS_PER_RANK.get(current_rank, 100)
            if not can_add_tasks(current_rank, target.get('completed_tasks', 0), self.tasks):
                return await interaction.response.send_message(
                    f'❌ Лимит ранга {current_rank}: {max_tasks} заданий за неделю.', ephemeral=True)
            target['completed_tasks'] += self.tasks
            target['lifetime_tasks_total'] = int(target.get('lifetime_tasks_total', 0) or 0) + self.tasks
            target['rank_points'] += self.points
            add_task_salary_base(target, self.tasks, rd)
            new_achievements = refresh_player_progress(target)
            save_data()
            nr, rem, prom = calculate_rank_up(target['rank_points'], current_rank)
            sal = player_weekly_salary(target)
            embed = discord.Embed(title='✅ Выполнено!', color=discord.Color.green()).add_field(name='👤',
                                                                                               value=self.nick,
                                                                                               inline=True).add_field(
                name='📊', value=f'+{self.tasks} (всего {target["completed_tasks"]})', inline=True).add_field(name='⭐',
                                                                                                             value=f'+{self.points} (всего {target["rank_points"]})',
                                                                                                             inline=True)
            if prom: embed.add_field(name='📈', value=f'Кандидат на повышение в понедельник: **{nr}**', inline=False)
            embed.add_field(name='💰', value=f'{sal}', inline=False)
            embed.add_field(name='🏷️ Титул', value=get_active_title_name(target), inline=True)
            if new_achievements:
                unlocked_names = [ACHIEVEMENT_CATALOG[a]['name'] for a in new_achievements]
                embed.add_field(name='🏆 Новые достижения', value='\n'.join(unlocked_names), inline=False)
            await interaction.response.edit_message(embed=embed, view=None)
            try:
                if u := await bot.fetch_user(int(uid)): await u.send(
                    f'📢 **{self.tasks}** заданий **{self.task_rank}**! 💰 {sal}')
            except:
                pass
        else:
            penalty = calculate_penalty(self.task_rank, rd)
            target['rank_points'] = max(0, target['rank_points'] - penalty)
            save_data()
            await interaction.response.edit_message(
                embed=discord.Embed(title='❌ Штраф', description=f'-{penalty} (теперь {target["rank_points"]})',
                                    color=discord.Color.red()), view=None)


@bot.command(name='add')
async def add_tasks(ctx, nick: str):
    gfc, lg = get_guild_from_category(ctx), get_leader_guild(ctx)
    if not gfc: return await ctx.send('❌ Только в категориях!')
    if not lg or lg != gfc: return await ctx.send('❌ Только для глав!')
    uid, target = find_player_by_nick(nick, lg)
    if not target: return await ctx.send(f'❌ **{nick}** не найден.')
    rank = target.get('rank', 'F')
    embed = discord.Embed(title='📝 Добавление',
                          description=f'{nick} | {rank} | {target.get("completed_tasks", 0)}/{MAX_TASKS_PER_RANK.get(rank, 5)} | ⭐ {target.get("rank_points", 0)}',
                          color=discord.Color.blue())
    view = AuthorizedView(creator_id=ctx.author.id, guild_name=lg, timeout=120)
    btn = discord.ui.Button(label='📝 Заполнить', style=discord.ButtonStyle.primary)

    async def on_click(interaction: discord.Interaction, *args):
        await interaction.response.send_modal(AddTaskModal(nick, lg, rank, ctx.author.id))

    btn.callback = on_click
    view.add_item(btn)
    await ctx.send(embed=embed, view=view)


# === МАССОВОЕ ДОБАВЛЕНИЕ ===

class BatchAddModal(discord.ui.Modal, title='Массовое добавление'):
    tasks_input = discord.ui.TextInput(label='Количество заданий', default='1', required=True, max_length=3)
    points_input = discord.ui.TextInput(label='Очки для ранга', default='0', required=True, max_length=6)

    def __init__(self, nicks: List[str], leader_guild: str, creator_id: int):
        super().__init__()
        self.nicks, self.leader_guild, self.creator_id = nicks, leader_guild, creator_id

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction_can_manage_guild(interaction, self.leader_guild, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
        try:
            tasks, points = int(self.tasks_input.value), int(self.points_input.value)
        except ValueError:
            return await interaction.response.send_message('❌ Неверный формат!', ephemeral=True)
        if not (1 <= tasks <= 100 and 0 <= points <= 100000):
            return await interaction.response.send_message('❌ Заданий: 1–100, очки: 0–100000.', ephemeral=True)
        await interaction.response.send_message(embed=discord.Embed(title='📋 Ранг',
                                                                    description=f'Игроки: **{", ".join(self.nicks)}**\nЗаданий: **{tasks}** | Очки: **{points}**',
                                                                    color=discord.Color.blue()),
                                                view=BatchRankView(self.nicks, self.leader_guild, tasks, points, self.creator_id), ephemeral=True)


class BatchRankView(AuthorizedView):
    def __init__(self, nicks, leader_guild, tasks, points, creator_id):
        super().__init__(creator_id=creator_id, guild_name=leader_guild, timeout=120)
        self.nicks, self.leader_guild, self.tasks, self.points, self.creator_id = nicks, leader_guild, tasks, points, creator_id
        for rank in RANK_ORDER:
            btn = discord.ui.Button(label=rank, style=discord.ButtonStyle.secondary)
            btn.callback = self._cb(rank)
            self.add_item(btn)

    def _cb(self, task_rank):
        async def cb(interaction: discord.Interaction, *args):
            await interaction.response.edit_message(embed=discord.Embed(title='📋 Статус',
                                                                        description=f'Игроки: **{", ".join(self.nicks)}**\nРанг: **{task_rank}**',
                                                                        color=discord.Color.gold()),
                                                    view=BatchStatusView(self.nicks, self.leader_guild, self.tasks,
                                                                         self.points, task_rank, self.creator_id))

        return cb


class BatchStatusView(AuthorizedView):
    def __init__(self, nicks, leader_guild, tasks, points, task_rank, creator_id):
        super().__init__(creator_id=creator_id, guild_name=leader_guild, timeout=120)
        self.nicks, self.leader_guild, self.tasks, self.points, self.task_rank, self.creator_id = nicks, leader_guild, tasks, points, task_rank, creator_id

    @discord.ui.button(label='✅ Всем выполнено', style=discord.ButtonStyle.success)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process(interaction, True)

    @discord.ui.button(label='❌ Всем не выполнено', style=discord.ButtonStyle.danger)
    async def fail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process(interaction, False)

    async def _process(self, interaction, success):
        results, skipped = [], []
        for nick in self.nicks:
            uid, target = find_player_by_nick(nick, self.leader_guild)
            if not target: skipped.append(f'{nick} — не найден'); continue
            pr = target.get('rank', 'F')
            if is_on_vacation(uid): skipped.append(f'{nick} — в отпуске'); continue
            if not can_take_task(pr, self.task_rank): skipped.append(f'{nick} — ранг {pr}'); continue
            rd = get_rank_diff(pr, self.task_rank)
            if success:
                max_tasks = MAX_TASKS_PER_RANK.get(pr, 100)
                if not can_add_tasks(pr, target.get('completed_tasks', 0), self.tasks):
                    skipped.append(f'{nick} — превышен лимит {max_tasks} заданий')
                    continue
                target['completed_tasks'] += self.tasks
                target['rank_points'] += self.points
                add_task_salary_base(target, self.tasks, rd)
                nr, rem, prom = calculate_rank_up(target['rank_points'], pr)
                sal = player_weekly_salary(target)
                results.append(
                    {'nick': nick, 'rank': pr, 'tasks': target['completed_tasks'], 'points': target['rank_points'],
                     'salary': sal, 'promotions': prom, 'new_rank': nr})
                try:
                    if u := await bot.fetch_user(int(uid)): await u.send(
                        f'📢 **{self.tasks}** заданий **{self.task_rank}**! 💰 {sal}')
                except:
                    pass
            else:
                penalty = calculate_penalty(self.task_rank, rd)
                target['rank_points'] = max(0, target['rank_points'] - penalty)
                results.append({'nick': nick, 'rank': pr, 'penalty': penalty, 'points': target['rank_points']})
        save_data()
        if success:
            embed = discord.Embed(title='✅ Массовое!', color=discord.Color.green())
            for r in results: embed.add_field(name=f'🎮 {r["nick"]} ({r["rank"]})',
                                              value=f'📊 {r["tasks"]} | ⭐ {r["points"]} | 💰 {r["salary"]}', inline=False)
        else:
            embed = discord.Embed(title='❌ Штрафы!', color=discord.Color.red())
            for r in results: embed.add_field(name=f'🎮 {r["nick"]} ({r["rank"]})',
                                              value=f'⭐ -{r["penalty"]} → {r["points"]}', inline=False)
        if skipped: embed.add_field(name='⚠️ Пропущены', value='\n'.join(skipped[:5]), inline=False)
        await interaction.response.edit_message(embed=embed, view=None)


@bot.command(name='add_batch')
async def add_batch(ctx, *, nicks: str):
    gfc, lg = get_guild_from_category(ctx), get_leader_guild(ctx)
    if not gfc: return await ctx.send('❌ Только в категориях!')
    if not lg or lg != gfc: return await ctx.send('❌ Только для глав!')
    valid = list(dict.fromkeys(n.strip() for n in nicks.split(',') if n.strip() and find_player_by_nick(n.strip(), lg)[1]))
    if not valid: return await ctx.send('❌ Никто не найден!')
    view = AuthorizedView(creator_id=ctx.author.id, guild_name=lg, timeout=120)
    btn = discord.ui.Button(label='📝 Заполнить', style=discord.ButtonStyle.primary)

    async def on_click(interaction: discord.Interaction, *args):
        await interaction.response.send_modal(BatchAddModal(valid, lg, ctx.author.id))

    btn.callback = on_click
    view.add_item(btn)
    await ctx.send(
        embed=discord.Embed(title='📝 Массовое', description=f'Игроков: **{len(valid)}**\n' + ', '.join(valid),
                            color=discord.Color.blue()), view=view)


# === LIST / REMOVE / РЕГИСТРАЦИЯ ===

@bot.command(name='list')
async def show_list(ctx):
    gfc, lg = get_guild_from_category(ctx), get_leader_guild(ctx)
    if not gfc or not lg or lg != gfc: return await ctx.send('❌ Только для глав в своей категории!')
    players = [{'nick': p.get('minecraft_nick', '?'), 'rank': p.get('rank', 'F'), 'tasks': p.get('completed_tasks', 0),
                'points': p.get('rank_points', 0),
                'salary': player_weekly_salary(p),
                'vac': is_on_vacation(uid)} for uid, p in data['players'].items() if p.get('guild') == lg]
    if not players: return await ctx.send('📭 Нет игроков.')
    players.sort(key=lambda x: RANK_ORDER_REV.index(x['rank']))
    embed = discord.Embed(title=f'📋 {lg.capitalize()}', description=f'👥 {len(players)} | {get_current_week_key()}',
                          color=discord.Color.blue())
    for p in players[:20]: embed.add_field(name=f"{p['rank']} | {p['nick']}{' 🌴' if p['vac'] else ''}",
                                           value=f"📊 {p['tasks']} | ⭐ {p['points']} | 💰 {p['salary']}", inline=False)
    await ctx.send(embed=embed)


@bot.command(name='remove')
async def remove_player(ctx, nick: str):
    gfc, lg = get_guild_from_category(ctx), get_leader_guild(ctx)
    if not gfc or not lg or lg != gfc: return await ctx.send('❌ Только для глав!')
    uid, target = find_player_by_nick(nick, lg)
    if not target: return await ctx.send(f'❌ **{nick}** не найден.')
    if discord_id := target.get('discord_id'):
        for g in bot.guilds:
            if member := g.get_member(discord_id): await remove_all_rank_roles(member, lg); break
    data['players'].pop(uid, None)
    data.get('vacations', {}).pop(uid, None)
    data.get('vacation_cooldowns', {}).pop(uid, None)
    data.get('temp_nick', {}).pop(uid, None)
    data.get('temp_code', {}).pop(uid, None)
    if discord_id in data['registered_users']: data['registered_users'].remove(discord_id)
    for qid in list(data['player_quests'].keys()): data['player_quests'][qid].pop(uid, None)
    save_data()
    await ctx.send(f'❌ **{nick}** удалён из **{lg.capitalize()}**')


# === ЛС И РЕГИСТРАЦИЯ ===

@bot.command(name='generate')
async def generate_code(ctx):
    if not isinstance(ctx.channel, discord.DMChannel): return await ctx.send('❌ Только в ЛС!')
    member = next((g.get_member(ctx.author.id) for g in bot.guilds if g.get_member(ctx.author.id)), None)
    lg = next((g for g, rid in GUILD_LEADER_ROLES.items() if member and discord.utils.get(member.roles, id=rid)),
              None) if member else None
    if not lg: return await ctx.send('❌ Только для глав!')
    code = generate_random_code()
    while code in data['invite_codes']: code = generate_random_code()
    data['invite_codes'][code] = {'guild': lg, 'creator_id': ctx.author.id, 'created_at': now_msk().isoformat(),
                                 'expires_at': (now_msk() + timedelta(hours=INVITE_CODE_TTL_HOURS)).isoformat()}
    save_data()
    await ctx.send(
        embed=discord.Embed(title='🔑 Код создан!', description=f'**`{code}`**', color=discord.Color.green()).add_field(
            name='Гильдия', value=lg.capitalize()))


@bot.command(name='codes')
async def show_codes(ctx):
    if not isinstance(ctx.channel, discord.DMChannel): return await ctx.send('❌ Только в ЛС!')
    member = next((g.get_member(ctx.author.id) for g in bot.guilds if g.get_member(ctx.author.id)), None)
    lg = next((g for g, rid in GUILD_LEADER_ROLES.items() if member and discord.utils.get(member.roles, id=rid)),
              None) if member else None
    if not lg: return await ctx.send('❌ Только для глав!')
    codes = [c for c, d in data['invite_codes'].items() if d.get('guild') == lg]
    if not codes: return await ctx.send('📭 Нет кодов.')
    lines = [f"`{c}` — {datetime.fromisoformat(data['invite_codes'][c]['created_at']).strftime('%d.%m %H:%M')}" for c in
             codes]
    await ctx.send(embed=discord.Embed(title=f'🔑 Коды {lg.capitalize()}', description='\n'.join(lines),
                                       color=discord.Color.blue()))


@bot.command(name='revoke')
async def revoke_code(ctx, code: str):
    if not isinstance(ctx.channel, discord.DMChannel): return await ctx.send('❌ Только в ЛС!')
    code = code.upper()
    member = next((g.get_member(ctx.author.id) for g in bot.guilds if g.get_member(ctx.author.id)), None)
    lg = next((g for g, rid in GUILD_LEADER_ROLES.items() if member and discord.utils.get(member.roles, id=rid)),
              None) if member else None
    if not lg or code not in data['invite_codes'] or data['invite_codes'][code]['guild'] != lg: return await ctx.send(
        '❌ Не ваш код или не найден.')
    data['invite_codes'].pop(code, None)
    save_data()
    await ctx.send(f'✅ Код **{code}** отозван.')


@bot.command(name='register', aliases=['регистрация'])
async def register_individually(ctx):
    """Начинает регистрацию игрока без обязательного выбора гильдии."""
    if not isinstance(ctx.channel, discord.DMChannel):
        try:
            await ctx.author.send('📝 Чтобы зарегистрироваться без гильдии, напишите `.register` в личные сообщения боту.')
            return await ctx.send('📩 Я отправил инструкцию в личные сообщения.')
        except discord.Forbidden:
            return await ctx.send('❌ Не могу написать вам в ЛС. Разрешите личные сообщения от участников сервера и повторите команду.')
    uid = str(ctx.author.id)
    player = data.get('players', {}).get(uid)
    if player and player.get('guild'):
        return await ctx.send('❌ Вы уже зарегистрированы в гильдии.')
    if player:
        return await ctx.send('✅ Вы уже зарегистрированы без гильдии. Используйте `.cabinet`, чтобы открыть профиль. Если хотите вступить в гильдию, отправьте сюда действующий код приглашения.')
    data.setdefault('temp_individual_registration', {})[uid] = {'started_at': now_msk().isoformat()}
    data.get('temp_code', {}).pop(uid, None)
    data.get('temp_nick', {}).pop(uid, None)
    save_data()
    await ctx.send('📝 **Регистрация без гильдии**\nОтправьте следующим сообщением свой ник Minecraft (3–16 символов: латинские буквы, цифры и `_`). Затем подтвердите его реакцией ✅.')


@bot.command(name='cancel_registration', aliases=['отмена_регистрации'])
async def cancel_individual_registration(ctx):
    if not isinstance(ctx.channel, discord.DMChannel):
        return await ctx.send('❌ Используйте эту команду в личных сообщениях боту.')
    uid = str(ctx.author.id)
    pending = uid in data.get('temp_individual_registration', {}) or uid in data.get('temp_nick', {})
    data.get('temp_individual_registration', {}).pop(uid, None)
    data.get('temp_nick', {}).pop(uid, None)
    data.get('temp_code', {}).pop(uid, None)
    for mid, selection in list(data.get('selection_messages', {}).items()):
        if str(selection.get('user_id')) == uid and selection.get('type') == 'individual_confirm':
            data['selection_messages'].pop(mid, None)
    save_data()
    await ctx.send('✅ Регистрация отменена.' if pending else 'ℹ️ Нет активной регистрации для отмены.')


@bot.event
async def on_message(message):
    if message.author == bot.user: return
    if isinstance(message.channel, discord.DMChannel):
        uid = str(message.author.id)
        if message.content.startswith('.'): return await bot.process_commands(message)
        existing_player = data.get('players', {}).get(uid)
        if existing_player and existing_player.get('guild'):
            return await message.channel.send('❌ Вы уже зарегистрированы в гильдии!')
        if not message.content.strip(): return

        # Independent registration asks for a Minecraft nickname before invite-code processing.
        if uid in data.get('temp_individual_registration', {}):
            nick = message.content.strip()
            if not re.fullmatch(r'[A-Za-z0-9_]{3,16}', nick):
                return await message.channel.send('❌ Ник Minecraft должен содержать 3–16 символов: латинские буквы, цифры и _. Попробуйте ещё раз или используйте `.cancel_registration`.')
            existing_uid = next((pid for pid, player in data.get('players', {}).items()
                                 if player.get('minecraft_nick', '').casefold() == nick.casefold() and pid != uid), None)
            if existing_uid:
                return await message.channel.send('❌ Этот ник Minecraft уже зарегистрирован. Укажите другой ник.')
            data.setdefault('temp_nick', {})[uid] = nick
            confirm = await message.channel.send(embed=discord.Embed(
                title='📝 Регистрация без гильдии',
                description=f'Ник Minecraft: **{nick}**\nГильдия: **не выбрана**\n\nНажмите ✅ для подтверждения или ❌ для отмены.',
                color=discord.Color.gold()))
            await confirm.add_reaction('✅')
            await confirm.add_reaction('❌')
            data.setdefault('selection_messages', {})[str(confirm.id)] = {
                'user_id': user_id if False else message.author.id, 'guild': None, 'invite_code': None, 'type': 'individual_confirm'}
            data['temp_individual_registration'].pop(uid, None)
            save_data()
            return

        code = message.content.strip().upper()
        # Истёкшие коды удаляются; код резервируется за первым пользователем до подтверждения.
        for saved_code, details in list(data.get('invite_codes', {}).items()):
            try:
                created = datetime.fromisoformat(details.get('created_at', ''))
                if now_msk() - created > timedelta(hours=INVITE_CODE_TTL_HOURS):
                    data['invite_codes'].pop(saved_code, None)
            except (ValueError, TypeError):
                data['invite_codes'].pop(saved_code, None)
        if code in data['invite_codes']:
            reserved_by_other = any(owner != uid and reserved_code == code
                                    for owner, reserved_code in data.get('temp_code', {}).items())
            if reserved_by_other:
                return await message.channel.send('❌ Этот код уже используется другим игроком.')
            data.setdefault('temp_code', {})[uid] = code
            save_data()
            return await message.channel.send(
                f'✅ Гильдия: **{data["invite_codes"][code]["guild"].capitalize()}**. Напишите ник.')

        if uid in data.get('temp_code', {}):
            nick = message.content.strip()
            if not re.fullmatch(r'[A-Za-z0-9_]{3,16}', nick):
                return await message.channel.send('❌ Ник Minecraft должен содержать 3–16 символов: латинские буквы, цифры и _.')
            existing_uid = next((pid for pid, player in data.get('players', {}).items()
                                 if player.get('minecraft_nick', '').casefold() == nick.casefold()), None)
            if existing_uid and existing_uid != uid:
                return await message.channel.send('❌ Этот ник Minecraft уже зарегистрирован.')
            code = data['temp_code'][uid]
            if code not in data['invite_codes']:
                data['temp_code'].pop(uid, None)
                save_data()
                return await message.channel.send('❌ Код использован или истёк.')
            g = normalize_guild_name(data['invite_codes'][code].get('guild', ''))
            if not g:
                data['temp_code'].pop(uid, None)
                save_data()
                return await message.channel.send('❌ У кода указана неизвестная гильдия.')
            data['temp_nick'][uid] = nick
            save_data()
            return await send_guild_selection(message.author, g, code)
        await message.channel.send('❌ Сначала код!')
        return
    await bot.process_commands(message)


async def send_guild_selection(user, guild_name, invite_code):
    msg = await user.send(
        embed=discord.Embed(title='🏛️', description=f'**{guild_name.capitalize()}**\n✅:', color=discord.Color.gold()))
    await msg.add_reaction('✅');
    await msg.add_reaction('❌')
    data['selection_messages'][str(msg.id)] = {'user_id': user.id, 'guild': guild_name, 'invite_code': invite_code, 'type': 'confirm'}
    save_data()


@bot.listen('on_raw_reaction_add')
async def on_raw_reaction_add_registration(payload: discord.RawReactionActionEvent):
    if bot.user and payload.user_id == bot.user.id:
        return
    msg_id = str(payload.message_id)
    if msg_id not in data.get('selection_messages', {}):
        return
    selection = data['selection_messages'][msg_id]
    if payload.user_id != selection.get('user_id'):
        try:
            channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
            if channel:
                message = await channel.fetch_message(payload.message_id)
                member = payload.member
                if member:
                    await message.remove_reaction(payload.emoji, member)
        except (discord.HTTPException, discord.Forbidden):
            pass
        return
    try:
        channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
    except discord.HTTPException:
        return
    if not channel:
        return
    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.HTTPException:
        return
    emoji = str(payload.emoji)
    user = bot.get_user(payload.user_id) or await bot.fetch_user(payload.user_id)
    if emoji == '✅':
        if selection.get('type') == 'individual_confirm':
            await process_individual_registration(user, message)
        else:
            await process_registration(user, selection.get('guild'), message)
    elif emoji == '❌':
        data.get('temp_nick', {}).pop(str(user.id), None)
        data.get('temp_code', {}).pop(str(user.id), None)
        data.get('temp_individual_registration', {}).pop(str(user.id), None)
        data['selection_messages'].pop(msg_id, None)
        save_data()
        try:
            await message.delete()
        except discord.HTTPException:
            pass


async def process_individual_registration(user, message):
    """Завершает регистрацию профиля без привязки к гильдии."""
    uid = str(user.id)
    message_id = str(message.id)
    selection = data.get('selection_messages', {}).get(message_id, {})
    if selection.get('type') != 'individual_confirm' or str(selection.get('user_id')) != uid:
        return
    player = data.get('players', {}).get(uid)
    if player and player.get('guild'):
        data['selection_messages'].pop(message_id, None)
        save_data()
        return await user.send('ℹ️ Вы уже зарегистрированы в гильдии.')
    nick = data.get('temp_nick', {}).get(uid)
    if not nick:
        data['selection_messages'].pop(message_id, None)
        save_data()
        return await user.send('❌ Не удалось найти ник. Начните заново командой `.register`.')
    existing_uid = next((pid for pid, saved in data.get('players', {}).items()
                         if saved.get('minecraft_nick', '').casefold() == nick.casefold() and pid != uid), None)
    if existing_uid:
        data.get('selection_messages', {}).pop(message_id, None)
        data.get('temp_nick', {}).pop(uid, None)
        save_data()
        return await user.send('❌ Этот ник Minecraft уже зарегистрирован. Начните заново командой `.register` и укажите другой ник.')

    # If this is a re-confirmation of an existing guildless profile, preserve all progress.
    if player:
        player['minecraft_nick'] = nick
        player['discord_id'] = user.id
        player.setdefault('rank', 'F')
        player.setdefault('completed_tasks', 0)
        player.setdefault('rank_points', 0)
        player.setdefault('quest_bonus', 0.0)
        player.setdefault('joined_date', now_msk().isoformat())
        player['guild'] = None
    else:
        data['players'][uid] = {
            'minecraft_nick': nick, 'discord_id': user.id, 'guild': None, 'rank': 'F',
            'completed_tasks': 0, 'rank_points': 0, 'quest_bonus': 0.0,
            'weekly_salary_base': 0.0, 'joined_date': now_msk().isoformat()
        }
    if user.id not in data['registered_users']:
        data['registered_users'].append(user.id)
    data.get('temp_nick', {}).pop(uid, None)
    data.get('temp_code', {}).pop(uid, None)
    data.get('temp_individual_registration', {}).pop(uid, None)
    data.get('selection_messages', {}).pop(message_id, None)
    save_data()
    await user.send(f'✅ Регистрация завершена! Ник Minecraft: **{nick}**. Гильдия не выбрана. Профиль доступен через `.cabinet`.')


async def process_registration(user, guild, message):
    uid = str(user.id)
    guild = normalize_guild_name(guild)
    selection = data.get('selection_messages', {}).get(str(message.id), {})
    invite_code = selection.get('invite_code') or data.get('temp_code', {}).get(uid)
    existing_profile = data.get('players', {}).get(uid)
    if existing_profile and existing_profile.get('guild'):
        data.get('selection_messages', {}).pop(str(message.id), None)
        data.get('temp_nick', {}).pop(uid, None)
        data.get('temp_code', {}).pop(uid, None)
        save_data()
        try:
            await user.send('ℹ️ Вы уже зарегистрированы в гильдии.')
        except discord.HTTPException:
            pass
        return
    if not guild or not (nick := data.get('temp_nick', {}).get(uid)):
        return
    invite = data.get('invite_codes', {}).get(invite_code) if invite_code else None
    expired = False
    if invite:
        try:
            expires_at = datetime.fromisoformat(invite.get('expires_at') or
                (datetime.fromisoformat(invite['created_at']) + timedelta(hours=INVITE_CODE_TTL_HOURS)).isoformat())
            expired = now_msk() > expires_at
        except (KeyError, ValueError, TypeError):
            expired = True
    if not invite or expired:
        if invite_code:
            data.get('invite_codes', {}).pop(invite_code, None)
        data.get('selection_messages', {}).pop(str(message.id), None)
        data.get('temp_nick', {}).pop(uid, None)
        data.get('temp_code', {}).pop(uid, None)
        save_data()
        await user.send('❌ Код приглашения больше недействителен. Попросите новый код у главы.')
        return
    existing_uid = next((pid for pid, player in data.get('players', {}).items()
                         if player.get('minecraft_nick', '').casefold() == nick.casefold()), None)
    if existing_uid and existing_uid != uid:
        data.get('temp_nick', {}).pop(uid, None)
        data.get('temp_code', {}).pop(uid, None)
        data.get('selection_messages', {}).pop(str(message.id), None)
        save_data()
        await user.send('❌ Этот ник Minecraft уже зарегистрирован. Начните регистрацию заново с новым приглашением.')
        return
    if existing_profile:
        # Preserve personal achievements/history when a standalone player joins a guild later.
        existing_profile.update({'minecraft_nick': nick, 'discord_id': user.id, 'guild': guild})
        existing_profile.setdefault('rank', 'F')
        existing_profile.setdefault('completed_tasks', 0)
        existing_profile.setdefault('rank_points', 0)
        existing_profile.setdefault('quest_bonus', 0.0)
        existing_profile.setdefault('joined_date', now_msk().isoformat())
    else:
        data['players'][uid] = {'minecraft_nick': nick, 'discord_id': user.id, 'guild': guild, 'rank': 'F',
                                'completed_tasks': 0, 'rank_points': 0, 'quest_bonus': 0.0,
                                'weekly_salary_base': 0.0, 'joined_date': now_msk().isoformat()}
    data['invite_codes'].pop(invite_code, None)
    data.get('temp_code', {}).pop(uid, None)
    if user.id not in data['registered_users']: data['registered_users'].append(user.id)
    data['temp_nick'].pop(uid, None)
    data['selection_messages'].pop(str(message.id), None)
    save_data()
    first_rank_role_id = RANK_ROLES.get(guild, {}).get('F')
    member = next((g.get_member(user.id) for g in bot.guilds
                   if g.get_member(user.id) and first_rank_role_id and g.get_role(first_rank_role_id)), None)
    if member:
        await update_rank_roles(member, 'F', guild)
    await user.send(f'✅ Добро пожаловать в **{guild.capitalize()}**!')


# === АДМИН-КОМАНДЫ ===

class DailyScheduleModal(discord.ui.Modal, title='Автоквесты: ежедневно'):
    publish_time = discord.ui.TextInput(label='Время публикации (ЧЧ:ММ)', default='08:00', max_length=5)
    close_time = discord.ui.TextInput(label='Время закрытия (ЧЧ:ММ)', default='22:00', max_length=5)
    count = discord.ui.TextInput(label='Количество квестов (1–10)', default='3', max_length=2)

    def __init__(self, guild_name: str, creator_id: int):
        super().__init__()
        self.guild_name, self.creator_id = guild_name, creator_id
        cfg = quest_schedules.get(guild_name, {}).get('daily', {})
        self.publish_time.default = str(cfg.get('publish_time', '08:00'))
        self.close_time.default = str(cfg.get('close_time', '22:00'))
        self.count.default = str(cfg.get('count',  '3'))

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction_can_manage_guild(interaction, self.guild_name, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав или меню создано другим пользователем.', ephemeral=True)
        try:
            pub, close = self.publish_time.value.strip(), self.close_time.value.strip()
            ph, pm = parse_clock(pub); ch, cm = parse_clock(close)
            count = int(self.count.value)
            if ch * 60 + cm <= ph * 60 + pm:
                raise ValueError('Время закрытия должно быть позже времени публикации в тот же день.')
            if not 1 <= count <= 10:
                raise ValueError('Количество квестов должно быть от 1 до 10.')
        except ValueError as exc:
            return await interaction.response.send_message(f'❌ {exc}', ephemeral=True)
        old = quest_schedules.setdefault(self.guild_name, {}).get('daily', {})
        quest_schedules[self.guild_name]['daily'] = {
            'enabled': True, 'publish_day': 'daily', 'publish_time': pub,
            'close_day': 'daily', 'close_time': close, 'count': count,
            'last_publish_period': old.get('last_publish_period'),
            'last_close_period': old.get('last_close_period')}
        save_quest_schedules()
        await interaction.response.send_message(
            f'✅ Ежедневные автоквесты для **{self.guild_name}** включены: публикация **{pub}**, закрытие **{close}**, квестов **{count}** за день. Часовой пояс — Москва (МСК, UTC+3).', ephemeral=True)


class WeeklyScheduleModal(discord.ui.Modal, title='Автоквесты: еженедельно'):
    publish_day = discord.ui.TextInput(label='День публикации (пн/вт/ср/чт/пт/сб/вс)', default='пн', max_length=12)
    publish_time = discord.ui.TextInput(label='Время публикации (ЧЧ:ММ)', default='09:00', max_length=5)
    close_day = discord.ui.TextInput(label='День закрытия (пн/вт/ср/чт/пт/сб/вс)', default='вс', max_length=12)
    close_time = discord.ui.TextInput(label='Время закрытия (ЧЧ:ММ)', default='22:00', max_length=5)
    count = discord.ui.TextInput(label='Количество квестов (1–10)', default='3', max_length=2)

    def __init__(self, guild_name: str, creator_id: int):
        super().__init__()
        self.guild_name, self.creator_id = guild_name, creator_id
        cfg = quest_schedules.get(guild_name, {}).get('weekly', {})
        self.publish_day.default = str(cfg.get('publish_day', 'mon'))
        self.publish_time.default = str(cfg.get('publish_time', '09:00'))
        self.close_day.default = str(cfg.get('close_day', 'sun'))
        self.close_time.default = str(cfg.get('close_time', '22:00'))
        self.count.default = str(cfg.get('count', 3))

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction_can_manage_guild(interaction, self.guild_name, self.creator_id):
            return await interaction.response.send_message('❌ Недостаточно прав или меню создано другим пользователем.', ephemeral=True)
        pd, cd = self.publish_day.value.strip().lower(), self.close_day.value.strip().lower()
        pd = {'пн':'mon','вт':'tue','ср':'wed','чт':'thu','пт':'fri','сб':'sat','вс':'sun'}.get(pd, pd)
        cd = {'пн':'mon','вт':'tue','ср':'wed','чт':'thu','пт':'fri','сб':'sat','вс':'sun'}.get(cd, cd)
        try:
            if pd not in WEEKDAY_ALIASES or cd not in WEEKDAY_ALIASES:
                raise ValueError('Укажите день недели: пн, вт, ср, чт, пт, сб или вс.')
            pub, close = self.publish_time.value.strip(), self.close_time.value.strip()
            ph, pm = parse_clock(pub); ch, cm = parse_clock(close)
            count = int(self.count.value)
            if (WEEKDAY_ALIASES[cd], ch*60+cm) <= (WEEKDAY_ALIASES[pd], ph*60+pm):
                raise ValueError('Закрытие должно быть позже публикации в пределах недели.')
            if not 1 <= count <= 10:
                raise ValueError('Количество квестов должно быть от 1 до 10.')
            pd = datetime(2024, 1, 1 + WEEKDAY_ALIASES[pd]).strftime('%a').lower()
            cd = datetime(2024, 1, 1 + WEEKDAY_ALIASES[cd]).strftime('%a').lower()
        except ValueError as exc:
            return await interaction.response.send_message(f'❌ {exc}', ephemeral=True)
        old = quest_schedules.setdefault(self.guild_name, {}).get('weekly', {})
        quest_schedules[self.guild_name]['weekly'] = {
            'enabled': True, 'publish_day': pd, 'publish_time': pub,
            'close_day': cd, 'close_time': close, 'count': count,
            'last_publish_period': old.get('last_publish_period'),
            'last_close_period': old.get('last_close_period')}
        save_quest_schedules()
        await interaction.response.send_message(
            f'✅ Еженедельные автоквесты для **{self.guild_name}** включены: публикация **{WEEKDAY_NAMES[WEEKDAY_ALIASES[pd]]} {pub}**, закрытие **{WEEKDAY_NAMES[WEEKDAY_ALIASES[cd]]} {close}**, квестов **{count}** за цикл. Часовой пояс — Москва (МСК, UTC+3).', ephemeral=True)


class AutoQuestTemplateTypeView(AuthorizedView):
    """Позволяет создать шаблон прямо из меню автоквестов."""
    def __init__(self, creator_id: int, guild_name: str):
        super().__init__(creator_id=creator_id, guild_name=guild_name, timeout=180)
        self.creator_id, self.guild_name = creator_id, guild_name
        for template_type, label, style in (
            ('daily', '📆 Шаблон ежедневного', discord.ButtonStyle.primary),
            ('weekly', '🗓️ Шаблон еженедельного', discord.ButtonStyle.success),
        ):
            button = discord.ui.Button(label=label, style=style)
            async def callback(interaction: discord.Interaction, selected_type=template_type):
                if not interaction_can_manage_guild(interaction, self.guild_name, self.creator_id):
                    return await interaction.response.send_message('❌ Недостаточно прав для этой гильдии.', ephemeral=True)
                await interaction.response.send_modal(CreateTemplateModal(self.creator_id, selected_type))
            button.callback = callback
            self.add_item(button)
        back = discord.ui.Button(label='↩️ Назад к автоквестам', style=discord.ButtonStyle.secondary, row=1)
        async def back_callback(interaction: discord.Interaction):
            menu = QuestScheduleMenu(self.creator_id, self.guild_name)
            await interaction.response.edit_message(embed=menu.make_embed(), view=menu)
        back.callback = back_callback
        self.add_item(back)


class QuestScheduleMenu(AuthorizedView):
    def __init__(self, creator_id: int, initial_guild: str):
        super().__init__(creator_id=creator_id, guild_name=initial_guild, timeout=180)
        self.selected_guild = initial_guild
        guild_select = discord.ui.Select(placeholder='Выберите гильдию', min_values=1, max_values=1,
            options=[discord.SelectOption(label=name, value=name, emoji=GUILD_EMOJIS.get(name)) for name in GUILD_NAMES])
        async def select_guild(interaction: discord.Interaction):
            chosen = guild_select.values[0]
            if not interaction_can_manage_guild(interaction, chosen, creator_id):
                return await interaction.response.send_message('❌ Главы могут настраивать только свою гильдию.', ephemeral=True)
            self.selected_guild = chosen
            self.guild_name = chosen
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        guild_select.callback = select_guild
        self.add_item(guild_select)

        daily = discord.ui.Button(label='📆 Настроить ежедневные', style=discord.ButtonStyle.primary, row=1)
        async def daily_cb(interaction: discord.Interaction):
            if not interaction_can_manage_guild(interaction, self.selected_guild, creator_id):
                return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
            await interaction.response.send_modal(DailyScheduleModal(self.selected_guild, creator_id))
        daily.callback = daily_cb
        self.add_item(daily)

        weekly = discord.ui.Button(label='🗓️ Настроить еженедельные', style=discord.ButtonStyle.primary, row=1)
        async def weekly_cb(interaction: discord.Interaction):
            if not interaction_can_manage_guild(interaction, self.selected_guild, creator_id):
                return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
            await interaction.response.send_modal(WeeklyScheduleModal(self.selected_guild, creator_id))
        weekly.callback = weekly_cb
        self.add_item(weekly)

        off_daily = discord.ui.Button(label='⏸️ Выключить ежедневные', style=discord.ButtonStyle.secondary, row=2)
        async def off_daily_cb(interaction: discord.Interaction):
            if not interaction_can_manage_guild(interaction, self.selected_guild, creator_id):
                return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
            cfg = quest_schedules.get(self.selected_guild, {}).get('daily')
            if not cfg: return await interaction.response.send_message('ℹ️ Ежедневное расписание ещё не настроено.', ephemeral=True)
            cfg['enabled'] = False; save_quest_schedules()
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
            await interaction.followup.send(f'⏸️ Ежедневные автоквесты гильдии **{self.selected_guild}** выключены.', ephemeral=True)
        off_daily.callback = off_daily_cb
        self.add_item(off_daily)

        off_weekly = discord.ui.Button(label='⏸️ Выключить еженедельные', style=discord.ButtonStyle.secondary, row=2)
        async def off_weekly_cb(interaction: discord.Interaction):
            if not interaction_can_manage_guild(interaction, self.selected_guild, creator_id):
                return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
            cfg = quest_schedules.get(self.selected_guild, {}).get('weekly')
            if not cfg: return await interaction.response.send_message('ℹ️ Еженедельное расписание ещё не настроено.', ephemeral=True)
            cfg['enabled'] = False; save_quest_schedules()
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
            await interaction.followup.send(f'⏸️ Еженедельные автоквесты гильдии **{self.selected_guild}** выключены.', ephemeral=True)
        off_weekly.callback = off_weekly_cb
        self.add_item(off_weekly)

        create_template = discord.ui.Button(label='➕ Создать шаблон автоквеста', style=discord.ButtonStyle.success, row=3)
        async def create_template_cb(interaction: discord.Interaction):
            if not interaction_can_manage_guild(interaction, self.selected_guild, creator_id):
                return await interaction.response.send_message('❌ Недостаточно прав.', ephemeral=True)
            view = AutoQuestTemplateTypeView(creator_id, self.selected_guild)
            await interaction.response.edit_message(
                embed=discord.Embed(title='➕ Создание автоквеста', description='Сначала создайте шаблон. Затем выберите его периодичность и настройте расписание публикации.', color=discord.Color.green()),
                view=view)
        create_template.callback = create_template_cb
        self.add_item(create_template)

    def make_embed(self):
        embed = discord.Embed(title='⚙️ Расписание автоматических квестов',
            description=f'Гильдия: **{self.selected_guild}**\nВремя используется по московскому времени (Europe/Moscow, UTC+3).', color=discord.Color.blue())
        for qtype, label in [('daily','📆 Ежедневные'), ('weekly','🗓️ Еженедельные')]:
            cfg = quest_schedules.get(self.selected_guild, {}).get(qtype)
            if not cfg:
                value = 'Не настроено'
            else:
                pd = 'каждый день' if qtype == 'daily' else WEEKDAY_NAMES[WEEKDAY_ALIASES.get(cfg.get('publish_day','mon'),0)]
                cd = 'каждый день' if qtype == 'daily' else WEEKDAY_NAMES[WEEKDAY_ALIASES.get(cfg.get('close_day','sun'),6)]
                value = (f"Статус: **{'включено' if cfg.get('enabled', True) else 'выключено'}**\n"
                         f"Публикация: {pd}, {cfg.get('publish_time','—')}\n"
                         f"Закрытие: {cd}, {cfg.get('close_time','—')}\nКвестов за цикл: {cfg.get('count',3)}")
            embed.add_field(name=label, value=value, inline=False)
        return embed


@bot.command(name='quest_schedule')
async def quest_schedule(ctx, *args):
    """Открывает меню настройки автоматических ежедневных и еженедельных квестов."""
    if not ctx.guild:
        return await ctx.send('❌ Команда доступна только на сервере Discord.')
    if not ctx.author.guild_permissions.administrator and not get_leader_guild(ctx):
        return await ctx.send('❌ Только глава гильдии или администратор может менять расписание.')
    leader_guild = get_leader_guild(ctx)
    initial_guild = leader_guild or GUILD_NAMES[0]
    view = QuestScheduleMenu(ctx.author.id, initial_guild)
    await ctx.send(embed=view.make_embed(), view=view)


@bot.command(name='set_quest_board')
@commands.has_permissions(administrator=True)
async def set_quest_board(ctx, guild: str, channel_id: int):
    if not ctx.guild: return await ctx.send('❌ Команда доступна только на сервере Discord.')
    guild = normalize_guild_name(guild)
    if guild is None: return await ctx.send(f'❌ Гильдии: {", ".join(GUILD_NAMES)}')
    if not (
    channel := ctx.guild.get_channel(channel_id)) or channel.type != discord.ChannelType.forum: return await ctx.send(
        '❌ Не форум!')
    GUILD_QUEST_BOARDS[guild] = channel_id
    save_config()
    await ctx.send(f'✅ {channel.mention} → **{guild.capitalize()}**')


@bot.command(name='set_category')
@commands.has_permissions(administrator=True)
async def set_category(ctx, guild: str, category_id: int):
    if not ctx.guild: return await ctx.send('❌ Команда доступна только на сервере Discord.')
    guild = normalize_guild_name(guild)
    if guild is None: return await ctx.send('❌ Неверная гильдия!')
    if not (category := ctx.guild.get_channel(
        category_id)) or category.type != discord.ChannelType.category: return await ctx.send('❌ Не категория!')
    GUILD_CATEGORIES[guild] = category_id
    save_config()
    await ctx.send(f'✅ {category.mention}')


@bot.command(name='set_report_channel')
@commands.has_permissions(administrator=True)
async def set_report_channel(ctx, guild: str, channel_id: int):
    if not ctx.guild: return await ctx.send('❌ Команда доступна только на сервере Discord.')
    guild = normalize_guild_name(guild)
    if guild is None: return await ctx.send('❌ Неверная гильдия!')
    if not (
    channel := ctx.guild.get_channel(channel_id)) or channel.type != discord.ChannelType.text: return await ctx.send(
        '❌ Не текстовый!')
    GUILD_REPORT_CHANNELS[guild] = channel_id
    save_config()
    await ctx.send(f'✅ {channel.mention}')


@bot.command(name='show_settings')
@commands.has_permissions(administrator=True)
async def show_settings(ctx):
    if not ctx.guild: return await ctx.send('❌ Команда доступна только на сервере Discord.')
    embed = discord.Embed(title='⚙️ Настройки', color=discord.Color.blue())
    embed.add_field(name='📁 Категории', value='\n'.join(
        [f'🏛️ {g.capitalize()}: {ctx.guild.get_channel(cid).mention if ctx.guild.get_channel(cid) else "❌"}' for g, cid
         in GUILD_CATEGORIES.items()]), inline=False)
    embed.add_field(name='📊 Отчёты', value='\n'.join(
        [f'🏛️ {g.capitalize()}: {ctx.guild.get_channel(cid).mention if ctx.guild.get_channel(cid) else "❌"}' for g, cid
         in GUILD_REPORT_CHANNELS.items()]), inline=False)
    embed.add_field(name='🎯 Доски', value='\n'.join(
        [f'🏛️ {g.capitalize()}: {ctx.guild.get_channel(cid).mention if cid and ctx.guild.get_channel(cid) else "❌"}' for
         g, cid in GUILD_QUEST_BOARDS.items()]), inline=False)
    await ctx.send(embed=embed)


@bot.command(name='force_reset')
@commands.has_permissions(administrator=True)
async def force_reset(ctx):
    if not ctx.guild: return await ctx.send('❌ Команда доступна только на сервере Discord.')
    current_week = get_current_week_key()
    if data.get('last_reset_week') == current_week:
        return await ctx.send('⚠️ Сброс этой недели уже выполнен. Повторный сброс запрещён, чтобы не удалить текущий прогресс и не перезаписать историю.')
    await perform_weekly_reset()
    data['last_reset_week'] = current_week
    save_data()
    await ctx.send(f'✅ Выполнен пропущенный недельный сброс: {current_week}')


@bot.command(name='sync_roles')
@commands.has_permissions(administrator=True)
async def sync_roles(ctx):
    if not ctx.guild: return await ctx.send('❌ Команда доступна только на сервере Discord.')
    await ctx.send('🔄 Синхронизация...')
    synced = 0
    for uid, p in data['players'].items():
        if member := ctx.guild.get_member(p.get('discord_id')):
            try:
                synced += 1 if await update_rank_roles(member, p.get('rank', 'F'), p.get('guild')) else 0
            except:
                pass
    await ctx.send(f'✅ **{synced}**')


@bot.command(name='reset_vacation_cooldown')
@commands.has_permissions(administrator=True)
async def reset_vacation_cooldown(ctx, nick: str):
    if not ctx.guild: return await ctx.send('❌ Команда доступна только на сервере Discord.')
    found_uid = next((uid for g in GUILD_NAMES if (uid := find_player_by_nick(nick, g)[0])), None)
    if not found_uid: return await ctx.send(f'❌ **{nick}** не найден.')
    if found_uid in data.get('vacation_cooldowns', {}):
        data['vacation_cooldowns'].pop(found_uid, None)
        save_data()
        await ctx.send(f'✅ Кулдаун отпуска для **{nick}** сброшен.')
    else:
        await ctx.send(f'ℹ️ У **{nick}** нет кулдауна.')


MAIN_MENU_EMBED_TITLES = {
    '🧭 Главное меню RPG-бота',
    'Главное меню RPG-бота',
    'Главное меню',
    'Панель управления RPG-бота',
}


async def _upsert_main_menu(ctx):
    """Keep one main-menu message per channel instead of stacking old and new panels."""
    embed = build_main_menu_embed(ctx.author)
    view = build_main_menu_view(ctx.author)
    existing = []
    if bot.user is not None:
        try:
            async for message in ctx.channel.history(limit=100):
                if message.author.id != bot.user.id or not message.embeds:
                    continue
                title = message.embeds[0].title
                if title in MAIN_MENU_EMBED_TITLES:
                    existing.append(message)
        except (discord.Forbidden, discord.HTTPException):
            # Without read-history permission, still provide the menu instead of failing.
            existing = []

    if existing:
        primary = existing[0]
        try:
            await primary.edit(content=None, embed=embed, view=view)
        except discord.HTTPException:
            primary = await ctx.send(embed=embed, view=view)
            try:
                await existing[0].delete()
            except discord.HTTPException:
                pass
        for duplicate in existing[1:]:
            try:
                await duplicate.delete()
            except discord.HTTPException:
                pass
        return primary

    return await ctx.send(embed=embed, view=view)


@bot.command(name='menu', aliases=['меню', 'панель'])
async def main_menu(ctx):
    """Открывает или обновляет единственное интерактивное меню игрока и руководителя."""
    if not ctx.guild:
        return await ctx.send('❌ Меню доступно только на сервере Discord.')
    await _upsert_main_menu(ctx)


@bot.command(name='chelp', aliases=['help_bot', 'помощь'])
async def chelp(ctx):
    """Показывает справочник команд и краткие инструкции по меню."""
    role = get_user_role(ctx)
    embed = discord.Embed(
        title='📚 Справка по RPG-боту',
        description=(
            f'Ваша роль: **{role.capitalize()}**. Все команды начинаются с точки (`.`).\n'
            '**Быстрый старт:** `.menu` (или `.меню`, `.панель`) открывает интерактивную панель. '
            'Нажимайте кнопки и выбирайте пункты в списках; для возврата используйте кнопки меню. '
            'Команды ниже остаются доступны как альтернативный способ управления.'
        ),
        color=discord.Color.blue()
    )
    embed.add_field(name='👤 Игрок — меню и профиль', value=(
        '`.menu` / `.меню` / `.панель` — открыть интерактивное меню игрока.\n'
        '`.chelp` / `.помощь` — показать эту справку.\n'
        '`.cabinet [@игрок]` — открыть личный кабинет; без упоминания показывает ваш профиль.\n'
        '`.stats` — краткая статистика; `.week` — итоги текущей недели.\n'
        '`.compare` — сравнение недельных показателей; `.history` — история недель.\n'
        '`.achievements` — достижения и прогресс; `.titles` — титулы; `.title_set ID` — выбрать открытый титул.\n'
        '`.rank_info [ранг]` — информация о ранге; `.territory_limit [база]` — расчёт лимита территории.\n'
        '`.my_quests` — посмотреть доступные и взятые личные квесты.\n'
        '`.vacation [дней]` — оформить отпуск; `.vacation_cancel` — отменить отпуск.'
    ), inline=False)
    embed.add_field(name='🏦 Аркейн Банк и кредиты', value=(
        '`.bank_help` — правила и справка по банку; `.credit_help` — справка по кредитам.\n'
        '`.credit_apply сумма 7|14|30` — подать заявку, например `.credit_apply 700 7`.\n'
        '`.credit_status` — проверить состояние кредита.\n'
        '`.savings_open topups` — открыть накопительный счёт с пополнениями; '
        '`.savings_open no_topups` — счёт без пополнений.\n'
        '`.savings_status` — состояние накопительного счёта; `.deposit_status` — состояние срочных вкладов.\n'
        'Подтверждение заявок и физические передачи алмазов выполняются по правилам банка; бот ведёт учёт.'
    ), inline=False)
    embed.add_field(name='🎯 Квесты — как пользоваться меню', value=(
        '1. Введите `.menu` и откройте **«Управление квестами»** (для главы гильдии/администратора).\n'
        '2. **«Создать квест»** → выберите создание из шаблона, еженедельного или ежедневного квеста.\n'
        '3. При создании выберите тип: **«С наградой»** (алмазы и/или XP) или **«Без награды»**. '
        'У обоих типов сохраняется бонус к зарплате за выполнение.\n'
        '4. **«Шаблоны и награды»** позволяет создать шаблон, просмотреть шаблоны, настроить награду '
        'или удалить пользовательский шаблон. Награда 0 алмазов и 0 XP означает отсутствие предметной награды.\n'
        '5. **«Выдать награду»** — выберите подтверждённое выполнение после фактической передачи алмазов/XP в Minecraft '
        'и подтвердите отметку. Эта кнопка только фиксирует выдачу, а не передаёт предметы в игре.\n'
        '6. **«Закрыть квест»** закрывает выбранный активный квест; **«Автоквесты»** открывает настройку расписания и создание шаблонов автоквестов. В создании квеста есть также вариант **«Единоразовый»**.'
    ), inline=False)
    if role in ['leader', 'admin']:
        embed.add_field(name='👑 Глава гильдии — команды квестов и управления', value=(
            '`.quest_create` — открыть меню создания квеста.\n'
            '`.quest_confirm ID_КВЕСТА Ник` — подтвердить выполнение индивидуального квеста; замените ID и ник реальными значениями.\n'
            '`.quest_reward_paid ID_КВЕСТА Ник` — вручную отметить предметную награду как выданную после передачи в Minecraft. '
            'Обычно удобнее использовать `.menu` → «Управление квестами» → «Выдать награду».\n'
            '`.quest_delete [ID]` — закрыть квест по ID; без ID показывает список активных квестов.\n'
            '`.template_add` — открыть создание шаблона; `.template_list` — показать шаблоны.\n'
            '`.template_reward ID_ШАБЛОН алмазы XP` — задать награду шаблона, например `.template_reward ID_ШАБЛОН 32 100`; '
            'для квеста без предметной награды используйте `0 0`.\n'
            '`.template_delete [ID]` — удалить пользовательский шаблон; без ID выводит ID пользовательских шаблонов, затем укажите нужный ID.\n'
            '`.quest_schedule` — открыть меню расписания автоквестов: включение, дни, время, количество и создание шаблонов.\n'
            '`.list` — список игроков; `.add "ник"` — начисление заданий игроку; `.add_batch "ник1, ник2"` — массовое начисление.\n'
            '`.analytics` — аналитика гильдии; `.vacation_list` — отпуска и кулдауны; `.remove ник` — удалить игрока из учёта.'
        ), inline=False)
    if _member_in_guild(ctx.author, 'СОБР'):
        embed.add_field(name='🛡️ СОБР — отчёты и личные дела', value=(
            '`.sobr_report` — создать отчёт (ранг D и выше); выберите тип и заполните форму. Для участников используйте упоминания, Discord ID или Minecraft-ники СОБР. Время можно оставить пустым (текущее МСК) или указать `ДД.ММ.ГГГГ ЧЧ:ММ`.\n'
            'Для инвентаризации укажите `Здание: название` и `Ресурсы: алмазы=10, железо=20`; бот сравнит остатки с прошлым отчётом по зданию.\n'
            '`.sobr_reports [ожидает]` — последние отчёты или только ожидающие подтверждения (ранг D+). `.sobr_dossier [@игрок]` — своё дело; чужое доступно рангу B и выше.'
        ), inline=False)
        embed.add_field(name='🛡️ СОБР — нарушения, штрафы и паспорта', value=(
            '`.sobr_violation_confirm ID [решение]` — подтвердить нарушение (ранг B+). Только подтверждённые нарушения учитываются; каждые 2 создают штраф 200 алмазов.\n'
            '`.sobr_fines [@игрок]` — посмотреть штрафы; `.sobr_fine_paid @игрок ID [примечание]` — отметить физически полученные 200 алмазов (ранг B+).\n'
            '`.sobr_report_correct ID текст` — добавить исправление, не меняя оригинал. `.sobr_passport_report` — вручную создать недельный отчёт (ранг B+); автоматически создаётся по понедельникам в 10:00 МСК в закрытом канале.\n'
            'Создание отчётов и исправлений — ранг D+. Подтверждение нарушений и оплаты — ранг B+. Бот не переводит алмазы.'
        ), inline=False)
    if _member_in_guild(ctx.author, 'торговцы'):
        embed.add_field(name='💰 Торговцы — кредитный отдел', value=(
            '`.credit_requests`, `.credit_approve ID`, `.credit_reject ID причина`, `.credit_issue ID [примечание]`, `.credit_pay ID сумма [примечание]`, `.credit_passport @участник да/нет`.\n'
            'Управление сотрудниками/аудитом для лидера: `.credit_staff @участник да/нет`, `.credit_edit ID поле значение причина`, `.credit_audit [количество]`, `.credit_service_channel #канал`.\n'
            'Доступ к служебным действиям кредитного отдела — у лидера и назначенных сотрудников Торговцев; сотрудник должен состоять в гильдии Торговцев.'
        ), inline=False)
        embed.add_field(name='💰 Торговцы — служебные команды банка', value=(
            '`.treasury`, `.treasury_add сумма причина`, `.treasury_expense сумма причина`, `.treasury_approve ID` (лидер), `.treasury_pay ID [примечание]`, `.treasury_reserve сумма причина`, `.treasury_release сумма причина`.\n'
            '`.bank_report week|month`, `.bank_history [количество]`, `.bank_staff @участник да/нет` (лидер).\n'
            '`.savings_deposit @участник сумма [примечание]`, `.savings_withdraw @участник сумма [примечание]`, `.savings_visit @участник`, `.deposit_open @участник сумма срок`, `.deposit_pay ID [примечание]`, `.deposit_early ID [примечание]`.'
        ), inline=False)
    if role == 'admin':
        embed.add_field(name='⚙️ Администратор — настройки', value=(
            '`.set_quest_board гильдия ID_канала` — назначить форумную доску квестов.\n'
            '`.set_category гильдия ID_категории` — назначить категорию Discord гильдии.\n'
            '`.set_report_channel гильдия ID_канала` — назначить канал недельных отчётов.\n'
            '`.show_settings` — показать настройки бота.\n'
            '`.force_reset` — вручную запустить недельный сброс; используйте осторожно, он влияет на прогресс.\n'
            '`.sync_roles` — синхронизировать роли рангов; `.reset_vacation_cooldown ник` — сбросить кулдаун отпуска.\n'
            '`.generate` — создать код приглашения; `.codes` — показать активные коды; `.revoke КОД` — отозвать код.'
        ), inline=False)
    embed.set_footer(text='Если команда не видна в справке, доступ к ней может зависеть от вашей роли. Для интерактивного управления начните с .menu.')

    # Discord limits: field value <= 1024 chars, <= 25 fields per embed,
    # and total embed size <= 6000 chars. Split long fields before pagination.
    original_fields = list(embed.fields)
    embed.clear_fields()

    def split_help_value(value: str, limit: int = 1000) -> list[str]:
        """Split help text into Discord-safe chunks, preferring line boundaries."""
        chunks = []
        current = ''
        for line in (value or '').splitlines() or ['']:
            # A single line can itself exceed the field limit, so split it too.
            while len(line) > limit:
                if current:
                    chunks.append(current)
                    current = ''
                chunks.append(line[:limit])
                line = line[limit:]
            candidate = line if not current else current + '\n' + line
            if len(candidate) > limit:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current or not chunks:
            chunks.append(current or '\u200b')
        return chunks

    safe_fields = []
    for field in original_fields:
        value_chunks = split_help_value(field.value)
        for index, value_chunk in enumerate(value_chunks):
            name = field.name if index == 0 else f'{field.name} (продолжение)'
            safe_fields.append((name[:256], value_chunk, field.inline if len(value_chunks) == 1 else False))

    def make_help_page(continuation: bool = False):
        if not continuation:
            page = discord.Embed(
                title=embed.title,
                description=embed.description,
                color=embed.color
            )
            if embed.footer.text:
                page.set_footer(text=embed.footer.text)
            return page
        page = discord.Embed(
            title='📚 Справка по RPG-боту — продолжение',
            description=f'Ваша роль: **{role.capitalize()}**. Дополнительные команды, доступные вашей роли.',
            color=discord.Color.blue()
        )
        page.set_footer(text='Для интерактивного управления начните с .menu.')
        return page

    pages = [make_help_page()]
    for name, value, inline in safe_fields:
        page = pages[-1]
        added_size = len(name) + len(value)
        if len(page.fields) >= 25 or len(page) + added_size > 5500:
            page = make_help_page(continuation=True)
            pages.append(page)
        page.add_field(name=name, value=value, inline=inline)

    for page in pages:
        await ctx.send(embed=page)

# === ЗАПУСК ===

@bot.event
async def on_ready():
    print(f'✅ {bot.user.name}')
    cw = get_current_week_key()
    if not data.get('last_reset_week'):
        # При первом запуске не начисляем и не сбрасываем данные автоматически.
        data['last_reset_week'] = cw
        save_data()
    elif data['last_reset_week'] != cw:
        try:
            await perform_weekly_reset()
            data['last_reset_week'] = cw
            save_data()
        except Exception as exc:
            print(f'❌ Не удалось завершить пропущенный недельный сброс: {exc}')
    if not weekly_reset_checker.is_running():
        weekly_reset_checker.start()
    if not check_overdue_quests.is_running():
        check_overdue_quests.start()
    if not quest_schedule_checker.is_running():
        quest_schedule_checker.start()
    if not sobr_weekly_passport_checker.is_running():
        sobr_weekly_passport_checker.start()
    for discord_guild in bot.guilds:
        await ensure_sobr_private_channel(discord_guild)
    if credit_daily_checker is not None and not credit_daily_checker.is_running():
        credit_daily_checker.start()
    if bank_daily_checker is not None and not bank_daily_checker.is_running():
        bank_daily_checker.start()
    print(f'📅 {cw}')


if __name__ == '__main__':
    if not TOKEN:
        raise RuntimeError('Переменная окружения DISCORD_TOKEN не задана. Установите токен через переменные окружения.')
    try:
        with open('rank_roles_config.json', 'r', encoding='utf-8') as f:
            for g, r in json.load(f).items():
                if (canonical := normalize_guild_name(g)) and isinstance(r, dict): RANK_ROLES[canonical].update(r)
    except:
        pass
    try:
        with open('guild_categories_config.json', 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            for g, c in cfg.get('categories', {}).items():
                if (canonical := normalize_guild_name(g)): GUILD_CATEGORIES[canonical] = c
            for g, c in cfg.get('report_channels', {}).items():
                if (canonical := normalize_guild_name(g)): GUILD_REPORT_CHANNELS[canonical] = c
            for g, c in cfg.get('quest_boards', {}).items():
                if (canonical := normalize_guild_name(g)): GUILD_QUEST_BOARDS[canonical] = c
    except:
        pass
    from bank_system import setup_bank_system
    from credit_system import setup_credit_system
    bank_api = setup_bank_system(
        bot=bot, data=data, is_registered=is_registered, leader_roles=GUILD_LEADER_ROLES, rank_roles=RANK_ROLES,
        atomic_write=_atomic_write_json, now_msk=now_msk
    )
    bank_daily_checker = bank_api["daily_checker"]
    credit_daily_checker = setup_credit_system(
        bot=bot, data=data, is_registered=is_registered, leader_roles=GUILD_LEADER_ROLES, rank_roles=RANK_ROLES,
        atomic_write=_atomic_write_json, now_msk=now_msk, report_channels=GUILD_REPORT_CHANNELS,
        bank_api=bank_api
    )
    # В публичной справке остаются две точки входа; все рабочие команды доступны
    # из тематических разделов меню и сохраняются как скрытые команды совместимости.
    for registered_command in bot.commands:
        if registered_command.name not in {'menu', 'chelp'}:
            registered_command.hidden = True
    bot.run(TOKEN)