"""Palette, fonts and ttk styles of the ROZ Bot Control window."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any, Final

from .errlog import log


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


class Fonts:
    """Font tuples, filled in by ThemeMixin._fonts() once Tk exists."""
    F_BASE: Any = None
    F_SMALL: Any = None
    F_SMALLB: Any = None
    F_BOLD: Any = None
    F_TITLE: Any = None
    F_BIG: Any = None
    F_MONO: Any = None


class ThemeMixin:
    """Mixin of App: uses the state that App.__init__ sets up."""

    # ------------------------------------------------------------- styling
    def _fonts(self) -> None:
        fams = set(tkfont.families())
        fam = next((f for f in ('Leelawadee UI', 'Leelawadee', 'Segoe UI', 'Tahoma') if f in fams), 'TkDefaultFont')
        mono = next((f for f in ('Cascadia Mono', 'Consolas', 'Courier New') if f in fams), 'TkFixedFont')
        Fonts.F_BASE = (fam, 10)
        Fonts.F_SMALL = (fam, 9)
        Fonts.F_SMALLB = (fam, 9, 'bold')
        Fonts.F_BOLD = (fam, 10, 'bold')
        Fonts.F_TITLE = (fam, 16, 'bold')
        Fonts.F_BIG = (fam, 13, 'bold')
        Fonts.F_MONO = (mono, 9)
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
                     selectbackground=ACCENT, selectforeground='#ffffff', insertcolor=TEXT, font=Fonts.F_BASE)
        st.configure('TFrame', background=BG)
        st.configure('Panel.TFrame', background=PANEL)
        st.configure('TLabel', background=BG, foreground=TEXT)
        st.configure('Panel.TLabel', background=PANEL)
        st.configure('Muted.TLabel', foreground=MUTED, font=Fonts.F_SMALL)
        st.configure('PanelMuted.TLabel', background=PANEL, foreground=MUTED, font=Fonts.F_SMALL)
        st.configure('Title.TLabel', font=Fonts.F_TITLE)
        st.configure('PanelTitle.TLabel', background=PANEL, font=Fonts.F_TITLE)
        st.configure('Big.TLabel', background=PANEL, font=Fonts.F_BIG)
        st.configure('H.TLabel', font=Fonts.F_BOLD)
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
        st.configure('TLabelframe.Label', background=PANEL, foreground=TEXT, font=Fonts.F_BOLD)
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
        self.option_add('*TCombobox*Listbox.font', Fonts.F_BASE)
        st.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=28, borderwidth=0)
        st.configure('Pickup.Treeview', rowheight=36)       # room for 32 px item icons
        st.map('Treeview', background=[('selected', '#2f4a7a')])
        st.configure('Treeview.Heading', background=PANEL2, foreground=MUTED, borderwidth=0, padding=6)
        st.configure('Vertical.TScrollbar', background=PANEL2, troughcolor=BG, arrowcolor=MUTED, borderwidth=0,
                     bordercolor=BG, lightcolor=PANEL2, darkcolor=PANEL2, gripcount=0)
        st.map('Vertical.TScrollbar', background=[('active', BORDER)])