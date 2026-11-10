"""สเตตัส / สกิล tab (gui/rozgui/statskilltab.py), driven in a hidden Tk window."""
from __future__ import annotations

import os
import shutil
import tempfile
import tkinter as tk
import unittest
from typing import Any

import support
from rozgui import autoraise as A
from rozgui.kconfig import KConfig
from rozgui.statskilltab import StatSkillTab

EXAMPLE = os.path.join(support.REPO_ROOT, 'bots', '_example', 'control', 'config.txt')

CHAR_JSON: dict[str, Any] = {
    'char': 'swordman',
    'stats': {'str': 16, 'agi': 1, 'vit': 1, 'int': 10, 'dex': 15, 'luk': 1, 'int_bonus': 1,
              'points_free': 20, 'points_skill': 3, 'lv': 15},
    'skills': [{'handle': 'SM_SWORD', 'name': 'Sword Mastery', 'lv': 4, 'target': 0}],
    'tree': [{'handle': 'SM_SWORD', 'name': 'Sword Mastery', 'lv': 4, 'up': 1},
             {'handle': 'SM_BASH', 'name': 'Bash', 'lv': 0, 'up': 1},
             {'handle': 'SM_PROVOKE', 'name': 'Provoke', 'lv': 0, 'up': 0}],
}


class StatSkillTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = tk.Tk()
        cls.root.withdraw()                    # never shown on the user's screen

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def setUp(self) -> None:
        self.path = os.path.join(tempfile.mkdtemp(), 'config.txt')
        shutil.copy(EXAMPLE, self.path)
        self.kc = KConfig(self.path)
        self.changes = 0
        self.tab = StatSkillTab(self.root, self._changed)
        self.tab.fill(self.kc, CHAR_JSON)

    def tearDown(self) -> None:
        self.tab.destroy()

    def _changed(self) -> None:
        self.changes += 1

    def test_shows_current_stats_and_free_points(self) -> None:
        text = self.tab.current_lbl.cget('text')
        for part in ('STR 16', 'INT 10', 'แต้มว่าง 20', 'แต้มสกิล 3'):
            self.assertIn(part, text)
        self.assertFalse(self.tab.is_dirty())

    def test_add_stat_steps_with_cost_preview(self) -> None:
        self.tab.add_stat('int', 60)
        self.tab.add_stat('dex', 25)
        rows = [self.tab.stat_tv.item(r, 'values') for r in self.tab.stat_tv.get_children()]
        self.assertEqual([tuple(str(v) for v in r) for r in rows],
                         [('INT', '60', '245', '17'), ('DEX', '25', '34', '15')])
        self.assertTrue(self.tab.is_dirty())
        self.assertGreater(self.changes, 0)

    def test_reorder_and_remove_stats(self) -> None:
        self.tab.add_stat('int', 60)
        self.tab.add_stat('dex', 25)
        self.tab.move_stat(1, -1)
        self.assertEqual(self.tab.settings.stats, [('dex', 25), ('int', 60)])
        self.tab.remove_stat(0)
        self.assertEqual(self.tab.settings.stats, [('int', 60)])

    def test_bad_stat_value_refused(self) -> None:
        for stat, value in (('int', 0), ('int', 100), ('foo', 50)):
            with self.assertRaises(ValueError):
                self.tab.add_stat(stat, value)
        self.assertEqual(self.tab.settings.stats, [])

    def test_skill_choices_come_from_the_skill_tree(self) -> None:
        values = list(self.tab.skill_box['values'])
        self.assertTrue(any('Bash' in v and 'SM_BASH' in v for v in values))
        self.assertTrue(any('SM_PROVOKE' in v for v in values))

    def test_add_reorder_remove_skills(self) -> None:
        self.tab.add_skill('SM_BASH', 10)
        self.tab.add_skill('SM_PROVOKE', 1)
        self.tab.move_skill(0, 1)
        self.assertEqual(self.tab.settings.skills, [('SM_PROVOKE', 1), ('SM_BASH', 10)])
        self.tab.remove_skill(1)
        self.assertEqual(self.tab.settings.skills, [('SM_PROVOKE', 1)])
        with self.assertRaises(ValueError):
            self.tab.add_skill('SM_BASH', 0)

    def test_apply_config_writes_the_plugin_keys(self) -> None:
        self.tab.add_stat('int', 60)
        self.tab.add_stat('dex', 25)
        self.tab.stats_on_var.set(1)
        self.tab.base_only_var.set(1)
        self.tab.add_skill('SM_BASH', 10)
        self.tab.skills_on_var.set(1)
        self.tab.apply_config(self.kc)
        self.assertEqual(self.kc.get('statsAddAuto'), '1')
        self.assertEqual(self.kc.get('statsAddAuto_list'), '60 int, 25 dex')
        self.assertEqual(self.kc.get('statsAddAuto_dontUseBonus'), '1')
        self.assertEqual(self.kc.get('skillsAddAuto'), '1')
        self.assertEqual(self.kc.get('skillsAddAuto_list'), 'SM_BASH 10')
        self.assertFalse(self.tab.is_dirty())

    def test_switching_on_without_targets_is_refused(self) -> None:
        self.tab.stats_on_var.set(1)
        self.tab._on_toggle()                  # what the checkbox command calls
        with self.assertRaises(ValueError):
            self.tab.apply_config(self.kc)
        self.assertFalse(self.kc.has('statsAddAuto'))

    def test_fill_reads_existing_settings(self) -> None:
        A.apply(self.kc, A.RaiseSettings(stats_on=True, stats=[('vit', 40)], skills_on=False, skills=[('SM_BASH', 5)]))
        self.tab.fill(self.kc, CHAR_JSON)
        self.assertEqual(self.tab.settings.stats, [('vit', 40)])
        self.assertEqual(self.tab.settings.skills, [('SM_BASH', 5)])
        self.assertEqual((self.tab.stats_on_var.get(), self.tab.skills_on_var.get()), (1, 0))
        self.assertFalse(self.tab.is_dirty())

    def test_unparsable_list_in_file_survives_a_save(self) -> None:
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write('\nstatsAddAuto 0\nstatsAddAuto_list 60 int, 30 foo\n')
        kc = KConfig(self.path)
        self.tab.fill(kc, CHAR_JSON)
        self.assertIn('statsAddAuto_list', self.tab.error_lbl.cget('text'))
        self.tab.apply_config(kc)                    # the app calls this on every save
        self.assertEqual(kc.get('statsAddAuto_list'), '60 int, 30 foo')
        self.assertFalse(kc.dirty)

    def test_without_char_json(self) -> None:
        self.tab.fill(self.kc, None)
        self.assertIn('ยังไม่รู้', self.tab.current_lbl.cget('text'))
        self.tab.add_stat('str', 30)                 # still editable, no preview numbers needed
        self.assertEqual(self.tab.settings.stats, [('str', 30)])


if __name__ == '__main__':
    unittest.main()
