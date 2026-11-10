"""✖ บังคับปิด: one elevated taskkill for OpenKore and the bot's game (gui/rozgui/bot.py)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import support  # noqa: F401  (puts gui/ on sys.path)
from rozgui import bot as B


class ForceKillTest(unittest.TestCase):
    def _kill(self, status: dict[str, Any], game_pid: int) -> tuple[bool, list[str]]:
        calls: list[str] = []
        fake = SimpleNamespace(name='sim', status=status)
        with mock.patch.object(B.subprocess, 'Popen', lambda args, **k: calls.append(args[-1])):
            ok = B.Bot.force_kill(fake, game_pid)        # type: ignore[arg-type]
        return ok, calls

    def test_kills_openkore_and_game_together(self) -> None:
        ok, calls = self._kill({'pid': 1234}, 5678)
        self.assertTrue(ok)
        self.assertIn("-ArgumentList '/PID','1234','/PID','5678','/F'", calls[0])

    def test_openkore_only_without_game(self) -> None:
        ok, calls = self._kill({'pid': 1234}, 0)
        self.assertTrue(ok)
        self.assertIn("-ArgumentList '/PID','1234','/F'", calls[0])

    def test_nothing_to_kill(self) -> None:
        self.assertEqual(self._kill({}, 0), (False, []))

    def test_bad_pid_kills_nothing(self) -> None:
        with mock.patch.object(B, 'log'):
            self.assertEqual(self._kill({'pid': 'x'}, 5678), (False, []))


if __name__ == '__main__':
    unittest.main()
