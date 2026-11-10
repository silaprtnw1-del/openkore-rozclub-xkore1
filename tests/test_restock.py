"""buyAuto / getAuto rules (gui/rozgui/restock.py) on a copy of bots/_example's config.txt."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import support
from rozgui import restock as RS
from rozgui.kconfig import KConfig

EXAMPLE = os.path.join(support.REPO_ROOT, 'bots', '_example', 'control', 'config.txt')


class RestockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = os.path.join(tempfile.mkdtemp(), 'config.txt')
        shutil.copy(EXAMPLE, self.path)
        self.kc = KConfig(self.path)

    def _rule(self, key: str, value: str) -> RS.Rule:
        return next(r for r in RS.load(self.kc) if r.key == key and r.value == value)

    def _body(self, key: str, value: str) -> str:
        b = next(b for b in self.kc.blocks if b.key == key and b.value == value)
        return self.kc.block_text(b)

    def test_reads_the_existing_blocks(self) -> None:
        fw = self._rule(RS.BUY, 'Fly Wing')
        self.assertEqual((fw.npc, fw.price, fw.min_amount, fw.max_amount, fw.zeny_min, fw.enabled),
                         ('payon 159 96', 250, 10, 50, 15000, True))
        self.assertFalse(self._rule(RS.BUY, 'Butterfly Wing').enabled)
        self.assertEqual(self._rule(RS.GET, 'Fly Wing').max_amount, 50)

    def test_edit_in_place_keeps_other_lines(self) -> None:
        fw = self._rule(RS.BUY, 'Fly Wing')
        fw.min_amount, fw.max_amount, fw.zeny_min = 5, 30, 20000
        RS.apply(self.kc, fw)
        body = self._body(RS.BUY, 'Fly Wing')
        for line in ('minAmount 5', 'maxAmount 30', 'zeny > 20000', 'standpoint', 'distance 5', 'price 250'):
            self.assertIn(line, body.splitlines())
        self.assertEqual(sum(1 for b in self.kc.blocks if b.key == RS.BUY and b.value == 'Fly Wing'), 1)

    def test_new_buy_rule_by_item_id(self) -> None:
        RS.apply(self.kc, RS.Rule(RS.BUY, '502', npc='payon 159 96', price=50, min_amount=5, max_amount=20, zeny_min=3000))
        body = self._body(RS.BUY, '502').splitlines()
        for line in ('npc payon 159 96', 'distance 5', 'price 50', 'minAmount 5', 'maxAmount 20', 'zeny > 3000', 'disabled 0'):
            self.assertIn(line, body)

    def test_new_get_rule_passive(self) -> None:
        RS.apply(self.kc, RS.Rule(RS.GET, '645', min_amount=1, max_amount=5, passive=True))
        self.assertIn('passive 1', self._body(RS.GET, '645').splitlines())

    def test_changing_the_item_renames_the_block(self) -> None:
        red = self._rule(RS.BUY, '501')
        red.value = '569'
        RS.apply(self.kc, red)
        self.assertFalse(any(b.key == RS.BUY and b.value == '501' for b in self.kc.blocks))
        self.assertIn('npc payon 159 96', self._body(RS.BUY, '569').splitlines())

    def test_toggle_and_remove(self) -> None:
        bw = self._rule(RS.BUY, 'Butterfly Wing')
        bw.enabled = True
        RS.apply(self.kc, bw)
        self.assertIn('disabled 0', self._body(RS.BUY, 'Butterfly Wing').splitlines())
        RS.remove(self.kc, self._rule(RS.BUY, 'Butterfly Wing'))
        self.assertFalse(any(b.value == 'Butterfly Wing' and b.key == RS.BUY for b in self.kc.blocks))

    def test_unusual_zeny_range_is_kept(self) -> None:
        RS.apply(self.kc, RS.Rule(RS.BUY, '503', npc='payon 159 96', min_amount=1, max_amount=5))
        b = next(b for b in self.kc.blocks if b.key == RS.BUY and b.value == '503')
        self.kc.replace_block(b, '503', self.kc.block_text(b) + '\nzeny 1000..50000')
        r = self._rule(RS.BUY, '503')
        self.assertIsNone(r.zeny_min)
        r.max_amount = 8
        RS.apply(self.kc, r)
        self.assertIn('zeny 1000..50000', self._body(RS.BUY, '503').splitlines())

    def test_validation(self) -> None:
        bad = [RS.Rule(RS.BUY, '501', npc='payon 1 2 3', min_amount=1, max_amount=5),
               RS.Rule(RS.BUY, '501', npc='payon 159 96', min_amount=5, max_amount=5),
               RS.Rule(RS.GET, '501', min_amount=None, max_amount=5),
               RS.Rule(RS.GET, '', min_amount=1, max_amount=5)]
        for r in bad:
            with self.assertRaises(ValueError):
                RS.validate(r)

    def test_file_written_by_save(self) -> None:
        fw = self._rule(RS.BUY, 'Fly Wing')
        fw.max_amount = 40
        RS.apply(self.kc, fw)
        self.kc.save()
        self.assertEqual(self._rule_from_disk(RS.BUY, 'Fly Wing').max_amount, 40)

    def _rule_from_disk(self, key: str, value: str) -> RS.Rule:
        return next(r for r in RS.load(KConfig(self.path)) if r.key == key and r.value == value)


class ZenyFloorTest(unittest.TestCase):
    def test_forms(self) -> None:
        self.assertEqual(RS.zeny_floor('> 15000'), 15000)
        self.assertEqual(RS.zeny_floor('>=1000'), 1000)
        self.assertIsNone(RS.zeny_floor('1000..5000'))
        self.assertIsNone(RS.zeny_floor(''))


if __name__ == '__main__':
    unittest.main()
