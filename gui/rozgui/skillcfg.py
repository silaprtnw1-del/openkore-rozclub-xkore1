"""Skill settings <-> OpenKore config.txt blocks, edited in place.

The GUI never rewrites a whole block: it changes only the attributes the user
touched (lvl, sp, hp, ...) and keeps every other line and comment, so
hand-tuned blocks such as `target potato7, kiminoto` or `target_timeout 170`
survive. Blocks are found again by (key, value, ordinal) on every edit, so
the advanced block editor and these tabs can both edit the same KConfig.

Keys and conditions verified in OpenKore src: AI/Attack.pm (attackSkillSlot,
maxUses), AI/CoreLogic.pm (useSelf_skill, partySkill), Misc.pm
checkSelfCondition (sp, hp, monstersCount, monstersCountDist, timeout,
whenStatusInactive), Utils.pm inRange (">= x", "<= x").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

from .kconfig import Block, KConfig

ATTACK: Final[str] = 'attackSkillSlot'
SELF: Final[str] = 'useSelf_skill'
PARTY: Final[str] = 'partySkill'

# Skill target types reported by the plugin (Skill::TARGET_*).
T_PASSIVE: Final[int] = 0
T_ENEMY: Final[int] = 1
T_SELF: Final[int] = 4
T_ACTORS: Final[int] = 16

HEAL_SKILLS: Final[frozenset[str]] = frozenset({'AL_HEAL', 'AB_HIGHNESSHEAL', 'AB_CHEAL'})
# Cast on demand, not timed buffs: kept out of the buff list.
NOT_BUFFS: Final[frozenset[str]] = frozenset({'NV_FIRSTAID', 'TF_DETOXIFY', 'AL_CURE', 'AL_TELEPORT', 'AL_WARP',
                                             'AL_PNEUMA', 'AL_HOLYWATER', 'AL_RUWACH', 'MG_SIGHT'})
# Skill -> status handle, each pair checked against tables/statusnametable.txt.
SKILL_STATUS: Final[dict[str, str]] = {
    'AL_INCAGI': 'EFST_INC_AGI', 'AL_BLESSING': 'EFST_BLESSING', 'AL_ANGELUS': 'EFST_ANGELUS',
    'AL_CRUCIS': 'EFST_CRUCIS', 'TF_HIDING': 'EFST_HIDING', 'SM_ENDURE': 'EFST_ENDURE',
    'SM_AUTOBERSERK': 'EFST_AUTOBERSERK', 'AC_CONCENTRATION': 'EFST_CONCENTRATION',
    'MG_ENERGYCOAT': 'EFST_ENERGYCOAT', 'KN_TWOHANDQUICKEN': 'EFST_TWOHANDQUICKEN',
    'KN_ONEHANDQUICKEN': 'EFST_ONEHANDQUICKEN', 'CR_SPEARQUICKEN': 'EFST_SPEARQUICKEN',
    'CR_AUTOGUARD': 'EFST_AUTOGUARD', 'CR_REFLECTSHIELD': 'EFST_REFLECTSHIELD', 'CR_DEFENDER': 'EFST_DEFENDER',
    'PR_MAGNIFICAT': 'EFST_MAGNIFICAT', 'PR_GLORIA': 'EFST_GLORIA', 'PR_IMPOSITIO': 'EFST_IMPOSITIO',
    'PR_SUFFRAGIUM': 'EFST_SUFFRAGIUM', 'PR_KYRIE': 'EFST_KYRIE', 'PR_ASPERSIO': 'EFST_ASPERSIO',
    'BS_ADRENALINE': 'EFST_ADRENALINE', 'BS_OVERTHRUST': 'EFST_OVERTHRUST', 'AS_POISONREACT': 'EFST_POISONREACT',
    'AS_ENCHANTPOISON': 'EFST_ENCHANTPOISON', 'AS_CLOAKING': 'EFST_CLOAKING',
    'MO_EXPLOSIONSPIRITS': 'EFST_EXPLOSIONSPIRITS', 'MO_STEELBODY': 'EFST_STEELBODY',
}
BUFF_FALLBACK_TIMEOUT: Final[str] = '60'
NEAR_DIST: Final[str] = '3'     # monstersCountDist used for "มอนรอบตัว"

_NUM_RE = re.compile(r'(-?\d+(?:\.\d+)?)')


@dataclass(frozen=True)
class LearnedSkill:
    handle: str
    name: str
    lv: int
    target: int


@dataclass
class SkillRef:
    """Where a skill's block lives: found again by (key, value, ordinal) before every edit."""
    key: str
    value: str
    ordinal: int = 0
    attrs: list[tuple[str, str]] = field(default_factory=list)

    def get(self, k: str) -> str | None:
        for kk, v in reversed(self.attrs):
            if kk == k:
                return v
        return None

    @property
    def enabled(self) -> bool:
        return (self.get('disabled') or '0').strip() in ('', '0')


