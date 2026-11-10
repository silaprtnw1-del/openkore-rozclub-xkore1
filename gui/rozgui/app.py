"""ROZ Bot Control - desktop GUI for the ROZCLUB OpenKore instances.

App is assembled from page mixins (overview, configpage, notifypage, logpage, programpage),
recovery (auto login), settings and theme; each lives in its own module.
"""
from __future__ import annotations

import collections
import os
import queue
import subprocess
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Final

from .addbot import AddBotDialog
from .bot import Bot, load_registry, LogEntry
from .configpage import ConfigPageMixin
from .errlog import log
from .icons import IconCache
from .kconfig import KConfig
from .logpage import LogPageMixin
from .notify import Notifier, Rules
from .notifypage import NotifyPageMixin
from .overview import OverviewMixin
from .programpage import ProgramPageMixin
from .recovery import RecoveryMixin, STARTUP_LOGIN_GIVEUP_SECONDS, USER_STOP_GRACE_SECONDS
from .settings import apply_console_default, CONSOLE_STYLE_REV, PHASE, ROOT_DIR, SettingsMixin
from .tables import Tables
from .teamtab import TeamSource, TeamTab
from .theme import BAD, BG, BORDER, Fonts, MUTED, OK, PANEL, TEXT, ThemeMixin, WARN
from .widgets import BotCard

# Re-exported: tests and older code read these from rozgui.app.
__all__ = ['App', 'main', 'CONSOLE_STYLE_REV', 'STARTUP_LOGIN_GIVEUP_SECONDS', 'USER_STOP_GRACE_SECONDS',
           'apply_console_default']


POLL_MS: Final[int] = 1000


def event_text(ev: dict[str, Any]) -> tuple[str, str]:
    t = str(ev.get('type') or 'unknown')
    ch = ev.get('char') or ''
    mp = ev.get('map') or ''
    return {
        'died': (f'💀 {ch} ตายที่ {mp}', 'bad'),
        'disconnected': ('🔌 หลุดจากเซิร์ฟเวอร์', 'bad'),
        'in_game': (f'✅ {ch} เข้าเกมแล้ว', 'ok'),
        'base_level': (f'🎉 Base Level {ev.get("level")}', 'ok'),
        'job_level': (f'🎉 Job Level {ev.get("level")}', 'ok'),
        'pm': (f'💬 PM จาก {ev.get("from")}: {ev.get("msg")}', 'info'),
        'item': (f'🎁 ได้ {ev.get("item")} x{ev.get("amount")}', 'muted'),
        'gm_near': (f'👮 เจอ {ev.get("who")} ใกล้ตัว', 'bad'),
        # Also fires on a Fly Wing teleport inside the same map.
        'map_changed': (f'🌀 วาร์ป / เปลี่ยนแผนที่ → {mp}', 'muted'),
    }.get(t, (f'{t}', 'muted'))


