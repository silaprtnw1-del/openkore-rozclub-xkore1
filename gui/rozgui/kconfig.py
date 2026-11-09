"""Read/modify/write an OpenKore config.txt without disturbing the rest of it.

Comments, blank lines, ordering and each line's own line ending are kept.
Only the lines that are actually changed get rewritten.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from typing import Final

from .errlog import log

_BLOCK_RE = re.compile(r'^(\S+)(?:\s+(.*?))?\s*\{\s*$')
_LINE_RE = re.compile(r'^(\S+)(?:\s+(.*?))?\s*$')
NEWLINE: Final[str] = '\r\n'
GUI_BACKUPS_KEPT: Final[int] = 15


class Block:
    def __init__(self, key: str, value: str, start: int, end: int) -> None:
        self.key = key          # e.g. useSelf_item
        self.value = value      # e.g. "501,502"
        self.start = start      # line index of "key value {"
        self.end = end          # line index of "}"

    def __repr__(self) -> str:
        return f'Block({self.key} {self.value!r} @{self.start}-{self.end})'


class KConfig:
    def __init__(self, path: str) -> None:
        self.path = path
        self.dirty = False
        self.load()

    # ---------------------------------------------------------------- loading
    def load(self) -> None:
        with open(self.path, 'rb') as f:
            data = f.read()
        if data.startswith(b'\xef\xbb\xbf'):
            data = data[3:]
        text = data.decode('utf-8', errors='surrogateescape')
        self.lines: list[str] = text.splitlines(keepends=True)
        self.mtime = os.path.getmtime(self.path)
        self.dirty = False
        self._index()

    def changed_on_disk(self) -> bool:
        try:
            return os.path.getmtime(self.path) != self.mtime
        except OSError as e:
            # Deleted / locked: report "changed" so save() asks before writing.
            log.warning('cannot stat %s: %s', self.path, e)
            return True

    def _index(self) -> None:
        self.simple: dict[str, list[int]] = {}   # key -> [line index, ...] (top level only)
        self.blocks: list[Block] = []
        i, n = 0, len(self.lines)
        while i < n:
            s = self.lines[i].strip()
            if not s or s.startswith('#'):
                i += 1
                continue
            m = _BLOCK_RE.match(s)
            if m:
                j = i + 1
                while j < n and self.lines[j].strip() != '}':
                    j += 1
                self.blocks.append(Block(m.group(1), m.group(2) or '', i, j))
                i = j + 1
                continue
            m = _LINE_RE.match(s)
            if m:
                self.simple.setdefault(m.group(1), []).append(i)
            i += 1

    # ------------------------------------------------------------ simple keys
    def keys(self) -> list[str]:
        return list(self.simple.keys())

    def has(self, key: str) -> bool:
        return key in self.simple

    def get(self, key: str, default: str = '') -> str:
        idx = self.simple.get(key)
        if not idx:
            return default
        m = _LINE_RE.match(self.lines[idx[-1]].strip())
        return (m.group(2) or '') if m else default

    @staticmethod
    def _eol(line: str) -> str:
        if line.endswith('\r\n'):
            return '\r\n'
        if line.endswith('\n'):
            return '\n'
        return NEWLINE

    def set(self, key: str, value: object) -> None:
        value = '' if value is None else str(value).strip()
        if key in self.simple:
            i = self.simple[key][-1]
            old = self.lines[i]
            indent = old[:len(old) - len(old.lstrip())]
            new = f'{indent}{key} {value}'.rstrip() + self._eol(old)
            if new != old:
                self.lines[i] = new
                self.dirty = True
        else:
            self._ensure_trailing_newline()
            self.lines.append(f'{key} {value}'.rstrip() + NEWLINE)
            self.dirty = True
            self._index()

    def _ensure_trailing_newline(self) -> None:
        if self.lines and not self.lines[-1].endswith('\n'):
            self.lines[-1] += NEWLINE

    # ----------------------------------------------------------------- blocks
    def block_items(self, b: Block) -> list[tuple[str, str]]:
        """[(key, value), ...] inside a block, comments skipped."""
        out: list[tuple[str, str]] = []
        for line in self.lines[b.start + 1:b.end]:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            m = _LINE_RE.match(s)
            if m:
                out.append((m.group(1), m.group(2) or ''))
        return out

    def block_text(self, b: Block) -> str:
        """Inner lines as plain text (one 'key value' per line)."""
        return '\n'.join(line.strip() for line in self.lines[b.start + 1:b.end] if line.strip())

    def block_disabled(self, b: Block) -> bool:
        for k, v in self.block_items(b):
            if k == 'disabled':
                return v.strip() not in ('', '0')
        return False

    def _render_block(self, key: str, value: str, inner_text: str, eol: str = NEWLINE) -> list[str]:
        head = f'{key} {value}'.strip() + ' {'
        body = [f'\t{ln.strip()}' for ln in inner_text.splitlines() if ln.strip()]
        return [head + eol] + [ln + eol for ln in body] + ['}' + eol]

    def replace_block(self, b: Block, value: str, inner_text: str) -> None:
        eol = self._eol(self.lines[b.start])
        new = self._render_block(b.key, value, inner_text, eol)
        end = min(b.end, len(self.lines) - 1)
        self.lines[b.start:end + 1] = new
        self.dirty = True
        self._index()

    def add_block(self, key: str, value: str, inner_text: str) -> None:
        self._ensure_trailing_newline()
        self.lines.append(NEWLINE)
        self.lines.extend(self._render_block(key, value, inner_text))
        self.dirty = True
        self._index()

    def trim_trailing_blank(self) -> None:
        """Drop blank lines at the end of the file (left behind after deleting trailing blocks)."""
        n = len(self.lines)
        while self.lines and not self.lines[-1].strip():
            self.lines.pop()
        if len(self.lines) != n:
            self.dirty = True
            self._index()

    def delete_block(self, b: Block) -> None:
        end = min(b.end, len(self.lines) - 1)
        del self.lines[b.start:end + 1]
        self.dirty = True
        self._index()

    def set_block_disabled(self, b: Block, disabled: bool) -> None:
        items = self.block_text(b).splitlines()
        flag = '1' if disabled else '0'
        found = False
        for i, ln in enumerate(items):
            if ln.split(None, 1)[0] == 'disabled':
                items[i] = f'disabled {flag}'
                found = True
        if not found:
            items.append(f'disabled {flag}')
        self.replace_block(b, b.value, '\n'.join(items))

    def find_block(self, key: str, value: str, ordinal: int = 0) -> Block | None:
        """Re-locate a block after the index changed."""
        hits = [b for b in self.blocks if b.key == key and b.value == value]
        return hits[ordinal] if ordinal < len(hits) else None

    # ----------------------------------------------------------------- saving
    def save(self) -> str:
        """Write the file, keeping a timestamped backup next to it."""
        stamp = time.strftime('%Y%m%d-%H%M%S')
        backup = f'{self.path}.bak-{stamp}-gui'
        shutil.copy2(self.path, backup)
        self._prune_backups()
        data = ''.join(self.lines).encode('utf-8', errors='surrogateescape')
        tmp = self.path + '.gui-tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, self.path)
        self.mtime = os.path.getmtime(self.path)
        self.dirty = False
        return backup

    def _prune_backups(self) -> None:
        folder = os.path.dirname(self.path)
        base = os.path.basename(self.path) + '.bak-'
        try:
            mine = sorted(f for f in os.listdir(folder) if f.startswith(base) and f.endswith('-gui'))
        except OSError as e:
            log.warning('cannot list backups in %s: %s', folder, e)
            return
        for f in mine[:-GUI_BACKUPS_KEPT]:
            try:
                os.remove(os.path.join(folder, f))
            except OSError as e:    # an old backup that stays behind is harmless; note it
                log.warning('cannot remove old backup %s: %s', f, e)
