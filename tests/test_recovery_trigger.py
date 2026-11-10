"""When the GUI starts an auto login on its own (App._maybe_recover)."""
from __future__ import annotations

import time
import unittest
from typing import Any
from unittest import mock

import support  # noqa: F401  (puts gui/ on sys.path)
from rozgui import app as A
from rozgui import relogin as R


class _Settings:
    enabled = True
    offline_seconds = 0.0
    cooldown_seconds = 0.0
    retries = 3

    def has_credentials(self) -> bool:
        return True


class _Bot:
    def __init__(self) -> None:
        self.name = 'sim'
        self.online = True
        self.running = True
        self.status: dict[str, Any] = {'state': 5}

    def cached_game_pid(self) -> int:
        return 99

    def discover_game_pid(self) -> int:
        return 99


def _app() -> Any:
    a = object.__new__(A.App)             # no window: only the recovery bookkeeping
    for k in ('_offline_since', '_recovery_attempts', '_last_recovery', 'pending_start', '_user_stop'):
        setattr(a, k, {})
    for k in ('_recovery_stopped', '_warned_no_game', '_login_episode', '_was_online', '_login_testing'):
        setattr(a, k, set())
    a._recovery_active = None
    a.started = []

    def start(b: Any, s: Any, pid: int, reason: str = 'หลุด') -> None:
        a.started.append(b.name)
        a._recovery_active = b.name               # like the real _start_recovery: one at a time
    a._start_recovery = start
    a.add_feed = lambda *x, **k: None
    return a


class RecoveryTriggerTest(unittest.TestCase):
    def setUp(self) -> None:
        p = mock.patch.multiple(R, load_settings=lambda n: _Settings(), is_admin=lambda: True,
                                has_window=lambda pid: True, has_dialog=lambda pid: False)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, steps: list[tuple[bool, bool, int]], app: Any = None) -> Any:
        a, b = app or _app(), _Bot()
        for online, running, state in steps:
            b.online, b.running, b.status = online, running, {'state': state}
            A.App._maybe_recover(a, b)
        return a

    def test_disconnect_while_farming_starts_recovery(self) -> None:
        self.assertEqual(self._run([(True, True, 5), (False, True, 1), (False, True, 1)]).started, ['sim'])

    def test_never_in_game_does_not_start(self) -> None:
        self.assertEqual(self._run([(False, True, 1), (False, True, 1)]).started, [])

    def test_openkore_stopped_does_not_start(self) -> None:
        self.assertEqual(self._run([(True, True, 5), (False, False, 1), (False, False, 1)]).started, [])

    def test_map_change_does_not_start(self) -> None:
        self.assertEqual(self._run([(True, True, 5), (False, True, 4), (False, True, 4)]).started, [])

    def test_character_select_starts(self) -> None:
        self.assertEqual(self._run([(True, True, 5), (False, True, 3)]).started, ['sim'])

    def test_user_stop_is_not_a_disconnect(self) -> None:
        a = _app()
        self._run([(True, True, 5)], a)
        a._was_online.discard('sim')               # what stop_selected / kill_selected do
        a._user_stop['sim'] = time.time()
        self._run([(True, True, 5), (False, True, 1), (False, True, 1)], a)   # OpenKore still exiting
        self.assertEqual(a.started, [])


if __name__ == '__main__':
    unittest.main()
