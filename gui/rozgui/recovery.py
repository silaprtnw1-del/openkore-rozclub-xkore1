"""Auto login after start and re-login after a disconnect (one bot at a time)."""
from __future__ import annotations

import functools
import threading
import time
from typing import Final

from . import relogin
from .bot import Bot
from .errlog import log


# After "start bot": give up waiting for the game window this long past boot_delay.
STARTUP_LOGIN_GIVEUP_SECONDS: Final[float] = 120.0
USER_STOP_GRACE_SECONDS: Final[float] = 90.0   # after ⏹/✖ a drop to the login screen is not a disconnect


class RecoveryMixin:
    """Mixin of App: uses the state that App.__init__ sets up."""

    # ----------------------------------------------------------- auto login
    def reset_recovery(self, name: str) -> None:
        """Settings were saved: let the next offline episode start from scratch."""
        self._recovery_attempts.pop(name, None)
        self._recovery_stopped.discard(name)
        self._last_recovery.pop(name, None)
        self._warned_no_game.discard(name)
        self._login_episode.discard(name)

    def begin_login_test(self, name: str) -> None:
        self._login_testing.add(name)
        self._last_recovery[name] = time.time()

    def end_login_test(self, name: str) -> None:
        self._login_testing.discard(name)
        self._last_recovery[name] = time.time()

    def _cache_game_pid(self, b: Bot) -> None:
        """Remember the game pid while the client is bridged (needed after a drop)."""
        if b.name in self._pid_checked:
            return
        pid = b.cached_game_pid()
        if pid and relogin.has_window(pid):
            self._pid_checked.add(b.name)
            self._warned_no_game.discard(b.name)
            return
        if not b.running:             # OpenKore must be alive to discover a game pid
            return
        if time.time() < self._pid_retry.get(b.name, 0.0):
            return
        self._pid_retry[b.name] = time.time() + 10.0     # one PowerShell call at a time

        def work() -> None:
            found = b.discover_game_pid()
            self._call_soon(lambda: self._pid_cached(b.name, found))
        threading.Thread(target=work, daemon=True).start()

    def _pid_cached(self, name: str, pid: int) -> None:
        if pid:
            b = self.bot_by_name.get(name)
            if b is not None:
                b.remember_game_pid(pid)
            self._pid_checked.add(name)
            self._pid_retry.pop(name, None)
            self._warned_no_game.discard(name)
        else:
            self._pid_retry[name] = time.time() + 30.0

    def _maybe_recover(self, b: Bot) -> None:
        name = b.name
        if not b.running:
            self._was_online.discard(name)   # stopped/closed by the user: never log back in on its own
        if b.online:
            self._was_online.add(name)
            self._offline_since.pop(name, None)
            self._recovery_attempts.pop(name, None)
            self._recovery_stopped.discard(name)
            self._warned_no_game.discard(name)
            self._login_episode.discard(name)
            return
        if b.status is None:          # never seen this bot online: do not guess
            return
        if self._login_testing or name in self.pending_start:
            return
        s = relogin.load_settings(name)
        if not s.enabled or not s.has_credentials():
            return
        if self._recovery_active is not None:
            return
        if name in self._recovery_stopped or not relogin.is_admin():
            return
        since = self._offline_since.setdefault(name, time.time())
        if time.time() - since < s.offline_seconds:
            return
        if time.time() - self._last_recovery.get(name, 0.0) < s.cooldown_seconds:
            return
        if self._recovery_attempts.get(name, 0) >= s.retries:
            self._recovery_stopped.add(name)
            self.notifier.notify(
                f'⚠️ [{name}] ล็อกอินอัตโนมัติหยุดหลังลอง {s.retries} ครั้ง — '
                'ตรวจบัญชี/เกมแล้วกดบันทึกในแท็บล็อกอินอัตโนมัติเพื่อเริ่มใหม่')
            return
        if name in self._warned_no_game:
            return                  # already told the user; _cache_game_pid clears it
        pid = b.cached_game_pid()
        if not (pid and relogin.has_window(pid)):
            pid = b.discover_game_pid()
            if pid:
                b.remember_game_pid(pid)
        if not pid or not relogin.has_window(pid):
            if name not in self._warned_no_game:
                self._warned_no_game.add(name)
                self.add_feed(name, '⚠ ไม่พบหน้าต่างเกมของบอทนี้ — เปิดเกม/ล็อกอินด้วยมือก่อน', 'warn')
                self.notifier.notify(f'⚠️ [{name}] หลุดและไม่พบหน้าต่างเกม — เปิดเกม/ล็อกอินด้วยมือก่อน')
            return
        if not relogin.has_dialog(pid):
            # No Windows popup. Start when:
            # - state 3 (character select): only clicks/arrows/Enter are sent;
            # - an episode already started (retries at the login screen);
            # - the bot was in game and OpenKore (still running) has been back at the
            #   login state for offline_seconds: a disconnect. ROZCLUB draws its
            #   'connection lost' box inside the game, so no popup is ever found;
            #   LoginRunner closes that box (screen check) before typing anything.
            state = int((b.status or {}).get('state', 0))
            dropped = (name in self._was_online and b.running and state in (0, 1)
                       and time.time() - self._user_stop.get(name, 0.0) > USER_STOP_GRACE_SECONDS)
            if state != 3 and name not in self._login_episode and not dropped:
                return
            if dropped:
                self._login_episode.add(name)
        else:
            self._login_episode.add(name)
        self._start_recovery(b, s, pid)

    def _maybe_startup_login(self, b: Bot) -> None:
        """After "start bot": once the game window has had boot_delay seconds to reach its
        login screen, run the same login as recovery. Failures then retry through
        _maybe_recover (the episode is marked), up to the bot's retry limit."""
        name = b.name
        started = self._startup_login.get(name)
        if started is None:
            return
        state = int((b.status or {}).get('state', 0))
        if b.online or state >= 2 or state == -1 or not b.running:
            # Logged in by hand / already past the login screen, or OpenKore died: nothing to do.
            self._startup_login.pop(name, None)
            self._game_seen.pop(name, None)
            return
        if self._recovery_active is not None or self._login_testing:
            return                                      # one login at a time; try again next poll
        s = relogin.load_settings(name)
        if not (s.enabled and s.has_credentials()):
            self._startup_login.pop(name, None)
            return
        now = time.time()
        if now - started > s.boot_delay + STARTUP_LOGIN_GIVEUP_SECONDS:
            self._startup_login.pop(name, None)
            self._game_seen.pop(name, None)
            self.add_feed(name, '⚠ ไม่พบหน้าต่างเกมหลังเปิดบอท — ล็อกอินเองในเกม', 'warn')
            return
        pid = b.cached_game_pid()                       # written by roz.ps1 when it launched the game
        if not (pid and relogin.has_window(pid)):
            return                                      # _cache_game_pid looks it up in the background
        seen = self._game_seen.setdefault(name, now)
        if now - seen < s.boot_delay:
            return
        self._startup_login.pop(name, None)
        self._game_seen.pop(name, None)
        self.reset_recovery(name)                       # a fresh start gets the full retry budget
        self._login_episode.add(name)                   # lets _maybe_recover retry at the login screen
        self._start_recovery(b, s, pid, reason='เปิดบอท')

    def _start_recovery(self, b: Bot, s: relogin.LoginSettings, pid: int, reason: str = 'หลุด') -> None:
        name = b.name
        attempt = self._recovery_attempts.get(name, 0) + 1
        self._recovery_attempts[name] = attempt
        self._last_recovery[name] = time.time()
        self._recovery_active = name
        self.add_feed(name, f'🔐 {reason} — กำลังล็อกอินอัตโนมัติ (ครั้งที่ {attempt}/{s.retries})', 'info')

        def log_cb(msg: str) -> None:
            self._call_soon(functools.partial(self.add_feed, name, msg, 'muted'))

        runner = relogin.LoginRunner(
            name, pid, s, log_cb,
            lambda: int((b.status or {}).get('state', 0)),
            get_chars=b.account_chars)

        def work() -> None:
            try:
                ok = runner.run(lambda: b.online, lambda: False)
            except Exception:
                log.exception('%s: auto login crashed', name)
                ok = False
            self._call_soon(lambda: self._recovery_done(name, ok, runner.debug_dir))
        threading.Thread(target=work, daemon=True).start()

    def _recovery_done(self, name: str, ok: bool, debug_dir: str) -> None:
        self._recovery_active = None
        s = relogin.load_settings(name)
        if ok:
            self._offline_since.pop(name, None)
            self._recovery_attempts.pop(name, None)
            self._recovery_stopped.discard(name)
            self._warned_no_game.discard(name)
            self._login_episode.discard(name)
            self.add_feed(name, '✅ ล็อกอินอัตโนมัติสำเร็จ', 'ok')
            self.notifier.notify(f'✅ [{name}] ล็อกอินอัตโนมัติสำเร็จ')
            self.toast(f'{name}: ล็อกอินอัตโนมัติสำเร็จ', 'ok')
            return
        attempt = self._recovery_attempts.get(name, 0)
        if attempt >= s.retries:
            self._recovery_stopped.add(name)
        self.add_feed(name, f'❌ ล็อกอินอัตโนมัติไม่สำเร็จ (ครั้งที่ {attempt}/{s.retries}) — ดูภาพที่ {debug_dir}', 'bad')
        self.notifier.notify(f'❌ [{name}] ล็อกอินอัตโนมัติไม่สำเร็จ (ครั้งที่ {attempt}/{s.retries})')
        self.toast(f'{name}: ล็อกอินอัตโนมัติไม่สำเร็จ — ดูแท็บล็อกอินอัตโนมัติ', 'bad')