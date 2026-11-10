"""Pure logic and validation for bot team coordination (no Tk)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from .kconfig import KConfig

SOLO: Final[str] = 'solo'
FOLLOW: Final[str] = 'follow'
PARTY_AUTO_TH: Final[dict[int, str]] = {0: 'ไม่ตอบ', 1: 'ปฏิเสธ', 2: 'รับเชิญ'}


@dataclass
class TeamMember:
    bot: str                      # bot (instance) name
    char: str = ''                # character name ('' = unknown)
    role: str = SOLO
    follow_target: str = ''       # character name
    follow_dist: int | None = None
    lock_map: str = ''
    party_attack: bool = False
    party_loot: bool = False
    party_auto: int = 0
    # read-only, from status.json (display only):
    online: bool = False
    level: int = 0
    job: str = ''
    map: str = ''
    hp_pct: int | None = None
    party: str = ''


def read_member(bot: str, kc: KConfig, status: dict[str, Any] | None) -> TeamMember:
    """Read a bot's team settings from KConfig and runtime status."""
    follow_raw = kc.get('follow').strip()
    role = FOLLOW if follow_raw not in ('', '0') else SOLO
    follow_target = kc.get('followTarget').strip()

    follow_dist_raw = kc.get('followDistanceMax').strip()
    follow_dist: int | None = None
    if follow_dist_raw:
        try:
            follow_dist = int(follow_dist_raw)
        except (ValueError, TypeError):
            follow_dist = None

    lock_map = kc.get('lockMap').strip()
    party_attack = kc.get('attackAuto_party').strip() not in ('', '0')
    party_loot = kc.get('itemsTakeAuto_party').strip() not in ('', '0')

    party_auto_raw = kc.get('partyAuto').strip()
    party_auto = 0
    if party_auto_raw:
        try:
            pa = int(party_auto_raw)
            if pa in (0, 1, 2):
                party_auto = pa
        except (ValueError, TypeError):
            party_auto = 0

    char = ''
    online = False
    level = 0
    job = ''
    map_ = ''
    hp_pct: int | None = None
    party = ''

    if status is not None:
        char = str(status.get('char') or '')
        online = bool(status.get('online'))
        try:
            level = int(status.get('level') or 0)
        except (ValueError, TypeError):
            level = 0
        job = str(status.get('job') or '')
        map_ = str(status.get('map') or '')
        party = str(status.get('party') or '')
        try:
            hp = status.get('hp')
            hp_max = status.get('hp_max')
            if hp is not None and hp_max is not None:
                hp_f = float(hp)
                hp_max_f = float(hp_max)
                if hp_max_f > 0:
                    hp_pct = round(100.0 * hp_f / hp_max_f)
        except (ValueError, TypeError, ZeroDivisionError):
            hp_pct = None

    return TeamMember(
        bot=bot,
        char=char,
        role=role,
        follow_target=follow_target,
        follow_dist=follow_dist,
        lock_map=lock_map,
        party_attack=party_attack,
        party_loot=party_loot,
        party_auto=party_auto,
        online=online,
        level=level,
        job=job,
        map=map_,
        hp_pct=hp_pct,
        party=party,
    )


def changes(old: TeamMember, new: TeamMember) -> dict[str, str]:
    """Calculate config differences between old and new TeamMember states."""
    ch: dict[str, str] = {}

    if new.role == FOLLOW and (old.role != FOLLOW or old.follow_target != new.follow_target):
        ch['follow'] = '1'
        ch['followTarget'] = new.follow_target
        ch['attackAuto'] = '0'
    elif new.role == SOLO and old.role == FOLLOW:
        ch['follow'] = '0'
        ch['attackAuto'] = '2'

    if new.follow_dist != old.follow_dist and new.follow_dist is not None:
        ch['followDistanceMax'] = str(new.follow_dist)

    if new.lock_map != old.lock_map:
        ch['lockMap'] = new.lock_map

    if new.party_attack != old.party_attack:
        ch['attackAuto_party'] = '1' if new.party_attack else '0'

    if new.party_loot != old.party_loot:
        ch['itemsTakeAuto_party'] = '1' if new.party_loot else '0'

    if new.party_auto != old.party_auto:
        ch['partyAuto'] = str(new.party_auto)

    return ch


def apply(kc: KConfig, ch: dict[str, str]) -> None:
    """Apply changes into KConfig lines."""
    for key, val in ch.items():
        kc.set(key, val)


def validate(members: list[TeamMember]) -> list[str]:
    """Validate team members settings and detect loops or invalid values."""
    errs: list[str] = []

    for m in members:
        if m.role == FOLLOW:
            if not m.follow_target:
                errs.append(f'{m.bot}: ต้องระบุตัวละครที่จะให้ตาม')
            elif m.char and m.follow_target == m.char:
                errs.append(f'{m.bot}: ไม่สามารถตั้งให้ตามตัวเองได้ ({m.char})')

        if m.follow_dist is not None and not (1 <= m.follow_dist <= 20):
            errs.append(f'{m.bot}: ระยะตามต้องอยู่ระหว่าง 1 ถึง 20 (ค่าปัจจุบัน {m.follow_dist})')

    # Detect follow loops
    graph: dict[str, str] = {}
    for m in members:
        if m.role == FOLLOW and m.char and m.follow_target and m.char != m.follow_target:
            graph[m.char] = m.follow_target

    loop_found = False
    for start_char in sorted(graph.keys()):
        if loop_found:
            break
        path: list[str] = []
        curr: str | None = start_char
        while curr and curr in graph:
            if curr in path:
                idx = path.index(curr)
                chain = path[idx:] + [curr]
                errs.append(f'ตามกันเป็นวงวน: {" → ".join(chain)}')
                loop_found = True
                break
            path.append(curr)
            curr = graph.get(curr)

    return errs


def warnings(members: list[TeamMember]) -> list[str]:
    """Produce warning messages for followers with mismatched map/party or external leaders."""
    warns: list[str] = []
    char_map: dict[str, TeamMember] = {m.char: m for m in members if m.char}

    for m in members:
        if m.role != FOLLOW or not m.follow_target:
            continue
        if m.follow_target not in char_map:
            warns.append(f'{m.bot} ตาม "{m.follow_target}" ซึ่งไม่ใช่บอทในทีม')
        else:
            leader = char_map[m.follow_target]
            if m.lock_map and leader.lock_map and m.lock_map != leader.lock_map:
                warns.append(f'{m.bot}: แผนที่ฟาร์ม {m.lock_map} ไม่ตรงกับหัวหน้า ({leader.lock_map})')
            if m.party and leader.party and m.party != leader.party:
                warns.append(f'{m.bot}: ปาร์ตี้ ({m.party}) ไม่ตรงกับหัวหน้า ({leader.party})')

    return warns