class App(ThemeMixin, SettingsMixin, OverviewMixin, ConfigPageMixin, NotifyPageMixin, LogPageMixin,
          ProgramPageMixin, RecoveryMixin, tk.Tk):
    """Main window. Each page / concern is a mixin in its own module; state lives on this one object."""

    def __init__(self) -> None:
        super().__init__()
        self.title('ROZ Bot Control')
        self.configure(bg=BG)
        self.minsize(1080, 680)
        self._fonts()
        self._style()

        self.settings = self._load_settings()
        if apply_console_default(self.settings):
            self._save_settings()
        self.geometry(self.settings.get('geometry') or '1280x800')
        reg = load_registry(ROOT_DIR)
        self.registry = reg
        self.bots = [Bot(ROOT_DIR, i) for i in reg.get('instances', [])]
        self.bot_by_name = {b.name: b for b in self.bots}
        self.tables = Tables(reg.get('openkoreRoot', r'C:\Users\silap\openkore'), ROOT_DIR)
        self.feeds: dict[str, collections.deque[tuple[float, str, str]]] = {
            b.name: collections.deque(maxlen=300) for b in self.bots}
        self.pending_start: dict[str, float] = {}
        self.add_dialog: AddBotDialog | None = None
        self._removing = False
        # auto login / recovery state (see _maybe_recover)
        self._offline_since: dict[str, float] = {}
        self._recovery_active: str | None = None
        self._recovery_attempts: dict[str, int] = {}
        self._last_recovery: dict[str, float] = {}
        self._recovery_stopped: set[str] = set()
        self._login_episode: set[str] = set()
        self._was_online: set[str] = set()      # in game since OpenKore started (a later drop = disconnect)
        self._user_stop: dict[str, float] = {}  # ⏹/✖ pressed: OpenKore may still report state 1 while exiting
        self._login_testing: set[str] = set()
        self._pid_checked: set[str] = set()
        self._pid_retry: dict[str, float] = {}
        self._warned_no_game: set[str] = set()
        # login right after "start bot" (see _maybe_startup_login)
        self._startup_login: dict[str, float] = {}     # bot -> when its OpenKore came up
        self._game_seen: dict[str, float] = {}         # bot -> when its game window was first seen
        self.kc: KConfig | None = None
        self.kc_bot: str | None = None
        self.form_vars: dict[str, tuple[str, Any, tk.Variable]] = {}
        self.log_lines: collections.deque[LogEntry] = collections.deque(maxlen=4000)
        # Worker threads must not touch Tk (not even after()); they queue callbacks for the Tk thread.
        self._ui_calls: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self.after(100, self._drain_ui_calls)

        self.notifier = Notifier(lambda: self.settings['notify'], self._notify_result)
        self.rules = Rules(self.notifier, lambda: self.settings['notify'])

        self._build()
        sel = self.settings.get('selected')
        self.selected = sel if sel in self.bot_by_name else (self.bots[0].name if self.bots else None)
        if self.selected:
            self.select_bot(self.selected, force=True)
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.monster_tab.tables = self.tables   # OpenKore names are needed even if the web data fails
        self.icons = IconCache(self._call_soon)
        self.potion_tab.icons = self.buff_item_tab.icons = self.pickup_tab.icons = self.icons
        self.trade_tab.icons = self.restock_tab.icons = self.icons
        self.pickup_tab.tables = self.trade_tab.tables = self.restock_tab.tables = self.tables
        self.potion_tab.render()
        self.buff_item_tab.render()
        self.after(200, self.poll)

    def _call_soon(self, fn: Callable[[], None]) -> None:
        """Thread-safe: run `fn` on the Tk thread within ~100 ms."""
        self._ui_calls.put(fn)

    def _drain_ui_calls(self) -> None:
        while True:
            try:
                fn = self._ui_calls.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:       # one bad callback must not stop the others or this loop
                log.exception('UI callback failed')
        self.after(100, self._drain_ui_calls)

    # --------------------------------------------------------------- layout
    def _build(self) -> None:
        side = tk.Frame(self, bg=PANEL, width=240)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        tk.Label(side, text='ROZ Bot Control', bg=PANEL, fg=TEXT, font=Fonts.F_BIG, anchor='w').pack(fill='x', padx=14, pady=(16, 2))
        tk.Label(side, text='ROZCLUB · OpenKore XKore 1', bg=PANEL, fg=MUTED, font=Fonts.F_SMALL, anchor='w').pack(fill='x', padx=14)
        tk.Frame(side, bg=BORDER, height=1).pack(fill='x', pady=12)
        self.card_box = tk.Frame(side, bg=PANEL)
        self.card_box.pack(fill='x')
        self.cards: dict[str, BotCard] = {}
        for b in self.bots:
            c = BotCard(self.card_box, self, b)
            c.pack(fill='x', pady=1)
            self.cards[b.name] = c
        manage = tk.Frame(side, bg=PANEL)
        manage.pack(fill='x', padx=12, pady=(10, 0))
        manage.columnconfigure(0, weight=1, uniform='m')
        manage.columnconfigure(1, weight=1, uniform='m')
        self.btn_add = ttk.Button(manage, text='➕ เพิ่มบอท', command=self.add_bot)
        self.btn_add.grid(row=0, column=0, sticky='ew', padx=(0, 2))
        self.btn_remove = ttk.Button(manage, text='➖ ลบบอท', command=self.remove_bot)
        self.btn_remove.grid(row=0, column=1, sticky='ew', padx=(2, 0))
        bottom = tk.Frame(side, bg=PANEL)
        bottom.pack(side='bottom', fill='x', padx=12, pady=12)
        ttk.Button(bottom, text='▶  เริ่มบอททุกตัว', style='Ok.TButton', command=self.start_all).pack(fill='x', pady=2)
        self.btn_summary = ttk.Button(bottom, text='📊  ส่งสรุปไปแจ้งเตือน', command=self.send_summary)
        self.btn_summary.pack(fill='x', pady=2)

        main = ttk.Frame(self)
        main.pack(side='left', fill='both', expand=True)
        self.statusbar = tk.Label(main, text='พร้อม', bg=BG, fg=MUTED, font=Fonts.F_SMALL, anchor='w')
        self.statusbar.pack(side='bottom', fill='x', padx=14, pady=(0, 6))
        self.nb = ttk.Notebook(main)
        self.nb.pack(fill='both', expand=True, padx=10, pady=(10, 4))
        self.tab_over = ttk.Frame(self.nb, style='Panel.TFrame')
        self.tab_conf = ttk.Frame(self.nb, style='Panel.TFrame')
        self.tab_noti = ttk.Frame(self.nb, style='Panel.TFrame')
        self.tab_log = ttk.Frame(self.nb, style='Panel.TFrame')
        self.tab_prog = ttk.Frame(self.nb, style='Panel.TFrame')
        self.nb.add(self.tab_over, text='🏠 ภาพรวม')
        self.nb.add(self.tab_conf, text='⚙️ ตั้งค่าบอท')
        # Team page: every bot's follow / party / farm map in one table (teamtab.py).
        self.team_tab = TeamTab(self.nb, self._team_sources, self._team_saved)
        self.nb.add(self.team_tab, text='👥 ทีม')
        self.nb.bind('<<NotebookTabChanged>>', lambda e: self._on_main_tab())
        self.nb.add(self.tab_noti, text='🔔 แจ้งเตือน')
        self.nb.add(self.tab_log, text='📜 บันทึก')
        self.nb.add(self.tab_prog, text='🧩 โปรแกรม')
        self._build_overview()
        self._build_config()
        self._build_notify()
        self._build_log()
        self._build_program()
        if PHASE < 3:
            self.nb.tab(self.tab_conf, state='hidden')
        if PHASE < 2:
            self.nb.tab(self.tab_noti, state='hidden')
            self.btn_summary.pack_forget()

    # ------------------------------------------------------------------ team
    def _team_sources(self) -> list[TeamSource]:
        out: list[TeamSource] = []
        for b in self.bots:
            if b.running:
                out.append(TeamSource(b.name, b.config_path, b.status, b.send))
                continue
            # Stopped: only the last known character name (so it can still be picked as a
            # leader and followers of it are not flagged); no stale map / HP / party.
            char = str((b.status or {}).get('char') or (b.read_char() or {}).get('char') or '')
            out.append(TeamSource(b.name, b.config_path, {'char': char, 'online': 0} if char else None, None))
        return out

    def _on_main_tab(self) -> None:
        if self.nb.select() == str(self.team_tab) and not self.team_tab.is_dirty():
            self.team_tab.refresh()            # read the files again: other tabs may have saved

    def _team_saved(self, bots: list[str]) -> None:
        for name in bots:
            self.add_feed(name, '👥 บันทึกการตั้งค่าทีม', 'ok')
        self.toast(f'บันทึกทีมแล้ว: {", ".join(bots)}', 'ok')
        # The config tab holds its own copy of one bot's config.txt: reload it unless it has edits.
        loaded = self.bot_by_name.get(self.kc_bot) if self.kc_bot else None
        if self.kc is not None and loaded is not None and loaded.name in bots and not self._config_dirty():
            self.load_config(bot=loaded)

    def toast(self, text: str, kind: str = 'muted') -> None:
        color = {'ok': OK, 'bad': BAD, 'warn': WARN}.get(kind, MUTED)
        self.statusbar.configure(text=f'{time.strftime("%H:%M:%S")}  {text}', fg=color)

    # ------------------------------------------------------------ selection
    def select_bot(self, name: str, force: bool = False) -> None:
        if name == self.selected and not force:
            return
        if not force and self._config_dirty():
            ans = messagebox.askyesnocancel('ยังไม่ได้บันทึก', f'บันทึกการตั้งค่าของ {self.kc_bot} ก่อนเปลี่ยนบอท?')
            if ans is None:
                return
            if ans:
                self.save_config()
        self.selected = name
        b = self.bot_by_name[name]
        for n, c in self.cards.items():
            c.refresh(n == name)
        self.feed.configure(state='normal')
        self.feed.delete('1.0', 'end')
        self.feed.configure(state='disabled')
        for ts, text, kind in self.feeds[name]:
            self._feed_append(ts, text, kind)
        # log view: refill from the file, then follow new lines
        self.log_lines.clear()
        b.log = type(b.log)(b.log.path)
        self.log_lines.extend(b.log_history())
        b.log.read()
        self.rerender_log()
        self.load_config(bot=b)
        self.refresh_overview()

    # ------------------------------------------------------------- polling
    def poll(self) -> None:
        try:
            for b in self.bots:
                b.poll_status()
                for ev in b.poll_events():
                    text, kind = event_text(ev)
                    if ev.get('type') != 'map_changed' or b.name == self.selected:
                        self.add_feed(b.name, text, kind, ev.get('ts'))
                    self.rules.handle_event(b, ev)
                self.rules.check_status(b)
                self._check_pending(b)
                self._cache_game_pid(b)
                self._maybe_startup_login(b)
                self._maybe_recover(b)
            self.rules.maybe_report(self.bots)
            cur = self.cur_bot()
            if cur:
                new = cur.poll_log()
                if new:
                    self.log_lines.extend(new)
                    self._log_insert([e for e in new if self._log_visible(e)])
            for n, c in self.cards.items():
                c.refresh(n == self.selected)
            self.refresh_overview()
        except Exception as e:      # keep the loop alive no matter what; full traceback goes to the log
            log.exception('poll loop error')
            self.toast(f'ข้อผิดพลาด: {e} (ดู gui\\gui-error.log)', 'bad')
        self.after(POLL_MS, self.poll)

    def on_close(self) -> None:
        if self._config_dirty():
            ans = messagebox.askyesnocancel('ยังไม่ได้บันทึก', f'บันทึกการตั้งค่าของ {self.kc_bot} ก่อนปิด?')
            if ans is None:
                return
            if ans:
                self.save_config()
        self.settings['geometry'] = self.geometry()
        self.settings['selected'] = self.selected
        self.settings['log_mode'] = self.log_mode.get()
        self._save_settings()   # failure is logged; closing must not be blocked by it
        self.destroy()

    # ------------------------------------------------------------- launch
    def _open_path(self, path: str) -> None:
        """Open a folder in Explorer, reporting failures instead of raising into Tk."""
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except OSError as e:
            log.warning('cannot open %s: %s', path, e)
            self.toast(f'เปิด {path} ไม่ได้: {e}', 'bad')

    def _notepad(self, path: str) -> None:
        try:
            subprocess.Popen(['notepad.exe', path])
        except OSError as e:
            log.warning('cannot start notepad for %s: %s', path, e)
            self.toast(f'เปิด Notepad ไม่ได้: {e}', 'bad')


def main() -> None:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (ImportError, AttributeError, OSError) as e:    # older Windows: blurry text, still usable
        log.warning('DPI awareness not set: %s', e)
    App().mainloop()