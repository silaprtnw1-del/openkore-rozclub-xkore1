"""The main window is assembled from mixins (rozgui/app.py): guard the assembly.

- No method is defined in two parts (the later one in the MRO would silently lose).
- The real App builds with its window withdrawn and every bot's config loads clean.
  No event loop runs, so poll / auto login never fire; settings are never written.
"""
from __future__ import annotations

import os
import tkinter as tk
import unittest
from unittest import mock

import support
from rozgui import app as A

MIXINS = [c for c in A.App.__mro__ if c.__name__.endswith('Mixin')]


class MixinLayout(unittest.TestCase):
    def test_every_part_is_mixed_in(self) -> None:
        self.assertEqual(len(MIXINS), 8)

    def test_no_method_defined_twice(self) -> None:
        owners: dict[str, str] = {}
        for cls in [A.App] + MIXINS:
            for name, val in vars(cls).items():
                if callable(val) or isinstance(val, staticmethod):
                    with self.subTest(name=name):
                        self.assertNotIn(name, owners, f'{name} in {owners.get(name)} and {cls.__name__}')
                    owners[name] = cls.__name__

    def test_reexports(self) -> None:
        for name in A.__all__:
            self.assertTrue(hasattr(A, name), name)


@unittest.skipUnless(os.path.exists(os.path.join(support.REPO_ROOT, 'instances.json')),
                     'no instances.json (fresh checkout): nothing to build against')
class BuildHidden(unittest.TestCase):
    def test_build_and_visit_every_bot(self) -> None:
        orig = tk.Tk.__init__

        def hidden_init(self: tk.Tk, *a: object, **k: object) -> None:
            orig(self, *a, **k)
            self.withdraw()

        with support.no_real_input(), mock.patch.object(tk.Tk, '__init__', hidden_init), \
                mock.patch.object(A.App, '_save_settings', lambda self: True):
            app = A.App()
            try:
                self.assertEqual(app.state(), 'withdrawn')
                for b in app.bots:
                    app.select_bot(b.name, force=True)
                    self.assertEqual(app.kc_bot, b.name)
                    self.assertFalse(app._config_dirty(), f'{b.name}: dirty right after load')
                app.refresh_overview()
                app.rerender_log()
                app.team_tab.refresh()
                for tab in app.nb.tabs():
                    app.nb.select(tab)
                app.update_idletasks()
                self.assertEqual(app.state(), 'withdrawn')
            finally:
                app.destroy()


if __name__ == '__main__':
    unittest.main()
