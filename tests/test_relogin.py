"""Auto login (gui/rozgui/relogin.py) against a fake ROZCLUB client.

The fake models what was seen live on 2026-11-10: the in-game service list
(state 2), the 5x3 character cards (state 3) whose highlight is not always
card 1, the first-map kick that leaves the map on screen under an in-game
[OK] box, and the 'connection lost' box after a disconnect.
"""
from __future__ import annotations

import time
import unittest
from typing import Any
from unittest import mock

import support
from support import R

BOXES = ('box_over_map', 'box_over_login')


class FakeGame:
    def __init__(self, screen: str = 'login', highlight: int = 1, kicks: int = 0, click_selects: bool = True,
                 stuck_box: bool = False, size: tuple[int, int] = (1024, 768)) -> None:
        self.screen = screen
        self.state = 1
        self.highlight = highlight
        self.kicks = kicks
        self.click_selects = click_selects
        self.stuck_box = stuck_box
        self.size = size
        self.typed = 0
        self.logins = 0
        self.entered_slot: int | None = None
        self.t_map = 0.0
        self.events: list[tuple[str, str]] = []

    # -- the client ---------------------------------------------------------
    def get_state(self) -> int:
        if self.screen == 'map' and self.kicks and time.time() - self.t_map > 0.1:
            self.kicks -= 1
            self.screen, self.state, self.typed = 'box_over_map', 1, 0
        return self.state

    def press(self, vk: int, hold: float = 0.0) -> None:
        name = {R.VK_RETURN: 'Enter', R.VK_LEFT: 'Left', R.VK_RIGHT: 'Right', R.VK_UP: 'Up',
                R.VK_DOWN: 'Down', R.VK_TAB: 'Tab'}.get(vk, str(vk))
        self.events.append((name, self.screen))
        if self.screen == 'char' and name in ('Left', 'Right', 'Up', 'Down'):
            c, r = (self.highlight - 1) % 5, (self.highlight - 1) // 5
            c += {'Left': -1, 'Right': 1}.get(name, 0)
            r += {'Up': -1, 'Down': 1}.get(name, 0)
            self.highlight = r * 5 + c + 1
        if name != 'Enter':
            return
        if self.screen in BOXES and not self.stuck_box:
            self.screen = 'login'
        elif self.screen == 'login' and self.typed >= 2:
            self.logins += 1
            self.screen, self.state = 'service', 2
        elif self.screen == 'service':
            self.screen, self.state = 'char', 3
        elif self.screen == 'char':
            self.entered_slot = self.highlight
            self.screen, self.state, self.t_map = 'map', 5, time.time()

    def type_text(self, text: str) -> None:
        self.events.append(('type', self.screen))
        if self.screen == 'login':
            self.typed += 1

    def click_client(self, hwnd: int, x: int, y: int, park: tuple[int, int] | None = None) -> bool:
        self.events.append(('click', self.screen))
        if self.click_selects and self.screen == 'char':
            self.highlight = next(s for s in range(1, 16) if R.char_card_point(s) == (x, y))
        return True

    def grab(self, hwnd: int) -> dict[str, Any]:
        return {'screen': self.screen, 'highlight': self.highlight}

    # -- helpers ------------------------------------------------------------
    def typed_off_login(self) -> list[tuple[str, str]]:
        return [e for e in self.events if e[0] == 'type' and e[1] != 'login']

    def run(self, slot: int = 1, chars: list[str] | None = None) -> bool:
        patches = dict(support.FAST_CONSTANTS)
        patches.update(
            is_admin=lambda: True, find_game_window=lambda pid: 10, focus_window=lambda h: True,
            is_foreground=lambda h: True, find_dialogs=lambda pid, main: [], caps_lock_on=lambda: False,
            chord=lambda m, k: None, press=self.press, type_text=self.type_text, click_client=self.click_client,
            client_size=lambda h: self.size, grab_client=self.grab, log=mock.Mock(),   # keep gui-error.log clean
            ingame_box_visible=lambda img: img['screen'] in BOXES,
            highlighted_cards=lambda img: [img['highlight']] if img['screen'] == 'char' else list(range(1, 16)))
        with support.no_real_input(), mock.patch.multiple(R, **patches):
            runner = R.LoginRunner('test', 1, support.fast_settings(char_slot=slot), log_cb=lambda m: None,
                                   get_state=self.get_state, get_chars=(lambda: chars) if chars is not None else None)
            return runner.run(lambda: self.get_state() == 5, lambda: False)


class LoginFlowTest(unittest.TestCase):
    def test_plain_login_reaches_the_map(self) -> None:
        g = FakeGame()
        self.assertTrue(g.run())
        self.assertEqual(g.logins, 1)
        self.assertEqual(g.entered_slot, 1)

    def test_first_map_kick_closes_box_then_logs_in_again(self) -> None:
        g = FakeGame(kicks=1)
        self.assertTrue(g.run())
        self.assertEqual(g.logins, 2)
        self.assertIn(('Enter', 'box_over_map'), g.events)
        self.assertEqual(g.typed_off_login(), [])

    def test_kicked_twice_stops(self) -> None:
        g = FakeGame(kicks=2)
        self.assertFalse(g.run())
        self.assertEqual(g.logins, 2)


class InGameBoxTest(unittest.TestCase):
    def test_disconnect_box_over_map_is_closed_before_typing(self) -> None:
        g = FakeGame(screen='box_over_map')
        self.assertTrue(g.run())
        self.assertEqual(g.events[0], ('Enter', 'box_over_map'))
        self.assertEqual(g.typed_off_login(), [])

    def test_box_over_login_screen_is_closed(self) -> None:
        g = FakeGame(screen='box_over_login')
        self.assertTrue(g.run())
        self.assertEqual(g.events[0], ('Enter', 'box_over_login'))

    def test_no_box_means_no_extra_enter(self) -> None:
        g = FakeGame(screen='login')
        self.assertTrue(g.run())
        self.assertEqual(g.events[0], ('type', 'login'))

    def test_box_that_never_closes_stops_without_typing(self) -> None:
        g = FakeGame(screen='box_over_map', stuck_box=True)
        self.assertFalse(g.run())
        self.assertFalse(any(e[0] == 'type' for e in g.events))


class CharacterSelectTest(unittest.TestCase):
    def test_click_selects_the_card(self) -> None:
        g = FakeGame(highlight=1)
        self.assertTrue(g.run(slot=2))
        self.assertEqual(g.entered_slot, 2)

    def test_arrows_fix_the_highlight_when_the_click_is_ignored(self) -> None:
        g = FakeGame(highlight=9, click_selects=False)
        self.assertTrue(g.run(slot=2))
        self.assertEqual(g.entered_slot, 2)
        self.assertEqual([e[0] for e in g.events if e[1] == 'char' and e[0] != 'click'][:3], ['Left', 'Left', 'Up'])

    def test_empty_slot_is_refused(self) -> None:
        g = FakeGame()
        self.assertFalse(g.run(slot=2, chars=['0:potato7']))
        self.assertIsNone(g.entered_slot)

    def test_unknown_window_size_never_presses_enter_on_a_card(self) -> None:
        g = FakeGame(size=(800, 600))
        self.assertFalse(g.run(slot=2))
        self.assertIsNone(g.entered_slot)


class CardGeometryTest(unittest.TestCase):
    def test_card_points(self) -> None:
        self.assertEqual(R.char_card_point(1), (101, 177))
        self.assertEqual(R.char_card_point(7), (101 + 157, 177 + 195))
        with self.assertRaises(ValueError):
            R.char_card_point(16)


if __name__ == '__main__':
    unittest.main()
