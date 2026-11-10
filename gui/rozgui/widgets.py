"""Small reusable widgets: stat bar, scrollable frame, bot card."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from .bot import Bot
from .theme import BG, FIELD, Fonts, MUTED, PANEL, PANEL2, STATE_COLORS, TEXT

if TYPE_CHECKING:
    from .app import App


def fmt_int(n: Any) -> str:
    try:
        return f'{int(n):,}'
    except (TypeError, ValueError):
        return '-'


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
        self.create_text(10, h // 2, text=txt, anchor='w', fill='#ffffff', font=Fonts.F_SMALLB)


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
        self.title = tk.Label(top, text=bot.name, bg=PANEL, fg=TEXT, font=Fonts.F_BOLD, anchor='w')
        self.title.pack(side='left', fill='x')
        self.sub = tk.Label(self, text='', bg=PANEL, fg=MUTED, font=Fonts.F_SMALL, anchor='w', justify='left')
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