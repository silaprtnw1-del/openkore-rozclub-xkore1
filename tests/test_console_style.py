"""OpenKore console windows are hidden by default (gui/rozgui/app.py, bot.py)."""
from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

import support
from rozgui import app as A
from rozgui import bot as B


class ConsoleDefaultTest(unittest.TestCase):
    def test_old_settings_switch_to_hidden_once(self) -> None:
        s: dict[str, Any] = {'console_style': 'Minimized'}          # what older versions saved
        self.assertTrue(A.apply_console_default(s))
        self.assertEqual(s['console_style'], 'Hidden')
        self.assertFalse(A.apply_console_default(s), 'only once')

    def test_choice_made_after_the_switch_is_kept(self) -> None:
        s: dict[str, Any] = {'console_style': 'Normal', 'console_style_rev': A.CONSOLE_STYLE_REV}
        self.assertFalse(A.apply_console_default(s))
        self.assertEqual(s['console_style'], 'Normal')

    def test_bad_revision_value(self) -> None:
        s: dict[str, Any] = {'console_style': 'Normal', 'console_style_rev': 'x'}
        self.assertTrue(A.apply_console_default(s))
        self.assertEqual(s['console_style'], 'Hidden')


class LaunchTest(unittest.TestCase):
    def _launch(self, style: str) -> list[str]:
        calls: list[list[str]] = []
        with mock.patch.object(B.subprocess, 'Popen', lambda args, **k: calls.append(list(args))), \
                mock.patch.object(B, 'log'):
            self.assertTrue(B.launch_roz_start(support.REPO_ROOT, ['potato7'], style))
        return calls[0]

    def test_style_is_passed_to_roz_ps1(self) -> None:
        args = self._launch('Hidden')
        self.assertEqual(args[args.index('-ConsoleStyle') + 1], 'Hidden')
        self.assertIn('-Quiet', args)

    def test_unknown_style_falls_back_to_hidden(self) -> None:
        args = self._launch('Weird')
        self.assertEqual(args[args.index('-ConsoleStyle') + 1], 'Hidden')


if __name__ == '__main__':
    unittest.main()
