"""Log page: filtered OpenKore console output."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Final

from .bot import LogEntry
from .theme import BAD, BG, Fonts, OK, TEXT, WARN


IMPORTANT_DOMAINS: Final[set[str]] = {
    'pm', 'pm/sent', 'publicchat', 'partychat', 'guildchat', 'schat', 'selfchat', 'drop',
    # 'exp' left out on purpose: one "You have gained ..." line per kill floods this view;
    # level-ups still arrive as events. The "all" filter shows them.
    'connection', 'success', 'teleport', 'storage', 'npc', 'system', 'xkore', 'deal', 'party',
}
LOG_TAG: Final[dict[str, str]] = {'error': 'err', 'warning': 'warn'}
CHAT_DOMAINS: Final[set[str]] = {'pm', 'pm/sent', 'publicchat', 'partychat', 'guildchat', 'schat', 'selfchat'}


class LogPageMixin:
    """Mixin of App: uses the state that App.__init__ sets up."""

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
                              font=Fonts.F_BASE, state='disabled', spacing1=2)
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