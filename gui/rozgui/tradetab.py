"""ขาย / ฝาก tab: where to store and sell (NPCs from the rozclub.com database) and
what to do with each item (items_control.txt GUI section, see itemctl.py).

config.txt keys owned here: storageAuto, storageAuto_npc, sellAuto, sellAuto_npc
(OpenKore src/AI/CoreLogic.pm processAutoStorage / processAutoSell). How heavy the
bag gets before going back (itemsMaxWeight_sellOrStore) stays in the พื้นฐาน tab.
"""
from __future__ import annotations

import functools
import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Final

from . import itemctl as I
from .errlog import log
from .icons import IconCache
from .kconfig import KConfig
from .rozdb import Npc, RozDB
from .tables import Tables
from .tabs3c import KIND_TH

NPC_RE: Final[re.Pattern[str]] = re.compile(r'^[\w@.-]+ \d+ \d+$')
OWNED_KEYS: Final[tuple[str, ...]] = ('storageAuto', 'storageAuto_npc', 'sellAuto', 'sellAuto_npc')
RISKY_KINDS: Final[frozenset[str]] = frozenset({'card', 'weapon', 'armor', 'headgear', 'shield', 'garment',
                                                'shoes', 'accessory', 'costume'})
SHOW_BAG: Final[str] = 'bag'
SHOW_DROPS: Final[str] = 'drops'
SHOW_SET: Final[str] = 'set'
SHOW_ALL: Final[str] = 'all'


def npc_label(n: Npc) -> str:
    return f'{n.name} — {n.where}'


def npc_value(text: str) -> str:
    """Combobox text ('Kafra Employee — payon 181 104' or 'payon 181 104') -> 'payon 181 104'."""
    return text.split(' — ')[-1].strip()


class TradeTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(parent, style='Panel.TFrame', padding=(16, 10))
        self.on_change = on_change
        self.db = RozDB()
        self.tables: Tables | None = None
        self.icons: IconCache | None = None
        self.ic = I.ItemCtl()
        self.file_vals: dict[str, tuple[int, int, int]] = {}
        self.control_dir = ''
        self.save_map = ''
        self.lock_map = ''
        self.bag: dict[int, tuple[str, int]] = {}      # id -> (OpenKore name, amount), not equipped
        self.baseline: dict[str, str] = {}
        self._load_error = ''
        self._items_dirty = False
        self._npc_dirty = False

        ttk.Label(self, text='ขาย / ฝากของ — ตั้งว่าไอเทมไหนเก็บไว้ ฝาก Kafra หรือขายให้ NPC',
                  style='Big.TLabel').pack(anchor='w')

        where = ttk.LabelFrame(self, text=' ที่ไหน ', padding=(12, 6))
        where.pack(fill='x', pady=(8, 4))
        where.columnconfigure(2, weight=1)
        self.store_on = tk.IntVar()
        self.sell_on = tk.IntVar()
        self.store_npc = tk.StringVar()
        self.sell_npc = tk.StringVar()
        for r, (text, on, var) in enumerate((('ฝากของอัตโนมัติ', self.store_on, self.store_npc),
                                              ('ขายของอัตโนมัติ', self.sell_on, self.sell_npc))):
            ttk.Checkbutton(where, text=text, variable=on, command=self._npc_changed).grid(
                row=r, column=0, sticky='w', pady=2)
            ttk.Label(where, text='Kafra' if r == 0 else 'NPC', style='Panel.TLabel').grid(
                row=r, column=1, sticky='w', padx=(16, 6))
            box = ttk.Combobox(where, textvariable=var, width=46)
            box.grid(row=r, column=2, sticky='w', pady=2)
            box.bind('<<ComboboxSelected>>', lambda e: self._npc_changed())
            box.bind('<KeyRelease>', lambda e: self._npc_changed())
            if r == 0:
                self.store_box = box
            else:
                self.sell_box = box
        self.where_note = ttk.Label(where, text='', style='PanelMuted.TLabel', wraplength=900, justify='left')
        self.where_note.grid(row=2, column=0, columnspan=3, sticky='w', pady=(4, 0))

        dflt = ttk.Frame(self, style='Panel.TFrame')
        dflt.pack(fill='x', pady=(6, 2))
        ttk.Label(dflt, text='ไอเทมที่ไม่ได้ตั้งไว้', style='Panel.TLabel').pack(side='left', padx=(0, 10))
        self.default_var = tk.StringVar(value=I.LEAVE)
        self.default_radios: dict[str, ttk.Radiobutton] = {}
        for a in I.ACTIONS:
            rb = ttk.Radiobutton(dflt, text=I.ACTION_TH[a], value=a, variable=self.default_var,
                                 command=self._default_changed)
            rb.pack(side='left', padx=(0, 12))
            self.default_radios[a] = rb

        bar = ttk.Frame(self, style='Panel.TFrame')
        bar.pack(fill='x', pady=(6, 4))
        ttk.Label(bar, text='แสดง', style='Panel.TLabel').pack(side='left', padx=(0, 6))
        self.show_var = tk.StringVar(value=SHOW_BAG)
        for val, text in ((SHOW_BAG, 'ในกระเป๋า'), (SHOW_DROPS, 'ดรอปในแผนที่ฟาร์ม'),
                          (SHOW_SET, 'ตั้งไว้ที่นี่'), (SHOW_ALL, 'ทั้งหมด')):
            ttk.Radiobutton(bar, text=text, value=val, variable=self.show_var,
                            command=self.render).pack(side='left', padx=(0, 10))
        ttk.Label(bar, text='ค้นหา', style='Panel.TLabel').pack(side='left', padx=(12, 4))
        self.q = tk.StringVar()
        ttk.Entry(bar, textvariable=self.q, width=22).pack(side='left')
        self.q.trace_add('write', lambda *a: self.render())

        tv = ttk.Treeview(self, columns=('amount', 'kind', 'gui', 'file'), show='tree headings',
                          selectmode='extended', height=10)
        tv.heading('#0', text='ไอเทม', anchor='w')
        tv.column('#0', width=300, anchor='w')
        for c, text, wdt in (('amount', 'ในกระเป๋า', 80), ('kind', 'ประเภท', 100),
                             ('gui', 'ตั้งที่นี่', 150), ('file', 'ตอนนี้ (ในไฟล์ / market)', 200)):
            tv.heading(c, text=text, anchor='w')
            tv.column(c, width=wdt, anchor='w', stretch=(c == 'file'))
        tv.configure(style='Pickup.Treeview')
        tv.pack(fill='both', expand=True)
        self.tv = tv

        act = ttk.Frame(self, style='Panel.TFrame')
        act.pack(fill='x', pady=(6, 0))
        ttk.Label(act, text='แถวที่เลือก →', style='Panel.TLabel').pack(side='left', padx=(0, 6))
        for a in I.ACTIONS:
            ttk.Button(act, text=I.ACTION_TH[a], command=functools.partial(self._apply_action, a)).pack(
                side='left', padx=(0, 4))
        ttk.Label(act, text='เหลือไว้ในตัว', style='Panel.TLabel').pack(side='left', padx=(14, 4))
        self.keep_var = tk.StringVar(value='0')
        ttk.Spinbox(act, textvariable=self.keep_var, from_=0, to=30000, increment=1, width=7).pack(side='left')
        ttk.Label(act, text='ชิ้น (ใช้กับฝาก/ขาย)', style='PanelMuted.TLabel').pack(side='left', padx=(4, 0))
        self.note = ttk.Label(self, text='', style='PanelMuted.TLabel', wraplength=900, justify='left')
        self.note.pack(anchor='w', pady=(4, 0))

    # ------------------------------------------------------------------ data
    def set_db(self, db: RozDB, tables: Tables) -> None:
        self.db, self.tables = db, tables
        self._fill_npc_choices()
        self.render()

    def fill(self, kc: KConfig | None, control_dir: str, char_json: dict[str, Any] | None) -> None:
        self.control_dir = control_dir
        self.save_map = (kc.get('saveMap', '') if kc else '').strip()
        self.lock_map = (kc.get('lockMap', '') if kc else '').strip()
        self.baseline = {k: (kc.get(k, '') if kc else '').strip() for k in OWNED_KEYS}
        self.store_on.set(0 if self.baseline['storageAuto'] in ('', '0') else 1)
        self.sell_on.set(0 if self.baseline['sellAuto'] in ('', '0') else 1)
        self._load_error = ''
        try:
            self.ic = I.load(control_dir)
            self.file_vals = I.file_values(control_dir)
        except OSError as e:          # read_lines only swallows a missing file
            log.warning('cannot read items_control.txt in %s: %s', control_dir, e)
            self.ic, self.file_vals = I.ItemCtl(), {}
            self._load_error = f'อ่าน items_control.txt ไม่ได้: {e}'
        self.default_var.set(self.ic.default)
        self.bag = {}
        for it in (char_json or {}).get('items') or []:
            if not isinstance(it, dict) or it.get('equipped'):
                continue
            try:
                iid, amount = int(it.get('id') or 0), int(it.get('amount') or 0)
            except (TypeError, ValueError):
                continue
            if iid > 0:
                prev = self.bag.get(iid)
                self.bag[iid] = (str(it.get('name') or ''), amount + (prev[1] if prev else 0))
        self._items_dirty = self._npc_dirty = False
        self._fill_npc_choices()
        self.render()

    def _fill_npc_choices(self) -> None:
        npcs = self.db.npcs_on(self.save_map) if self.save_map else []
        kafras = sorted((n for n in npcs if n.is_kafra and 'teleport' not in n.name.lower()),
                        key=lambda n: (0 if 'employee' in n.name.lower() else 1, n.name))
        shops = sorted((n for n in npcs if n.kind == 'shop'), key=lambda n: (-len(n.shop), n.name))
        self.store_box['values'] = [npc_label(n) for n in kafras]
        self.sell_box['values'] = [npc_label(n) for n in shops]
        for var, key, pool in ((self.store_npc, 'storageAuto_npc', kafras), (self.sell_npc, 'sellAuto_npc', shops)):
            if self._npc_dirty:
                continue                                 # keep what the user is typing
            raw = self.baseline.get(key, '')
            match = next((n for n in pool if n.where == raw), None)
            var.set(npc_label(match) if match else raw)
        town = self.db.maps.get(self.save_map)
        where = f'{self.save_map} — {town.title}' if town else (self.save_map or '(ยังไม่ได้ตั้ง)')
        extra = '' if npcs or not self.save_map else ' · ไม่มีข้อมูล NPC ของเมืองนี้ — พิมพ์ "แผนที่ x y" เองได้'
        self.where_note.configure(text=(
            f'เมืองเซฟ: {where}{extra} · รายชื่อ NPC จาก rozclub.com · กลับเมืองเมื่อน้ำหนักถึงค่าที่ตั้งในแท็บพื้นฐาน\n'
            'ขั้นตอนคุยกับ Kafra (storageAuto_npc_steps) ใช้ค่าเดิม — ถ้าเปลี่ยน Kafra ต่างเมืองแล้วฝากไม่ได้ ให้แก้ในแท็บขั้นสูง'))

    def _names(self, item_id: int) -> list[str]:
        """rozclub name, OpenKore table name, name in the bag (OpenKore matches names first)."""
        out: list[str] = []
        roz = self.db.items.get(item_id)
        for n in ((roz[0] if roz else None), (self.tables.items.get(item_id) if self.tables else None),
                  self.bag.get(item_id, ('', 0))[0]):
            if n and n not in out:
                out.append(n)
        return out

    def _kore_names(self, item_id: int) -> list[str]:
        """The name OpenKore itself uses for lookups: from the bag, else its items table."""
        bag = self.bag.get(item_id, ('', 0))[0]
        if bag:
            return [bag]
        t = self.tables.items.get(item_id) if self.tables else None
        return [t] if t else []

    def _label(self, item_id: int) -> str:
        names = [n for n in self._names(item_id) if not n.lower().startswith('unknown ')]
        return names[0] if names else str(item_id)

    def _kind(self, item_id: int) -> str:
        roz = self.db.items.get(item_id)
        return roz[1] if roz else ''

    def _ids(self) -> list[int]:
        show = self.show_var.get()
        if show == SHOW_BAG:
            return sorted(self.bag, key=lambda i: self._label(i).lower())
        if show == SHOW_DROPS:
            return [i for i, _rate, _mobs in self.db.map_drops(self.lock_map)]
        if show == SHOW_SET:
            return sorted(self.ic.rules, key=lambda i: self._label(i).lower())
        ids = set(self.bag) | set(self.ic.rules) | {i for i, _r, _m in self.db.map_drops(self.lock_map)}
        ids |= {int(k) for k in self.file_vals if k.isdigit()}
        return sorted(ids, key=lambda i: self._label(i).lower())

    # ---------------------------------------------------------------- render
    def render(self) -> None:
        tv = self.tv
        keep_sel = set(tv.selection())
        tv.delete(*tv.get_children())
        q = self.q.get().strip().lower()
        shown = 0
        for item_id in self._ids():
            label = self._label(item_id)
            if q and q not in label.lower() and q != str(item_id):
                continue
            rule = self.ic.rules.get(item_id)
            gui = ''
            if rule:
                gui = I.describe(I.columns(rule.action, rule.keep))
            now = I.describe(I.lookup(self.file_vals, item_id, self._kore_names(item_id)))
            iid = str(item_id)
            amount = self.bag.get(item_id, ('', 0))[1]
            tv.insert('', 'end', iid=iid, text=f'  {label}',
                      values=(amount or '', KIND_TH.get(self._kind(item_id), self._kind(item_id) or '-'),
                              gui or '–', now or '–'))
            if iid in keep_sel:
                tv.selection_add(iid)
            if self.icons:
                self.icons.request(item_id, functools.partial(self._row_icon, iid))
            shown += 1
        file_default = I.describe(self.file_vals.get('all'))
        self.default_radios[I.LEAVE].configure(text=f'ไม่ยุ่ง (ตามไฟล์: {file_default or "ไม่ฝาก ไม่ขาย"})')
        if getattr(self, '_load_error', ''):
            self.note.configure(text=self._load_error)
        elif self.show_var.get() == SHOW_BAG and not self.bag:
            self.note.configure(text='ยังไม่รู้ของในกระเป๋า — บอทต้องเข้าเกมก่อน (ปลั๊กอินเขียน char.json ทุก 5 วินาที)')
        elif self.show_var.get() == SHOW_DROPS and not shown:
            self.note.configure(text=f'ไม่มีข้อมูลดรอปของแผนที่ฟาร์ม "{self.lock_map}" จาก rozclub.com')
        else:
            self.note.configure(text=(
                'เลือกแถว (Ctrl/Shift เลือกหลายแถว) แล้วกดปุ่มด้านล่าง · "ตั้งที่นี่" ชนะค่าในไฟล์และค่าจาก market scanner · '
                '"ไม่ยุ่ง" = ใช้ค่าตามไฟล์'))

    def _row_icon(self, iid: str, img: Any) -> None:
        if self.tv.exists(iid):
            self.tv.item(iid, image=img)

    # --------------------------------------------------------------- editing
    def _apply_action(self, action: str) -> None:
        rows = [int(r) for r in self.tv.selection()]
        if not rows:
            self.note.configure(text='เลือกไอเทมในตารางก่อน แล้วค่อยกดปุ่ม')
            return
        try:
            keep = int(self.keep_var.get().strip() or '0')
            if keep < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror('ค่าไม่ถูกต้อง', '"เหลือไว้ในตัว" ต้องเป็นจำนวนเต็มตั้งแต่ 0 ขึ้นไป')
            return
        if action == I.SELL:
            risky = [self._label(i) for i in rows if self._kind(i) in RISKY_KINDS]
            if risky and not messagebox.askyesno(
                    'ขายของสำคัญ?', 'รายการนี้มีการ์ด/อุปกรณ์:\n' + '\n'.join(risky[:10])
                    + ('\n...' if len(risky) > 10 else '') + '\n\nจะให้บอทขายให้ NPC จริงไหม?'):
                return
        for i in rows:
            if action == I.LEAVE:
                self.ic.rules.pop(i, None)
            else:
                self.ic.rules[i] = I.ItemRule(i, self._label(i), action, keep if action in (I.STORE, I.SELL) else 0)
        self._items_dirty = True
        self.on_change()
        self.render()
        shared = self._shared_names(rows)
        if shared:
            self.note.configure(text='⚠ OpenKore เรียกไอเทมเหล่านี้ด้วยชื่อเดียวกัน และหาไอเทมจากชื่อก่อน ID '
                                     'จึงใช้ค่าเดียวกันทั้งหมด (ค่าที่บันทึกทีหลังชนะ): ' + ' · '.join(shared))

    def _shared_names(self, item_ids: list[int]) -> list[str]:
        """'"Concentration Potion" = 645, 22542' for OpenKore names used by more than one item."""
        if not self.tables:
            return []
        by_name: dict[str, list[int]] = {}
        for iid, name in self.tables.items.items():
            by_name.setdefault(name.lower(), []).append(iid)
        out: list[str] = []
        for i in item_ids:
            for n in self._names(i):
                ids = by_name.get(n.lower(), [])
                if len(ids) > 1:
                    text = f'"{n}" = ' + ', '.join(f'{self._label(x)} ({x})' for x in sorted(ids))
                    if text not in out:
                        out.append(text)
        return out

    def _default_changed(self) -> None:
        self.ic.default = self.default_var.get()
        self._items_dirty = True
        self.on_change()

    def _npc_changed(self) -> None:
        self._npc_dirty = True
        self.on_change()

    # ------------------------------------------------------------------ save
    def is_dirty(self) -> bool:
        return self._items_dirty or self._npc_dirty

    def apply_config(self, kc: KConfig) -> None:
        """Write the four config.txt keys this tab owns. Raises ValueError on a bad NPC."""
        if not self._npc_dirty:
            return
        wanted = {'storageAuto': '1' if self.store_on.get() else '0',
                  'sellAuto': '1' if self.sell_on.get() else '0'}
        for key, var, on in (('storageAuto_npc', self.store_npc, self.store_on.get()),
                             ('sellAuto_npc', self.sell_npc, self.sell_on.get())):
            v = npc_value(var.get())
            if v and not NPC_RE.match(v):
                raise ValueError(f'ตำแหน่ง NPC "{v}" ต้องเป็นรูปแบบ "แผนที่ x y" เช่น payon 181 104')
            if on and not v:
                raise ValueError('เปิดฝาก/ขายอัตโนมัติแล้ว ต้องเลือก NPC ด้วย')
            wanted[key] = v
        for key, v in wanted.items():
            old = self.baseline.get(key, '')
            same_flag = key in ('storageAuto', 'sellAuto') and (old not in ('', '0')) == (v == '1')
            if v != old and not same_flag:
                kc.set(key, v)
                self.baseline[key] = v

    def save(self) -> bool:
        """Write the items_control.txt section. True if written. Raises OSError."""
        if not self._items_dirty:
            self._npc_dirty = False
            return False
        I.save(self.control_dir, self.ic, {i: self._names(i) for i in self.ic.rules})
        self.file_vals = I.file_values(self.control_dir)
        self._items_dirty = self._npc_dirty = False
        self.render()
        return True
