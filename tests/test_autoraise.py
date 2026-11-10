"""Auto stat / skill raise settings (gui/rozgui/autoraise.py).

Formats follow OpenKore's plugins/raiseStat (`60 int` or `int 60`, comma
separated, values above 99 refused unless statsAdd_over_99) and
plugins/raiseSkill (`SM_BASH 10`, level 1 when left out). Stat costs are the
standard ones, checked on this server for kiminoto on 2026-11-06
(bots/kiminoto/control/config.txt: INT 10->60 = 245 points, DEX 15->25 = 34,
INT 60->65 = 39, DEX 25->29 = 16).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import support
from rozgui import autoraise as A
from rozgui.kconfig import KConfig

EXAMPLE = os.path.join(support.REPO_ROOT, 'bots', '_example', 'control', 'config.txt')
KIMINOTO_PLAN = [('int', 60), ('dex', 25), ('int', 65), ('dex', 29)]
KIMINOTO_BASE = {'str': 16, 'agi': 1, 'vit': 1, 'int': 10, 'dex': 15, 'luk': 1}


class StatListTest(unittest.TestCase):
    def test_parse_both_orders_and_spacing(self) -> None:
        self.assertEqual(A.parse_stat_list('60 int, 25 dex , int 65,29 dex'), KIMINOTO_PLAN)

    def test_parse_empty(self) -> None:
        self.assertEqual(A.parse_stat_list(''), [])
        self.assertEqual(A.parse_stat_list('   '), [])

    def test_parse_errors(self) -> None:
        for bad in ('60 foo', 'int', '60', 'int sixty', '100 int'):
            with self.assertRaises(ValueError, msg=bad):
                A.parse_stat_list(bad)
        self.assertEqual(A.parse_stat_list('120 str', allow_over_99=True), [('str', 120)])

    def test_format(self) -> None:
        self.assertEqual(A.format_stat_list(KIMINOTO_PLAN), '60 int, 25 dex, 65 int, 29 dex')
        self.assertEqual(A.format_stat_list([]), '')


class SkillListTest(unittest.TestCase):
    def test_parse(self) -> None:
        self.assertEqual(A.parse_skill_list('SM_BASH 10, SM_PROVOKE,SM_ENDURE 3'),
                         [('SM_BASH', 10), ('SM_PROVOKE', 1), ('SM_ENDURE', 3)])
        self.assertEqual(A.parse_skill_list(''), [])

    def test_parse_errors(self) -> None:
        for bad in ('SM_BASH 0', 'SM_BASH 11', ' , '):
            with self.assertRaises(ValueError, msg=bad):
                A.parse_skill_list(bad)

    def test_format(self) -> None:
        self.assertEqual(A.format_skill_list([('SM_BASH', 10), ('SM_PROVOKE', 1)]), 'SM_BASH 10, SM_PROVOKE 1')


class StatCostTest(unittest.TestCase):
    def test_cost_of_next_point(self) -> None:
        self.assertEqual([A.stat_cost(v) for v in (1, 10, 11, 20, 21, 99)], [2, 2, 3, 3, 4, 11])

    def test_points_needed_matches_kiminoto_plan(self) -> None:
        self.assertEqual(A.points_needed(10, 60), 245)
        self.assertEqual(A.points_needed(15, 25), 34)
        self.assertEqual(A.points_needed(60, 65), 39)
        self.assertEqual(A.points_needed(25, 29), 16)
        self.assertEqual(A.points_needed(30, 30), 0)
        self.assertEqual(A.points_needed(30, 20), 0)

    def test_plan_with_free_points(self) -> None:
        steps, left = A.plan_stats(KIMINOTO_BASE, 20, KIMINOTO_PLAN)
        self.assertEqual([(s.stat, s.start, s.target, s.cost, s.reach) for s in steps], [
            ('int', 10, 60, 245, 17),        # 20 points: 10->11 costs 2, then 3 each up to 17
            ('dex', 15, 25, 34, 15),
            ('int', 60, 65, 39, 60),         # starts where the earlier INT step ends
            ('dex', 25, 29, 16, 25)])
        self.assertEqual(left, 0)

    def test_plan_target_already_reached(self) -> None:
        steps, left = A.plan_stats(KIMINOTO_BASE, 5, [('str', 10), ('dex', 16)])
        self.assertEqual([(s.cost, s.reach) for s in steps], [(0, 16), (3, 16)])
        self.assertEqual(left, 2)


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = os.path.join(tempfile.mkdtemp(), 'config.txt')
        shutil.copy(EXAMPLE, self.path)

    def _kc(self) -> KConfig:
        return KConfig(self.path)

    def test_defaults_when_absent(self) -> None:
        s = A.load(self._kc())
        self.assertEqual((s.stats_on, s.stats, s.base_only, s.skills_on, s.skills, s.errors),
                         (False, [], False, False, [], []))

    def test_apply_then_load_round_trip(self) -> None:
        kc = self._kc()
        A.apply(kc, A.RaiseSettings(stats_on=True, stats=KIMINOTO_PLAN, base_only=True,
                                    skills_on=True, skills=[('SM_BASH', 10)]))
        kc.save()
        s = A.load(self._kc())
        self.assertEqual((s.stats_on, s.stats, s.base_only, s.skills_on, s.skills),
                         (True, KIMINOTO_PLAN, True, True, [('SM_BASH', 10)]))
        kc2 = self._kc()
        self.assertEqual(kc2.get('statsAddAuto_list'), '60 int, 25 dex, 65 int, 29 dex')
        self.assertEqual(kc2.get('skillsAddAuto_list'), 'SM_BASH 10')

    def test_existing_lines_edited_in_place_and_comments_kept(self) -> None:
        with open(self.path, 'a', encoding='utf-8', newline='') as f:
            f.write('\r\n# keep me\r\nstatsAddAuto 0\r\nstatsAddAuto_dontUseBonus 1\r\n'
                    'statsAddAuto_list 60 int, 25 dex\r\n#skillsAddAuto 1\r\n#skillsAddAuto_list AL_HEAL 5\r\n')
        kc = self._kc()
        s = A.load(kc)
        self.assertEqual((s.stats_on, s.stats, s.base_only, s.skills_on, s.skills), (False, [('int', 60), ('dex', 25)], True, False, []))
        n_lines = len(kc.lines)
        s.stats_on = True
        A.apply(kc, s)
        self.assertEqual(len(kc.lines), n_lines, 'only changed lines are rewritten, nothing appended')
        self.assertEqual(kc.get('statsAddAuto'), '1')
        text = ''.join(kc.lines)
        self.assertIn('# keep me', text)
        self.assertIn('#skillsAddAuto_list AL_HEAL 5', text)

    def test_nothing_written_when_nothing_set(self) -> None:
        kc = self._kc()
        A.apply(kc, A.load(kc))
        self.assertFalse(kc.dirty)

    def test_on_without_targets_is_refused(self) -> None:
        for s in (A.RaiseSettings(stats_on=True), A.RaiseSettings(skills_on=True)):
            with self.assertRaises(ValueError):
                A.apply(self._kc(), s)

    def test_bad_list_in_file_is_reported_not_raised(self) -> None:
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write('\nstatsAddAuto 1\nstatsAddAuto_list 60 int, 30 foo\n')
        s = A.load(self._kc())
        self.assertEqual(s.stats, [])
        self.assertEqual(len(s.errors), 1)
        self.assertIn('foo', s.errors[0])


class CharStatsTest(unittest.TestCase):
    def test_from_char_json(self) -> None:
        cj = {'stats': {'str': 16, 'agi': 1, 'vit': 1, 'int': 10, 'dex': 15, 'luk': 1, 'int_bonus': 1,
                        'points_free': 20, 'points_skill': 3, 'lv': 15}}
        cs = A.char_stats(cj)
        assert cs is not None
        self.assertEqual(cs.base, KIMINOTO_BASE)
        self.assertEqual((cs.bonus['int'], cs.bonus['str'], cs.points_free, cs.points_skill, cs.level), (1, 0, 20, 3, 15))

    def test_missing_or_bad(self) -> None:
        self.assertIsNone(A.char_stats(None))
        self.assertIsNone(A.char_stats({'items': []}))
        self.assertIsNone(A.char_stats({'stats': {'str': 'x'}}))


if __name__ == '__main__':
    unittest.main()
