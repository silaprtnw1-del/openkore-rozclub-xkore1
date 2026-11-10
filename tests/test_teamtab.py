"""👥 ทีม tab (gui/rozgui/teamtab.py), driven in a hidden Tk window on temp copies of configs."""
from __future__ import annotations

import os
import shutil
import tempfile
import tkinter as tk
import unittest
from typing import Any

import support
from rozgui import team as T
from rozgui.kconfig import KConfig
from rozgui.teamtab import TeamSource, TeamTab

EXAMPLE = os.path.join(support.REPO_ROOT, 'bots', '_example', 'control', 'config.txt')


class TeamTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = tk.Tk()
        cls.root.withdraw()                    # never shown on the user's screen

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def setUp(self) -> None:
        d = tempfile.mkdtemp()
        self.paths: dict[str, str] = {}
        for bot, extra in (('potato7', ''), ('kiminoto', 'follow 1\nfollowTarget potato7\npartyAuto 2\n'),
                           ('swordman', 'lockMap pay_fild08\n')):
            p = os.path.join(d, f'{bot}.txt')
            shutil.copy(EXAMPLE, p)
            with open(p, 'a', encoding='utf-8') as f:
                f.write('\n' + extra)
            self.paths[bot] = p
        self.sent: list[tuple[str, tuple[str, ...]]] = []
        self.saved: list[list[str]] = []
        self.statuses: dict[str, dict[str, Any] | None] = {
            'potato7': {'char': 'potato7', 'party': 'potata7', 'online': 1, 'level': 38, 'map': 'pay_dun00',
                        'hp': 80, 'hp_max': 100, 'job': 'Thief'},
            'kiminoto': {'char': 'kiminoto', 'party': 'potata7', 'online': 1, 'level': 36, 'map': 'pay_dun00',
                         'hp': 70, 'hp_max': 100, 'job': 'Acolyte'},
            'swordman': None,                  # not running
        }
        self.tab = TeamTab(self.root, self._provider, self.saved.append)
        self.tab.refresh()

    def tearDown(self) -> None:
        self.tab.destroy()

    def _provider(self) -> list[TeamSource]:
        out = []
        for bot, path in self.paths.items():
            st = self.statuses[bot]
            send = (lambda *cmds, b=bot: self.sent.append((b, cmds)) or True) if st else None
            out.append(TeamSource(bot, path, st, send))
        return out

    def _row(self, bot: str) -> tuple[str, ...]:
        return tuple(str(v) for v in self.tab.tv.item(bot, 'values'))

    def test_rows_show_every_bot(self) -> None:
        self.assertEqual(list(self.tab.tv.get_children()), ['potato7', 'kiminoto', 'swordman'])
        self.assertIn('potato7', ' '.join(self._row('kiminoto')))      # whom it follows
        self.assertIn('pay_fild08', ' '.join(self._row('swordman')))
        self.assertFalse(self.tab.is_dirty())

    def test_make_swordman_follow_potato7_and_save(self) -> None:
        self.tab.set_role('swordman', T.FOLLOW, 'potato7')
        self.tab.copy_leader_map('swordman')
        self.tab.set_party('swordman', auto=2)
        self.assertTrue(self.tab.is_dirty())
        saved = self.tab.save()
        self.assertEqual(saved, ['swordman'])
        kc = KConfig(self.paths['swordman'])
        self.assertEqual((kc.get('follow'), kc.get('followTarget'), kc.get('attackAuto'), kc.get('lockMap'),
                          kc.get('partyAuto')), ('1', 'potato7', '0', 'pay_dun00', '2'))
        self.assertEqual(self.sent, [], 'swordman is not running: nothing sent')
        self.assertEqual(self.saved, [['swordman']])
        self.assertFalse(self.tab.is_dirty())

    def test_running_bot_gets_reload(self) -> None:
        self.tab.set_party('kiminoto', attack=False)       # the example config has attackAuto_party 1
        self.tab.save()
        self.assertEqual(self.sent, [('kiminoto', ('reload config',))])
        self.assertEqual(KConfig(self.paths['kiminoto']).get('attackAuto_party'), '0')

    def test_no_change_means_nothing_saved(self) -> None:
        self.tab.set_party('kiminoto', attack=True)        # already 1: not a change
        self.assertFalse(self.tab.is_dirty())
        self.assertEqual(self.tab.save(), [])
        self.assertEqual((self.sent, self.saved), ([], []))

    def test_follow_loop_is_refused_and_nothing_written(self) -> None:
        self.tab.set_role('potato7', T.FOLLOW, 'kiminoto')                # kiminoto already follows potato7
        before = {b: open(p, encoding='utf-8').read() for b, p in self.paths.items()}
        with self.assertRaises(ValueError):
            self.tab.save()
        self.assertEqual(before, {b: open(p, encoding='utf-8').read() for b, p in self.paths.items()})

    def test_leader_choices_are_other_bots_characters(self) -> None:
        self.assertEqual(sorted(self.tab.leader_choices('kiminoto')), ['potato7'])   # swordman's char unknown

    def test_warnings_shown(self) -> None:
        self.tab.set_role('swordman', T.FOLLOW, 'potato7')                # different lockMap than potato7
        self.assertIn('pay_fild08', self.tab.warnings_lbl.cget('text'))

    def test_unreadable_config_is_reported(self) -> None:
        self.paths['swordman'] = os.path.join(tempfile.mkdtemp(), 'missing.txt')
        self.tab.refresh()
        self.assertIn('swordman', self.tab.warnings_lbl.cget('text'))
        with self.assertRaises(ValueError):
            self.tab.set_role('swordman', T.SOLO)


if __name__ == '__main__':
    unittest.main()
