"""Auto stat / skill raise settings (logic, parsing, planning, config).

Pure logic module — no Tkinter dependencies.
Supports OpenKore plugins: raiseStat and raiseSkill.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

from .kconfig import KConfig

STATS: Final[tuple[str, ...]] = ('str', 'agi', 'vit', 'int', 'dex', 'luk')


def parse_stat_list(text: str, allow_over_99: bool = False) -> list[tuple[str, int]]:
    """Parse comma-separated stat raise list (e.g. '60 int, 25 dex' or 'int 65, 29 dex')."""
    stripped = text.strip()
    if not stripped:
        return []

    pieces = re.split(r'\s*,+\s*', stripped)
    out: list[tuple[str, int]] = []
    for piece in pieces:
        if not piece:
            raise ValueError(f'ชิ้นส่วนสเตตัสว่างเปล่าใน {text!r}')

        m1 = re.match(r'^(\d+)\s+([a-zA-Z]+)$', piece)
        m2 = re.match(r'^([a-zA-Z]+)\s+(\d+)$', piece)
        if m1:
            val_str, stat_str = m1.group(1), m1.group(2)
        elif m2:
            stat_str, val_str = m2.group(1), m2.group(2)
        else:
            raise ValueError(f'รูปแบบสเตตัสไม่ถูกต้อง: {piece!r}')

        stat = stat_str.lower()
        if stat not in STATS:
            raise ValueError(f'ไม่รู้จักสเตตัส {stat!r} ใน {piece!r}')

        try:
            val = int(val_str)
        except ValueError:
            raise ValueError(f'ค่าสเตตัสไม่ใช่ตัวเลข: {piece!r}') from None

        if val < 1:
            raise ValueError(f'ค่าสเตตัสต้อง >= 1 ใน {piece!r}')
        if not allow_over_99 and val > 99:
            raise ValueError(f'ค่าสเตตัสเกิน 99 ใน {piece!r}')

        out.append((stat, val))
    return out


def format_stat_list(steps: list[tuple[str, int]]) -> str:
    """Format steps to OpenKore raiseStat string (e.g. '60 int, 25 dex')."""
    return ', '.join(f'{val} {stat}' for stat, val in steps)


def parse_skill_list(text: str) -> list[tuple[str, int]]:
    """Parse comma-separated skill raise list (e.g. 'SM_BASH 10, SM_PROVOKE')."""
    stripped = text.strip()
    if not stripped:
        return []

    pieces = re.split(r'\s*,+\s*', stripped)
    out: list[tuple[str, int]] = []
    for piece in pieces:
        if not piece:
            raise ValueError(f'ชิ้นส่วนสกิลว่างเปล่าใน {text!r}')

        m = re.match(r'^(.*?)(?:\s+(\d+))?$', piece.strip())
        if not m:
            raise ValueError(f'รูปแบบสกิลไม่ถูกต้อง: {piece!r}')

        name = m.group(1).strip()
        if not name:
            raise ValueError(f'ชื่อสกิลว่างเปล่า: {piece!r}')

        lvl_str = m.group(2)
        if lvl_str is not None:
            try:
                lvl = int(lvl_str)
            except ValueError:
                raise ValueError(f'เลเวลสกิลไม่ถูกต้อง: {piece!r}') from None
        else:
            lvl = 1

        if not (1 <= lvl <= 10):
            raise ValueError(f'เลเวลสกิลต้องอยู่ระหว่าง 1 ถึง 10 ใน {piece!r}')

        out.append((name, lvl))
    return out


def format_skill_list(steps: list[tuple[str, int]]) -> str:
    """Format steps to OpenKore raiseSkill string (e.g. 'SM_BASH 10, SM_PROVOKE 1')."""
    return ', '.join(f'{handle} {lvl}' for handle, lvl in steps)


def stat_cost(value: int) -> int:
    """Cost in stat points of raising value -> value + 1."""
    return 2 + (value - 1) // 10


def points_needed(current: int, target: int) -> int:
    """Total points needed to raise stat from current to target."""
    if target <= current:
        return 0
    return sum(stat_cost(v) for v in range(current, target))


@dataclass(frozen=True)
class StepPlan:
    stat: str
    start: int
    target: int
    cost: int
    reach: int


def plan_stats(
    current: dict[str, int],
    free: int,
    steps: list[tuple[str, int]],
) -> tuple[list[StepPlan], int]:
    """Simulate OpenKore spending free points sequentially through steps."""
    planned = dict(current)
    budget = max(0, free)
    ran_out = False
    plans: list[StepPlan] = []

    for stat, target in steps:
        start = planned.get(stat, 1)
        cost = points_needed(start, target)
        planned[stat] = max(start, target)

        if ran_out:
            reach = start
        else:
            val = start
            while val < target and budget >= stat_cost(val):
                budget -= stat_cost(val)
                val += 1
            reach = val
            if reach < target:
                ran_out = True

        plans.append(StepPlan(stat=stat, start=start, target=target, cost=cost, reach=reach))

    return plans, budget


@dataclass
class RaiseSettings:
    stats_on: bool = False
    stats: list[tuple[str, int]] = field(default_factory=list)
    base_only: bool = False
    skills_on: bool = False
    skills: list[tuple[str, int]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def load(kc: KConfig) -> RaiseSettings:
    """Read auto raise settings from config.txt."""
    stats_on = kc.get('statsAddAuto').strip() not in ('', '0')
    base_only = kc.get('statsAddAuto_dontUseBonus').strip() not in ('', '0')
    skills_on = kc.get('skillsAddAuto').strip() not in ('', '0')

    errors: list[str] = []
    stats: list[tuple[str, int]] = []
    stats_raw = kc.get('statsAddAuto_list').strip()
    if stats_raw:
        try:
            stats = parse_stat_list(stats_raw)
        except ValueError as e:
            errors.append(f'statsAddAuto_list: {e}')

    skills: list[tuple[str, int]] = []
    skills_raw = kc.get('skillsAddAuto_list').strip()
    if skills_raw:
        try:
            skills = parse_skill_list(skills_raw)
        except ValueError as e:
            errors.append(f'skillsAddAuto_list: {e}')

    return RaiseSettings(
        stats_on=stats_on,
        stats=stats,
        base_only=base_only,
        skills_on=skills_on,
        skills=skills,
        errors=errors,
    )


def apply(kc: KConfig, s: RaiseSettings) -> None:
    """Write auto raise settings into KConfig (editing existing lines in place)."""
    if s.stats_on and not s.stats:
        raise ValueError('เปิดอัปสเตตัสอัตโนมัติแต่ยังไม่ได้กำหนดรายการสเตตัส')
    if s.skills_on and not s.skills:
        raise ValueError('เปิดอัปสกิลอัตโนมัติแต่ยังไม่ได้กำหนดรายการสกิล')

    keys_spec: list[tuple[str, bool, bool, str, bool]] = [
        ('statsAddAuto', True, s.stats_on, '1' if s.stats_on else '0', s.stats_on),
        ('statsAddAuto_dontUseBonus', True, s.base_only, '1' if s.base_only else '0', s.base_only),
        ('statsAddAuto_list', False, False, format_stat_list(s.stats), bool(s.stats)),
        ('skillsAddAuto', True, s.skills_on, '1' if s.skills_on else '0', s.skills_on),
        ('skillsAddAuto_list', False, False, format_skill_list(s.skills), bool(s.skills)),
    ]

    for key, is_flag, flag_val, new_val, meaningful in keys_spec:
        if kc.has(key):
            old_val = kc.get(key)
            if is_flag:
                old_flag = old_val.strip() not in ('', '0')
                if old_flag != flag_val:
                    kc.set(key, new_val)
            else:
                if old_val != new_val:
                    kc.set(key, new_val)
        else:
            if meaningful:
                kc.set(key, new_val)


@dataclass(frozen=True)
class CharStats:
    base: dict[str, int]
    bonus: dict[str, int]
    points_free: int
    points_skill: int
    level: int


def char_stats(char_json: dict[str, Any] | None) -> CharStats | None:
    """Parse character stats from char.json data."""
    if not isinstance(char_json, dict):
        return None
    stats_dict = char_json.get('stats')
    if not isinstance(stats_dict, dict):
        return None

    base: dict[str, int] = {}
    for stat in STATS:
        if stat not in stats_dict:
            return None
        try:
            base[stat] = int(stats_dict[stat])
        except (TypeError, ValueError):
            return None

    bonus: dict[str, int] = {}
    for stat in STATS:
        bonus_key = f'{stat}_bonus'
        raw_val = stats_dict.get(bonus_key, 0)
        try:
            bonus[stat] = int(raw_val)
        except (TypeError, ValueError):
            bonus[stat] = 0

    def _get_int(key: str, default: int = 0) -> int:
        raw = stats_dict.get(key, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    points_free = _get_int('points_free', 0)
    points_skill = _get_int('points_skill', 0)
    level = _get_int('lv', 0)

    return CharStats(
        base=base,
        bonus=bonus,
        points_free=points_free,
        points_skill=points_skill,
        level=level,
    )
