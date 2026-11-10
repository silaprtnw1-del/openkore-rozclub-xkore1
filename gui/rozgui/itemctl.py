"""Sell / store choices from the GUI -> the GUI section of items_control.txt.

OpenKore (FileParsers.pm parseItemsControl, Misc.pm items_control) lowercases
every line, keeps the LAST line for a key, and looks an item up by name, then
by ID, then `all`. Columns: <keep> <storage> <sell>: keep that many in the
bag, store / sell the rest when the flag is 1.

The market scanner rewrites the rest of the file and re-appends this section
(rozclub_market_scanner.py _keep_gui_block), so the GUI section always comes
last and wins. Each item gets an ID line and name lines (OpenKore's and
rozclub's names), because a scanner name line would otherwise beat a GUI ID line.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Final

from .monctl import BEGIN, END, read_lines, split_block, write_file

LEAVE: Final[str] = 'leave'   # ไม่ยุ่ง   - no GUI line, the rest of the file decides
KEEP: Final[str] = 'keep'     # เก็บในตัว - never store or sell
STORE: Final[str] = 'store'   # ฝาก Kafra - store all but <keep>
SELL: Final[str] = 'sell'     # ขาย NPC   - sell all but <keep>
ACTIONS: Final[tuple[str, ...]] = (LEAVE, KEEP, STORE, SELL)
ACTION_TH: Final[dict[str, str]] = {LEAVE: 'ไม่ยุ่ง', KEEP: 'เก็บในตัว', STORE: 'ฝาก Kafra', SELL: 'ขาย NPC'}

_RULE_RE = re.compile(r'^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*#\s*(keep|store|sell)\s*\|\s*(.*)$')
_DEFAULT_RE = re.compile(r'^all\s+(\d+)\s+(\d+)\s+(\d+)\s*#\s*default\b')


@dataclass
class ItemRule:
    item_id: int
    name: str        # display name (rozclub database)
    action: str      # KEEP / STORE / SELL
    keep: int = 0    # how many stay in the bag (STORE / SELL)


@dataclass
class ItemCtl:
    rules: dict[int, ItemRule] = field(default_factory=dict)
    default: str = LEAVE      # unlisted items: LEAVE = the file's own `all` line decides


def columns(action: str, keep: int) -> tuple[int, int, int]:
    """(keep, storage, sell) for an action."""
    if action == STORE:
        return max(0, keep), 1, 0
    if action == SELL:
        return max(0, keep), 0, 1
    return 0, 0, 0                                   # KEEP: never store or sell


def describe(cols: tuple[int, int, int] | None) -> str:
    """Thai text for a (keep, storage, sell) triple, '' if there is none."""
    if cols is None:
        return ''
    keep, store, sell = cols
    rest = f' (เหลือ {keep})' if keep else ''
    if sell:
        return 'ขาย NPC' + rest
    if store:
        return 'ฝาก Kafra' + rest
    return 'เก็บในตัว'


def path_for(control_dir: str) -> str:
    return os.path.join(control_dir, 'items_control.txt')


def load(control_dir: str) -> ItemCtl:
    _, inside = split_block(read_lines(path_for(control_dir)))
    ic = ItemCtl()
    for ln in inside:
        s = ln.strip()
        m = _RULE_RE.match(s)
        if m:
            iid = int(m.group(1))
            ic.rules[iid] = ItemRule(iid, m.group(6).strip() or str(iid), m.group(5), int(m.group(2)))
            continue
        m = _DEFAULT_RE.match(s)
        if m:
            keep, store, sell = int(m.group(1)), int(m.group(2)), int(m.group(3))
            ic.default = SELL if sell else STORE if store else KEEP
    return ic


def _parse_line(line: str) -> tuple[str, tuple[int, int, int]] | None:
    """One items_control.txt line -> (lowercased key, (keep, storage, sell)), like parseItemsControl."""
    s = line.strip()
    if not s or s.startswith('#'):
        return None
    s = s.split('#', 1)[0].rstrip() if not s.startswith('"') else s
    m = re.match(r'^(\d+)\s+(.*)$', s)
    if m:
        key, args = m.group(1), m.group(2)
    else:
        q = re.match(r'^"([^"]*)"\s*(.*)$', s)
        if q:
            key, args = q.group(1), q.group(2).split('#', 1)[0]
        else:
            t = re.match(r'^(.*?)([\s\d]*)$', s)
            if not t:
                return None
            key, args = t.group(1), t.group(2)
    nums = [int(x) for x in args.split() if x.isdigit()]
    if not key.strip():
        return None
    nums += [0] * (3 - len(nums))
    return key.strip().lower(), (nums[0], nums[1], nums[2])


def file_values(control_dir: str) -> dict[str, tuple[int, int, int]]:
    """Effective values from the part of the file outside the GUI section (lowercased keys)."""
    outside, _ = split_block(read_lines(path_for(control_dir)))
    out: dict[str, tuple[int, int, int]] = {}
    for ln in outside:
        p = _parse_line(ln)
        if p:
            out[p[0]] = p[1]
    return out


def lookup(values: dict[str, tuple[int, int, int]], item_id: int, names: list[str]) -> tuple[int, int, int] | None:
    """What OpenKore would use: a name line, then the ID line, then `all`."""
    for n in names:
        v = values.get(n.strip().lower())
        if v is not None:
            return v
    return values.get(str(item_id)) or values.get('all')


def _name_key(name: str) -> str | None:
    """A name as an items_control.txt key, or None when OpenKore would misread it.
    parseItemsControl: a line starting with a digit is an ID line, '#' starts a comment,
    trailing digits are the columns (so such names must be quoted)."""
    n = name.strip()
    if not n or '#' in n or n[0].isdigit() or n[0] in '\'"`' or n.lower().startswith('unknown '):
        return None
    if n[-1].isdigit():
        return None if '"' in n else f'"{n}"'
    return n


def build_block(ic: ItemCtl, names_of: dict[int, list[str]]) -> list[str]:
    out = [BEGIN]
    if ic.default != LEAVE:
        k, st, se = columns(ic.default, 0)
        out.append(f'all {k} {st} {se} # default | {ic.default}')
    for iid, r in sorted(ic.rules.items()):
        if r.action not in (KEEP, STORE, SELL):
            continue
        k, st, se = columns(r.action, r.keep)
        out.append(f'{iid} {k} {st} {se} # {r.action} | {r.name}')
        keys = (_name_key(n) for n in names_of.get(iid, []))
        for key in dict.fromkeys(x for x in keys if x):
            if key.lower() == str(iid):
                continue
            out.append(f'{key} {k} {st} {se}')
    out.append(END)
    return out


def save(control_dir: str, ic: ItemCtl, names_of: dict[int, list[str]]) -> None:
    """Write the GUI section at the end of the profile's items_control.txt. Raises OSError."""
    path = path_for(control_dir)
    outside, _ = split_block(read_lines(path))
    while outside and not outside[-1].strip():
        outside.pop()
    write_file(path, outside + [''] + build_block(ic, names_of))
