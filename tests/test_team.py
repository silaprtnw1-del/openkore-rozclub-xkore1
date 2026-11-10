"""Team settings across bots (gui/rozgui/team.py).

Keys (OpenKore src): follow / followTarget (character name) / followDistanceMax
(AI/CoreLogic.pm processFollow), attackAuto_party, itemsTakeAuto_party,
partyAuto (AI/CoreLogic.pm: 1 = refuse, 2 = accept, 0 = do nothing).
A follower is set like the พื้นฐาน tab does: follow 1, followTarget, attackAuto 0;
back to solo: follow 0, attackAuto 2.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from typing import Any

import support
from rozgui import team as T
from rozgui.kconfig import KConfig

EXAMPLE = os.path.join(support.REPO_ROOT, 'bots', '_example', 'control', 'config.txt')


def status(char: str, party: str = '', online: int = 1, **kw: Any) -> dict[str, Any]:
    s = {'char': char, 'party': party, 'online': online, 'level': 30, 'job': 'Swordman', 'map': 'pay_dun00',
         'hp': 50, 'hp_max': 100}
    s.update(kw)
    return s


class TeamLogicTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()

    def _kc(self, name: str, extra: str = '') -> KConfig:
        path = os.path.join(self.dir, f'{name}.txt')
        shutil.copy(EXAMPLE, path)
        if extra:
            with open(path, 'a', encoding='utf-8') as f:
                f.write('\n' + extra + '\n')
        return KConfig(path)

    def test_read_solo_member(self) -> None:
        m = T.read_member('potato7', self._kc('p'), status('potato7', 'potata7'))
        self.assertEqual((m.bot, m.char, m.role, m.lock_map, m.party_attack, m.party_loot, m.party_auto),
                         ('potato7', 'potato7', T.SOLO, 'pay_dun00', True, True, 0))
        self.assertEqual((m.online, m.level, m.job, m.map, m.hp_pct, m.party), (True, 30, 'Swordman', 'pay_dun00', 50, 'potata7'))

    def test_read_follower(self) -> None:
        kc = self._kc('k', 'follow 1\nfollowTarget potato7\nfollowDistanceMax 6\npartyAuto 2\nattackAuto_party 0')
        m = T.read_member('kiminoto', kc, None)
        self.assertEqual((m.role, m.follow_target, m.follow_dist, m.party_auto, m.party_attack, m.char, m.online),
                         (T.FOLLOW, 'potato7', 6, 2, False, '', False))

    def test_changes_only_what_differs(self) -> None:
        old = T.read_member('swordman', self._kc('s'), status('swordman'))
        new = T.TeamMember(**{**old.__dict__})
        self.assertEqual(T.changes(old, new), {})
        new.role, new.follow_target = T.FOLLOW, 'potato7'
        self.assertEqual(T.changes(old, new), {'follow': '1', 'followTarget': 'potato7', 'attackAuto': '0'})
        new.party_auto, new.lock_map = 2, 'pay_fild08'
        ch = T.changes(old, new)
        self.assertEqual((ch['partyAuto'], ch['lockMap']), ('2', 'pay_fild08'))

    def test_back_to_solo(self) -> None:
        kc = self._kc('k', 'follow 1\nfollowTarget potato7')
        old = T.read_member('kiminoto', kc, None)
        new = T.TeamMember(**{**old.__dict__})
        new.role = T.SOLO
        self.assertEqual(T.changes(old, new), {'follow': '0', 'attackAuto': '2'})

    def test_apply_writes_in_place(self) -> None:
        kc = self._kc('k', 'follow 1\nfollowTarget potato7')
        n = len(kc.lines)
        T.apply(kc, {'followTarget': 'swordman', 'partyAuto': '2'})
        self.assertEqual((kc.get('followTarget'), kc.get('partyAuto')), ('swordman', '2'))
        self.assertEqual(len(kc.lines), n + 1, 'followTarget edited in place, partyAuto appended')

    def test_validate(self) -> None:
        a = T.TeamMember('a', char='A', role=T.FOLLOW, follow_target='B')
        b = T.TeamMember('b', char='B', role=T.FOLLOW, follow_target='A')
        errs = T.validate([a, b])
        self.assertTrue(any('วน' in e for e in errs), errs)              # A -> B -> A
        self.assertTrue(T.validate([T.TeamMember('a', char='A', role=T.FOLLOW, follow_target='')]))
        self.assertTrue(T.validate([T.TeamMember('a', char='A', role=T.FOLLOW, follow_target='A')]))
        self.assertTrue(T.validate([T.TeamMember('a', char='A', follow_dist=0)]))
        ok = [T.TeamMember('p', char='P'), T.TeamMember('k', char='K', role=T.FOLLOW, follow_target='P', follow_dist=6)]
        self.assertEqual(T.validate(ok), [])

    def test_warnings(self) -> None:
        leader = T.TeamMember('p', char='P', lock_map='pay_dun00', party='team1')
        f1 = T.TeamMember('k', char='K', role=T.FOLLOW, follow_target='P', lock_map='pay_fild08', party='other')
        f2 = T.TeamMember('s', char='S', role=T.FOLLOW, follow_target='Stranger')
        text = ' | '.join(T.warnings([leader, f1, f2]))
        self.assertIn('pay_fild08', text)          # follower farms a different map than its leader
        self.assertIn('ปาร์ตี้', text)             # not in the leader's party
        self.assertIn('Stranger', text)            # leader is not one of our bots
        self.assertEqual(T.warnings([leader, T.TeamMember('k', char='K', role=T.FOLLOW, follow_target='P',
                                                          lock_map='pay_dun00', party='team1')]), [])


if __name__ == '__main__':
    unittest.main()