def parse_learned(char_json: dict[str, Any] | None) -> list[LearnedSkill]:
    out: list[LearnedSkill] = []
    for s in (char_json or {}).get('skills') or []:
        if not isinstance(s, dict) or not s.get('handle'):
            continue
        raw_target = s.get('target')
        try:
            target = int(raw_target) if raw_target is not None else -1
            out.append(LearnedSkill(str(s['handle']), str(s.get('name') or s['handle']), int(s.get('lv') or 0), target))
        except (TypeError, ValueError):
            continue    # malformed row from the plugin: skip it, the rest still shows
    return out


def status_for(handle: str, status_names: dict[str, str]) -> str | None:
    """Status handle a buff skill puts on its target, if OpenKore knows it."""
    st = SKILL_STATUS.get(handle)
    if st and (not status_names or st in status_names):
        return st
    guess = 'EFST_' + handle.split('_', 1)[-1]
    return guess if guess in status_names else None


def _same_skill(value: str, skill: LearnedSkill | None, handle: str) -> bool:
    v = value.strip().lower()
    return v == handle.lower() or (skill is not None and v == skill.name.lower())


def find_refs(kc: KConfig, key: str, handle: str, skill: LearnedSkill | None = None) -> list[SkillRef]:
    """Blocks of `key` for this skill (by handle or by its name), in file order."""
    refs: list[SkillRef] = []
    counts: dict[str, int] = {}
    for b in kc.blocks:
        if b.key != key:
            continue
        n = counts.get(b.value, 0)
        counts[b.value] = n + 1
        if _same_skill(b.value, skill, handle):
            refs.append(SkillRef(b.key, b.value, n, kc.block_items(b)))
    return refs


def _locate(kc: KConfig, ref: SkillRef) -> Block:
    b = kc.find_block(ref.key, ref.value, ref.ordinal)
    if b is None:
        raise LookupError(f'block {ref.key} {ref.value} #{ref.ordinal} is gone (file changed?)')
    return b


def _edit_lines(inner: str, changes: dict[str, str | None]) -> str:
    """Change attributes in a block body. None removes; comments and unknown lines stay put."""
    lines = inner.splitlines()
    done: set[str] = set()
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        k = s.split(None, 1)[0] if s and not s.startswith('#') else None
        if k is not None and k in changes:
            if k in done:
                continue                      # drop duplicate keys we are setting
            done.add(k)
            if changes[k] is not None:
                out.append(f'{k} {changes[k]}')
            continue
        out.append(s)
    for k, v in changes.items():
        if k not in done and v is not None:
            out.append(f'{k} {v}')
    return '\n'.join(out)


def edit(kc: KConfig, ref: SkillRef, changes: dict[str, str | None]) -> None:
    b = _locate(kc, ref)
    kc.replace_block(b, b.value, _edit_lines(kc.block_text(b), changes))


def delete(kc: KConfig, ref: SkillRef) -> None:
    kc.delete_block(_locate(kc, ref))


def all_refs(kc: KConfig, key: str) -> list[SkillRef]:
    """Every `key` block in file order, with its (value, ordinal) identity."""
    refs: list[SkillRef] = []
    counts: dict[str, int] = {}
    for b in kc.blocks:
        if b.key == key:
            n = counts.get(b.value, 0)
            counts[b.value] = n + 1
            refs.append(SkillRef(b.key, b.value, n, kc.block_items(b)))
    return refs


def create(kc: KConfig, key: str, handle: str, attrs: dict[str, str]) -> None:
    kc.add_block(key, handle, '\n'.join(f'{k} {v}' for k, v in attrs.items()))


def set_enabled(kc: KConfig, ref: SkillRef | None, key: str, handle: str, on: bool,
                defaults: dict[str, str]) -> None:
    """Turn a skill on/off. Off keeps the block (disabled 1) so its settings are not lost."""
    if ref is None:
        if on:
            create(kc, key, handle, {**defaults, 'disabled': '0'})
        return
    edit(kc, ref, {'disabled': '0' if on else '1'})


def reorder(kc: KConfig, key: str, order: list[str]) -> None:
    """Rewrite all `key` blocks so the ones whose value is in `order` come first, in that order."""
    blocks = [b for b in kc.blocks if b.key == key]
    texts = [(b.value, kc.block_text(b)) for b in blocks]
    for b in sorted(blocks, key=lambda b: b.start, reverse=True):
        kc.delete_block(b)
    kc.trim_trailing_blank()
    rank = {v.lower(): i for i, v in enumerate(order)}
    texts.sort(key=lambda t: rank.get(t[0].strip().lower(), len(order)))
    for value, body in texts:
        kc.add_block(key, value, body)


# ---------------------------------------------------------------- value helpers
def pct(raw: str | None) -> int | None:
    """'>= 20%' / '< 65%' / '20' -> 20. None when absent or not a single number."""
    if raw is None:
        return None
    nums = _NUM_RE.findall(raw)
    if len(nums) != 1 or '..' in raw:
        return None
    return int(float(nums[0]))


def ge(n: int) -> str | None:
    """'at least n%' (0 = no condition)."""
    return f'>= {n}%' if n > 0 else None


def le(n: int) -> str | None:
    """'at most n%' (100 = no condition)."""
    return f'<= {n}%' if 0 < n < 100 else None
