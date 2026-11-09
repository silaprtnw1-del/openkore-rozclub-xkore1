"""เก็บไอเทม and เคลื่อนที่ tabs, laid out like the ROZCLUB in-game window.

PickupTab -> pickupitems.txt GUI section (pickup.py) + config itemsTakeAuto/itemsGatherAuto for "ไม่เก็บเลย"
MoveTab   -> config teleportAuto_* + timeouts.txt ai_teleport_idle
Keys verified in OpenKore src: AI/CoreLogic.pm (teleportAuto_hp/minAggressives/idle,
ai_teleport_idle timeout), Task/Teleport/Random.pm (teleportAuto_useSkill, Fly Wing fallback).
"""
from __future__ import annotations

import functools
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Final

from . import pickup as P
from .icons import IconCache
from .kconfig import KConfig
from .rozdb import RozDB
from .tables import Tables

KIND_TH: Final[dict[str, str]] = {
    'etc': 'ของสะสม', 'card': 'การ์ด', 'usable': 'ใช้ได้', 'weapon': 'อาวุธ', 'armor': 'ชุดเกราะ',
    'headgear': 'หมวก', 'shield': 'โล่', 'garment': 'ผ้าคลุม', 'shoes': 'รองเท้า', 'accessory': 'เครื่องประดับ',
    'ammo': 'กระสุน', 'costume': 'คอสตูม', 'pet': 'สัตว์เลี้ยง'}
CHECK: Final[str] = '☑'
UNCHECK: Final[str] = '☐'
FLY_WING_IDS: Final[frozenset[int]] = frozenset({601, 12323})   # Fly Wing, Novice Fly Wing


class PickupTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(parent, style='Panel.TFrame', padding=(16, 10))
        self.on_change = on_change
        self.db = RozDB()
        self.tables: Tables | None = None
        self.icons: IconCache | None = None
        self.ps = P.PickupSettings()
        self.control_dir = ''
        self.current_map = ''
        self.market: dict[str, str] = {}
        self._dirty = False
        self._shown: dict[int, str] = {}           # item id -> display name of rows currently listed

        ttk.Label(self, text='ตั้งค่ารูปแบบการเก็บไอเทม — เก็บไอเทมประเภทที่เลือกโดยอัตโนมัติ', style='Big.TLabel').pack(anchor='w')
        modes = ttk.Frame(self, style='Panel.TFrame')
        modes.pack(fill='x', pady=(6, 0))
        self.mode_var = tk.StringVar(value=P.EXCEPT)
        for val, text in ((P.EXCEPT, 'เก็บทุกอย่าง ยกเว้นที่ไม่ได้เลือก'), (P.ONLY, 'เก็บเฉพาะที่เลือก'), (P.NONE, 'ไม่เก็บเลย')):
            ttk.Radiobutton(modes, text=text, value=val, variable=self.mode_var,
                            command=self._mode_changed).pack(side='left', padx=(0, 18))
        ttk.Label(self, style='PanelMuted.TLabel', wraplength=900, justify='left', text=(
            'ค่าที่ตั้งตรงนี้ชนะค่าจาก market auto (ราคาตลาด) ถ้าไอเทมเดียวกัน · '
            'OpenKore แยกอาวุธ/ชุดเกราะตาม Option สุ่มไม่ได้ จึงไม่มีตัวเลือก Option แบบในเกม')).pack(anchor='w', pady=(4, 6))

        top = ttk.Frame(self, style='Panel.TFrame')
        top.pack(fill='x')
        ttk.Label(top, text='ไอเทมที่ดรอปในแผนที่', style='Panel.TLabel').pack(side='left')
        self.map_var = tk.StringVar()
        self.map_box = ttk.Combobox(top, textvariable=self.map_var, width=38)
        self.map_box.pack(side='left', padx=8)
        self.map_box.bind('<<ComboboxSelected>>', lambda e: self.render())
        self.map_box.bind('<Return>', lambda e: self.render())
        ttk.Button(top, text='📍 แผนที่ที่บอทอยู่', command=self._use_current).pack(side='left')
        bulk = ttk.Frame(self, style='Panel.TFrame')
        bulk.pack(fill='x', pady=6)
        for text, fn in (('เลือกทั้งหมด', self._all_on), ('ไม่เลือกเลย', self._all_off),
                         ('เฉพาะการ์ด', self._cards_only), ('ไม่เก็บของสะสม', self._no_etc)):
            ttk.Button(bulk, text=text, command=fn).pack(side='left', padx=(0, 4))
        ttk.Label(bulk, text='ค้นหา', style='Panel.TLabel').pack(side='left', padx=(16, 4))
        self.q = tk.StringVar()
        ttk.Entry(bulk, textvariable=self.q, width=22).pack(side='left')
        self.q.trace_add('write', lambda *a: self.render())

        tv = ttk.Treeview(self, columns=('kind', 'rate', 'from', 'market'), show='tree headings',
                          selectmode='none', height=12)
        tv.heading('#0', text='เลือก   ไอเทม', anchor='w')
        tv.column('#0', width=300, anchor='w')
        for c, text, w in (('kind', 'ประเภท', 100), ('rate', 'โอกาสดรอป', 90), ('from', 'ดรอปจาก', 220),
                           ('market', 'market ตั้งไว้', 100)):
            tv.heading(c, text=text, anchor='w')
            tv.column(c, width=w, anchor='w', stretch=(c == 'from'))
        tv.configure(style='Pickup.Treeview')
        tv.pack(fill='both', expand=True)
        tv.bind('<ButtonRelease-1>', self._on_click)
        self.tv = tv
        self.note = ttk.Label(self, text='', style='PanelMuted.TLabel')
        self.note.pack(anchor='w', pady=(4, 0))

    # ------------------------------------------------------------------ data
    def set_db(self, db: RozDB, tables: Tables) -> None:
        self.db, self.tables = db, tables
        maps = sorted(n for n, m in db.maps.items() if m.spawns)
        self.map_box['values'] = [f'{n} — {db.maps[n].title}' for n in maps]
        self.render()

    def fill(self, kc: KConfig | None, control_dir: str, lock_map: str, current_map: str) -> None:
        self.control_dir = control_dir
        self.current_map = current_map
        self.ps = P.load(control_dir)
        self.market = P.market_values(control_dir)
        take = (kc.get('itemsTakeAuto', '') if kc else '').strip()
        gather = (kc.get('itemsGatherAuto', '') if kc else '').strip()
        if take == '0' and gather == '0':
            self.ps.mode = P.NONE                  # config says the bot picks nothing up
        self.mode_var.set(self.ps.mode)
        self._orig_take, self._orig_gather = take, gather
        self._set_map(lock_map or current_map)
        self._dirty = False

    def _map_name(self) -> str:
        return self.map_var.get().split(' — ')[0].strip()

    def _set_map(self, name: str) -> None:
        info = self.db.maps.get(name)
        self.map_var.set(f'{name} — {info.title}' if info else name)
        self.render()

    def _use_current(self) -> None:
        if self.current_map:
            self._set_map(self.current_map)

    def _item_label(self, item_id: int) -> str:
        roz = self.db.items.get(item_id)
        if roz:
            return roz[0]
        return (self.tables.items.get(item_id) if self.tables else None) or str(item_id)

    def _kind(self, item_id: int) -> str:
        roz = self.db.items.get(item_id)
        return roz[1] if roz else ''

    # ---------------------------------------------------------------- state
    def checked(self, item_id: int) -> bool:
        if self.mode_var.get() == P.ONLY:
            return item_id in self.ps.pick
        return item_id not in self.ps.skip

    def _set_checked(self, item_id: int, on: bool) -> None:
        name = self._item_label(item_id)
        if self.mode_var.get() == P.ONLY:
            if on:
                self.ps.pick[item_id] = name
                self.ps.skip.pop(item_id, None)
            else:
                self.ps.pick.pop(item_id, None)
        elif on:
            self.ps.skip.pop(item_id, None)
        else:
            self.ps.skip[item_id] = name

    def _mode_changed(self) -> None:
        old, new = self.ps.mode, self.mode_var.get()
        # Keep the ticks the user sees when switching between the two list modes.
        if old == P.EXCEPT and new == P.ONLY:
            self.ps.pick = {i: n for i, n in self._shown.items() if i not in self.ps.skip}
        elif old == P.ONLY and new == P.EXCEPT:
            for i, n in self._shown.items():
                if i not in self.ps.pick:
                    self.ps.skip[i] = n
        self.ps.mode = new
        self._changed()
        self.render()

    def _changed(self) -> None:
        self._dirty = True
        self.on_change()

    def _bulk(self, pred: Callable[[int], bool]) -> None:
        for item_id in self._shown:
            self._set_checked(item_id, pred(item_id))
        self._changed()
        self.render()

    def _all_on(self) -> None:
        self._bulk(lambda i: True)

    def _all_off(self) -> None:
        self._bulk(lambda i: False)

    def _cards_only(self) -> None:
        self._bulk(lambda i: self._kind(i) == 'card')

    def _no_etc(self) -> None:
        self._bulk(lambda i: self._kind(i) != 'etc' and self.checked(i))

    # ---------------------------------------------------------------- render
    def render(self) -> None:
        tv = self.tv
        tv.delete(*tv.get_children())
        self._shown = {}
        none_mode = self.mode_var.get() == P.NONE
        q = self.q.get().strip().lower()
        drops = self.db.map_drops(self._map_name())
        for item_id, rate, mobs in drops:
            name = self._item_label(item_id)
            self._shown[item_id] = name
            if q and q not in name.lower():
                continue
            mk = self.market.get(str(item_id)) or self.market.get(name.lower()) or ''
            mk_text = {'2': 'เก็บก่อน', '1': 'เก็บ', '0': 'ไม่เก็บ', '-1': 'เก็บแล้วทิ้ง'}.get(mk, '-')
            iid = str(item_id)
            mark = '–' if none_mode else (CHECK if self.checked(item_id) else UNCHECK)
            tv.insert('', 'end', iid=iid, text=f' {mark}   {name}',
                      values=(KIND_TH.get(self._kind(item_id), self._kind(item_id) or '-'),
                              f'{rate / 100:g}%', ', '.join(mobs), mk_text))
            if self.icons:
                self.icons.request(item_id, functools.partial(self._row_icon, iid))
        if self.db.error and not drops:
            self.note.configure(text=f'โหลดข้อมูลแผนที่จาก rozclub.com ไม่ได้: {self.db.error}')
        elif none_mode:
            self.note.configure(text='โหมด "ไม่เก็บเลย": บอทจะไม่เก็บไอเทมใด ๆ (itemsTakeAuto 0, itemsGatherAuto 0)')
        else:
            self.note.configure(text='คลิกแถวเพื่อเลือก/ไม่เลือก')

    def _row_icon(self, iid: str, img: Any) -> None:
        if self.tv.exists(iid):
            self.tv.item(iid, image=img)

    def _on_click(self, event: tk.Event) -> None:
        if self.mode_var.get() == P.NONE:
            return
        row = self.tv.identify_row(event.y)
        if not row:
            return
        item_id = int(row)
        self._set_checked(item_id, not self.checked(item_id))
        self._changed()
        self.render()

    # ------------------------------------------------------------------ save
    def is_dirty(self) -> bool:
        return self._dirty

    def apply_config(self, kc: KConfig) -> None:
        """'ไม่เก็บเลย' lives in config.txt; leaving it restores the previous values."""
        if not self._dirty:
            return
        if self.mode_var.get() == P.NONE:
            for key in ('itemsTakeAuto', 'itemsGatherAuto'):
                if kc.get(key, '').strip() != '0':
                    kc.set(key, '0')
        elif self._orig_take == '0' and self._orig_gather == '0':
            kc.set('itemsTakeAuto', '2')            # OpenKore's usual farming values
            kc.set('itemsGatherAuto', '1')

    def save(self, fallback_path: str) -> bool:
        """Write the pickupitems.txt section. True if written. Raises OSError."""
        if not self._dirty:
            return False
        self.ps.mode = self.mode_var.get()
        if self.ps.mode == P.ONLY:                   # unticked rows must override market lines
            for i, n in self._shown.items():
                if i not in self.ps.pick:
                    self.ps.skip[i] = n
        names_of = {i: [n for n in (self._item_label(i), self.tables.items.get(i) if self.tables else None) if n]
                    for i in {*self.ps.skip, *self.ps.pick}}
        P.save(self.control_dir, self.ps, names_of, fallback_path)
        self.market = P.market_values(self.control_dir)
        self._dirty = False
        return True


class MoveTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(parent, style='Panel.TFrame', padding=(16, 10))
        self.on_change = on_change
        self.baseline: dict[str, str] = {}
        self._dirty = False
        ttk.Label(self, text='ตั้งค่าการเคลื่อนที่ — Teleport อัตโนมัติ', style='Big.TLabel').pack(anchor='w')
        self.how = ttk.Label(self, text='', style='Panel.TLabel', wraplength=900, justify='left')
        self.how.pack(anchor='w', pady=(6, 2))
        self.skill_var = tk.IntVar(value=1)
        self.skill_cb = ttk.Checkbutton(self, text='ใช้สกิล Teleport (ถ้ามี)', variable=self.skill_var, command=self._changed)
        self.skill_cb.pack(anchor='w')
        self.master_var = tk.IntVar(value=0)
        ttk.Checkbutton(self, text='เปิดใช้ Teleport อัตโนมัติ', variable=self.master_var,
                        command=self._master_changed).pack(anchor='w', pady=(10, 4))
        lf = ttk.LabelFrame(self, text=' 🌀 วาร์ปเมื่อ ', padding=(12, 8))
        lf.pack(fill='x')
        self.vals: dict[str, tk.StringVar] = {}
        self.spins: list[ttk.Spinbox] = []
        for r, (key, text, hi, step) in enumerate((
                ('idle', 'ไม่มีการต่อสู้ภายใน (วินาที, 0 = ปิด)', 600, 5),
                ('aggr', 'โดนมอนสเตอร์รุมตั้งแต่ (ตัว, 0 = ปิด)', 30, 1),
                ('hp', 'โดนตีแล้ว HP ต่ำกว่า (%, 0 = ปิด)', 99, 5))):
            ttk.Label(lf, text=text, style='Panel.TLabel').grid(row=r, column=0, sticky='w', pady=3, padx=(0, 12))
            v = tk.StringVar(value='0')
            sb = ttk.Spinbox(lf, textvariable=v, from_=0, to=hi, increment=step, width=7, command=self._changed)
            sb.grid(row=r, column=1, sticky='w')
            sb.bind('<KeyRelease>', lambda e: self._changed())
            self.vals[key] = v
            self.spins.append(sb)
        ttk.Label(self, style='PanelMuted.TLabel', text=(
            'มอนสเตอร์ที่ต้องการหนีทันทีเมื่อเจอ ตั้งได้ที่แท็บ [มอนสเตอร์] → เจอแล้วหนี')).pack(anchor='w', pady=(10, 0))

    def fill(self, kc: KConfig | None, tkc: KConfig | None, char_json: dict[str, Any] | None) -> None:
        g = (lambda k: kc.get(k, '').strip()) if kc else (lambda k: '')
        skills = {s.get('handle'): s.get('lv') for s in (char_json or {}).get('skills') or [] if isinstance(s, dict)}
        has_skill = bool(skills.get('AL_TELEPORT'))
        wings = sum(int(i.get('amount') or 0) for i in (char_json or {}).get('items') or []
                    if isinstance(i, dict) and int(i.get('id') or 0) in FLY_WING_IDS)
        how = (f'มีสกิล Teleport Lv {skills["AL_TELEPORT"]}' if has_skill else 'ตัวละครนี้ยังไม่มีสกิล Teleport')
        how += f' · Fly Wing ในกระเป๋า {wings} ชิ้น' if char_json else ' · (ไม่มีข้อมูลกระเป๋า)'
        how += ' — บอทใช้สกิลก่อนถ้าเปิดไว้และ SP พอ ไม่งั้นใช้ Fly Wing'
        self.how.configure(text=how)
        self.skill_var.set(0 if g('teleportAuto_useSkill') == '0' else 1)
        self.skill_cb.state(['!disabled'] if has_skill else ['disabled'])
        idle_on = g('teleportAuto_idle') not in ('', '0')
        idle_secs = (tkc.get('ai_teleport_idle', '').strip() if tkc else '') or '0'
        self.vals['idle'].set(idle_secs if idle_on else '0')
        self.vals['aggr'].set(g('teleportAuto_minAggressives') or '0')
        self.vals['hp'].set(g('teleportAuto_hp') or '0')
        self.master_var.set(1 if any(v.get() not in ('', '0') for v in self.vals.values()) else 0)
        self._sync_master()
        self.baseline = self._compute(strict=False)
        self._dirty = False

    def _sync_master(self) -> None:
        for sb in self.spins:
            sb.state(['!disabled'] if self.master_var.get() else ['disabled'])

    def _master_changed(self) -> None:
        self._sync_master()
        self._changed()

    def _changed(self) -> None:
        self._dirty = True
        self.on_change()

    def is_dirty(self) -> bool:
        return self._dirty

    def _compute(self, strict: bool) -> dict[str, str]:
        def num(key: str, hi: int, label: str) -> int:
            raw = self.vals[key].get().strip() or '0'
            try:
                n = int(float(raw))
            except ValueError:
                if strict:
                    raise ValueError(f'ช่อง "{label}" ต้องเป็นตัวเลข')
                return 0
            if strict and not 0 <= n <= hi:
                raise ValueError(f'ช่อง "{label}" ต้องอยู่ระหว่าง 0–{hi}')
            return n
        on = bool(self.master_var.get())
        idle = num('idle', 600, 'ไม่มีการต่อสู้ภายใน') if on else 0
        aggr = num('aggr', 30, 'โดนมอนสเตอร์รุมตั้งแต่') if on else 0
        hp = num('hp', 99, 'HP ต่ำกว่า') if on else 0
        out = {'teleportAuto_useSkill': '1' if self.skill_var.get() else '0',
               'teleportAuto_idle': '1' if idle > 0 else '0',
               'teleportAuto_minAggressives': str(aggr), 'teleportAuto_hp': str(hp)}
        if idle > 0:
            out['timeouts:ai_teleport_idle'] = str(idle)
        return out

    def apply(self, kc: KConfig, tkc: KConfig | None) -> bool:
        """Write changed keys. Returns True if timeouts.txt changed. Raises ValueError (Thai)."""
        timeouts_changed = False
        for k, v in self._compute(strict=True).items():
            if v == self.baseline.get(k):
                continue
            if k.startswith('timeouts:'):
                if tkc is not None:
                    tkc.set(k.split(':', 1)[1], v)
                    timeouts_changed = True
            else:
                kc.set(k, v)
        self._dirty = False
        return timeouts_changed
