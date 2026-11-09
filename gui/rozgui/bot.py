"""One bot instance: its files, status, events, log and commands."""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Final

from .errlog import log, warn_once

CREATE_NO_WINDOW: Final[int] = 0x08000000
STALE_AFTER: Final[int] = 20   # seconds without a status.json update = not responding

Status = dict[str, Any]                # parsed status.json / events.jsonl line
LogEntry = tuple[float, str, str, str]  # (epoch, type, domain, text)


def load_registry(root: str) -> dict[str, Any]:
    with open(os.path.join(root, 'instances.json'), 'r', encoding='utf-8-sig') as f:
        return json.load(f)


class FileTail:
    """Reads lines appended to a file since the last call."""

    def __init__(self, path: str, from_start: bool = False) -> None:
        self.path = path
        self.pos: int | None = None if not from_start else 0
        self.buf = b''

    def read(self) -> list[str]:
        try:
            size = os.path.getsize(self.path)
        except FileNotFoundError:
            if self.pos is None:        # file not created yet: read it from the start later
                self.pos = 0
            return []
        except OSError as e:
            warn_once(f'stat:{self.path}', 'cannot stat %s: %s', self.path, e)
            return []
        if self.pos is None:            # first call: skip what is already there
            self.pos = size
            return []
        if size < self.pos:             # rotated / truncated
            self.pos = 0
            self.buf = b''
        if size == self.pos:
            return []
        try:
            with open(self.path, 'rb') as f:
                f.seek(self.pos)
                data = f.read(size - self.pos)
        except OSError as e:            # e.g. locked by OneDrive / antivirus: retry next poll
            warn_once(f'read:{self.path}', 'cannot read %s: %s', self.path, e)
            return []
        self.pos += len(data)
        data = self.buf + data
        parts = data.split(b'\n')
        self.buf = parts.pop()          # incomplete last line
        return [p.decode('utf-8', errors='replace').rstrip('\r') for p in parts if p.strip()]

    def read_last(self, max_bytes: int = 200_000) -> list[str]:
        """Last part of the file (for filling the log view once)."""
        try:
            size = os.path.getsize(self.path)
            with open(self.path, 'rb') as f:
                f.seek(max(0, size - max_bytes))
                data = f.read()
        except FileNotFoundError:
            return []
        except OSError as e:
            warn_once(f'readlast:{self.path}', 'cannot read %s: %s', self.path, e)
            return []
        lines = data.split(b'\n')
        if size > max_bytes:
            lines = lines[1:]
        return [p.decode('utf-8', errors='replace').rstrip('\r') for p in lines if p.strip()]


