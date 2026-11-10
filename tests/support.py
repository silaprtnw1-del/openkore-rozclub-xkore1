"""Shared test helpers. Run all tests from the repo root:  python -m unittest discover -s tests -v

Nothing here may touch the real game: every test that drives relogin.LoginRunner
patches the input functions, and `no_real_input()` makes any unpatched call fail.
"""
from __future__ import annotations

import contextlib
import os
import sys
from typing import Any, Iterator
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_DIR = os.path.join(REPO_ROOT, 'gui')
if GUI_DIR not in sys.path:
    sys.path.insert(0, GUI_DIR)

from rozgui import relogin as R  # noqa: E402  (needs GUI_DIR on sys.path)


def _refuse(*_a: Any, **_k: Any) -> Any:
    raise AssertionError('a test tried to send real keyboard/mouse input or touch a real window')


@contextlib.contextmanager
def no_real_input() -> Iterator[None]:
    """Make the lowest-level Win32 input/focus/capture calls fail loudly."""
    with mock.patch.multiple(R, _send_key=_refuse, _send_mouse=_refuse, press=_refuse, chord=_refuse,
                             type_text=_refuse, click_client=_refuse, focus_window=_refuse,
                             screenshot=lambda h, p: False, grab_client=_refuse):
        yield


def fast_settings(**over: float) -> R.LoginSettings:
    s = R.LoginSettings()
    s.login_delay = 0
    s.server_delay = 0.5
    s.char_delay = 0.5
    s.map_timeout = 3
    for k, v in over.items():
        setattr(s, k, v)
    return s


FAST_CONSTANTS: dict[str, float] = {
    'ONLINE_HOLD_SECONDS': 0.3, 'KICK_CONFIRM_SECONDS': 0.3, 'KICK_BOX_CLOSE_SECONDS': 0.01,
    'MSGBOX_CLOSE_SECONDS': 0.01, 'UI_SETTLE_SECONDS': 0.0,
}
