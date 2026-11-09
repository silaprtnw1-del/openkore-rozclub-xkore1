"""Monster rules from the GUI -> OpenKore mon_control.txt + priority.txt.

The GUI owns one marked block in each file; everything outside it is left
alone. The block goes at the END of mon_control.txt because OpenKore keeps the
last line for a key, and at the TOP of priority.txt because upper entries
there have higher priority.

Value meanings (verified in OpenKore src/Misc.pm and src/AI/CoreLogic.pm):
  attack_auto  -1 never attack · 0 only fight back · 1 attack normally
  teleport_auto 1 teleport away as soon as it is seen
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from typing import Final

from .errlog import log

BEGIN: Final[str] = '# >>> ROZ Bot Control (GUI) - managed by the GUI, edit there >>>'
END: Final[str] = '# <<< ROZ Bot Control (GUI) <<<'
NL: Final[str] = '\r\n'

NORMAL: Final[str] = 'normal'   # ปกติ      - attack normally
ONLY: Final[str] = 'only'       # ตีเฉพาะ   - if any monster is ONLY, hunt only those
SKIP: Final[str] = 'skip'       # ไม่ตี     - walk past
FLEE: Final[str] = 'flee'       # เจอแล้วหนี - teleport on sight
MODES: Final[tuple[str, ...]] = (NORMAL, ONLY, SKIP, FLEE)

_RULE_RE = re.compile(r'^(\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+).*#\s*(\w+)\s*\|\s*(.*)$')


@dataclass
class MonRule:
    mob_id: int
    name: str     # display name (rozclub database)
    mode: str


@dataclass
class MonSettings:
    rules: dict[int, MonRule]
    counter: bool   # ตอบโต้มอนที่เข้ามาโจมตีแม้ไม่อยู่ในรายการ


def read_lines(path: str) -> list[str]:
    try:
        with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return []


def split_block(lines: list[str]) -> tuple[list[str], list[str]]:
    """(lines outside the GUI block, lines inside it)."""
    outside: list[str] = []
    inside: list[str] = []
    in_block = False
    for ln in lines:
        s = ln.strip()
        if s == BEGIN:
            in_block = True
            continue
        if s == END:
            in_block = False
            continue
        (inside if in_block else outside).append(ln)
    if in_block:
        log.warning('GUI block has no end marker; treating the rest of the file as the block')
    return outside, inside


def load(control_dir: str) -> MonSettings:
    """Read the GUI block back. Missing file / block -> empty rules, counter on."""
    _, inside = split_block(read_lines(os.path.join(control_dir, 'mon_control.txt')))
    rules: dict[int, MonRule] = {}
    counter = True
    for ln in inside:
        s = ln.strip()
        m = _RULE_RE.match(s)
        if m and m.group(5) in MODES:
            mid = int(m.group(1))
            rules[mid] = MonRule(mid, m.group(6).strip() or str(mid), m.group(5))
            continue
        if s.startswith('# saved ') and 'fight back when attacked:' in s:
            counter = s.rstrip().endswith('yes')
    return MonSettings(rules, counter)


def _mon_line(key: str, attack: int, teleport: int, comment: str) -> str:
    return f'{key} {attack} {teleport} 0 # {comment}'


def build_mon_block(ms: MonSettings, kore_names: dict[int, str]) -> list[str]:
    """Lines for mon_control.txt. `kore_names` = OpenKore's own names (it matches by name first)."""
    fallback = 0 if ms.counter else -1           # what "don't hunt" means for this profile
    any_only = any(r.mode == ONLY for r in ms.rules.values())
    # Unlisted monsters keep being hunted unless something is set to ONLY. Otherwise saving
    # this tab would quietly stop the bot attacking anything it meets outside the shown map.
    unlisted = fallback if any_only else 1
    out = [BEGIN, f'# saved {time.strftime("%Y-%m-%d %H:%M")} · fight back when attacked: {"yes" if ms.counter else "no"}',
           _mon_line('all', unlisted, 0, 'unlisted monsters')]
    for r in sorted(ms.rules.values(), key=lambda r: r.mob_id):
        if r.mode == FLEE:
            attack, tele = fallback, 1
        elif r.mode == SKIP or (r.mode == NORMAL and any_only):
            attack, tele = fallback, 0
        else:                                    # NORMAL, or ONLY
            attack, tele = 1, 0
        tag = f'{r.mode} | {r.name}'
        out.append(_mon_line(str(r.mob_id), attack, tele, tag))
        kname = kore_names.get(r.mob_id)
        if kname:                                # OpenKore looks names up before IDs
            out.append(_mon_line(kname.lower(), attack, tele, f'name of {r.mob_id}'))
    out.append(END)
    return out


def build_priority_block(ms: MonSettings) -> list[str]:
    only = sorted((r for r in ms.rules.values() if r.mode == ONLY), key=lambda r: r.mob_id)
    return [BEGIN] + [f'{r.mob_id} # {r.name}' for r in only] + [END]


def _prune_backups(path: str, keep: int = 15) -> None:
    folder, base = os.path.dirname(path), os.path.basename(path) + '.bak-'
    try:
        mine = sorted(f for f in os.listdir(folder) if f.startswith(base) and f.endswith('-gui'))
    except OSError as e:
        log.warning('cannot list backups in %s: %s', folder, e)
        return
    for f in mine[:-keep]:
        try:
            os.remove(os.path.join(folder, f))
        except OSError as e:
            log.warning('cannot remove old backup %s: %s', f, e)


def write_file(path: str, lines: list[str]) -> str | None:
    """Back up then replace. Returns the backup path (None if the file did not exist)."""
    backup = None
    if os.path.exists(path):
        backup = f'{path}.bak-{time.strftime("%Y%m%d-%H%M%S")}-gui'
        shutil.copy2(path, backup)
        _prune_backups(path)
    tmp = path + '.gui-tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(NL.join(lines) + NL)
    os.replace(tmp, path)
    return backup


def save(control_dir: str, ms: MonSettings, kore_names: dict[int, str]) -> None:
    """Write both files. Raises OSError; the caller reports it."""
    mon_path = os.path.join(control_dir, 'mon_control.txt')
    outside, _ = split_block(read_lines(mon_path))
    while outside and not outside[-1].strip():
        outside.pop()
    write_file(mon_path, outside + [''] + build_mon_block(ms, kore_names))

    pri_path = os.path.join(control_dir, 'priority.txt')
    p_outside, _ = split_block(read_lines(pri_path))
    write_file(pri_path, build_priority_block(ms) + p_outside)
