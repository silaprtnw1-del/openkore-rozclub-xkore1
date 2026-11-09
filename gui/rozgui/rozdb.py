"""ROZCLUB game database (https://rozclub.com/database/): map spawns and monsters.

The site serves plain JSON wrapped as `RZ.put("<name>", <json>);`. Files are
cached under gui/cache/ and refreshed once a day; when the site cannot be
reached the cached copy is used, so the GUI keeps working offline.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Final

from .errlog import log
from .notify import UA, SSL_CTX

BASE_URL: Final[str] = 'https://rozclub.com/database/data/'
CACHE_DIR: Final[str] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache')
MAX_AGE: Final[float] = 24 * 3600
TIMEOUT: Final[float] = 20


@dataclass(frozen=True)
class Spawn:
    mob_id: int
    count: int
    respawn_ms: int


@dataclass(frozen=True)
class MapInfo:
    name: str          # pay_dun00
    title: str         # Payon Cave F1
    kind: str          # field / dungeon / town
    spawns: tuple[Spawn, ...]


@dataclass(frozen=True)
class Mob:
    mob_id: int
    name: str
    level: int
    hp: int
    element: str
    race: str
    size: str
    boss: bool
    mvp: bool
    drops: tuple[tuple[int, int], ...] = ()     # (item id, rate per 10000)


def _unwrap(raw: str, name: str) -> Any:
    """'RZ.put("maps",[...]);' -> parsed JSON."""
    prefix = f'RZ.put("{name}",'
    text = raw.strip()
    if not text.startswith(prefix):
        raise ValueError(f'{name}.js: unexpected format (starts with {text[:30]!r})')
    text = text[len(prefix):].rstrip().rstrip(';').rstrip()
    if not text.endswith(')'):
        raise ValueError(f'{name}.js: missing closing parenthesis')
    return json.loads(text[:-1])


def _cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, f'{name}.js')


def _load(name: str, force: bool = False) -> tuple[Any, str]:
    """(parsed data, source) where source is 'web', 'cache' or 'cache (offline)'."""
    path = _cache_path(name)
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE
    if not force and fresh:
        with open(path, 'r', encoding='utf-8') as f:
            return _unwrap(f.read(), name), 'cache'
    try:
        req = urllib.request.Request(BASE_URL + f'{name}.js', headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as r:
            raw = r.read().decode('utf-8')
        data = _unwrap(raw, name)           # validate before replacing the cache
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(raw)
        os.replace(tmp, path)
        return data, 'web'
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError, ValueError, UnicodeDecodeError) as e:
        if os.path.exists(path):
            log.warning('rozclub %s.js download failed (%s); using cached copy', name, e)
            with open(path, 'r', encoding='utf-8') as f:
                return _unwrap(f.read(), name), 'cache (offline)'
        raise


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class RozDB:
    """Parsed maps + monsters. Construct with load(); never raises on bad rows."""

    def __init__(self) -> None:
        self.maps: dict[str, MapInfo] = {}
        self.mobs: dict[int, Mob] = {}
        self.items: dict[int, tuple[str, str]] = {}    # 11615 -> ('Sweet Potato', 'usable')
        self.source = 'none'
        self.error = ''

    @classmethod
    def load(cls, force: bool = False) -> RozDB:
        db = cls()
        try:
            maps_raw, src_maps = _load('maps', force)
            mobs_raw, src_mobs = _load('mobs', force)
        except Exception as e:      # no network and no cache: GUI shows the reason, keeps running
            log.warning('rozclub database unavailable: %s', e)
            db.error = str(e)
            return db
        db.source = src_maps if src_maps == src_mobs else f'{src_maps}/{src_mobs}'
        db._parse_maps(maps_raw)
        db._parse_mobs(mobs_raw)
        try:                                   # item names are a nice-to-have: never fail the load
            items_raw, _ = _load('items-index', force)
            db._parse_items(items_raw)
        except Exception as e:
            log.warning('rozclub items-index unavailable: %s', e)
        return db

    def _parse_items(self, rows: Any) -> None:
        if not isinstance(rows, list):
            log.warning('items-index.js: expected a list, got %s', type(rows).__name__)
            return
        for r in rows:
            # [id, name, kind, ...]
            if isinstance(r, list) and len(r) >= 3 and isinstance(r[1], str):
                self.items[_int(r[0])] = (r[1], str(r[2]))

    def _parse_maps(self, rows: Any) -> None:
        if not isinstance(rows, list):
            log.warning('maps.js: expected a list, got %s', type(rows).__name__)
            return
        bad = 0
        for row in rows:
            # [name, title, kind, [[sub, ...]], [[mob_id, count, respawn_ms], ...]]
            if not (isinstance(row, list) and len(row) >= 5 and isinstance(row[0], str) and isinstance(row[4], list)):
                bad += 1
                continue
            spawns = tuple(Spawn(_int(s[0]), _int(s[1]), _int(s[2])) for s in row[4]
                           if isinstance(s, list) and len(s) >= 3)
            self.maps[row[0]] = MapInfo(row[0], str(row[1]), str(row[2]), spawns)
        if bad:
            log.warning('maps.js: skipped %d malformed rows', bad)

    def _parse_mobs(self, rows: Any) -> None:
        if not isinstance(rows, list):
            log.warning('mobs.js: expected a list, got %s', type(rows).__name__)
            return
        for r in rows:
            if not isinstance(r, dict) or 'id' not in r:
                continue
            mid = _int(r.get('id'))
            # dr: [[item_id, rate_per_10000(, 1 = card slot)], ...]
            drops = tuple((_int(d[0]), _int(d[1])) for d in (r.get('dr') or [])
                          if isinstance(d, list) and len(d) >= 2)
            self.mobs[mid] = Mob(mid, str(r.get('n') or mid), _int(r.get('lv')), _int(r.get('hp')),
                                 str(r.get('el') or ''), str(r.get('rc') or ''), str(r.get('sz') or ''),
                                 bool(r.get('boss')), bool(r.get('mvp')), drops)

    def mob_name(self, mob_id: int) -> str:
        m = self.mobs.get(mob_id)
        return m.name if m else str(mob_id)

    def map_drops(self, map_name: str) -> list[tuple[int, int, list[str]]]:
        """Items dropped on a map: (item id, best rate per 10000, monster names), best rate first."""
        best: dict[int, int] = {}
        by: dict[int, list[str]] = {}
        for mob, _ in self.map_spawns(map_name):
            if mob is None:
                continue
            for item_id, rate in mob.drops:
                if item_id <= 0:
                    continue
                best[item_id] = max(best.get(item_id, 0), rate)
                if mob.name not in by.setdefault(item_id, []):
                    by[item_id].append(mob.name)
        return sorted(((i, best[i], by[i]) for i in best), key=lambda t: -t[1])

    def map_spawns(self, map_name: str) -> list[tuple[Mob | None, Spawn]]:
        """Spawns of a map, merged per monster (a map can list one monster twice), most numerous first."""
        info = self.maps.get(map_name)
        if info is None:
            return []
        merged: dict[int, Spawn] = {}
        for s in info.spawns:
            prev = merged.get(s.mob_id)
            merged[s.mob_id] = Spawn(s.mob_id, s.count + (prev.count if prev else 0),
                                     min(s.respawn_ms, prev.respawn_ms) if prev else s.respawn_ms)
        out = [(self.mobs.get(s.mob_id), s) for s in merged.values()]
        out.sort(key=lambda t: -t[1].count)
        return out
