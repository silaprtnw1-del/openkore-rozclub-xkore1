"""Paths and the GUI settings file (%APPDATA%\\ROZBotControl\\settings.json)."""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Final

from .errlog import log
from .notify import DEFAULTS as NOTIFY_DEFAULTS


# OpenKore console windows: hidden by default since 2026-11-10 (user: only the GUI should show).
# Settings saved before that hold 'Minimized' (it used to be written as the default), so they
# are switched to 'Hidden' once; a choice made after that in the โปรแกรม tab is kept.
CONSOLE_STYLE_REV: Final[int] = 2


def apply_console_default(s: dict[str, Any]) -> bool:
    """Switch older settings to hidden consoles once. True if `s` changed (save it)."""
    try:
        rev = int(s.get('console_style_rev') or 0)
    except (TypeError, ValueError):
        rev = 0
    if rev >= CONSOLE_STYLE_REV:
        return False
    s['console_style'] = 'Hidden'
    s['console_style_rev'] = CONSOLE_STYLE_REV
    return True


# Delivered in phases. 1 = dashboard + control + log, 2 = + notifications, 3 = + settings editor.
PHASE: Final[int] = 3
GUI_DIR: Final[str] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR: str = os.path.dirname(GUI_DIR)
# Settings hold the Telegram token / Discord webhook: keep them outside the project
# folder (which sits under OneDrive and in git), in the user's own profile.
SETTINGS_DIR: Final[str] = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'ROZBotControl')
SETTINGS_PATH: str = os.path.join(SETTINGS_DIR, 'settings.json')
LEGACY_SETTINGS_PATH: str = os.path.join(GUI_DIR, 'settings.json')   # before 2026-11-10


class SettingsMixin:
    """Mixin of App: uses the state that App.__init__ sets up."""

    # ------------------------------------------------------------ settings
    @staticmethod
    def _migrate_settings() -> None:
        """Move gui/settings.json (old place, inside the project) to SETTINGS_PATH once."""
        if os.path.exists(SETTINGS_PATH) or not os.path.exists(LEGACY_SETTINGS_PATH):
            return
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            shutil.move(LEGACY_SETTINGS_PATH, SETTINGS_PATH)
            log.info('settings moved to %s', SETTINGS_PATH)
        except OSError as e:
            log.warning('cannot move %s to %s (%s); reading it in place', LEGACY_SETTINGS_PATH, SETTINGS_PATH, e)

    def _load_settings(self) -> dict[str, Any]:
        self._migrate_settings()
        # If the move failed, keep using the old file rather than silently starting from defaults.
        path = LEGACY_SETTINGS_PATH if (not os.path.exists(SETTINGS_PATH)
                                        and os.path.exists(LEGACY_SETTINGS_PATH)) else SETTINGS_PATH
        s: dict[str, Any] = {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                s = loaded
            else:
                log.warning('%s is not a JSON object; using defaults', SETTINGS_PATH)
        except FileNotFoundError:
            pass    # first run: defaults below
        except (OSError, ValueError) as e:
            log.warning('cannot load %s (%s); using defaults', SETTINGS_PATH, e)
        if not isinstance(s.get('notify'), dict):
            s['notify'] = {}
        n = dict(NOTIFY_DEFAULTS)
        n['events'] = dict(NOTIFY_DEFAULTS['events'])
        n.update({k: v for k, v in s.get('notify', {}).items() if k != 'events'})
        n['events'].update(s.get('notify', {}).get('events', {}))
        s['notify'] = n
        s.setdefault('console_style', 'Hidden')
        return s

    def _save_settings(self) -> bool:
        tmp = SETTINGS_PATH + '.tmp'
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            os.replace(tmp, SETTINGS_PATH)
        except OSError as e:
            log.exception('cannot save %s', SETTINGS_PATH)
            self.toast(f'บันทึกการตั้งค่าโปรแกรมไม่ได้: {e}', 'bad')
            return False
        return True