class SessionStats:
    """EXP/zeny gained since the GUI started watching this bot."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.start: float | None = None
        self.base_gain: int = 0
        self.job_gain: int = 0
        self.zeny_start: int | None = None
        self.prev: Status | None = None

    def update(self, s: Status) -> None:
        if not s.get('online') or not s.get('exp_max'):
            return
        now = time.time()
        if self.start is None:
            self.start = now
            self.zeny_start = s.get('zeny', 0)
        p = self.prev
        if p and p.get('char') == s.get('char'):
            self.base_gain += self._delta(p, s, 'exp', 'exp_max', 'level')
            self.job_gain += self._delta(p, s, 'exp_job', 'exp_job_max', 'level_job')
        elif p:
            self.reset()
            self.start = now
            self.zeny_start = s.get('zeny', 0)
        self.prev = dict(s)

    @staticmethod
    def _delta(p: Status, s: Status, k: str, kmax: str, klv: str) -> int:
        if s.get(klv, 0) > p.get(klv, 0):
            return max(0, p.get(kmax, 0) - p.get(k, 0)) + s.get(k, 0)
        d = s.get(k, 0) - p.get(k, 0)
        return d if d > 0 else 0

    def hours(self) -> float:
        return (time.time() - self.start) / 3600 if self.start else 0

    def per_hour(self, value: float) -> float:
        h = self.hours()
        return value / h if h > 0.01 else 0

    def zeny_gain(self) -> int:
        if self.prev is None or self.zeny_start is None:
            return 0
        return self.prev.get('zeny', 0) - self.zeny_start


class Bot:
    def __init__(self, root: str, inst: dict[str, Any]) -> None:
        self.root = root
        self.name = inst['name']
        self.port = int(inst.get('port', 0))
        self.role = inst.get('role', '')
        self.follow = inst.get('follow', '')
        self.profile = os.path.normpath(os.path.join(root, inst.get('profile') or ('instances\\' + self.name)))
        self.logs = os.path.join(self.profile, 'logs')
        self.control = os.path.join(self.profile, 'control')
        self.config_path = os.path.join(self.control, 'config.txt')
        self.status: Status | None = None
        self.status_age: float | None = None
        self.events = FileTail(os.path.join(self.logs, 'events.jsonl'))
        self.log = FileTail(os.path.join(self.logs, 'gui_log.txt'))
        self.stats = SessionStats()

    # ------------------------------------------------------------- reading
    def poll_status(self) -> Status | None:
        path = os.path.join(self.logs, 'status.json')
        try:
            mtime = os.path.getmtime(path)
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f'expected a JSON object, got {type(data).__name__}')
        except (OSError, ValueError) as e:
            # Missing or caught mid-write: keep the last good one, age it.
            if not isinstance(e, FileNotFoundError):
                warn_once(f'status:{path}:{type(e).__name__}', 'status.json unreadable (%s): %s', path, e)
            if self.status is not None:
                self.status_age = time.time() - self.status.get('_mtime', 0)
            return self.status
        data['_mtime'] = mtime
        self.status = data
        self.status_age = time.time() - mtime
        if self.running:
            self.stats.update(data)
        return data

    @property
    def running(self) -> bool:
        """OpenKore is alive and the plugin is writing status."""
        return self.status is not None and self.status_age is not None and self.status_age < STALE_AFTER

    @property
    def online(self) -> bool:
        return self.running and self.status is not None and bool(self.status.get('online'))

    def state_text(self) -> tuple[str, str]:
        s = self.status
        if not self.running or s is None:
            return 'ปิดอยู่', 'off'
        if not s.get('online'):
            return 'ยังไม่เข้าเกม', 'warn'
        if s.get('dead'):
            return 'ตาย', 'bad'
        ai = s.get('ai')
        if ai == 'auto':
            return 'กำลังทำงาน', 'ok'
        if ai == 'manual':
            return 'หยุดชั่วคราว (manual)', 'warn'
        return 'AI ปิด', 'warn'

    def read_char(self) -> Status | None:
        """Learned skills + inventory written by the plugin (logs/char.json), or None."""
        path = os.path.join(self.logs, 'char.json')
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            warn_once(f'char:{path}:{type(e).__name__}', 'char.json unreadable (%s): %s', path, e)
            return None
        return data if isinstance(data, dict) else None

    def poll_events(self) -> list[Status]:
        out: list[Status] = []
        for line in self.events.read():
            try:
                ev = json.loads(line)
            except ValueError as e:
                log.warning('%s: bad event line skipped (%s): %.200s', self.name, e, line)
                continue
            if isinstance(ev, dict):
                out.append(ev)
            else:
                log.warning('%s: non-object event skipped: %.200s', self.name, line)
        return out

    def poll_log(self) -> list[LogEntry]:
        return [self._parse_log(l) for l in self.log.read()]

    def log_history(self) -> list[LogEntry]:
        return [self._parse_log(l) for l in self.log.read_last()]

    @staticmethod
    def _parse_log(line: str) -> LogEntry:
        parts = line.split('\t', 3)
        if len(parts) < 4:
            return (time.time(), 'message', '', line)
        try:
            ts = float(parts[0])
        except ValueError:
            ts = time.time()
        return (ts, parts[1], parts[2], parts[3])

    # ------------------------------------------------------------- control
    def send(self, *commands: str) -> bool:
        """Queue console commands for the plugin. Retries briefly while the plugin holds the file."""
        path = os.path.join(self.logs, 'cmd_input.txt')
        last_err: OSError | None = None
        for _ in range(10):
            try:
                os.makedirs(self.logs, exist_ok=True)
                with open(path, 'a', encoding='utf-8') as f:
                    for c in commands:
                        f.write(c.strip() + '\n')
                return True
            except OSError as e:
                last_err = e
                time.sleep(0.05)
        log.error('%s: could not write %s after 10 tries: %s', self.name, path, last_err)
        return False

    def start(self, console_style: str = 'Minimized') -> bool:
        return launch_roz_start(self.root, [self.name], console_style)

    def force_kill(self) -> bool:
        """Kill OpenKore (needs Administrator: the bot runs elevated)."""
        pid = (self.status or {}).get('pid')
        try:
            pid_num = int(pid) if pid else 0
        except (TypeError, ValueError):
            log.error('%s: invalid pid in status.json: %r', self.name, pid)
            return False
        if pid_num <= 0:
            return False
        cmd = ("Start-Process -FilePath taskkill.exe -ArgumentList '/PID','%d','/F' "
               "-Verb RunAs -WindowStyle Hidden" % pid_num)
        try:
            subprocess.Popen(['powershell.exe', '-NoProfile', '-Command', cmd], creationflags=CREATE_NO_WINDOW)
        except OSError:
            log.exception('%s: could not launch taskkill for pid %d', self.name, pid_num)
            return False
        return True


def launch_roz_start(root: str, names: list[str], console_style: str) -> bool:
    """Run `roz.ps1 start <names...>` hidden; it raises its own UAC prompt. False if it could not launch."""
    if console_style not in ('Normal', 'Minimized', 'Hidden'):
        log.error('invalid console style %r, using Minimized', console_style)
        console_style = 'Minimized'
    ps1 = os.path.join(root, 'multi', 'roz.ps1')
    if not os.path.isfile(ps1):
        log.error('roz.ps1 not found: %s', ps1)
        return False
    try:
        subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps1, 'start',
             *names, '-ConsoleStyle', console_style, '-Quiet'],
            cwd=root, creationflags=CREATE_NO_WINDOW)
    except OSError:
        log.exception('could not launch roz.ps1 start %s', ' '.join(names))
        return False
    return True
