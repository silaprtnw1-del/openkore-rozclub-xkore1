"""ROZ Bot Control - desktop GUI for the ROZCLUB OpenKore instances."""
from __future__ import annotations

import collections
import functools
import json
import os
import re
import subprocess
import queue
import shutil
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable, Final

from .bot import Bot, LogEntry, launch_roz_start, load_registry, run_roz
from . import relogin
from .errlog import log
from .logintab import AutoLoginTab
from .monctl import load as monctl_load
from .kconfig import Block, KConfig
from .notify import (DEFAULTS as NOTIFY_DEFAULTS, EVENT_TYPES, Notifier, Rules, describe_error, summary_line,
                     telegram_find_chats)
from .ingame import BasicTab, MonsterTab
from .icons import IconCache
from .itemtab import BuffItemTab, PotionTab
from .skilltab import SkillTab
from .tabs3c import MoveTab, PickupTab
from .restocktab import RestockTab
from .statskilltab import StatSkillTab
from .tradetab import TradeTab
from .rozdb import RozDB
from .tables import Tables

# ----------------------------------------------------------------- palette
BG = '#15171c'
PANEL = '#1d2027'
PANEL2 = '#252932'
FIELD = '#2b303b'
BORDER = '#343a47'
TEXT = '#e8eaf0'
MUTED = '#8e96aa'
ACCENT = '#4f8cff'
ACCENT_D = '#3a6fd1'
OK = '#3ecf8e'
WARN = '#f5b942'
BAD = '#ff5d5d'
C_HP, C_SP, C_EXP, C_JOB, C_W = '#e5484d', '#3e8bff', '#f5b942', '#a36bff', '#3ecf8e'
STATE_COLORS: Final[dict[str, str]] = {'ok': OK, 'warn': WARN, 'bad': BAD, 'off': '#5b6273'}

POLL_MS: Final[int] = 1000
# After "start bot": give up waiting for the game window this long past boot_delay.
STARTUP_LOGIN_GIVEUP_SECONDS: Final[float] = 120.0
USER_STOP_GRACE_SECONDS: Final[float] = 90.0   # after ⏹/✖ a drop to the login screen is not a disconnect
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

# ------------------------------------------------------- settings form spec
# (section, key, label, kind, options, help)
FormField = tuple[str, str, str, Any, str]   # key, label, kind, options, help
FORM: Final[list[tuple[str, list[FormField]]]] = [
    ('🗺️ พื้นที่ฟาร์ม', [
        ('lockMap', 'แผนที่ฟาร์ม', 'map', None, 'บอทจะเดินไปฟาร์มที่แผนที่นี้'),
        ('saveMap', 'เมืองเซฟ', 'map', None, 'เมืองที่กลับไปขาย / ฝากของ'),
        ('route_randomWalk', 'เดินสุ่มหามอน', 'bool', None, 'เดินไปเรื่อย ๆ ในแผนที่เพื่อหามอน'),
        ('attackAuto_inLockOnly', 'ตีเฉพาะในแผนที่ฟาร์ม', 'bool', None, 'ระหว่างเดินทางจะไม่แวะตีมอน'),
    ]),
    # attackAuto / attackUseWeapon / sitAuto_* / itemsMaxWeight* live in the in-game style
    # "พื้นฐาน" tab (ingame.BasicTab); listing them here too would let two widgets write one key.
    ('⚔️ การต่อสู้', [
        ('attackAuto_party', 'ช่วยตีมอนที่ตีปาร์ตี้', 'bool', None, ''),
        ('attackDistance', 'ระยะโจมตี', 'num', (0, 15, 0.5), '1.5 = ประชิด, 9+ = ยิงไกล / เวท'),
        ('attackMaxDistance', 'ระยะโจมตีสูงสุด', 'num', (0, 15, 0.5), 'ควรมากกว่าระยะโจมตีเล็กน้อย'),
        ('attackChangeTarget', 'เปลี่ยนเป้าเมื่อมีมอนตีเรา', 'bool', None, ''),
    ]),
    # itemsTakeAuto / itemsGatherAuto ("ไม่เก็บเลย") are owned by tabs3c.PickupTab,
    # teleportAuto_hp / minAggressives / idle by tabs3c.MoveTab and sellAuto(_npc) /
    # storageAuto(_npc) by tradetab.TradeTab: one widget per key.
    ('🛡️ ความปลอดภัย', [
        ('dcOnPM', 'ออกเกมทันทีเมื่อมีคน PM', 'bool', None, ''),
    ]),
]

BLOCK_TYPES: Final[dict[str, str]] = {
    'useSelf_item': 'ใช้ไอเทม / ยา',
    'useSelf_skill': 'สกิลใส่ตัวเอง (บัฟ/ฮีล)',
    'attackSkillSlot': 'สกิลโจมตี',
    'partySkill': 'สกิลใส่ปาร์ตี้',
    'buyAuto': 'ซื้อของอัตโนมัติ',
    'getAuto': 'เบิกของจากคลัง',
    'equipAuto': 'สวมอุปกรณ์อัตโนมัติ',
    'monsterSkill': 'สกิลตามชนิดมอน',
    'doCommand': 'สั่งคำสั่งตามเงื่อนไข',
}
BLOCK_TEMPLATES: Final[list[tuple[str, str, str, str]]] = [
    ('💊 ยาฟื้น HP', 'useSelf_item', 'Red Potion', 'hp < 50%\ntimeout 1\ndisabled 0'),
    ('🔷 ยาฟื้น SP', 'useSelf_item', 'Blue Potion', 'sp < 30%\ntimeout 2\ndisabled 0'),
    ('✨ บัฟตัวเอง', 'useSelf_skill', 'Increase AGI',
     'lvl 10\nsp > 30%\nwhenStatusInactive Increase AGI\nnotInTown 1\ntimeout 5\ndisabled 0'),
    ('🗡️ สกิลโจมตี', 'attackSkillSlot', 'Bash', 'lvl 10\ndist 1.5\nsp > 20%\nmaxUses 0\ndisabled 0'),
    ('🛒 ซื้อของ', 'buyAuto', 'Fly Wing', 'npc payon 159 96\ndistance 5\nminAmount 10\nmaxAmount 50\ndisabled 0'),
    ('📦 เบิกของจากคลัง', 'getAuto', 'Fly Wing', 'minAmount 10\nmaxAmount 50\npassive 0\ndisabled 0'),
]
BLOCK_HELP: Final[dict[str, str]] = {
    'useSelf_item': 'ค่าที่ใช้บ่อย: hp < 50%  ·  sp < 30%  ·  timeout 1  ·  notInTown 1  ·  inLockOnly 1\n'
                    'whenStatusInactive <ชื่อสถานะ>  ·  onAction attack  ·  disabled 1 (ปิดไว้)',
    'useSelf_skill': 'lvl 10  ·  sp > 30%  ·  hp < 60%  ·  whenStatusInactive <ชื่อบัฟ>  ·  notInTown 1  ·  timeout 5',
    'attackSkillSlot': 'lvl 10  ·  dist 1.5  ·  sp > 20%  ·  maxUses 1  ·  monsters Poring, Lunatic  ·  target_hp > 50%',
    'buyAuto': 'npc <map> <x> <y>  ·  distance 5  ·  minAmount 10  ·  maxAmount 50  ·  price 250  ·  zeny > 10000',
    'getAuto': 'minAmount 10  ·  maxAmount 50  ·  passive 0',
}

IMPORTANT_DOMAINS: Final[set[str]] = {
    'pm', 'pm/sent', 'publicchat', 'partychat', 'guildchat', 'schat', 'selfchat', 'drop',
    # 'exp' left out on purpose: one "You have gained ..." line per kill floods this view;
    # level-ups still arrive as events. The "all" filter shows them.
    'connection', 'success', 'teleport', 'storage', 'npc', 'system', 'xkore', 'deal', 'party',
}
LOG_TAG: Final[dict[str, str]] = {'error': 'err', 'warning': 'warn'}
CHAT_DOMAINS: Final[set[str]] = {'pm', 'pm/sent', 'publicchat', 'partychat', 'guildchat', 'schat', 'selfchat'}


def fmt_int(n: Any) -> str:
    try:
        return f'{int(n):,}'
    except (TypeError, ValueError):
        return '-'


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


