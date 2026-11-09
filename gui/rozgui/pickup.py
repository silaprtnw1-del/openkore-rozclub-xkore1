"""Pickup choices from the GUI -> the GUI section of pickupitems.txt.

OpenKore (FileParsers.pm parseDataFile_lc, Misc.pm pickupitems) lowercases
keys, keeps the LAST line for a key, and looks an item up by name before ID,
then falls back to `all`. Values: 0 = leave it, 1 = pick up, 2 = pick up first.

The market scanner owns the rest of the file and copies this section to the
end on every rescan (rozclub_market_scanner.py _keep_gui_block), so here:
  except -> unchecked items 0, nothing else (market priorities / `all 1` stay)
  only   -> `all 0`, unchecked 0, checked 1 unless the market already picks them
  none   -> handled in config.txt (itemsTakeAuto / itemsGatherAuto 0)
Each item gets an ID line and name lines (OpenKore's and rozclub's names),
because a market name line would otherwise beat a GUI ID line.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Final

from .monctl import BEGIN, END, read_lines, split_block, write_file

EXCEPT: Final[str] = 'except'
ONLY: Final[str] = 'only'
NONE: Final[str] = 'none'
MODES: Final[tuple[str, ...]] = (EXCEPT, ONLY, NONE)

_MODE_RE = re.compile(r'^#\s*mode:\s*(\w+)')
_ITEM_RE = re.compile(r'^(\d+)\s+(-?\d+)\s*#\s*(skip|pick)\s*\|\s*(.*)$')


@dataclass
class PickupSettings:
    mode: str = EXCEPT
    skip: dict[int, str] = field(default_factory=dict)   # id -> display name (unchecked)
    pick: dict[int, str] = field(default_factory=dict)   # id -> display name (checked, ONLY mode)


def path_for(control_dir: str) -> str:
    return os.path.join(control_dir, 'pickupitems.txt')


def load(control_dir: str) -> PickupSettings:
    _, inside = split_block(read_lines(path_for(control_dir)))
    ps = PickupSettings()
    for ln in inside:
        s = ln.strip()
        m = _MODE_RE.match(s)
        if m and m.group(1) in MODES:
            ps.mode = m.group(1)
            continue
        m = _ITEM_RE.match(s)
        if m:
            (ps.skip if m.group(3) == 'skip' else ps.pick)[int(m.group(1))] = m.group(4).strip()
    return ps


def market_values(control_dir: str) -> dict[str, str]:
    """Effective values from the part of the file outside the GUI section (lowercased keys)."""
    outside, _ = split_block(read_lines(path_for(control_dir)))
    out: dict[str, str] = {}
    for ln in outside:
        s = ln.split('#', 1)[0].rstrip()
        if not s or s.startswith('#') or ' ' not in s:
            continue
        k, v = s.rsplit(' ', 1)
        out[k.strip().lower()] = v.strip()
    return out


def build_block(ps: PickupSettings, names_of: dict[int, list[str]], market: dict[str, str]) -> list[str]:
    out = [BEGIN, f'# mode: {ps.mode}']
    if ps.mode == ONLY:
        out.append('all 0')

    def lines_for(item_id: int, value: int, tag: str, label: str) -> None:
        out.append(f'{item_id} {value} # {tag} | {label}')
        lowered = (x.strip().lower() for x in names_of.get(item_id, []))
        for n in dict.fromkeys(x for x in lowered if x and not x.startswith('unknown #')):
            out.append(f'{n} {value}')

    for item_id, label in sorted(ps.skip.items()):
        lines_for(item_id, 0, 'skip', label)
    if ps.mode == ONLY:
        for item_id, label in sorted(ps.pick.items()):
            keys = [str(item_id)] + [x.lower() for x in names_of.get(item_id, [])]
            if any(market.get(k, '0') not in ('', '0', '-1') for k in keys):
                continue                     # the market already picks it (keeps its priority)
            lines_for(item_id, 1, 'pick', label)
    out.append(END)
    return out


def save(control_dir: str, ps: PickupSettings, names_of: dict[int, list[str]], fallback_path: str) -> None:
    """Write the GUI section at the end of the profile's pickupitems.txt. Raises OSError.

    A profile without its own file reads OpenKore's shared one; copy that first
    so creating the profile file does not silently drop those rules.
    """
    path = path_for(control_dir)
    if not os.path.exists(path) and os.path.exists(fallback_path):
        shutil.copy2(fallback_path, path)
    outside, _ = split_block(read_lines(path))
    while outside and not outside[-1].strip():
        outside.pop()
    write_file(path, outside + [''] + build_block(ps, names_of, market_values(control_dir)))
