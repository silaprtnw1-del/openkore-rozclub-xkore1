"""Settings tabs laid out like the ROZCLUB in-game auto-hunt window.

BasicTab   (พื้นฐาน)    -> config.txt keys
MonsterTab (มอนสเตอร์)  -> mon_control.txt / priority.txt via monctl
Only values the user actually changed are written back.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Final

from . import monctl
from .kconfig import KConfig
from .rozdb import RozDB
from .tables import Tables

MODE_COLS: Final[tuple[tuple[str, str], ...]] = (
    (monctl.NORMAL, 'ปกติ'), (monctl.ONLY, 'ตีเฉพาะ'), (monctl.SKIP, 'ไม่ตี'), (monctl.FLEE, 'เจอแล้วหนี'))
ON: Final[str] = '●'
OFF: Final[str] = '○'


def _num(v: str, label: str, lo: float = 0, hi: float = 100) -> str:
    s = v.strip()
    try:
        f = float(s)
    except ValueError:
        raise ValueError(f'ช่อง "{label}" ต้องเป็นตัวเลข')
    if not lo <= f <= hi:
        raise ValueError(f'ช่อง "{label}" ต้องอยู่ระหว่าง {lo:g}–{hi:g}')
    return f'{f:g}'


class BasicTab(ttk.Frame):
    """พื้นฐาน: attack style, support/follow, auto-sit, weight."""

    def __init__(self, parent: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(parent, style='Panel.TFrame', padding=(16, 10))
        self.on_change = on_change
        self.orig: dict[str, str] = {}
        self.baseline: dict[str, str] = {}
        self._dirty = False

        self.status = ttk.Label(self, text='', style='PanelMuted.TLabel')
        self.status.pack(anchor='w', pady=(0, 6))

        atk = ttk.LabelFrame(self, text=' ⚔️ การโจมตี ', padding=(12, 8))
        atk.pack(fill='x', pady=4)
        row = ttk.Frame(atk, style='Panel.TFrame')
        row.pack(fill='x')
        ttk.Label(row, text='รูปแบบการโจมตี:', style='Panel.TLabel').pack(side='left', padx=(0, 10))
        self.style_var = tk.StringVar(value='weapon')
        for val, text in (('weapon', 'ตีปกติ + สกิล'), ('skill', 'ตีเฉพาะสกิล')):
            ttk.Radiobutton(row, text=text, value=val, variable=self.style_var,
                            command=self._changed).pack(side='left', padx=(0, 16))
        ttk.Label(atk, text='ตีด้วยอาวุธตามปกติ และใช้สกิลที่เลือกไว้ในแท็บ [สกิล] ร่วมด้วย',
                  style='PanelMuted.TLabel').pack(anchor='w')
        self.counter_var = tk.IntVar(value=1)
        ttk.Checkbutton(atk, text='ตอบโต้มอนสเตอร์ที่เข้ามาโจมตี แม้จะไม่อยู่ในรายการ',
                        variable=self.counter_var, command=self._changed).pack(anchor='w', pady=(6, 0))
        sup = ttk.Frame(atk, style='Panel.TFrame')
        sup.pack(fill='x', pady=(6, 0))
        self.support_var = tk.IntVar(value=0)
        ttk.Checkbutton(sup, text='Support (เดินตามคนในปาร์ตี้ ไม่ตีมอนสเตอร์)', variable=self.support_var,
                        command=self._changed).pack(side='left')
        self.target_var = tk.StringVar()
        self.target_box = ttk.Combobox(sup, textvariable=self.target_var, width=24)
        self.target_box.pack(side='left', padx=12)
        self.target_box.bind('<<ComboboxSelected>>', lambda e: self._changed())
        self.target_box.bind('<KeyRelease>', lambda e: self._changed())
        ttk.Label(atk, text='เดินตามคนที่เลือก (รายชื่อจากปาร์ตี้และบอทตัวอื่น) — ฮีล/บัฟใช้สกิลที่ตั้งในแท็บ [สกิล]',
                  style='PanelMuted.TLabel', wraplength=820, justify='left').pack(anchor='w')

        sit = ttk.LabelFrame(self, text=' 🪑 นั่งพักฟื้นอัตโนมัติ ', padding=(12, 8))
        sit.pack(fill='x', pady=4)
        self.sit_var = tk.IntVar(value=0)
        ttk.Checkbutton(sit, text='นั่งพักเมื่อ HP/SP ต่ำ', variable=self.sit_var,
                        command=self._changed).grid(row=0, column=0, columnspan=4, sticky='w')
        self.sit_vals: dict[str, tk.StringVar] = {}
        for r, (lo_key, hi_key, what) in enumerate((('sitAuto_hp_lower', 'sitAuto_hp_upper', 'HP'),
                                                    ('sitAuto_sp_lower', 'sitAuto_sp_upper', 'SP')), start=1):
            for c, (key, text) in enumerate(((lo_key, f'นั่งเมื่อ {what} ต่ำกว่า (%)'), (hi_key, f'ลุกเมื่อ {what} ถึง (%)'))):
                ttk.Label(sit, text=text, style='Panel.TLabel').grid(row=r, column=c * 2, sticky='w', pady=3, padx=(0, 8))
                v = tk.StringVar()
                sb = ttk.Spinbox(sit, textvariable=v, from_=0, to=100, increment=5, width=6, command=self._changed)
                sb.grid(row=r, column=c * 2 + 1, sticky='w', padx=(0, 24))
                sb.bind('<KeyRelease>', lambda e: self._changed())
                self.sit_vals[key] = v

        wt = ttk.LabelFrame(self, text=' 🎒 น้ำหนัก ', padding=(12, 8))
        wt.pack(fill='x', pady=4)
        self.weight_vals: dict[str, tk.StringVar] = {}
        for r, (key, text) in enumerate((('itemsMaxWeight', 'หยุดเก็บของเมื่อน้ำหนักถึง (%)'),
                                         ('itemsMaxWeight_sellOrStore', 'กลับเมืองไปขาย/ฝากเมื่อน้ำหนักถึง (%)'))):
            ttk.Label(wt, text=text, style='Panel.TLabel').grid(row=r, column=0, sticky='w', pady=3, padx=(0, 10))
            v = tk.StringVar()
            sb = ttk.Spinbox(wt, textvariable=v, from_=0, to=100, increment=1, width=6, command=self._changed)
            sb.grid(row=r, column=1, sticky='w')
            sb.bind('<KeyRelease>', lambda e: self._changed())
            self.weight_vals[key] = v

    def _changed(self) -> None:
        self._dirty = True
        self.on_change()

    def is_dirty(self) -> bool:
        return self._dirty

    def fill(self, kc: KConfig | None, status: dict[str, Any] | None, follow_choices: list[str],
             counter: bool) -> None:
        keys = ('attackUseWeapon', 'follow', 'followTarget', 'attackAuto', *self.sit_vals, *self.weight_vals)
        self.orig = {k: (kc.get(k, '') if kc else '').strip() for k in keys}
        self.style_var.set('skill' if self.orig['attackUseWeapon'] == '0' else 'weapon')
        self.counter_var.set(1 if counter else 0)
        self.support_var.set(1 if self.orig['follow'] not in ('', '0') else 0)
        self.target_var.set(self.orig['followTarget'])
        self.target_box['values'] = follow_choices
        lows = [self.orig['sitAuto_hp_lower'], self.orig['sitAuto_sp_lower']]
        self.sit_var.set(1 if any(v not in ('', '0') for v in lows) else 0)
        for k, v in self.sit_vals.items():
            v.set(self.orig[k] or '0')
        for k, v in self.weight_vals.items():
            v.set(self.orig[k])
        # What saving the untouched form would produce. apply() writes only keys that differ
        # from this, so keys missing from config.txt are never appended just because they show 0.
        self.baseline = self._compute(strict=False)
        self.set_status(status)
        self._dirty = False

    def set_status(self, status: dict[str, Any] | None) -> None:
        if status and status.get('online'):
            hp = status['hp'] * 100 // status['hp_max'] if status.get('hp_max') else 0
            sp = status['sp'] * 100 // status['sp_max'] if status.get('sp_max') else 0
            state = 'ทำงาน' if status.get('ai') == 'auto' else 'หยุดอยู่'
            self.status.configure(text=f'สถานะ: {state}   แผนที่: {status.get("map")}   HP {hp}%   SP {sp}%')
        else:
            self.status.configure(text='สถานะ: บอทไม่ได้อยู่ในเกม — แก้ค่าได้ จะมีผลเมื่อบอทโหลด config')

    def _compute(self, strict: bool) -> dict[str, str]:
        """config.txt values the form currently stands for. strict=True raises ValueError (Thai)
        on input the user must fix; strict=False (baseline) never raises."""
        labels = {'sitAuto_hp_lower': 'นั่งเมื่อ HP ต่ำกว่า', 'sitAuto_hp_upper': 'ลุกเมื่อ HP ถึง',
                  'sitAuto_sp_lower': 'นั่งเมื่อ SP ต่ำกว่า', 'sitAuto_sp_upper': 'ลุกเมื่อ SP ถึง',
                  'itemsMaxWeight': 'หยุดเก็บของเมื่อน้ำหนักถึง',
                  'itemsMaxWeight_sellOrStore': 'กลับเมืองไปขาย/ฝากเมื่อน้ำหนักถึง'}

        def num(raw: str, key: str) -> str:
            try:
                return _num(raw, labels[key])
            except ValueError:
                if strict:
                    raise
                return raw.strip()

        new: dict[str, str] = {'attackUseWeapon': '0' if self.style_var.get() == 'skill' else '1'}
        target = self.target_var.get().strip()
        if self.support_var.get():
            if strict and not target:
                raise ValueError('เปิด Support แล้ว ต้องเลือกคนที่จะเดินตาม')
            new.update(follow='1', followTarget=target, attackAuto='0')
        else:
            new.update(follow='0', attackAuto='2')
        for k, v in self.sit_vals.items():
            new[k] = num(v.get(), k)
        if self.sit_var.get():
            if strict and new['sitAuto_hp_lower'] == '0' and new['sitAuto_sp_lower'] == '0':
                raise ValueError('เปิดนั่งพักแล้ว ต้องตั้ง "นั่งเมื่อ HP ต่ำกว่า" หรือ "นั่งเมื่อ SP ต่ำกว่า" มากกว่า 0')
        else:
            new['sitAuto_hp_lower'] = new['sitAuto_sp_lower'] = '0'
        for k, v in self.weight_vals.items():
            if v.get().strip():
                new[k] = num(v.get(), k)
        return new

    def apply(self, kc: KConfig) -> None:
        """Write only keys the user changed. Raises ValueError with a Thai message on bad input."""
        for k, value in self._compute(strict=True).items():
            if value != self.baseline.get(k):
                kc.set(k, value)
        self._dirty = False

    def counter(self) -> bool:
        return bool(self.counter_var.get())


class MonsterTab(ttk.Frame):
    """มอนสเตอร์: per-monster mode for a map, monster list from the rozclub database."""

    def __init__(self, parent: tk.Misc, on_change: Callable[[], None], on_refresh_db: Callable[[], None]) -> None:
        super().__init__(parent, style='Panel.TFrame', padding=(16, 10))
        self.on_change = on_change
        self.db = RozDB()
        self.tables: Tables | None = None
        self.settings = monctl.MonSettings({}, True)
        self.control_dir = ''
        self._dirty = False

        top = ttk.Frame(self, style='Panel.TFrame')
        top.pack(fill='x')
        ttk.Label(top, text='แผนที่', style='Panel.TLabel').pack(side='left')
        self.map_var = tk.StringVar()
        self.map_box = ttk.Combobox(top, textvariable=self.map_var, width=42)
        self.map_box.pack(side='left', padx=8)
        self.map_box.bind('<<ComboboxSelected>>', lambda e: self.render())
        self.map_box.bind('<Return>', lambda e: self.render())
        self.cur_btn = ttk.Button(top, text='📍 แผนที่ที่บอทอยู่', command=self._use_current)
        self.cur_btn.pack(side='left', padx=2)
        ttk.Button(top, text='🔄 โหลดข้อมูลเกมใหม่', command=on_refresh_db).pack(side='right')
        self.db_label = ttk.Label(self, text='', style='PanelMuted.TLabel')
        self.db_label.pack(anchor='w', pady=(4, 0))
        ttk.Label(self, style='PanelMuted.TLabel', justify='left', text=(
            'คลิกช่องเพื่อเลือกว่าจะทำอะไรกับมอนแต่ละตัว   ปกติ = ตีตามปกติ  |  ตีเฉพาะ = ถ้ามีตัวไหนตั้ง "ตีเฉพาะ" '
            'จะตีแค่กลุ่มนี้  |  ไม่ตี = เดินผ่าน  |  เจอแล้วหนี = วาร์ปทันทีเมื่อเห็น')).pack(anchor='w', pady=(2, 6))

        cols = ('name', 'lv', 'count') + tuple(m for m, _ in MODE_COLS)
        tv = ttk.Treeview(self, columns=cols, show='headings', selectmode='none', height=12)
        tv.heading('name', text='มอนสเตอร์', anchor='w')
        tv.column('name', width=230, anchor='w', stretch=True)
        for c, text, w in (('lv', 'Lv', 50), ('count', 'จำนวน', 90)):
            tv.heading(c, text=text, anchor='center')
            tv.column(c, width=w, anchor='center', stretch=False)
        for mode, text in MODE_COLS:
            tv.heading(mode, text=text, anchor='center')
            tv.column(mode, width=90, anchor='center', stretch=False)
        tv.tag_configure('other', foreground='#8e96aa')
        tv.pack(fill='both', expand=True)
        tv.bind('<ButtonRelease-1>', self._on_click)
        self.tv = tv

        add = ttk.Frame(self, style='Panel.TFrame')
        add.pack(fill='x', pady=(8, 0))
        ttk.Label(add, text='เพิ่มด้วย ID มอนสเตอร์:', style='Panel.TLabel').pack(side='left')
        self.add_id = tk.StringVar()
        ttk.Entry(add, textvariable=self.add_id, width=10).pack(side='left', padx=6)
        self.add_mode = tk.StringVar(value=dict(MODE_COLS)[monctl.FLEE])
        ttk.Combobox(add, textvariable=self.add_mode, values=[t for _, t in MODE_COLS], state='readonly',
                     width=12).pack(side='left', padx=6)
        ttk.Button(add, text='เพิ่ม', command=self._add).pack(side='left', padx=6)
        self.add_msg = ttk.Label(add, text='', style='PanelMuted.TLabel')
        self.add_msg.pack(side='left', padx=8)
        self.current_map = ''

    # ------------------------------------------------------------------ data
    def set_db(self, db: RozDB, tables: Tables) -> None:
        self.db, self.tables = db, tables
        maps = sorted(n for n, m in db.maps.items() if m.spawns)
        self.map_box['values'] = [f'{n} — {db.maps[n].title}' for n in maps]
        if db.error:
            self.db_label.configure(text=f'⚠ โหลดข้อมูลมอนจาก rozclub.com ไม่ได้: {db.error}')
        else:
            src = {'web': 'อัปเดตล่าสุดจาก rozclub.com', 'cache': 'จากแคชในเครื่อง (อายุไม่เกิน 1 วัน)',
                   'cache (offline)': 'จากแคชในเครื่อง (ออฟไลน์)'}.get(db.source, db.source)
            self.db_label.configure(text=f'ข้อมูลมอน {len(db.mobs)} ตัว / {len(maps)} แผนที่ — {src}')
        self.render()

    def fill(self, control_dir: str, lock_map: str, current_map: str) -> None:
        self.control_dir = control_dir
        self.settings = monctl.load(control_dir)
        self.current_map = current_map
        self._set_map(lock_map or current_map)
        self._dirty = False

    def set_current_map(self, current_map: str) -> None:
        self.current_map = current_map
        self.cur_btn.state(['!disabled'] if current_map else ['disabled'])

    def _map_name(self) -> str:
        return self.map_var.get().split(' — ')[0].strip()

    def _set_map(self, name: str) -> None:
        info = self.db.maps.get(name)
        self.map_var.set(f'{name} — {info.title}' if info else name)
        self.render()

    def _use_current(self) -> None:
        if self.current_map:
            self._set_map(self.current_map)

    # ---------------------------------------------------------------- table
    def render(self) -> None:
        tv = self.tv
        tv.delete(*tv.get_children())
        shown: set[int] = set()
        for mob, sp in self.db.map_spawns(self._map_name()):
            self._insert(sp.mob_id, mob.name if mob else str(sp.mob_id), mob.level if mob else 0, str(sp.count), ())
            shown.add(sp.mob_id)
        for r in sorted(self.settings.rules.values(), key=lambda r: r.name.lower()):
            if r.mob_id not in shown and r.mode != monctl.NORMAL:
                mob = self.db.mobs.get(r.mob_id)
                self._insert(r.mob_id, r.name, mob.level if mob else 0, 'แผนที่อื่น', ('other',))

    def _mode(self, mob_id: int) -> str:
        r = self.settings.rules.get(mob_id)
        return r.mode if r else monctl.NORMAL

    def _insert(self, mob_id: int, name: str, lv: int, count: str, tags: tuple[str, ...]) -> None:
        mode = self._mode(mob_id)
        self.tv.insert('', 'end', iid=str(mob_id), tags=tags,
                       values=(f'{name}  ({mob_id})', lv or '-', count) + tuple(ON if m == mode else OFF for m, _ in MODE_COLS))

    def _on_click(self, event: tk.Event) -> None:
        row = self.tv.identify_row(event.y)
        col = self.tv.identify_column(event.x)       # '#4'..'#7' are the mode columns
        if not row or not col:
            return
        idx = int(col[1:]) - 4
        if not 0 <= idx < len(MODE_COLS):
            return
        self._set_mode(int(row), MODE_COLS[idx][0])

    def _set_mode(self, mob_id: int, mode: str) -> None:
        mob = self.db.mobs.get(mob_id)
        name = mob.name if mob else (self.tables.monsters.get(mob_id) if self.tables else None) or str(mob_id)
        self.settings.rules[mob_id] = monctl.MonRule(mob_id, name, mode)
        self._dirty = True
        self.on_change()
        self.render()

    def _add(self) -> None:
        raw = self.add_id.get().strip()
        if not raw.isdigit():
            self.add_msg.configure(text='ใส่เลข ID มอน เช่น 1015')
            return
        mob_id = int(raw)
        known = mob_id in self.db.mobs or (self.tables is not None and mob_id in self.tables.monsters)
        mode = next(m for m, t in MODE_COLS if t == self.add_mode.get())
        self._set_mode(mob_id, mode)
        self.add_msg.configure(text='' if known else f'⚠ ไม่พบ ID {mob_id} ในฐานข้อมูล — เพิ่มไว้แล้ว ตรวจเลขอีกครั้ง')
        self.add_id.set('')

    # ----------------------------------------------------------------- save
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_shown_map_rules(self) -> None:
        """Every monster on the shown map gets an explicit rule, like the in-game list."""
        for _, sp in self.db.map_spawns(self._map_name()):
            if sp.mob_id not in self.settings.rules:
                self.settings.rules[sp.mob_id] = monctl.MonRule(sp.mob_id, self.db.mob_name(sp.mob_id), monctl.NORMAL)

    def save(self, counter: bool) -> None:
        """Write mon_control.txt / priority.txt. Raises OSError."""
        self.settings.counter = counter
        self.mark_shown_map_rules()
        monctl.save(self.control_dir, self.settings, self.tables.monsters if self.tables else {})
        self._dirty = False