# ===================================================================== widgets
class Bar(tk.Canvas):
    def __init__(self, master: tk.Misc, label: str, color: str, height: int = 22) -> None:
        super().__init__(master, height=height, bg=PANEL, highlightthickness=0, bd=0)
        self.label, self.color, self.h = label, color, height
        self.cur: float = 0
        self.mx: float = 0
        self.extra: str = ''
        self.bind('<Configure>', lambda e: self.redraw())

    def set(self, cur: float | None, mx: float | None, extra: str = '') -> None:
        self.cur, self.mx, self.extra = cur or 0, mx or 0, extra
        self.redraw()

    def redraw(self) -> None:
        self.delete('all')
        w = max(self.winfo_width(), 10)
        h = self.h
        self.create_rectangle(0, 0, w, h, fill=FIELD, outline='')
        frac = (self.cur / self.mx) if self.mx else 0
        frac = max(0.0, min(1.0, frac))
        if frac > 0:
            self.create_rectangle(0, 0, int(w * frac), h, fill=self.color, outline='')
        txt = f'{self.label}  {fmt_int(self.cur)} / {fmt_int(self.mx)}  ({frac * 100:.1f}%)' if self.mx else f'{self.label}  -'
        if self.extra:
            txt += f'   {self.extra}'
        self.create_text(10, h // 2, text=txt, anchor='w', fill='#ffffff', font=App.F_SMALLB)


class Scrollable(ttk.Frame):
    """A vertically scrolling frame (mouse wheel works while hovered)."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.vsb.pack(side='right', fill='y')
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.bind_all_wheel()

    def bind_all_wheel(self) -> None:
        def wheel(e: tk.Event) -> None:
            self.canvas.yview_scroll(int(-e.delta / 120), 'units')
        self.canvas.bind('<Enter>', lambda e: self.canvas.bind_all('<MouseWheel>', wheel))
        self.canvas.bind('<Leave>', lambda e: self.canvas.unbind_all('<MouseWheel>'))


class BotCard(tk.Frame):
    def __init__(self, master: tk.Misc, app: App, bot: Bot) -> None:
        super().__init__(master, bg=PANEL, cursor='hand2', padx=12, pady=9)
        self.app, self.bot = app, bot
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill='x')
        self.top = top
        self.dot =tk.Canvas(top, width=12, height=12, bg=PANEL, highlightthickness=0)
        self.dot.pack(side='left', padx=(0, 8))
        self.title = tk.Label(top, text=bot.name, bg=PANEL, fg=TEXT, font=App.F_BOLD, anchor='w')
        self.title.pack(side='left', fill='x')
        self.sub = tk.Label(self, text='', bg=PANEL, fg=MUTED, font=App.F_SMALL, anchor='w', justify='left')
        self.sub.pack(fill='x', pady=(3, 0))
        for w in (self, top, self.dot, self.title, self.sub):
            w.bind('<Button-1>', lambda e: app.select_bot(bot.name))

    def refresh(self, selected: bool) -> None:
        bg = PANEL2 if selected else PANEL
        for w in (self, self.dot, self.title, self.sub, self.top):
            w.configure(bg=bg)
        text, kind = self.bot.state_text()
        self.dot.delete('all')
        self.dot.create_oval(1, 1, 11, 11, fill=STATE_COLORS[kind], outline='')
        s = self.bot.status if self.bot.running else None
        if s and s.get('online'):
            self.sub.configure(text=f'{s.get("char")} · Lv {s.get("level")}\n{s.get("map")} · {text}')
        else:
            self.sub.configure(text=f'{self.bot.role or "bot"} · port {self.bot.port}\n{text}')


_NAME_RE: Final[re.Pattern[str]] = re.compile(r'^[a-z0-9_][a-z0-9_-]*$')


def roz_error_text(out: str) -> str:
    """Thai hint for the usual roz.ps1 new/remove failures ('' if unknown)."""
    low = out.lower()
    if 'folder already exists' in low:
        return 'มีโฟลเดอร์โปรไฟล์ชื่อนี้อยู่แล้ว — เปลี่ยนชื่อบอท'
    if 'already exists' in low:
        return 'ชื่อบอทนี้มีอยู่แล้ว — เปลี่ยนชื่อ'
    if 'already used by another instance' in low or 'is already used' in low:
        return 'Port นี้ถูกใช้อยู่ — เลือกพอร์ตอื่น หรือให้เลือกอัตโนมัติ'
    if 'needs -follow' in low:
        return 'Support ต้องเลือกบอทที่จะเดินตาม'
    if 'is running' in low:
        return 'บอทตัวนี้ยังรันอยู่ — ปิดบอทก่อนแล้วค่อยลบ'
    if 'bad name' in low:
        return 'ชื่อบอทไม่ถูกต้อง — ใช้ a-z, 0-9, _ และ -'
    return ''


class AddBotDialog(tk.Toplevel):
    """➕ เพิ่มบอท: fills in `roz.ps1 new`, then reloads the sidebar list."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.app = app
        self.title('เพิ่มบอท')
        self.configure(bg=PANEL)
        self.transient(app)
        self.resizable(False, False)
        self._running = False
        # (label shown in a combobox, value passed to roz.ps1). For Support the value
        # must be the CHARACTER name (followTarget), not the instance name.
        self._chars: list[tuple[str, str]] = []
        for b in app.bots:
            st = b.status if b.running else None
            char = str(st.get('char') or '') if st else ''
            if not char:                      # offline: last known character from char.json
                cj = b.read_char()
                char = str(cj.get('char') or '') if cj else ''
            label = f'{b.name} — {char}' if char and char != b.name else b.name
            self._chars.append((label, char or b.name))
        self._bots: list[tuple[str, str]] = [(f'{b.name} — {b.role or "bot"}', b.name) for b in app.bots]

        body = ttk.Frame(self, style='Panel.TFrame', padding=16)
        body.pack(fill='both', expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text='ชื่อบอท', style='Panel.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 4))
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(body, textvariable=self.name_var, width=36)
        self.name_entry.grid(row=0, column=1, sticky='ew', pady=(0, 4))
        ttk.Label(body, text='ใช้ได้เฉพาะ a-z, 0-9, _ และ - · เริ่มด้วยตัวอักษรหรือ _',
                  style='PanelMuted.TLabel').grid(row=1, column=1, sticky='w')

        mode = ttk.LabelFrame(body, text=' แบบ ', padding=(10, 6))
        mode.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(12, 4))
        mode.columnconfigure(1, weight=1)
        self.mode_var = tk.StringVar(value='clone' if app.bots else 'support')
        self.rb_clone = ttk.Radiobutton(mode, text='คัดลอกการตั้งค่าจากบอทที่มีอยู่', value='clone',
                                        variable=self.mode_var, command=self._mode_changed)
        self.rb_clone.grid(row=0, column=0, sticky='w', pady=2)
        self.clone_var = tk.StringVar(value=self._bots[0][0] if self._bots else '')
        self.clone_box = ttk.Combobox(mode, textvariable=self.clone_var, state='readonly',
                                      values=[lab for lab, _ in self._bots], width=28)
        self.clone_box.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=2)
        self.rb_support = ttk.Radiobutton(mode, text='Support — เดินตาม ฮีล และบัฟบอทที่เลือก',
                                          value='support', variable=self.mode_var, command=self._mode_changed)
        self.rb_support.grid(row=1, column=0, sticky='w', pady=2)
        self.follow_var = tk.StringVar(value=self._chars[0][0] if self._chars else '')
        self.follow_box = ttk.Combobox(mode, textvariable=self.follow_var, state='readonly',
                                       values=[lab for lab, _ in self._chars], width=28)
        self.follow_box.grid(row=1, column=1, sticky='w', padx=(10, 0), pady=2)
        ttk.Label(mode, text='บอทสายตี (farmer) ต้องคัดลอกจากบอทที่มีอยู่ เพราะ roz.ps1 มีแม่แบบแค่สาย Support',
                  style='PanelMuted.TLabel', wraplength=520, justify='left').grid(
            row=2, column=0, columnspan=2, sticky='w', pady=(6, 0))
        if not app.bots:
            ttk.Label(mode, text='ยังไม่มีบอทให้คัดลอกหรือเดินตาม — ต้องมีบอทอย่างน้อย 1 ตัวก่อน',
                      style='PanelMuted.TLabel', foreground=WARN, wraplength=520,
                      justify='left').grid(row=3, column=0, columnspan=2, sticky='w', pady=(6, 0))

        portf = ttk.LabelFrame(body, text=' Port ', padding=(10, 6))
        portf.grid(row=3, column=0, columnspan=2, sticky='ew', pady=4)
        self.port_auto = tk.IntVar(value=1)
        self.rb_auto = ttk.Radiobutton(portf, text='เลือกให้อัตโนมัติ', value=1,
                                       variable=self.port_auto, command=self._port_changed)
        self.rb_auto.grid(row=0, column=0, sticky='w')
        self.rb_manual = ttk.Radiobutton(portf, text='กำหนดเอง', value=0,
                                         variable=self.port_auto, command=self._port_changed)
        self.rb_manual.grid(row=0, column=1, sticky='w', padx=(18, 0))
        self.port_var = tk.StringVar(value=str(self._next_port()))
        self.port_spin = ttk.Spinbox(portf, from_=1024, to=65535, increment=1,
                                     textvariable=self.port_var, width=8, command=self._update_preview)
        self.port_spin.grid(row=0, column=2, sticky='w', padx=(8, 0))
        self.port_spin.configure(state='disabled')

        self.preview = ttk.Label(body, text='', style='PanelMuted.TLabel', font=App.F_MONO,
                                 wraplength=560, justify='left')
        self.preview.grid(row=4, column=0, columnspan=2, sticky='w', pady=(6, 2))

        outf = ttk.Frame(body, style='Panel.TFrame')
        outf.grid(row=5, column=0, columnspan=2, sticky='nsew', pady=(6, 2))
        outf.columnconfigure(0, weight=1)
        self.out = tk.Text(outf, height=8, width=64, bg=BG, fg=TEXT, relief='flat',
                           font=App.F_MONO, padx=8, pady=6, state='disabled', wrap='word')
        vsb = ttk.Scrollbar(outf, orient='vertical', command=self.out.yview)
        self.out.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky='ns')
        self.out.grid(row=0, column=0, sticky='nsew')

        self.status_lbl = ttk.Label(body, text='', style='PanelMuted.TLabel', foreground=MUTED,
                                    wraplength=560, justify='left')
        self.status_lbl.grid(row=6, column=0, columnspan=2, sticky='w', pady=(4, 0))

        btns = ttk.Frame(body, style='Panel.TFrame')
        btns.grid(row=7, column=0, columnspan=2, sticky='e', pady=(10, 0))
        self.btn_cancel = ttk.Button(btns, text='ยกเลิก', command=self._cancel)
        self.btn_cancel.pack(side='right', padx=(6, 0))
        self.btn_ok = ttk.Button(btns, text='สร้างบอท', style='Accent.TButton', command=self._submit)
        self.btn_ok.pack(side='right')

        self.name_var.trace_add('write', lambda *a: self._update_preview())
        self.clone_var.trace_add('write', lambda *a: self._update_preview())
        self.follow_var.trace_add('write', lambda *a: self._update_preview())
        self.port_var.trace_add('write', lambda *a: self._update_preview())
        self.name_entry.bind('<Return>', lambda e: self._submit())
        self.bind('<Escape>', lambda e: self._cancel())
        self.wm_protocol('WM_DELETE_WINDOW', self._cancel)
        self._mode_changed()
        self._update_preview()
        self.update_idletasks()
        x = app.winfo_rootx() + max(0, (app.winfo_width() - self.winfo_width()) // 2)
        y = app.winfo_rooty() + max(0, (app.winfo_height() - self.winfo_height()) // 3)
        self.geometry(f'+{x}+{y}')
        self.grab_set()
        self.name_entry.focus_set()

    # ------------------------------------------------------------------ form
    def _next_port(self) -> int:
        used = {b.port for b in self.app.bots}
        port = max(used, default=1023) + 1
        while port in used:
            port += 1
        return port

    @staticmethod
    def _pick(choices: list[tuple[str, str]], label: str) -> str:
        return next((value for lab, value in choices if lab == label), '')

    def _update_preview(self) -> None:
        if not hasattr(self, 'preview'):
            return
        name = self.name_var.get().strip() or '<ชื่อ>'
        if self.mode_var.get() == 'clone':
            src = self._pick(self._bots, self.clone_var.get()) or '<บอทต้นแบบ>'
            args = f'new {name} -CloneFrom {src}'
        else:
            fol = self._pick(self._chars, self.follow_var.get()) or '<บอทที่จะเดินตาม>'
            args = f'new {name} -Follow {fol}'
        if not self.port_auto.get():
            args += f' -Port {self.port_var.get().strip() or "<port>"}'
        self.preview.configure(text=f'คำสั่ง:  roz.ps1 {args}')

    def _mode_changed(self) -> None:
        clone = self.mode_var.get() == 'clone'
        self.clone_box.configure(state='readonly' if clone else 'disabled')
        self.follow_box.configure(state='disabled' if clone else 'readonly')
        self._update_preview()

    def _port_changed(self) -> None:
        self.port_spin.configure(state='disabled' if self.port_auto.get() else 'normal')
        self._update_preview()

    def _args(self) -> list[str]:
        name = self.name_var.get().strip()
        if not name:
            raise ValueError('ใส่ชื่อบอท')
        if not _NAME_RE.match(name):
            raise ValueError('ชื่อบอทใช้ได้เฉพาะ a-z, 0-9, _ และ - (เริ่มด้วยตัวอักษรหรือ _)')
        if any(b.name.lower() == name.lower() for b in self.app.bots):
            raise ValueError(f'มีบอทชื่อ {name} อยู่แล้ว')
        args = ['new', name]
        if self.mode_var.get() == 'clone':
            src = self._pick(self._bots, self.clone_var.get())
            if not src:
                raise ValueError('เลือกบอทที่จะคัดลอกการตั้งค่า')
            args += ['-CloneFrom', src]
        else:
            fol = self._pick(self._chars, self.follow_var.get())
            if not fol:
                raise ValueError('เลือกบอทที่จะเดินตาม')
            args += ['-Follow', fol]
        if not self.port_auto.get():
            raw = self.port_var.get().strip()
            if not raw.isdigit():
                raise ValueError('Port ต้องเป็นตัวเลข 1024–65535')
            port = int(raw)
            if not 1024 <= port <= 65535:
                raise ValueError('Port ต้องอยู่ระหว่าง 1024–65535')
            if any(b.port == port for b in self.app.bots):
                raise ValueError(f'Port {port} ถูกใช้โดยบอทอื่นแล้ว')
            args += ['-Port', str(port)]
        return args

    # ------------------------------------------------------------------ run
    def _submit(self) -> None:
        if self._running:
            return
        try:
            args = self._args()
        except ValueError as e:
            self._status(str(e), BAD)
            return
        name = args[1]
        self._running = True
        self._inputs(False)
        self._status('กำลังสร้างบอท... (roz.ps1 new)', MUTED)
        self._append(f'> roz.ps1 {" ".join(args)}\n')

        def work() -> None:
            code, out = run_roz(ROOT_DIR, args)
            self.app._call_soon(lambda: self._done(name, code, out))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, name: str, code: int, out: str) -> None:
        self._running = False
        self._append((out or '(ไม่มีข้อความจาก roz.ps1)') + '\n')
        if code == 0:
            self._status(f'สร้างบอท {name} แล้ว — กด ▶ เริ่มบอท ที่แถบซ้ายเพื่อล็อกอิน', OK)
            self.grab_release()
            self.app.reload_registry(select=name)
            self.btn_cancel.pack_forget()
            self.btn_ok.configure(text='ปิด', command=self._close)
            self.btn_ok.state(['!disabled'])
        else:
            hint = roz_error_text(out)
            self._status(f'สร้างไม่สำเร็จ (exit {code})' + (f'\n{hint}' if hint else ''), BAD)
            self._inputs(True)

    def _inputs(self, enabled: bool) -> None:
        for w in (self.name_entry, self.rb_clone, self.rb_support, self.rb_auto, self.rb_manual):
            w.configure(state='normal' if enabled else 'disabled')
        if enabled:
            self._mode_changed()
            self._port_changed()
            self.btn_ok.state(['!disabled'])
            self.btn_cancel.state(['!disabled'])
        else:
            for w in (self.clone_box, self.follow_box, self.port_spin):
                w.configure(state='disabled')
            self.btn_ok.state(['disabled'])
            self.btn_cancel.state(['disabled'])

    def _status(self, text: str, color: str) -> None:
        self.status_lbl.configure(text=text, foreground=color)

    def _append(self, text: str) -> None:
        self.out.configure(state='normal')
        self.out.insert('end', text)
        self.out.see('end')
        self.out.configure(state='disabled')

    def _close(self) -> None:
        if self._running:
            return
        if self.app.add_dialog is self:
            self.app.add_dialog = None
        self.destroy()

    def _cancel(self) -> None:
        self._close()


# ======================================================================== app
class App(tk.Tk):
    # Font tuples, filled in by _fonts() once Tk exists.
    F_BASE: Any = None
    F_SMALL: Any = None
    F_SMALLB: Any = None
    F_BOLD: Any = None
    F_TITLE: Any = None
    F_BIG: Any = None
    F_MONO: Any = None

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

    # ------------------------------------------------------------- styling
    def _fonts(self) -> None:
        fams = set(tkfont.families())
        fam = next((f for f in ('Leelawadee UI', 'Leelawadee', 'Segoe UI', 'Tahoma') if f in fams), 'TkDefaultFont')
        mono = next((f for f in ('Cascadia Mono', 'Consolas', 'Courier New') if f in fams), 'TkFixedFont')
        App.F_BASE = (fam, 10)
        App.F_SMALL = (fam, 9)
        App.F_SMALLB = (fam, 9, 'bold')
        App.F_BOLD = (fam, 10, 'bold')
        App.F_TITLE = (fam, 16, 'bold')
        App.F_BIG = (fam, 13, 'bold')
        App.F_MONO = (mono, 9)
        # Named defaults instead of option_add('*Font'): that would override ttk style fonts.
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont', 'TkCaptionFont'):
            try:
                tkfont.nametofont(name).configure(family=fam, size=10)
            except tk.TclError as e:    # that named font is missing on this Tk build: keep its default
                log.warning('font %s not configured: %s', name, e)

    def _style(self) -> None:
        st = ttk.Style(self)
        st.theme_use('clam')
        st.configure('.', background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=BORDER,
                     lightcolor=BORDER, darkcolor=BORDER, troughcolor=PANEL, focuscolor=ACCENT,
                     selectbackground=ACCENT, selectforeground='#ffffff', insertcolor=TEXT, font=App.F_BASE)
        st.configure('TFrame', background=BG)
        st.configure('Panel.TFrame', background=PANEL)
        st.configure('TLabel', background=BG, foreground=TEXT)
        st.configure('Panel.TLabel', background=PANEL)
        st.configure('Muted.TLabel', foreground=MUTED, font=App.F_SMALL)
        st.configure('PanelMuted.TLabel', background=PANEL, foreground=MUTED, font=App.F_SMALL)
        st.configure('Title.TLabel', font=App.F_TITLE)
        st.configure('PanelTitle.TLabel', background=PANEL, font=App.F_TITLE)
        st.configure('Big.TLabel', background=PANEL, font=App.F_BIG)
        st.configure('H.TLabel', font=App.F_BOLD)
        st.configure('TButton', background=PANEL2, foreground=TEXT, padding=(12, 6), borderwidth=0)
        st.map('TButton', background=[('pressed', BORDER), ('active', '#30353f'), ('disabled', PANEL)],
               foreground=[('disabled', '#5b6273')])
        for name, c, ca in (('Accent', ACCENT, ACCENT_D), ('Ok', '#23a26b', '#1d8a5b'), ('Danger', '#c93c3c', '#a83232')):
            st.configure(f'{name}.TButton', background=c, foreground='#ffffff')
            st.map(f'{name}.TButton', background=[('pressed', ca), ('active', ca)])
        st.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
        st.configure('TNotebook.Tab', background=BG, foreground=MUTED, padding=(16, 8), borderwidth=0)
        st.map('TNotebook.Tab', background=[('selected', PANEL)], foreground=[('selected', TEXT)])
        st.configure('TLabelframe', background=PANEL, bordercolor=BORDER, relief='solid', borderwidth=1)
        st.configure('TLabelframe.Label', background=PANEL, foreground=TEXT, font=App.F_BOLD)
        for w in ('TCheckbutton', 'TRadiobutton'):
            st.configure(w, background=PANEL, foreground=TEXT, indicatorbackground=FIELD,
                         indicatorforeground='#ffffff', indicatorrelief='flat')
            st.map(w, background=[('active', PANEL)], indicatorbackground=[('selected', ACCENT), ('active', BORDER)])
        st.configure('Bg.TCheckbutton', background=BG)
        st.map('Bg.TCheckbutton', background=[('active', BG)])
        st.configure('Bg.TRadiobutton', background=BG)
        st.map('Bg.TRadiobutton', background=[('active', BG)])
        st.configure('TEntry', fieldbackground=FIELD, foreground=TEXT, padding=5, borderwidth=0)
        st.configure('TSpinbox', fieldbackground=FIELD, foreground=TEXT, padding=4, arrowcolor=TEXT,
                     background=PANEL2, borderwidth=0)
        st.configure('TCombobox', fieldbackground=FIELD, foreground=TEXT, padding=4, arrowcolor=TEXT,
                     background=PANEL2, borderwidth=0)
        st.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', TEXT)],
               selectbackground=[('readonly', FIELD)], selectforeground=[('readonly', TEXT)])
        self.option_add('*TCombobox*Listbox.background', FIELD)
        self.option_add('*TCombobox*Listbox.foreground', TEXT)
        self.option_add('*TCombobox*Listbox.selectBackground', ACCENT)
        self.option_add('*TCombobox*Listbox.font', App.F_BASE)
        st.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=28, borderwidth=0)
        st.configure('Pickup.Treeview', rowheight=36)       # room for 32 px item icons
        st.map('Treeview', background=[('selected', '#2f4a7a')])
        st.configure('Treeview.Heading', background=PANEL2, foreground=MUTED, borderwidth=0, padding=6)
        st.configure('Vertical.TScrollbar', background=PANEL2, troughcolor=BG, arrowcolor=MUTED, borderwidth=0,
                     bordercolor=BG, lightcolor=PANEL2, darkcolor=PANEL2, gripcount=0)
        st.map('Vertical.TScrollbar', background=[('active', BORDER)])

    # --------------------------------------------------------------- layout
    def _build(self) -> None:
        side = tk.Frame(self, bg=PANEL, width=240)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        tk.Label(side, text='ROZ Bot Control', bg=PANEL, fg=TEXT, font=App.F_BIG, anchor='w').pack(fill='x', padx=14, pady=(16, 2))
        tk.Label(side, text='ROZCLUB · OpenKore XKore 1', bg=PANEL, fg=MUTED, font=App.F_SMALL, anchor='w').pack(fill='x', padx=14)
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
        self.statusbar = tk.Label(main, text='พร้อม', bg=BG, fg=MUTED, font=App.F_SMALL, anchor='w')
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

    def toast(self, text: str, kind: str = 'muted') -> None:
        color = {'ok': OK, 'bad': BAD, 'warn': WARN}.get(kind, MUTED)
        self.statusbar.configure(text=f'{time.strftime("%H:%M:%S")}  {text}', fg=color)

    # ------------------------------------------------------------- overview
    def _build_overview(self) -> None:
        f = self.tab_over
        padx = 18
        head = ttk.Frame(f, style='Panel.TFrame')
        head.pack(fill='x', pady=(16, 4), padx=padx)
        self.o_name = ttk.Label(head, text='-', style='PanelTitle.TLabel')
        self.o_name.pack(side='left')
        self.o_state = tk.Label(head, text='', bg=PANEL2, fg=TEXT, font=App.F_SMALLB, padx=10, pady=3)
        self.o_state.pack(side='left', padx=12)
        self.o_where = ttk.Label(head, text='', style='Big.TLabel')
        self.o_where.pack(side='right')
        self.o_sub = ttk.Label(f, text='', style='PanelMuted.TLabel')
        self.o_sub.pack(fill='x', padx=padx)

        bars = ttk.Frame(f, style='Panel.TFrame')
        bars.pack(fill='x', pady=(12, 6), padx=padx)
        self.b_hp = Bar(bars, 'HP', C_HP)
        self.b_sp = Bar(bars, 'SP', C_SP)
        self.b_exp = Bar(bars, 'Base EXP', C_EXP)
        self.b_job = Bar(bars, 'Job EXP', C_JOB)
        self.b_w = Bar(bars, 'น้ำหนัก', C_W)
        for b in (self.b_hp, self.b_sp, self.b_exp, self.b_job, self.b_w):
            b.pack(fill='x', pady=3)

        tiles = ttk.Frame(f, style='Panel.TFrame')
        tiles.pack(fill='x', pady=6, padx=padx)
        self.tiles: dict[str, tk.Label] = {}
        names = [('zeny', 'Zeny'), ('eph', 'Base EXP / ชม.'), ('jph', 'Job EXP / ชม.'), ('zgain', 'Zeny ที่ได้ (รอบนี้)'),
                 ('mon', 'มอนรอบตัว'), ('ply', 'ผู้เล่นรอบตัว'), ('lock', 'แผนที่ฟาร์ม'), ('act', 'กำลังทำ')]
        for i, (k, lab) in enumerate(names):
            box = tk.Frame(tiles, bg=PANEL2, padx=12, pady=8)
            box.grid(row=i // 4, column=i % 4, sticky='nsew', padx=3, pady=3)
            tk.Label(box, text=lab, bg=PANEL2, fg=MUTED, font=App.F_SMALL, anchor='w').pack(fill='x')
            v = tk.Label(box, text='-', bg=PANEL2, fg=TEXT, font=App.F_BIG, anchor='w')
            v.pack(fill='x')
            self.tiles[k] = v
        for c in range(4):
            tiles.columnconfigure(c, weight=1, uniform='t')

        ctl = ttk.Frame(f, style='Panel.TFrame')
        ctl.pack(fill='x', pady=(10, 4), padx=padx)
        row1 = ttk.Frame(ctl, style='Panel.TFrame')
        row1.pack(fill='x', pady=2)
        ttk.Label(row1, text='บอท', style='PanelMuted.TLabel', width=8).pack(side='left')
        self.btn_start = ttk.Button(row1, text='▶ เริ่มบอท', style='Ok.TButton', command=self.start_selected)
        self.btn_start.pack(side='left', padx=2)
        ttk.Button(row1, text='⏹ ปิดบอท', command=self.stop_selected).pack(side='left', padx=2)
        ttk.Button(row1, text='✖ บังคับปิด', style='Danger.TButton', command=self.kill_selected).pack(side='left', padx=2)
        ttk.Label(row1, text='   AI', style='PanelMuted.TLabel').pack(side='left', padx=(16, 6))
        ttk.Button(row1, text='▶ ออโต้', style='Accent.TButton', command=lambda: self.cmd('ai on', 'เปิด AI ออโต้')).pack(side='left', padx=2)
        ttk.Button(row1, text='⏸ หยุดชั่วคราว', command=lambda: self.cmd('ai manual', 'AI โหมด manual')).pack(side='left', padx=2)
        ttk.Button(row1, text='⏹ ปิด AI', command=lambda: self.cmd('ai off', 'ปิด AI')).pack(side='left', padx=2)

        row2 = ttk.Frame(ctl, style='Panel.TFrame')
        row2.pack(fill='x', pady=2)
        ttk.Label(row2, text='สั่งงาน', style='PanelMuted.TLabel', width=8).pack(side='left')
        for label, command, desc in (('🌀 วาร์ป', 'tele', 'วาร์ป'), ('🏠 กลับจุดเซฟ', 'respawn', 'กลับจุดเซฟ'),
                                     ('📦 ไปฝากของ', 'autostorage', 'ไปฝากของ'), ('💰 ไปขายของ', 'autosell', 'ไปขายของ'),
                                     ('🛒 ไปซื้อของ', 'autobuy', 'ไปซื้อของ')):
            ttk.Button(row2, text=label, command=functools.partial(self.cmd, command, desc)).pack(side='left', padx=2)
        ttk.Button(row2, text='🪑 นั่ง/ยืน', command=self.toggle_sit).pack(side='left', padx=2)
        ttk.Button(row2, text='🔄 โหลด config ใหม่', command=lambda: self.cmd('reload config', 'โหลด config ใหม่')).pack(side='left', padx=2)

        row3 = ttk.Frame(ctl, style='Panel.TFrame')
        row3.pack(fill='x', pady=(6, 2))
        ttk.Label(row3, text='คำสั่ง', style='PanelMuted.TLabel', width=8).pack(side='left')
        self.cmd_var = tk.StringVar()
        e = ttk.Entry(row3, textvariable=self.cmd_var)
        e.pack(side='left', fill='x', expand=True, padx=2)
        e.bind('<Return>', lambda ev: self.send_custom())
        ttk.Button(row3, text='ส่ง', style='Accent.TButton', command=self.send_custom).pack(side='left', padx=2)

        ttk.Label(f, text='เหตุการณ์ล่าสุด', style='Panel.TLabel', font=App.F_BOLD).pack(anchor='w', pady=(12, 4), padx=padx)
        self.feed = tk.Text(f, bg=BG, fg=TEXT, relief='flat', height=8, wrap='word', padx=10, pady=8,
                            font=App.F_BASE, state='disabled', cursor='arrow')
        self.feed.pack(fill='both', expand=True, pady=(0, 14), padx=padx)
        for tag, color in (('ok', OK), ('bad', BAD), ('warn', WARN), ('info', '#7cc7ff'), ('muted', MUTED), ('time', '#5b6273')):
            self.feed.tag_configure(tag, foreground=color)

    def add_feed(self, bot_name: str, text: str, kind: str = 'muted', ts: float | None = None) -> None:
        self.feeds[bot_name].append((ts or time.time(), text, kind))
        if bot_name == self.selected:
            self._feed_append(ts or time.time(), text, kind)

    def _feed_append(self, ts: float, text: str, kind: str) -> None:
        self.feed.configure(state='normal')
        self.feed.insert('1.0', f'{text}\n', kind)
        self.feed.insert('1.0', time.strftime('%H:%M:%S  ', time.localtime(ts)), 'time')
        if int(self.feed.index('end-1c').split('.')[0]) > 300:
            self.feed.delete('300.0', 'end')
        self.feed.configure(state='disabled')

    def refresh_overview(self) -> None:
        b = self.cur_bot()
        if not b:
            return
        text, kind = b.state_text()
        self.o_state.configure(text=text, bg=STATE_COLORS[kind], fg='#0f1115' if kind != 'off' else TEXT)
        s = b.status if b.running else None
        if s and s.get('online'):
            self.o_name.configure(text=f'{s.get("char") or b.name}')
            job = s.get('job') or ''
            party = f' · ปาร์ตี้ {s["party"]}' if s.get('party') else ''
            self.o_sub.configure(text=f'บอท {b.name} · {job} · Base Lv {s.get("level")} / Job Lv {s.get("level_job")}{party}')
            self.o_where.configure(text=f'📍 {s.get("map")}  ({s.get("x")}, {s.get("y")})')
            self.b_hp.set(s.get('hp'), s.get('hp_max'), 'ตาย' if s.get('dead') else ('นั่งพัก' if s.get('sit') else ''))
            self.b_sp.set(s.get('sp'), s.get('sp_max'))
            self.b_exp.set(s.get('exp'), s.get('exp_max'))
            self.b_job.set(s.get('exp_job'), s.get('exp_job_max'))
            self.b_w.set(s.get('weight'), s.get('weight_max'))
            st = b.stats
            self.tiles['zeny'].configure(text=fmt_int(s.get('zeny')))
            warm = st.hours() > 0.01
            self.tiles['eph'].configure(text=fmt_int(st.per_hour(st.base_gain)) if warm else 'กำลังคำนวณ…')
            self.tiles['jph'].configure(text=fmt_int(st.per_hour(st.job_gain)) if warm else 'กำลังคำนวณ…')
            zg = st.zeny_gain()
            self.tiles['zgain'].configure(text=('+' if zg > 0 else '') + fmt_int(zg),
                                          fg=OK if zg > 0 else (BAD if zg < 0 else TEXT))
            self.tiles['mon'].configure(text=str(s.get('monsters', 0)))
            gms = s.get('gms') or []
            self.tiles['ply'].configure(text=f'{s.get("players", 0)}' + (f'  ⚠ GM {len(gms)}' if gms else ''),
                                        fg=BAD if gms else TEXT)
            self.tiles['lock'].configure(text=s.get('lockMap') or '-')
            self.tiles['act'].configure(text=s.get('action') or 'ว่าง')
        else:
            self.o_name.configure(text=b.name)
            self.o_where.configure(text='')
            if b.running:
                self.o_sub.configure(text=f'OpenKore เปิดอยู่ (port {b.port}) · รอเข้าเกม — ล็อกอินในหน้าต่างเกม')
            elif b.name in self.pending_start:
                self.o_sub.configure(text='กำลังเปิดบอท... (กด Yes ที่หน้าต่าง UAC แล้วรอสักครู่)')
            else:
                self.o_sub.configure(text=f'บอทปิดอยู่ · port {b.port} · กด "เริ่มบอท" เพื่อเปิด OpenKore + เกม')
            for bar in (self.b_hp, self.b_sp, self.b_exp, self.b_job, self.b_w):
                bar.set(0, 0)
            for v in self.tiles.values():
                v.configure(text='-', fg=TEXT)

    # --------------------------------------------------------- bot actions
    def cur_bot(self) -> Bot | None:
        return self.bot_by_name.get(self.selected)

    def cmd(self, command: str, desc: str | None = None, bot: Bot | None = None) -> None:
        b = bot or self.cur_bot()
        if not b:
            return
        if not b.running:
            self.toast(f'{b.name}: บอทยังไม่ได้เปิด สั่งงานไม่ได้', 'warn')
            return
        if b.send(command):
            self.add_feed(b.name, f'➡ สั่ง: {desc or command}', 'info')
            self.toast(f'{b.name}: ส่งคำสั่ง "{command}" แล้ว', 'ok')
        else:
            self.toast(f'{b.name}: เขียนไฟล์คำสั่งไม่ได้', 'bad')

    def send_custom(self) -> None:
        c = self.cmd_var.get().strip()
        if c:
            self.cmd(c)
            self.cmd_var.set('')

    def toggle_sit(self) -> None:
        b = self.cur_bot()
        if b and b.status:
            self.cmd('stand' if b.status.get('sit') else 'sit')

    def start_selected(self) -> None:
        b = self.cur_bot()
        if b:
            self.start_bots([b])

    def start_all(self) -> None:
        self.start_bots([b for b in self.bots if not b.running])

    def start_bots(self, bots: list[Bot]) -> None:
        bots = [b for b in bots if not b.running and b.name not in self.pending_start]
        if not bots:
            self.toast('บอทที่เลือกเปิดอยู่แล้ว หรือกำลังเปิด', 'warn')
            return
        style = str(self.settings.get('console_style', 'Hidden'))
        if not launch_roz_start(ROOT_DIR, [b.name for b in bots], style):
            self.toast('เปิด PowerShell ไม่ได้ — ดูรายละเอียดใน gui\\gui-error.log', 'bad')
            return
        now = time.time()
        for b in bots:
            self.pending_start[b.name] = now
            self.add_feed(b.name, '▶ กำลังเปิดบอท... กด Yes ที่หน้าต่าง UAC', 'info')
        self.toast('กำลังเปิดบอท — กด Yes ที่หน้าต่าง UAC (สิทธิ์ Administrator)', 'ok')

    def stop_selected(self) -> None:
        b = self.cur_bot()
        if b and b.running and messagebox.askyesno('ปิดบอท', f'ปิด OpenKore ของ {b.name}?\n(หน้าต่างเกมจะหลุดการเชื่อมต่อ)'):
            self._was_online.discard(b.name)        # a stop, not a disconnect: no auto login
            self._user_stop[b.name] = time.time()
            self.cmd('quit', 'ปิดบอท')

    def kill_selected(self) -> None:
        b = self.cur_bot()
        if not b or not b.status:
            return
        game_pid = b.cached_game_pid()
        if game_pid and not relogin.find_game_window(game_pid):
            game_pid = 0            # gone, or the pid now belongs to another program: never kill that
        game_line = (f'และปิดเกม (pid {game_pid}) ด้วย' if game_pid
                     else '(ไม่พบหน้าต่างเกมของบอทนี้ — ปิดเฉพาะ OpenKore)')
        if messagebox.askyesno('บังคับปิด', f'บังคับปิด OpenKore ของ {b.name} (pid {b.status.get("pid")}) {game_line}?\n'
                                             'ใช้เมื่อบอทค้างและกดปิดปกติไม่ได้ — จะมีหน้าต่าง UAC ถาม'):
            self._was_online.discard(b.name)
            self._user_stop[b.name] = time.time()
            if b.force_kill(game_pid):
                self.add_feed(b.name, '✖ สั่งบังคับปิด' + (' (OpenKore + เกม)' if game_pid else ''), 'bad')
            else:
                self.toast(f'{b.name}: บังคับปิดไม่ได้ — ดูรายละเอียดใน gui\\gui-error.log', 'bad')

    def send_summary(self) -> None:
        lines = ['📊 สรุปสถานะบอท'] + [summary_line(b) for b in self.bots]
        self.notifier.notify('\n'.join(lines), force=True)
        self.toast('กำลังส่งสรุป...', 'ok')

    def _check_pending(self, b: Bot) -> None:
        t = self.pending_start.get(b.name)
        if t is None:
            return
        if b.running:
            del self.pending_start[b.name]
            s = relogin.load_settings(b.name)
            if s.enabled and s.has_credentials() and relogin.is_admin():
                self._startup_login[b.name] = time.time()
                self._game_seen.pop(b.name, None)
                self.add_feed(b.name, f'✅ OpenKore เปิดแล้ว — จะล็อกอินให้อัตโนมัติเมื่อเกมโหลดเสร็จ '
                                      f'(รอ {s.boot_delay:g} วินาที)', 'ok')
            elif s.enabled and s.has_credentials():
                self.add_feed(b.name, '✅ OpenKore เปิดแล้ว — ล็อกอินอัตโนมัติไม่ได้เพราะ GUI ไม่ได้เปิดแบบ '
                                      'Administrator (ใช้ Start-GUI-Admin.cmd) — ล็อกอินในเกมเองก่อน', 'warn')
            else:
                self.add_feed(b.name, '✅ OpenKore เปิดแล้ว — ล็อกอินในหน้าต่างเกมได้เลย', 'ok')
        elif time.time() - t > 100:
            del self.pending_start[b.name]
            err = self._start_log_errors()
            self.add_feed(b.name, '❌ เปิดบอทไม่สำเร็จ' + (f': {err}' if err else ' (ไม่เห็นสถานะจากบอท)'), 'bad')
            self.toast(f'{b.name}: เปิดบอทไม่สำเร็จ ดูรายละเอียดในแท็บ โปรแกรม', 'bad')

    @staticmethod
    def _start_log_errors() -> str:
        """Last ERROR/WARNING line of the PowerShell transcript ('' if none or unreadable)."""
        path = os.path.join(ROOT_DIR, 'logs', 'gui-start.log')
        try:
            with open(path, 'rb') as f:
                raw = f.read()
        except FileNotFoundError:
            return ''
        except OSError as e:
            log.warning('cannot read %s: %s', path, e)
            return ''
        # PowerShell 5.1 transcripts are UTF-16 LE with a BOM; fall back to UTF-8.
        text = raw.decode('utf-16', errors='replace') if raw.startswith(b'\xff\xfe') \
            else raw.decode('utf-8', errors='replace')
        errs = [l for l in text.splitlines() if 'ERROR' in l or 'WARNING' in l]
        return errs[-1].strip() if errs else ''

    # -------------------------------------------------------------- config
    def _build_config(self) -> None:
        f = self.tab_conf
        top = ttk.Frame(f, style='Panel.TFrame')
        top.pack(fill='x', padx=18, pady=(14, 6))
        self.c_title = ttk.Label(top, text='', style='Big.TLabel')
        self.c_title.pack(side='left')
        self.c_dirty = ttk.Label(top, text='', style='Panel.TLabel', foreground=WARN)
        self.c_dirty.pack(side='left', padx=12)
        ttk.Button(top, text='💾 บันทึก & ใช้งานทันที', style='Accent.TButton', command=self.save_config).pack(side='right', padx=2)
        ttk.Button(top, text='↺ โหลดจากไฟล์ใหม่', command=lambda: self.load_config(ask=True)).pack(side='right', padx=2)
        ttk.Button(top, text='📝 เปิดใน Notepad', command=self.open_config_notepad).pack(side='right', padx=2)
        self.c_path = ttk.Label(f, text='', style='PanelMuted.TLabel')
        self.c_path.pack(fill='x', padx=18)

        self.cnb = ttk.Notebook(f)
        self.cnb.pack(fill='both', expand=True, padx=12, pady=8)
        # In-game style tabs first (Phase 3a); the older generic editors stay as "advanced".
        self.basic_tab = BasicTab(self.cnb, self._mark_dirty)
        self.monster_tab = MonsterTab(self.cnb, self._mark_dirty, self.refresh_rozdb)
        self.skill_tab = SkillTab(self.cnb, self._skills_changed)
        self.potion_tab = PotionTab(self.cnb, self._skills_changed)
        self.buff_item_tab = BuffItemTab(self.cnb, self._skills_changed)
        self.rozdb = RozDB()
        self.char_items: dict[str, str] = {}
        self.cnb.add(self.basic_tab, text='พื้นฐาน')
        self.cnb.add(self.monster_tab, text='มอนสเตอร์')
        self.cnb.add(self.skill_tab, text='สกิล')
        self.statskill_tab = StatSkillTab(self.cnb, self._mark_dirty)
        self.cnb.add(self.statskill_tab, text='อัปสเตตัส/สกิล')
        self.cnb.add(self.potion_tab, text='Potion')
        self.cnb.add(self.buff_item_tab, text='ไอเทมบัฟ')
        self.pickup_tab = PickupTab(self.cnb, self._mark_dirty)
        self.move_tab = MoveTab(self.cnb, self._mark_dirty)
        self.tkc: KConfig | None = None
        self.cnb.add(self.pickup_tab, text='เก็บไอเทม')
        self.trade_tab = TradeTab(self.cnb, self._mark_dirty,
                                  dict(bg=PANEL2, fg=TEXT, activebackground=ACCENT, font=App.F_BASE))
        self.cnb.add(self.trade_tab, text='ขาย / ฝาก')
        self.restock_tab = RestockTab(self.cnb, self._skills_changed)
        self.cnb.add(self.restock_tab, text='ซื้อ / เบิก')
        self.cnb.add(self.move_tab, text='เคลื่อนที่')
        self.login_tab = AutoLoginTab(self.cnb, self)
        self.cnb.add(self.login_tab, text='ล็อกอินอัตโนมัติ')
        # The skill tab and the advanced block editor edit the same KConfig: re-read on switch.
        self.cnb.bind('<<NotebookTabChanged>>', lambda e: self._on_config_subtab())
        self.c_basic = Scrollable(self.cnb)
        self.c_blocks = ttk.Frame(self.cnb)
        self.c_raw = ttk.Frame(self.cnb)
        self.cnb.add(self.c_basic, text='ตั้งค่าอื่น ๆ')
        self.cnb.add(self.c_blocks, text='ยา / สกิล / ซื้อของ (ขั้นสูง)')
        self.cnb.add(self.c_raw, text='ค่าทั้งหมด (ขั้นสูง)')
        self.refresh_rozdb(force=False)
        self._build_form(self.c_basic.inner)
        self._build_blocks(self.c_blocks)
        self._build_raw(self.c_raw)

    def _build_form(self, parent: ttk.Frame) -> None:
        cols = [ttk.Frame(parent), ttk.Frame(parent)]
        cols[0].grid(row=0, column=0, sticky='nsew', padx=(6, 4), pady=6)
        cols[1].grid(row=0, column=1, sticky='nsew', padx=(4, 6), pady=6)
        parent.columnconfigure(0, weight=1, uniform='c')
        parent.columnconfigure(1, weight=1, uniform='c')
        map_values = self.tables.map_choices()
        for si, (section, fields) in enumerate(FORM):
            lf = ttk.LabelFrame(cols[si % 2], text=f' {section} ', padding=(12, 8))
            lf.pack(fill='x', pady=6)
            lf.columnconfigure(1, weight=1)
            r = 0
            for key, label, kind, opts, help_ in fields:
                ttk.Label(lf, text=label, style='Panel.TLabel').grid(row=r, column=0, sticky='w', pady=(6, 0), padx=(0, 10))
                var: tk.Variable
                w: ttk.Widget
                if kind == 'bool':
                    var = tk.IntVar()
                    w = ttk.Checkbutton(lf, variable=var, text='เปิด', command=self._mark_dirty)
                elif kind == 'choice':
                    var = tk.StringVar()
                    w = ttk.Combobox(lf, textvariable=var, state='readonly',
                                     values=[f'{v} — {t}' for v, t in opts])
                    w.bind('<<ComboboxSelected>>', lambda e: self._mark_dirty())
                elif kind == 'num':
                    var = tk.StringVar()
                    lo, hi, step = opts
                    w = ttk.Spinbox(lf, textvariable=var, from_=lo, to=hi, increment=step, width=8,
                                    command=self._mark_dirty)
                    w.bind('<KeyRelease>', lambda e: self._mark_dirty())
                elif kind == 'map':
                    var = tk.StringVar()
                    w = ttk.Combobox(lf, textvariable=var, values=map_values)
                    w.bind('<<ComboboxSelected>>', lambda e: self._mark_dirty())
                    w.bind('<KeyRelease>', lambda e: self._mark_dirty())
                else:
                    var = tk.StringVar()
                    w = ttk.Entry(lf, textvariable=var)
                    w.bind('<KeyRelease>', lambda e: self._mark_dirty())
                w.grid(row=r, column=1, sticky='w' if kind in ('bool', 'num') else 'ew', pady=(6, 0))
                r += 1
                if help_:
                    ttk.Label(lf, text=help_, style='PanelMuted.TLabel').grid(row=r, column=1, sticky='w')
                    r += 1
                self.form_vars[key] = (kind, opts, var)

    def _form_fill(self) -> None:
        kc = self.kc
        self.form_orig: dict[str, str] = {}
        for key, (kind, opts, var) in self.form_vars.items():
            raw = kc.get(key, '') if kc else ''
            self.form_orig[key] = raw
            if kind == 'bool':
                var.set(1 if raw.strip() not in ('', '0') else 0)
            elif kind == 'choice':
                lab = next((f'{v} — {t}' for v, t in opts if v == raw.strip()), raw)
                var.set(lab)
            elif kind == 'map':
                desc = self.tables.maps.get(raw.strip())
                var.set(f'{raw.strip()} — {desc}' if desc else raw)
            else:
                var.set(raw)

    def _form_value(self, key: str) -> str:
        kind, opts, var = self.form_vars[key]
        orig = self.form_orig.get(key, '')
        if kind == 'bool':
            on = bool(var.get())
            was_on = orig.strip() not in ('', '0')
            return orig if on == was_on else ('1' if on else '0')
        v = str(var.get()).strip()
        if kind in ('choice', 'map'):
            v = v.split(' — ')[0].strip()
        if kind == 'num' and v:
            try:
                float(v)
            except ValueError:
                raise ValueError(f'"{key}" ต้องเป็นตัวเลข')
        return v

    def _mark_dirty(self, *a: object) -> None:
        self.c_dirty.configure(text='● ยังไม่ได้บันทึก')

    def load_config(self, ask: bool = False, bot: Bot | None = None) -> None:
        b = bot or self.cur_bot()
        if not b:
            return
        if ask and self._config_dirty() and not messagebox.askyesno('โหลดใหม่', 'ทิ้งการแก้ไขที่ยังไม่บันทึก?'):
            return
        try:
            self.kc = KConfig(b.config_path)
            self.kc_bot = b.name
        except OSError as e:
            self.kc = None
            log.warning('cannot read %s: %s', b.config_path, e)
            self.toast(f'อ่าน config ไม่ได้: {e}', 'bad')
        self.c_title.configure(text=f'ตั้งค่าบอท: {b.name}')
        self.c_path.configure(text=b.config_path)
        self.c_dirty.configure(text='')
        self._form_fill()
        self.refresh_blocks()
        self.refresh_raw()
        status = b.status if b.online else None
        try:
            mon = monctl_load(b.control)
            counter = mon.counter
        except OSError as e:
            log.warning('cannot read mon_control.txt of %s: %s', b.name, e)
            counter = True
        self.basic_tab.fill(self.kc, status, self._follow_choices(b), counter)
        self.monster_tab.fill(b.control, self.kc.get('lockMap', '') if self.kc else '',
                              (status or {}).get('map', ''))
        self.monster_tab.set_current_map((status or {}).get('map', ''))
        char_json = b.read_char()
        self.skill_tab.fill(self.kc, char_json, self.tables.statuses,
                            list((b.status or {}).get('party_members') or []))
        self.char_items = {str(i.get('id')): str(i.get('name')) for i in (char_json or {}).get('items') or []
                           if isinstance(i, dict)}
        self.potion_tab.fill(self.kc, char_json, self._item_name)
        self.buff_item_tab.fill(self.kc, char_json, self._item_name)
        self.pickup_tab.fill(self.kc, b.control, self.kc.get('lockMap', '') if self.kc else '',
                             (status or {}).get('map', ''))
        self.trade_tab.fill(self.kc, b.control, char_json)
        self.restock_tab.fill(self.kc, char_json)
        self.statskill_tab.fill(self.kc, char_json)
        tpath = os.path.join(b.control, 'timeouts.txt')
        try:
            self.tkc = KConfig(tpath) if os.path.exists(tpath) else None
        except OSError as e:
            log.warning('cannot read %s: %s', tpath, e)
            self.tkc = None
        self.move_tab.fill(self.kc, self.tkc, char_json)
        self.login_tab.fill(b)

    def _openkore_root(self) -> str:
        return str(self.registry.get('openkoreRoot') or r'C:\Users\silap\openkore')

    def _item_name(self, token: str) -> str:
        """Item id or name -> display name: rozclub (this server) > character's bag > OpenKore tables."""
        t = token.strip()
        if not t.isdigit():
            return t
        roz = self.rozdb.items.get(int(t))
        if roz:
            return roz[0]
        bag = self.char_items.get(t, '')
        if bag and not bag.startswith('Unknown #'):
            return bag
        return self.tables.items.get(int(t), t)

    def _skills_changed(self) -> None:
        self._mark_dirty()
        self.refresh_blocks()
        self.refresh_raw()

    def _on_config_subtab(self) -> None:
        cur = self.cnb.select()
        if cur == str(self.skill_tab):
            self.skill_tab.render()
        elif cur in (str(self.potion_tab), str(self.buff_item_tab)):
            self.nametowidget(cur).render()
        elif cur == str(self.restock_tab):
            self.restock_tab.reload()           # the advanced block editor may have changed buyAuto/getAuto
        elif cur == str(self.c_blocks):
            self.refresh_blocks()

    def _follow_choices(self, b: Bot) -> list[str]:
        """Party members of this bot + character names of the other bots."""
        names: list[str] = list((b.status or {}).get('party_members') or [])
        for other in self.bots:
            ch = (other.status or {}).get('char')
            if other is not b and ch and ch not in names:
                names.append(str(ch))
        return names

    def refresh_rozdb(self, force: bool = True) -> None:
        """Load the rozclub.com database off the Tk thread, then hand it to the monster tab."""
        self.toast('กำลังโหลดข้อมูลมอนจาก rozclub.com...' if force else 'กำลังโหลดข้อมูลเกม...', 'muted')

        def work() -> None:
            db = RozDB.load(force=force)
            self._call_soon(lambda: self._rozdb_ready(db))
        threading.Thread(target=work, daemon=True).start()

    def _rozdb_ready(self, db: RozDB) -> None:
        self.rozdb = db
        self.monster_tab.set_db(db, self.tables)
        self.pickup_tab.set_db(db, self.tables)
        self.trade_tab.set_db(db, self.tables)
        self.restock_tab.set_db(db, self.tables)
        self.potion_tab.render()            # item names may have improved
        self.buff_item_tab.render()
        if db.error:
            self.toast(f'โหลดข้อมูลมอนไม่ได้: {db.error}', 'bad')
        else:
            self.toast(f'ข้อมูลเกมพร้อม: มอน {len(db.mobs)} ตัว, {len(db.maps)} แผนที่', 'ok')

    def _config_dirty(self) -> bool:
        if not self.kc:
            return False
        if (self.kc.dirty or self.basic_tab.is_dirty() or self.monster_tab.is_dirty()
                or self.pickup_tab.is_dirty() or self.move_tab.is_dirty() or self.trade_tab.is_dirty()
                or self.statskill_tab.is_dirty()):
            return True
        try:
            return any(self._form_value(k) != self.form_orig.get(k, '') for k in self.form_vars)
        except ValueError:
            return True

    def save_config(self) -> None:
        if not self.kc or self.kc_bot not in self.bot_by_name:
            return
        b = self.bot_by_name[self.kc_bot]
        try:
            values = {k: self._form_value(k) for k in self.form_vars}
        except ValueError as e:
            messagebox.showerror('ค่าไม่ถูกต้อง', str(e))
            return
        if self.kc.changed_on_disk():
            if not messagebox.askyesno('ไฟล์ถูกแก้จากที่อื่น',
                                       'config.txt ถูกแก้ไขจากที่อื่นหลังจากเปิดหน้านี้ (เช่น OpenKore เอง)\n\n'
                                       'Yes = เขียนทับด้วยค่าในหน้านี้\nNo = ยกเลิก (กด "โหลดจากไฟล์ใหม่" ก่อน)'):
                return
        for k, v in values.items():
            if v != self.form_orig.get(k, ''):
                if v == '' and not self.kc.has(k):
                    continue
                self.kc.set(k, v)
        try:
            self.basic_tab.apply(self.kc)
            timeouts_changed = self.move_tab.apply(self.kc, self.tkc)
            self.trade_tab.apply_config(self.kc)
            self.statskill_tab.apply_config(self.kc)
        except ValueError as e:
            messagebox.showerror('ค่าไม่ถูกต้อง', str(e))
            return
        self.pickup_tab.apply_config(self.kc)
        counter_changed = self.basic_tab.counter() != self.monster_tab.settings.counter
        mon_changed = self.monster_tab.is_dirty() or counter_changed
        pickup_changed = items_changed = False
        try:
            backup = self.kc.save()
            if mon_changed:
                self.monster_tab.save(self.basic_tab.counter())
            pickup_changed = self.pickup_tab.save(os.path.join(self._openkore_root(), 'control', 'pickupitems.txt'))
            items_changed = self.trade_tab.save()
            if timeouts_changed and self.tkc is not None:
                self.tkc.save()
        except OSError as e:
            log.exception('cannot save settings of %s', b.name)
            messagebox.showerror('บันทึกไม่ได้', str(e))
            return
        self._form_fill()
        self.refresh_raw()
        self.c_dirty.configure(text='')
        msg = f'บันทึกแล้ว (สำรองไว้ที่ {os.path.basename(backup)})'
        if b.running:
            reloads = (['reload config'] + (['reload mon_control', 'reload priority'] if mon_changed else [])
                       + (['reload pickupitems'] if pickup_changed else [])
                       + (['reload items_control'] if items_changed else [])
                       + (['reload timeouts'] if timeouts_changed else []))
            if b.send(*reloads):
                msg += ' และสั่งบอทโหลดค่าใหม่แล้ว'
            else:
                msg += ' แต่สั่งบอทโหลดใหม่ไม่ได้ — กดปุ่ม "โหลด config ใหม่" เอง'
        self.add_feed(b.name, '💾 บันทึกการตั้งค่า', 'ok')
        self.toast(msg, 'ok')

    def open_config_notepad(self) -> None:
        if self.kc:
            self._notepad(self.kc.path)

    # blocks ------------------------------------------------------------
    def _build_blocks(self, f: ttk.Frame) -> None:
        bar = ttk.Frame(f)
        bar.pack(fill='x', padx=8, pady=8)
        mb = ttk.Menubutton(bar, text='➕ เพิ่ม', style='TButton')
        menu = tk.Menu(mb, tearoff=0, bg=PANEL2, fg=TEXT, activebackground=ACCENT, font=App.F_BASE)
        for label, key, value, inner in BLOCK_TEMPLATES:
            menu.add_command(label=label, command=functools.partial(self.edit_block, None, (key, value, inner)))
        menu.add_separator()
        menu.add_command(label='บล็อกเปล่า...', command=lambda: self.edit_block(None, ('useSelf_item', '', '')))
        mb['menu'] = menu
        mb.pack(side='left', padx=2)
        ttk.Button(bar, text='✏️ แก้ไข', command=lambda: self.edit_block(self._sel_block())).pack(side='left', padx=2)
        ttk.Button(bar, text='⏯ เปิด/ปิด', command=self.toggle_block).pack(side='left', padx=2)
        ttk.Button(bar, text='🗑 ลบ', command=self.delete_block).pack(side='left', padx=2)
        ttk.Label(bar, text='ดับเบิลคลิกเพื่อแก้ไข · แก้แล้วกด "บันทึก & ใช้งานทันที" ด้านบน', style='Muted.TLabel').pack(side='right')
        cols = ('on', 'type', 'what', 'detail')
        tv = ttk.Treeview(f, columns=cols, show='headings', selectmode='browse')
        for c, t, w in (('on', 'สถานะ', 70), ('type', 'ประเภท', 190), ('what', 'ไอเทม / สกิล', 260), ('detail', 'เงื่อนไข', 520)):
            tv.heading(c, text=t, anchor='w')
            tv.column(c, width=w, anchor='w', stretch=(c == 'detail'))
        tv.tag_configure('off', foreground='#6b7284')
        tv.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        tv.bind('<Double-1>', lambda e: self.edit_block(self._sel_block()))
        self.block_tv = tv

    def refresh_blocks(self) -> None:
        tv = self.block_tv
        tv.delete(*tv.get_children())
        if not self.kc:
            return
        for i, b in enumerate(self.kc.blocks):
            off = self.kc.block_disabled(b)
            items = [f'{k} {v}'.strip() for k, v in self.kc.block_items(b) if k != 'disabled']
            what = self.tables.describe_items(b.value) if b.key in ('useSelf_item', 'buyAuto', 'getAuto', 'sellAuto') else b.value
            tv.insert('', 'end', iid=str(i), tags=('off',) if off else (),
                      values=('✖ ปิด' if off else '✔ เปิด', BLOCK_TYPES.get(b.key, b.key), what, ' · '.join(items)))

    def _sel_block(self) -> Block | None:
        sel = self.block_tv.selection()
        if not sel or not self.kc:
            return None
        return self.kc.blocks[int(sel[0])]

    def toggle_block(self) -> None:
        b = self._sel_block()
        kc = self.kc
        if b and kc:
            idx = self.block_tv.selection()[0]
            kc.set_block_disabled(b, not kc.block_disabled(b))
            self.refresh_blocks()
            self.block_tv.selection_set(idx)
            self._mark_dirty()

    def delete_block(self) -> None:
        b = self._sel_block()
        kc = self.kc
        if b and kc and messagebox.askyesno('ลบ', f'ลบบล็อก "{b.key} {b.value}"?'):
            kc.delete_block(b)
            self.refresh_blocks()
            self.refresh_raw()
            self._mark_dirty()

    def edit_block(self, block: Block | None, template: tuple[str, str, str] | None = None) -> None:
        kc = self.kc
        if kc is None:
            return
        if block is not None:
            key, value, inner = block.key, block.value, kc.block_text(block)
        elif template is not None:
            key, value, inner = template
        else:
            return
        dlg = tk.Toplevel(self)
        dlg.title('แก้ไขบล็อก' if block else 'เพิ่มบล็อก')
        dlg.configure(bg=PANEL)
        dlg.transient(self)
        dlg.geometry('640x520')
        frm = ttk.Frame(dlg, style='Panel.TFrame', padding=16)
        frm.pack(fill='both', expand=True)
        frm.columnconfigure(1, weight=1)
        ttk.Label(frm, text='ประเภท', style='Panel.TLabel').grid(row=0, column=0, sticky='w', pady=4)
        kvar = tk.StringVar(value=key)
        kbox = ttk.Combobox(frm, textvariable=kvar, values=list(BLOCK_TYPES.keys()))
        kbox.grid(row=0, column=1, sticky='ew', pady=4)
        klabel = ttk.Label(frm, text='', style='PanelMuted.TLabel')
        klabel.grid(row=1, column=1, sticky='w')
        ttk.Label(frm, text='ไอเทม / สกิล', style='Panel.TLabel').grid(row=2, column=0, sticky='w', pady=4)
        vvar = tk.StringVar(value=value)
        ttk.Entry(frm, textvariable=vvar).grid(row=2, column=1, sticky='ew', pady=4)
        vhint = ttk.Label(frm, text='', style='PanelMuted.TLabel')
        vhint.grid(row=3, column=1, sticky='w')
        ttk.Label(frm, text='เงื่อนไข\n(บรรทัดละค่า)', style='Panel.TLabel').grid(row=4, column=0, sticky='nw', pady=6)
        txt = tk.Text(frm, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief='flat', font=App.F_MONO, padx=8, pady=6, height=10)
        txt.grid(row=4, column=1, sticky='nsew', pady=6)
        txt.insert('1.0', inner)
        frm.rowconfigure(4, weight=1)
        help_l = ttk.Label(frm, text='', style='PanelMuted.TLabel', wraplength=480, justify='left')
        help_l.grid(row=5, column=1, sticky='w')

        def upd(*a: object) -> None:
            k = kvar.get().strip()
            klabel.configure(text=BLOCK_TYPES.get(k, ''))
            help_l.configure(text=BLOCK_HELP.get(k, 'ดูรายละเอียดค่าต่าง ๆ ได้ในคู่มือ config ของ OpenKore'))
            v = vvar.get()
            d = self.tables.describe_items(v) if k in ('useSelf_item', 'buyAuto', 'getAuto') else ''
            vhint.configure(text=f'= {d}' if d and d != v else 'ใส่ได้ทั้งชื่อหรือเลข ID คั่นด้วย , เช่น 501,502 หรือ Red Potion')
        kvar.trace_add('write', upd)
        vvar.trace_add('write', upd)
        upd()

        def ok() -> None:
            k = kvar.get().strip()
            if not k or ' ' in k:
                messagebox.showerror('ผิดพลาด', 'ประเภทต้องเป็นคำเดียว เช่น useSelf_item', parent=dlg)
                return
            v = vvar.get().strip()
            body = txt.get('1.0', 'end').strip()
            if block is not None:
                if k != block.key:
                    kc.delete_block(block)
                    kc.add_block(k, v, body)
                else:
                    kc.replace_block(block, v, body)
            else:
                kc.add_block(k, v, body)
            self.refresh_blocks()
            self.refresh_raw()
            self._mark_dirty()
            dlg.destroy()

        btns = ttk.Frame(frm, style='Panel.TFrame')
        btns.grid(row=6, column=1, sticky='e', pady=(12, 0))
        ttk.Button(btns, text='ยกเลิก', command=dlg.destroy).pack(side='right', padx=4)
        ttk.Button(btns, text='ตกลง', style='Accent.TButton', command=ok).pack(side='right', padx=4)
        dlg.grab_set()

    # raw ------------------------------------------------------------------
    def _build_raw(self, f: ttk.Frame) -> None:
        bar = ttk.Frame(f)
        bar.pack(fill='x', padx=8, pady=8)
        ttk.Label(bar, text='ค้นหา').pack(side='left')
        self.raw_q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.raw_q, width=30)
        e.pack(side='left', padx=6)
        self.raw_q.trace_add('write', lambda *a: self.refresh_raw())
        ttk.Button(bar, text='➕ เพิ่มค่าใหม่', command=self.raw_add).pack(side='left', padx=6)
        ttk.Label(bar, text='ดับเบิลคลิกเพื่อแก้ค่า', style='Muted.TLabel').pack(side='right')
        tv = ttk.Treeview(f, columns=('key', 'value'), show='headings', selectmode='browse')
        tv.heading('key', text='ชื่อค่า', anchor='w')
        tv.heading('value', text='ค่า', anchor='w')
        tv.column('key', width=300, anchor='w', stretch=False)
        tv.column('value', width=600, anchor='w')
        vsb = ttk.Scrollbar(f, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y', pady=(0, 8))
        tv.pack(fill='both', expand=True, padx=(8, 0), pady=(0, 8))
        tv.bind('<Double-1>', lambda ev: self.raw_edit())
        self.raw_tv = tv

    def refresh_raw(self) -> None:
        tv = self.raw_tv
        tv.delete(*tv.get_children())
        if not self.kc:
            return
        q = self.raw_q.get().strip().lower()
        for k in self.kc.keys():
            v = self.kc.get(k)
            if q and q not in k.lower() and q not in v.lower():
                continue
            tv.insert('', 'end', iid=k, values=(k, v))

    def raw_edit(self) -> None:
        sel = self.raw_tv.selection()
        kc = self.kc
        if not sel or kc is None:
            return
        k = sel[0]
        if k in self.form_vars:
            messagebox.showinfo('แก้ในหน้าพื้นฐาน', f'"{k}" อยู่ในหน้า พื้นฐาน แล้ว — แก้จากที่นั่นได้เลย')
            self.cnb.select(self.c_basic)
            return
        v = simpledialog.askstring('แก้ค่า', k, initialvalue=kc.get(k), parent=self)
        if v is not None:
            kc.set(k, v)
            self.refresh_raw()
            self._mark_dirty()

    def raw_add(self) -> None:
        if not self.kc:
            return
        k = simpledialog.askstring('เพิ่มค่าใหม่', 'ชื่อค่า (เช่น teleportAuto_search)', parent=self)
        if not k or not k.strip() or ' ' in k.strip():
            return
        v = simpledialog.askstring('เพิ่มค่าใหม่', f'ค่าของ {k.strip()}', parent=self) or ''
        self.kc.set(k.strip(), v)
        self.refresh_raw()
        self._mark_dirty()

    # --------------------------------------------------------------- notify
    def _build_notify(self) -> None:
        sc = Scrollable(self.tab_noti)
        sc.pack(fill='both', expand=True)
        f = sc.inner
        n = self.settings['notify']
        self.nv: dict[str, tk.Variable] = {}

        def entry(parent: ttk.LabelFrame, key: str, row: int, label: str,
                  show: str | None = None, width: int = 60) -> ttk.Entry:
            ttk.Label(parent, text=label, style='Panel.TLabel').grid(row=row, column=0, sticky='w', pady=4, padx=(0, 10))
            v = tk.StringVar(value=str(n.get(key, '')))
            e = ttk.Entry(parent, textvariable=v, width=width, show=show or '')
            e.grid(row=row, column=1, sticky='ew', pady=4)
            self.nv[key] = v
            return e

        cols = ttk.Frame(f)
        cols.pack(fill='x', padx=12, pady=8)
        cols.columnconfigure(0, weight=1, uniform='n')
        cols.columnconfigure(1, weight=1, uniform='n')

        tg = ttk.LabelFrame(cols, text=' ✈️ Telegram ', padding=12)
        tg.grid(row=0, column=0, sticky='nsew', padx=6, pady=6)
        tg.columnconfigure(1, weight=1)
        self.nv['telegram_enabled'] = tk.IntVar(value=1 if n.get('telegram_enabled') else 0)
        ttk.Checkbutton(tg, text='เปิดใช้ Telegram', variable=self.nv['telegram_enabled']).grid(row=0, column=0, columnspan=2, sticky='w')
        entry(tg, 'telegram_token', 1, 'Bot Token', show='•', width=40)
        entry(tg, 'telegram_chat_id', 2, 'Chat ID', width=40)
        ttk.Button(tg, text='🔍 หา Chat ID ให้อัตโนมัติ', command=self.find_chat_id).grid(row=3, column=1, sticky='w', pady=4)
        ttk.Label(tg, style='PanelMuted.TLabel', justify='left', wraplength=420, text=(
            'วิธีตั้งค่า:\n1. ใน Telegram คุยกับ @BotFather แล้วพิมพ์ /newbot ตั้งชื่อบอท\n'
            '2. คัดลอก Token ที่ได้มาใส่ช่อง Bot Token\n3. เปิดแชทกับบอทของคุณ แล้วส่งข้อความอะไรก็ได้ 1 ข้อความ\n'
            '4. กด "หา Chat ID ให้อัตโนมัติ" แล้วกดบันทึก')).grid(row=4, column=0, columnspan=2, sticky='w', pady=(8, 0))

        dc = ttk.LabelFrame(cols, text=' 💬 Discord ', padding=12)
        dc.grid(row=0, column=1, sticky='nsew', padx=6, pady=6)
        dc.columnconfigure(1, weight=1)
        self.nv['discord_enabled'] = tk.IntVar(value=1 if n.get('discord_enabled') else 0)
        ttk.Checkbutton(dc, text='เปิดใช้ Discord', variable=self.nv['discord_enabled']).grid(row=0, column=0, columnspan=2, sticky='w')
        entry(dc, 'discord_webhook', 1, 'Webhook URL', show='•', width=40)
        ttk.Label(dc, style='PanelMuted.TLabel', justify='left', wraplength=420, text=(
            'วิธีตั้งค่า:\n1. ใน Discord ไปที่ห้องที่อยากให้แจ้งเตือน → ตั้งค่าห้อง (รูปเฟือง)\n'
            '2. Integrations → Webhooks → New Webhook\n3. กด Copy Webhook URL แล้ววางในช่องด้านบน')).grid(
            row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))

        ev = ttk.LabelFrame(f, text=' 🔔 แจ้งเตือนเมื่อ ', padding=12)
        ev.pack(fill='x', padx=18, pady=6)
        self.nv_events: dict[str, tk.IntVar] = {}
        for i, (k, (label, default)) in enumerate(EVENT_TYPES.items()):
            v = tk.IntVar(value=1 if n.get('events', {}).get(k, default) else 0)
            ttk.Checkbutton(ev, text=label, variable=v).grid(row=i // 3, column=i % 3, sticky='w', padx=(0, 30), pady=3)
            self.nv_events[k] = v

        opt = ttk.LabelFrame(f, text=' ⚙️ รายละเอียด ', padding=12)
        opt.pack(fill='x', padx=18, pady=6)
        opt.columnconfigure(1, weight=1)
        entry(opt, 'item_keywords', 0, 'ไอเทมที่ต้องการแจ้ง (คั่นด้วย ,)', width=50)
        ttk.Label(opt, text='เช่น Card, Elunium, Oridecon — ถ้าชื่อไอเทมที่เก็บได้มีคำเหล่านี้จะแจ้งเตือน',
                  style='PanelMuted.TLabel').grid(row=1, column=1, sticky='w')
        entry(opt, 'weight_percent', 2, 'แจ้งเมื่อน้ำหนักเกิน (%)', width=8)
        entry(opt, 'ai_stuck_minutes', 3, 'แจ้งเมื่อ AI ไม่ได้ออโต้นาน (นาที)', width=8)
        entry(opt, 'report_minutes', 4, 'ส่งสรุปสถานะทุก ๆ (นาที, 0 = ไม่ส่ง)', width=8)

        btns = ttk.Frame(f)
        btns.pack(fill='x', padx=18, pady=(12, 0), before=cols)   # keep Save/Test visible without scrolling
        ttk.Button(btns, text='💾 บันทึกการแจ้งเตือน', style='Accent.TButton', command=self.save_notify).pack(side='left', padx=2)
        ttk.Button(btns, text='📨 ส่งข้อความทดสอบ', command=self.test_notify).pack(side='left', padx=2)
        ttk.Label(btns, text='Token / Webhook เก็บไว้ในเครื่องที่ %APPDATA%\\ROZBotControl\\settings.json (นอกโปรเจกต์) — อย่าแชร์ไฟล์นี้',
                  style='Muted.TLabel').pack(side='right')

    def _collect_notify(self) -> dict[str, Any]:
        n = dict(self.settings['notify'])
        for k, v in self.nv.items():
            if isinstance(v, tk.IntVar):
                n[k] = bool(v.get())
            else:
                n[k] = v.get().strip()
        for k in ('weight_percent', 'ai_stuck_minutes', 'report_minutes'):
            try:
                n[k] = float(n[k]) if n[k] not in ('', None) else NOTIFY_DEFAULTS[k]
            except ValueError:
                label = {'weight_percent': 'แจ้งเมื่อน้ำหนักเกิน', 'ai_stuck_minutes': 'แจ้งเมื่อ AI ไม่ได้ออโต้นาน',
                         'report_minutes': 'ส่งสรุปสถานะทุก ๆ'}[k]
                raise ValueError(f'ช่อง "{label}" ต้องเป็นตัวเลข')
        n['events'] = {k: bool(v.get()) for k, v in self.nv_events.items()}
        return n

    def save_notify(self, quiet: bool = False) -> bool:
        try:
            self.settings['notify'] = self._collect_notify()
        except ValueError as e:
            messagebox.showerror('ค่าไม่ถูกต้อง', str(e))
            return False
        if not self._save_settings():
            return False
        if not quiet:
            chans = self.notifier.channels_ready()
            self.toast('บันทึกการแจ้งเตือนแล้ว' + (f' (ใช้งาน: {", ".join(chans)})' if chans else ' — ยังไม่ได้เปิดช่องทางใด'), 'ok')
        return True

    def test_notify(self) -> None:
        if self.save_notify(quiet=True):
            self.notifier.notify('✅ ทดสอบแจ้งเตือนจาก ROZ Bot Control สำเร็จ!', force=True)
            self.toast('กำลังส่งข้อความทดสอบ...', 'muted')

    def _notify_result(self, ok: bool, msg: str) -> None:
        self._call_soon(lambda: self.toast(msg, 'ok' if ok else 'bad'))

    def find_chat_id(self) -> None:
        token = self.nv['telegram_token'].get().strip()
        if not token:
            messagebox.showinfo('Telegram', 'ใส่ Bot Token ก่อน')
            return
        self.toast('กำลังค้นหา Chat ID...', 'muted')

        def work() -> None:
            try:
                chats = telegram_find_chats(token)
            except Exception as e:      # network/HTTP/JSON: report it, never kill the thread silently
                log.warning('telegram getUpdates failed: %s', e)
                msg = f'ค้นหาไม่สำเร็จ: {describe_error(e)}'   # bind now: `e` is cleared after except
                self._call_soon(lambda: self.toast(msg, 'bad'))
                return
            self._call_soon(lambda: self._chat_found(chats))
        threading.Thread(target=work, daemon=True).start()

    def _chat_found(self, chats: list[tuple[str, str]]) -> None:
        if not chats:
            messagebox.showinfo('Telegram', 'ยังไม่พบแชท\nเปิด Telegram แล้วส่งข้อความหาบอทของคุณก่อน 1 ข้อความ จากนั้นกดอีกครั้ง')
            return
        cid, name = chats[-1]
        if len(chats) > 1:
            listing = '\n'.join(f'{c}  {n}' for c, n in chats)
            ans = simpledialog.askstring('เลือก Chat ID', f'พบหลายแชท:\n{listing}\n\nใส่ Chat ID ที่ต้องการ', initialvalue=cid, parent=self)
            if not ans:
                return
            cid = ans.strip()
        self.nv['telegram_chat_id'].set(cid)
        self.nv['telegram_enabled'].set(1)
        self.toast(f'พบ Chat ID {cid} ({name}) — กดบันทึกการแจ้งเตือน', 'ok')

    # ------------------------------------------------------------------ log
    def _build_log(self) -> None:
        f = self.tab_log
        bar = ttk.Frame(f, style='Panel.TFrame')
        bar.pack(fill='x', padx=14, pady=10)
        self.log_mode = tk.StringVar(value=self.settings.get('log_mode', 'important'))
        for val, text in (('important', 'เฉพาะที่สำคัญ'), ('chat', 'แชท'), ('all', 'ทั้งหมด')):
            ttk.Radiobutton(bar, text=text, value=val, variable=self.log_mode, command=self.rerender_log).pack(side='left', padx=(0, 12))
        ttk.Label(bar, text='ค้นหา', style='Panel.TLabel').pack(side='left', padx=(20, 4))
        self.log_q = tk.StringVar()
        ttk.Entry(bar, textvariable=self.log_q, width=24).pack(side='left')
        self.log_q.trace_add('write', lambda *a: self.rerender_log())
        self.log_follow = tk.IntVar(value=1)
        ttk.Checkbutton(bar, text='เลื่อนตามอัตโนมัติ', variable=self.log_follow).pack(side='right')
        ttk.Button(bar, text='📂 เปิดโฟลเดอร์ logs', command=self.open_logs).pack(side='right', padx=8)
        frame = ttk.Frame(f, style='Panel.TFrame')
        frame.pack(fill='both', expand=True, padx=14, pady=(0, 14))
        self.logtxt = tk.Text(frame, bg=BG, fg=TEXT, relief='flat', wrap='word', padx=10, pady=8,
                              font=App.F_BASE, state='disabled', spacing1=2)
        vsb = ttk.Scrollbar(frame, orient='vertical', command=self.logtxt.yview)
        self.logtxt.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        self.logtxt.pack(fill='both', expand=True)
        for tag, color in (('err', BAD), ('warn', WARN), ('chat', '#7cc7ff'), ('drop', OK), ('time', '#5b6273'), ('dom', '#6b7284')):
            self.logtxt.tag_configure(tag, foreground=color)

    def _log_visible(self, entry: LogEntry) -> bool:
        ts, typ, dom, text = entry
        mode = self.log_mode.get()
        if mode == 'important' and not (typ in ('warning', 'error') or dom in IMPORTANT_DOMAINS):
            return False
        if mode == 'chat' and dom not in CHAT_DOMAINS:
            return False
        q = self.log_q.get().strip().lower()
        return not q or q in text.lower()

    def _log_insert(self, entries: list[LogEntry]) -> None:
        if not entries:
            return
        t = self.logtxt
        t.configure(state='normal')
        for ts, typ, dom, text in entries:
            tag = LOG_TAG.get(typ) or ('chat' if dom in CHAT_DOMAINS else 'drop' if dom == 'drop' else None)
            t.insert('end', time.strftime('%H:%M:%S ', time.localtime(ts)), 'time')
            t.insert('end', text + '\n', tag or ())
        lines = int(t.index('end-1c').split('.')[0])
        if lines > 3000:
            t.delete('1.0', f'{lines - 2500}.0')
        t.configure(state='disabled')
        if self.log_follow.get():
            t.see('end')

    def rerender_log(self) -> None:
        t = self.logtxt
        t.configure(state='normal')
        t.delete('1.0', 'end')
        t.configure(state='disabled')
        self._log_insert([e for e in self.log_lines if self._log_visible(e)][-2500:])

    def open_logs(self) -> None:
        b = self.cur_bot()
        if b:
            self._open_path(b.logs)

    # -------------------------------------------------------------- program
    def _build_program(self) -> None:
        f = self.tab_prog
        lf = ttk.LabelFrame(f, text=' 🖥️ หน้าต่าง OpenKore (console) ตอนเริ่มบอท ', padding=12)
        lf.pack(fill='x', padx=18, pady=(16, 6))
        self.console_style = tk.StringVar(value=self.settings.get('console_style', 'Hidden'))
        for val, text in (('Hidden', 'ซ่อนทั้งหมด (แนะนำ) — ดู log ในแท็บ 📜 บันทึก · ปิดบอทจากโปรแกรมนี้'),
                          ('Minimized', 'ย่อไว้ที่ taskbar'),
                          ('Normal', 'แสดงตามปกติ')):
            ttk.Radiobutton(lf, text=text, value=val, variable=self.console_style,
                            command=self._save_prog).pack(anchor='w', pady=2)
        ttk.Label(lf, style='PanelMuted.TLabel', text='มีผลกับการเริ่มบอทครั้งถัดไปจากโปรแกรมนี้').pack(anchor='w', pady=(6, 0))

        lf2 = ttk.LabelFrame(f, text=' 🧰 เครื่องมือ ', padding=12)
        lf2.pack(fill='x', padx=18, pady=6)
        row = ttk.Frame(lf2, style='Panel.TFrame')
        row.pack(fill='x')
        ttk.Button(row, text='📄 ดูผลการเริ่มบอทครั้งล่าสุด', command=self.show_start_log).pack(side='left', padx=2)
        ttk.Button(row, text='📂 เปิดโฟลเดอร์โปรไฟล์', command=lambda: self._open_path(ROOT_DIR)).pack(side='left', padx=2)
        ttk.Button(row, text='🔁 โหลดรายชื่อบอท (instances.json) ใหม่', command=self.reload_registry).pack(side='left', padx=2)

        lf3 = ttk.LabelFrame(f, text=' ℹ️ วิธีทำงาน ', padding=12)
        lf3.pack(fill='x', padx=18, pady=6)
        ttk.Label(lf3, style='PanelMuted.TLabel', justify='left', wraplength=900, text=(
            '• โปรแกรมนี้คุยกับบอทผ่านปลั๊กอิน gui_ipc (plugins\\gui_ipc) ซึ่งจะถูกโหลดเมื่อเริ่มบอทผ่านโปรแกรมนี้ หรือ roz.cmd\n'
            '• โปรไฟล์ของบอทแต่ละตัวอยู่ที่ bots\\<ชื่อ>\\ (control, tables, logs) · รายชื่อบอทอยู่ใน instances.json\n'
            '• ปุ่ม ➕ เพิ่มบอท / ➖ ลบบอท ที่แถบซ้ายเรียก scripts\\roz.ps1 new / remove ให้ทันที (ไม่ต้องปิดโปรแกรม)\n'
            '• ล็อกอินอัตโนมัติ (แท็บตั้งค่า) ต้องเปิด GUI ด้วย Start-GUI-Admin.cmd และไม่ล็อกจอ/ไม่สลีป\n'
            '• ล็อกอินอัตโนมัติจะทำงานเมื่อเห็นกล่อง Disconnected/Error ของเกม (กดทดสอบเองได้ตอนอยู่หน้า login)\n'
            '• ปุ่มเริ่มบอทจะขอสิทธิ์ Administrator (UAC) เพราะเกม Ragnarok.exe ต้องใช้สิทธิ์นี้\n'
            '• ทุกครั้งที่บันทึกการตั้งค่า จะสำรอง config.txt ไว้เป็น config.txt.bak-วันที่-gui (เก็บ 15 ไฟล์ล่าสุด)\n'
            '• การแจ้งเตือนทำงานเฉพาะตอนเปิดโปรแกรมนี้ไว้ (ย่อหน้าต่างไว้ได้)')).pack(anchor='w')

    def _save_prog(self) -> None:
        self.settings['console_style'] = self.console_style.get()
        if self._save_settings():
            self.toast('บันทึกแล้ว', 'ok')

    def show_start_log(self) -> None:
        path = os.path.join(ROOT_DIR, 'logs', 'gui-start.log')
        if os.path.exists(path):
            self._notepad(path)
        else:
            messagebox.showinfo('ยังไม่มี', 'ยังไม่เคยเริ่มบอทจากโปรแกรมนี้')

    def reload_registry(self, select: str | None = None) -> None:
        """Re-read instances.json and rebuild the sidebar (after roz new/remove)."""
        try:
            reg = load_registry(ROOT_DIR)
        except (OSError, ValueError) as e:
            log.exception('cannot reload instances.json')
            self.toast(f'โหลดรายชื่อบอทไม่ได้: {e}', 'bad')
            return
        instances = [i for i in reg.get('instances', []) if isinstance(i, dict) and i.get('name')]
        old = self.bot_by_name
        bots: list[Bot] = []
        for inst in instances:
            name = str(inst['name'])
            bots.append(old.get(name) or Bot(ROOT_DIR, inst))
        self.registry = reg
        self.bots = bots
        self.bot_by_name = {b.name: b for b in bots}
        self.feeds = {b.name: self.feeds.get(b.name, collections.deque(maxlen=300)) for b in bots}
        for name in list(self.pending_start):
            if name not in self.bot_by_name:
                del self.pending_start[name]
        for card in self.cards.values():
            card.destroy()
        self.cards = {}
        for b in self.bots:
            card = BotCard(self.card_box, self, b)
            card.pack(fill='x', pady=1)
            card.refresh(b.name == self.selected)
            self.cards[b.name] = card
        if select and select in self.bot_by_name:
            self.select_bot(select)
        elif self.selected is not None and self.selected in self.bot_by_name:
            self.cards[str(self.selected)].refresh(True)
        elif self.bots:
            self.select_bot(self.bots[0].name, force=True)
        else:
            self.selected = None
            self._clear_bot_view()
            self.toast('ไม่มีบอทใน instances.json — กด ➕ เพิ่มบอท', 'warn')

    def add_bot(self) -> None:
        dlg = self.add_dialog
        if dlg is not None:
            try:
                alive = bool(dlg.winfo_exists())
            except tk.TclError:
                alive = False
            if alive:
                dlg.lift()
                dlg.focus_set()
                return
        self.add_dialog = AddBotDialog(self)

    def remove_bot(self) -> None:
        b = self.cur_bot()
        if not b:
            self.toast('ไม่มีบอทให้ลบ', 'warn')
            return
        if self._removing:
            return
        if self._recovery_active == b.name:
            messagebox.showwarning('กำลังล็อกอินอัตโนมัติ',
                                   f'ระบบกำลังล็อกอิน {b.name} อยู่ — รอให้เสร็จก่อนแล้วค่อยลบ')
            return
        if b.running:
            messagebox.showwarning('ลบบอท', f'{b.name} กำลังรันอยู่ — ปิดบอท (⏹ ปิดบอท หรือ ✖ บังคับปิด) ก่อนแล้วค่อยลบ')
            return
        if self.kc_bot == b.name and self._config_dirty():
            if not messagebox.askyesno('ยังไม่ได้บันทึก', f'ทิ้งการแก้ไขที่ยังไม่ได้บันทึกของ {b.name}?'):
                return
        ans = messagebox.askyesnocancel(
            'ลบบอท',
            f'เอา {b.name} ออกจาก instances.json?\n\n'
            'Yes = ลบโฟลเดอร์โปรไฟล์ด้วย\nNo = เก็บโฟลเดอร์ไว้\nCancel = ยกเลิก')
        if ans is None:
            return
        args = ['remove', b.name] + (['-DeleteFiles'] if ans else [])
        self._removing = True
        self.btn_remove.state(['disabled'])
        self.toast(f'กำลังลบ {b.name}...', 'muted')

        def work() -> None:
            code, out = run_roz(ROOT_DIR, args)
            self._call_soon(lambda: self._removed(b.name, bool(ans), code, out))
        threading.Thread(target=work, daemon=True).start()

    def _removed(self, name: str, deleted: bool, code: int, out: str) -> None:
        self._removing = False
        self.btn_remove.state(['!disabled'])
        if code != 0:
            log.warning('roz remove %s failed: %s', name, out)
            hint = roz_error_text(out)
            messagebox.showerror('ลบบอทไม่สำเร็จ', (hint + '\n\n' if hint else '') + out)
            return
        self.reload_registry()
        self.toast(f'ลบ {name} แล้ว', 'ok')
        messagebox.showinfo('ลบบอท', f'นำ {name} ออกจากรายชื่อแล้ว'
                            + (' และลบโฟลเดอร์โปรไฟล์' if deleted else ' (เก็บโฟลเดอร์ไว้)'))

    def _clear_bot_view(self) -> None:
        """No bot left in the registry: reset the overview/config panels."""
        self.kc = None
        self.kc_bot = None
        self.c_title.configure(text='ยังไม่มีบอท')
        self.c_path.configure(text='')
        self.c_dirty.configure(text='')
        self.o_name.configure(text='-')
        self.o_state.configure(text='', bg=PANEL2, fg=TEXT)
        self.o_where.configure(text='')
        self.o_sub.configure(text='กด ➕ เพิ่มบอท ที่แถบซ้ายเพื่อสร้างบอทตัวแรก')
        for bar in (self.b_hp, self.b_sp, self.b_exp, self.b_job, self.b_w):
            bar.set(0, 0)
        for v in self.tiles.values():
            v.configure(text='-', fg=TEXT)

    # ----------------------------------------------------------- auto login
    def reset_recovery(self, name: str) -> None:
        """Settings were saved: let the next offline episode start from scratch."""
        self._recovery_attempts.pop(name, None)
        self._recovery_stopped.discard(name)
        self._last_recovery.pop(name, None)
        self._warned_no_game.discard(name)
        self._login_episode.discard(name)

    def begin_login_test(self, name: str) -> None:
        self._login_testing.add(name)
        self._last_recovery[name] = time.time()

    def end_login_test(self, name: str) -> None:
        self._login_testing.discard(name)
        self._last_recovery[name] = time.time()

    def _cache_game_pid(self, b: Bot) -> None:
        """Remember the game pid while the client is bridged (needed after a drop)."""
        if b.name in self._pid_checked:
            return
        pid = b.cached_game_pid()
        if pid and relogin.has_window(pid):
            self._pid_checked.add(b.name)
            self._warned_no_game.discard(b.name)
            return
        if not b.running:             # OpenKore must be alive to discover a game pid
            return
        if time.time() < self._pid_retry.get(b.name, 0.0):
            return
        self._pid_retry[b.name] = time.time() + 10.0     # one PowerShell call at a time

        def work() -> None:
            found = b.discover_game_pid()
            self._call_soon(lambda: self._pid_cached(b.name, found))
        threading.Thread(target=work, daemon=True).start()

    def _pid_cached(self, name: str, pid: int) -> None:
        if pid:
            b = self.bot_by_name.get(name)
            if b is not None:
                b.remember_game_pid(pid)
            self._pid_checked.add(name)
            self._pid_retry.pop(name, None)
            self._warned_no_game.discard(name)
        else:
            self._pid_retry[name] = time.time() + 30.0

    def _maybe_recover(self, b: Bot) -> None:
        name = b.name
        if not b.running:
            self._was_online.discard(name)   # stopped/closed by the user: never log back in on its own
        if b.online:
            self._was_online.add(name)
            self._offline_since.pop(name, None)
            self._recovery_attempts.pop(name, None)
            self._recovery_stopped.discard(name)
            self._warned_no_game.discard(name)
            self._login_episode.discard(name)
            return
        if b.status is None:          # never seen this bot online: do not guess
            return
        if self._login_testing or name in self.pending_start:
            return
        s = relogin.load_settings(name)
        if not s.enabled or not s.has_credentials():
            return
        if self._recovery_active is not None:
            return
        if name in self._recovery_stopped or not relogin.is_admin():
            return
        since = self._offline_since.setdefault(name, time.time())
        if time.time() - since < s.offline_seconds:
            return
        if time.time() - self._last_recovery.get(name, 0.0) < s.cooldown_seconds:
            return
        if self._recovery_attempts.get(name, 0) >= s.retries:
            self._recovery_stopped.add(name)
            self.notifier.notify(
                f'⚠️ [{name}] ล็อกอินอัตโนมัติหยุดหลังลอง {s.retries} ครั้ง — '
                'ตรวจบัญชี/เกมแล้วกดบันทึกในแท็บล็อกอินอัตโนมัติเพื่อเริ่มใหม่')
            return
        if name in self._warned_no_game:
            return                  # already told the user; _cache_game_pid clears it
        pid = b.cached_game_pid()
        if not (pid and relogin.has_window(pid)):
            pid = b.discover_game_pid()
            if pid:
                b.remember_game_pid(pid)
        if not pid or not relogin.has_window(pid):
            if name not in self._warned_no_game:
                self._warned_no_game.add(name)
                self.add_feed(name, '⚠ ไม่พบหน้าต่างเกมของบอทนี้ — เปิดเกม/ล็อกอินด้วยมือก่อน', 'warn')
                self.notifier.notify(f'⚠️ [{name}] หลุดและไม่พบหน้าต่างเกม — เปิดเกม/ล็อกอินด้วยมือก่อน')
            return
        if not relogin.has_dialog(pid):
            # No Windows popup. Start when:
            # - state 3 (character select): only clicks/arrows/Enter are sent;
            # - an episode already started (retries at the login screen);
            # - the bot was in game and OpenKore (still running) has been back at the
            #   login state for offline_seconds: a disconnect. ROZCLUB draws its
            #   'connection lost' box inside the game, so no popup is ever found;
            #   LoginRunner closes that box (screen check) before typing anything.
            state = int((b.status or {}).get('state', 0))
            dropped = (name in self._was_online and b.running and state in (0, 1)
                       and time.time() - self._user_stop.get(name, 0.0) > USER_STOP_GRACE_SECONDS)
            if state != 3 and name not in self._login_episode and not dropped:
                return
            if dropped:
                self._login_episode.add(name)
        else:
            self._login_episode.add(name)
        self._start_recovery(b, s, pid)

    def _maybe_startup_login(self, b: Bot) -> None:
        """After "start bot": once the game window has had boot_delay seconds to reach its
        login screen, run the same login as recovery. Failures then retry through
        _maybe_recover (the episode is marked), up to the bot's retry limit."""
        name = b.name
        started = self._startup_login.get(name)
        if started is None:
            return
        state = int((b.status or {}).get('state', 0))
        if b.online or state >= 2 or state == -1 or not b.running:
            # Logged in by hand / already past the login screen, or OpenKore died: nothing to do.
            self._startup_login.pop(name, None)
            self._game_seen.pop(name, None)
            return
        if self._recovery_active is not None or self._login_testing:
            return                                      # one login at a time; try again next poll
        s = relogin.load_settings(name)
        if not (s.enabled and s.has_credentials()):
            self._startup_login.pop(name, None)
            return
        now = time.time()
        if now - started > s.boot_delay + STARTUP_LOGIN_GIVEUP_SECONDS:
            self._startup_login.pop(name, None)
            self._game_seen.pop(name, None)
            self.add_feed(name, '⚠ ไม่พบหน้าต่างเกมหลังเปิดบอท — ล็อกอินเองในเกม', 'warn')
            return
        pid = b.cached_game_pid()                       # written by roz.ps1 when it launched the game
        if not (pid and relogin.has_window(pid)):
            return                                      # _cache_game_pid looks it up in the background
        seen = self._game_seen.setdefault(name, now)
        if now - seen < s.boot_delay:
            return
        self._startup_login.pop(name, None)
        self._game_seen.pop(name, None)
        self.reset_recovery(name)                       # a fresh start gets the full retry budget
        self._login_episode.add(name)                   # lets _maybe_recover retry at the login screen
        self._start_recovery(b, s, pid, reason='เปิดบอท')

    def _start_recovery(self, b: Bot, s: relogin.LoginSettings, pid: int, reason: str = 'หลุด') -> None:
        name = b.name
        attempt = self._recovery_attempts.get(name, 0) + 1
        self._recovery_attempts[name] = attempt
        self._last_recovery[name] = time.time()
        self._recovery_active = name
        self.add_feed(name, f'🔐 {reason} — กำลังล็อกอินอัตโนมัติ (ครั้งที่ {attempt}/{s.retries})', 'info')

        def log_cb(msg: str) -> None:
            self._call_soon(functools.partial(self.add_feed, name, msg, 'muted'))

        runner = relogin.LoginRunner(
            name, pid, s, log_cb,
            lambda: int((b.status or {}).get('state', 0)),
            get_chars=b.account_chars)

        def work() -> None:
            try:
                ok = runner.run(lambda: b.online, lambda: False)
            except Exception:
                log.exception('%s: auto login crashed', name)
                ok = False
            self._call_soon(lambda: self._recovery_done(name, ok, runner.debug_dir))
        threading.Thread(target=work, daemon=True).start()

    def _recovery_done(self, name: str, ok: bool, debug_dir: str) -> None:
        self._recovery_active = None
        s = relogin.load_settings(name)
        if ok:
            self._offline_since.pop(name, None)
            self._recovery_attempts.pop(name, None)
            self._recovery_stopped.discard(name)
            self._warned_no_game.discard(name)
            self._login_episode.discard(name)
            self.add_feed(name, '✅ ล็อกอินอัตโนมัติสำเร็จ', 'ok')
            self.notifier.notify(f'✅ [{name}] ล็อกอินอัตโนมัติสำเร็จ')
            self.toast(f'{name}: ล็อกอินอัตโนมัติสำเร็จ', 'ok')
            return
        attempt = self._recovery_attempts.get(name, 0)
        if attempt >= s.retries:
            self._recovery_stopped.add(name)
        self.add_feed(name, f'❌ ล็อกอินอัตโนมัติไม่สำเร็จ (ครั้งที่ {attempt}/{s.retries}) — ดูภาพที่ {debug_dir}', 'bad')
        self.notifier.notify(f'❌ [{name}] ล็อกอินอัตโนมัติไม่สำเร็จ (ครั้งที่ {attempt}/{s.retries})')
        self.toast(f'{name}: ล็อกอินอัตโนมัติไม่สำเร็จ — ดูแท็บล็อกอินอัตโนมัติ', 'bad')

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
