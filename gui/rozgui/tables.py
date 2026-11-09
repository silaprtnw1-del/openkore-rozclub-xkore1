"""Map / item name lookups from OpenKore's tables (for nicer menus)."""
from __future__ import annotations

import os
import re

from .errlog import warn_once


def _read(path: str) -> list[str]:
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.readlines()
    except FileNotFoundError:
        return []   # not every server folder has every table
    except OSError as e:
        warn_once(f'table:{path}', 'cannot read table %s: %s', path, e)
        return []


class Tables:
    def __init__(self, openkore_root: str, profile_root: str) -> None:
        t = os.path.join(openkore_root, 'tables')
        self.maps: dict[str, str] = {}       # 'pay_dun00' -> 'Payon Cave'
        for folder in ('iRO', 'kRO', 'tRO'):
            for line in _read(os.path.join(t, folder, 'maps.txt')):
                m = re.match(r'^([\w@.-]+?)(?:\.rsw|\.gat)?#([^#]*)#', line.strip())
                if m and m.group(1) not in self.maps:
                    self.maps[m.group(1)] = m.group(2).strip()
        self.items: dict[int, str] = {}      # 501 -> 'Red Potion'
        for folder in ('tRO', 'iRO', 'kRO'):
            for line in _read(os.path.join(t, folder, 'items.txt')):
                m = re.match(r'^(\d+)#([^#]*)#', line.strip())
                if m and int(m.group(1)) not in self.items:
                    self.items[int(m.group(1))] = m.group(2).strip()
        self.item_ids: dict[str, int] = {}
        for i, n in self.items.items():
            self.item_ids.setdefault(n.lower(), i)
        # Status handle -> name ('EFST_INC_AGI' -> 'Increase Agility'), for buff conditions.
        self.statuses: dict[str, str] = {}
        for line in _read(os.path.join(t, 'statusnametable.txt')):
            m = re.match(r'^(EFST_\w+)\s+(.+?)\s*$', line)
            if m:
                self.statuses.setdefault(m.group(1), m.group(2))
        # OpenKore's own monster names: mon_control.txt is matched by name before ID.
        self.monsters: dict[int, str] = {}  # 1015 -> 'Zombie'
        for line in _read(os.path.join(t, 'monsters.txt')):
            m = re.match(r'^(\d+)\s+(.+?)\s*$', line)
            if m:
                self.monsters.setdefault(int(m.group(1)), m.group(2))

    def map_choices(self) -> list[str]:
        return [f'{k} — {v}' if v else k for k, v in sorted(self.maps.items())]

    def describe_items(self, spec: object) -> str:
        """'569,501, Blue Potion' -> 'Novice Potion, Red Potion, Blue Potion'."""
        out: list[str] = []
        for part in str(spec).split(','):
            p = part.strip()
            if not p:
                continue
            if p.isdigit():
                out.append(self.items.get(int(p), p))
            else:
                out.append(p)
        return ', '.join(out)
