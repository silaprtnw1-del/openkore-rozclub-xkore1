"""ซื้อ / เบิกของ tab: buyAuto / getAuto blocks (restock.py), with shops and prices
from the rozclub.com NPC database (each shop lists what it sells and the price).

Edits go straight into the shared KConfig (like the skill and potion tabs) and are
written by the normal "บันทึก" button.
"""
from __future__ import annotations

import functools
import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Final

from . import restock as RS
from .errlog import log
from .icons import IconCache
from .kconfig import KConfig
from .rozdb import Npc, RozDB
from .tables import Tables

_ITEM_RE: Final[re.Pattern[str]] = re.compile(r'\((\d+)\)\s*$')


def shop_label(n: Npc, price: int) -> str:
    return f'{n.name} — {n.where} · {price:,}z'


class RestockTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(parent, style='Panel.TFrame', padding=(16, 10))
        self.on_change = on_change
        self.db = RozDB()
        self.tables: Tables | None = None
        self.icons: IconCache | None = None
        self.kc: KConfig | None = None
        self.save_map = ''
        self.bag: dict[int, tuple[str, int]] = {}
        self.rules: list[RS.Rule] = []
        self.editing: RS.Rule | None = None
        self._shops: list[tuple[Npc, int]] = []     # shops shown in the shop box for the current item

        ttk.Label(self, text='ซื้อ / เบิกของ — เติมของอัตโนมัติเมื่อของในกระเป๋าเหลือน้อย',
                  style='Big.TLabel').pack(anchor='w')
        self.town_note = ttk.Label(self, text='', style='PanelMuted.TLabel', wraplength=900, justify='left')
        self.town_note.pack(anchor='w', pady=(2, 6))

        cols = ('kind', 'where', 'price', 'min', 'max', 'zeny', 'bag', 'on')
        tv = ttk.Treeview(self, columns=cols, show='tree headings', selectmode='browse', height=7)
        tv.heading('#0', text='ไอเทม', anchor='w')
        tv.column('#0', width=250, anchor='w')
        for c, text, wdt in (('kind', 'วิธี', 100), ('where', 'จากที่ไหน', 220), ('price', 'ราคา', 70),
                             ('min', 'เมื่อเหลือ ≤', 85), ('max', 'เติมถึง', 70), ('zeny', 'เงื่อนไขเงิน', 110),
                             ('bag', 'ในกระเป๋า', 75), ('on', 'สถานะ', 60)):
            tv.heading(c, text=text, anchor='w')
            tv.column(c, width=wdt, anchor='w', stretch=(c == 'where'))
        tv.configure(style='Pickup.Treeview')
        tv.pack(fill='both', expand=True)
        tv.bind('<<TreeviewSelect>>', lambda e: self._on_select())
        self.tv = tv

        bar = ttk.Frame(self, style='Panel.TFrame')
        bar.pack(fill='x', pady=(6, 4))
        ttk.Button(bar, text='➕ ซื้อของจาก NPC', command=functools.partial(self._new, RS.BUY)).pack(side='left', padx=(0, 4))
        ttk.Button(bar, text='➕ เบิกจากคลัง', command=functools.partial(self._new, RS.GET)).pack(side='left', padx=(0, 4))
        ttk.Button(bar, text='⏯ เปิด / ปิด', command=self._toggle).pack(side='left', padx=(12, 4))
        ttk.Button(bar, text='🗑 ลบ', command=self._delete).pack(side='left')

        ed = ttk.LabelFrame(self, text=' แก้ไข ', padding=(12, 6))
        ed.pack(fill='x', pady=(4, 0))
        self.ed = ed
        self.ed_title = ttk.Label(ed, text='เลือกแถวด้านบน หรือกด ➕ เพื่อเพิ่ม', style='Panel.TLabel')
        self.ed_title.grid(row=0, column=0, columnspan=6, sticky='w', pady=(0, 6))

        ttk.Label(ed, text='ไอเทม', style='Panel.TLabel').grid(row=1, column=0, sticky='w')
        self.item_var = tk.StringVar()
        self.item_box = ttk.Combobox(ed, textvariable=self.item_var, width=40)
        self.item_box.grid(row=1, column=1, columnspan=3, sticky='w', padx=(6, 12))
        self.item_box.bind('<<ComboboxSelected>>', lambda e: self._item_changed())
        self.item_box.bind('<FocusOut>', lambda e: self._item_changed(keep_price=True))

        self.shop_lbl = ttk.Label(ed, text='ร้าน', style='Panel.TLabel')
        self.shop_lbl.grid(row=2, column=0, sticky='w', pady=(4, 0))
        self.shop_var = tk.StringVar()
        self.shop_box = ttk.Combobox(ed, textvariable=self.shop_var, width=52)
        self.shop_box.grid(row=2, column=1, columnspan=3, sticky='w', padx=(6, 12), pady=(4, 0))
        self.shop_box.bind('<<ComboboxSelected>>', lambda e: self._shop_changed())
        self.price_lbl = ttk.Label(ed, text='ราคา', style='Panel.TLabel')
        self.price_lbl.grid(row=2, column=4, sticky='w', pady=(4, 0))
        self.price_var = tk.StringVar()
        self.price_ent = ttk.Entry(ed, textvariable=self.price_var, width=9)
        self.price_ent.grid(row=2, column=5, sticky='w', pady=(4, 0))

        ttk.Label(ed, text='เมื่อเหลือ ≤', style='Panel.TLabel').grid(row=3, column=0, sticky='w', pady=(4, 0))
        self.min_var = tk.StringVar()
        ttk.Spinbox(ed, textvariable=self.min_var, from_=0, to=30000, width=7).grid(
            row=3, column=1, sticky='w', padx=(6, 12), pady=(4, 0))
        ttk.Label(ed, text='เติมถึง', style='Panel.TLabel').grid(row=3, column=2, sticky='w', pady=(4, 0))
        self.max_var = tk.StringVar()
        ttk.Spinbox(ed, textvariable=self.max_var, from_=1, to=30000, width=7).grid(
            row=3, column=3, sticky='w', padx=(6, 12), pady=(4, 0))
        self.zeny_lbl = ttk.Label(ed, text='ซื้อเมื่อมีเงินมากกว่า', style='Panel.TLabel')
        self.zeny_lbl.grid(row=3, column=4, sticky='w', pady=(4, 0))
        self.zeny_var = tk.StringVar()
        self.zeny_ent = ttk.Entry(ed, textvariable=self.zeny_var, width=9)
        self.zeny_ent.grid(row=3, column=5, sticky='w', pady=(4, 0))

        self.passive_var = tk.IntVar()
        self.passive_cb = ttk.Checkbutton(ed, text='เบิกเฉพาะตอนเปิดคลังอยู่แล้ว (ไม่เดินกลับเมืองเพื่อเบิกอย่างเดียว)',
                                          variable=self.passive_var)
        self.passive_cb.grid(row=4, column=0, columnspan=6, sticky='w', pady=(4, 0))
        self.enabled_var = tk.IntVar(value=1)
        ttk.Checkbutton(ed, text='เปิดใช้', variable=self.enabled_var).grid(row=5, column=0, sticky='w', pady=(6, 0))
        ttk.Button(ed, text='✔ ใช้ค่านี้', style='Accent.TButton', command=self._apply).grid(
            row=5, column=5, sticky='e', pady=(6, 0))
        self.ed_note = ttk.Label(ed, text='', style='PanelMuted.TLabel', wraplength=880, justify='left')
        self.ed_note.grid(row=6, column=0, columnspan=6, sticky='w', pady=(4, 0))
        self._set_editor_kind(RS.BUY)

    # ------------------------------------------------------------------ data
    def set_db(self, db: RozDB, tables: Tables) -> None:
        self.db, self.tables = db, tables
        self._item_choices()
        self.render()

    def fill(self, kc: KConfig | None, char_json: dict[str, Any] | None) -> None:
        self.kc = kc
        self.save_map = (kc.get('saveMap', '') if kc else '').strip()
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
        self.editing = None
        self._item_choices()
        self.reload()

    def reload(self) -> None:
        """Re-read the rules from the shared KConfig (other tabs may have changed blocks)."""
        self.rules = RS.load(self.kc) if self.kc else []
        self.render()

    def _town_shops(self) -> list[Npc]:
        return [n for n in self.db.npcs_on(self.save_map) if n.kind == 'shop' and n.shop] if self.save_map else []

    def _item_choices(self) -> None:
        ids: dict[int, None] = {}
        for n in self._town_shops():
            for iid, _price in n.shop:
                ids[iid] = None
        for iid in self.bag:
            ids[iid] = None
        self.item_box['values'] = [f'{self._label(i)} ({i})' for i in sorted(ids, key=lambda i: self._label(i).lower())]
        town = self.db.maps.get(self.save_map)
        where = f'{self.save_map} — {town.title}' if town else (self.save_map or '(ยังไม่ได้ตั้ง)')
        self.town_note.configure(text=(
            f'เมืองเซฟ: {where} · ร้านและราคาจาก rozclub.com · บอทจะกลับเมืองไปซื้อ/เบิกเมื่อของเหลือไม่เกิน '
            '"เมื่อเหลือ ≤" แล้วเติมจนถึง "เติมถึง" · ช่องรายการไอเทมแสดงของที่ร้านในเมืองเซฟขายและของในกระเป๋า'))

    # --------------------------------------------------------------- naming
    def _label(self, item_id: int) -> str:
        roz = self.db.items.get(item_id)
        if roz:
            return roz[0]
        bag = self.bag.get(item_id, ('', 0))[0]
        if bag and not bag.lower().startswith('unknown'):
            return bag
        return (self.tables.items.get(item_id) if self.tables else None) or str(item_id)

    def _id_of(self, value: str) -> int | None:
        """Block value or combobox text -> item id (None if unknown)."""
        v = value.strip()
        m = _ITEM_RE.search(v)
        if m:
            return int(m.group(1))
        if v.isdigit():
            return int(v)
        low = v.lower()
        if self.tables and low in self.tables.item_ids:
            return self.tables.item_ids[low]
        for iid, (name, _kind) in self.db.items.items():
            if name.lower() == low:
                return iid
        for iid, (name, _amount) in self.bag.items():
            if name.lower() == low:
                return iid
        return None

    def _bag_amount(self, r: RS.Rule) -> int | None:
        iid = r.item_id or self._id_of(r.value)
        if iid is not None and iid in self.bag:
            return self.bag[iid][1]
        low = r.value.strip().lower()
        hits = [a for n, a in self.bag.values() if n.lower() == low]
        return sum(hits) if hits else (0 if self.bag else None)

    def _shops_for(self, item_id: int) -> list[tuple[Npc, int]]:
        """Shops selling the item: the save town first, then the rest by price."""
        out = [(n, p) for n in self.db.npcs if n.kind == 'shop' for i, p in n.shop if i == item_id]
        out.sort(key=lambda t: (t[0].map != self.save_map, t[1], t[0].map))
        return out

    def _npc_label(self, where: str) -> str:
        for n in self.db.npcs:
            if n.where == where and n.kind in ('shop', 'kafra'):
                return f'{n.name} — {where}'
        return where

    # ---------------------------------------------------------------- render
    def render(self) -> None:
        tv = self.tv
        keep = tv.selection()
        tv.delete(*tv.get_children())
        for idx, r in enumerate(self.rules):
            iid = r.item_id or self._id_of(r.value)
            label = self._label(iid) if iid is not None else r.value
            if iid is not None and not r.value.strip().isdigit() and label.lower() != r.value.strip().lower():
                label = f'{label} ({r.value})'
            where = self._npc_label(r.npc) if r.key == RS.BUY else ('Kafra' + (' · เฉพาะตอนเปิดคลัง' if r.passive else ''))
            zeny = (f'> {r.zeny_min:,}z' if r.zeny_min is not None else r.zeny_raw) if r.key == RS.BUY else ''
            bag = self._bag_amount(r)
            row = str(idx)
            tv.insert('', 'end', iid=row, text=f'  {label}', values=(
                RS.KIND_TH[r.key], where or '–', f'{r.price:,}' if r.price else '', '' if r.min_amount is None else r.min_amount,
                '' if r.max_amount is None else r.max_amount, zeny, '' if bag is None else bag,
                'เปิด' if r.enabled else 'ปิด'))
            if self.icons and iid is not None:
                self.icons.request(iid, functools.partial(self._row_icon, row))
        if keep and tv.exists(keep[0]):
            tv.selection_set(keep)
        if not self.rules:
            self.ed_note.configure(text='ยังไม่มีรายการ — กด ➕ ซื้อของจาก NPC หรือ ➕ เบิกจากคลัง')

    def _row_icon(self, row: str, img: Any) -> None:
        if self.tv.exists(row):
            self.tv.item(row, image=img)

    # --------------------------------------------------------------- editor
    def _set_editor_kind(self, key: str) -> None:
        buy = key == RS.BUY
        for w in (self.shop_lbl, self.shop_box, self.price_lbl, self.price_ent, self.zeny_lbl, self.zeny_ent):
            if buy:
                w.grid()
            else:
                w.grid_remove()
        if buy:
            self.passive_cb.grid_remove()
        else:
            self.passive_cb.grid()

    def _load_editor(self, r: RS.Rule) -> None:
        self.editing = r
        self._set_editor_kind(r.key)
        iid = r.item_id or self._id_of(r.value)
        self.item_var.set(f'{self._label(iid)} ({iid})' if iid is not None else r.value)
        self.min_var.set('' if r.min_amount is None else str(r.min_amount))
        self.max_var.set('' if r.max_amount is None else str(r.max_amount))
        self.price_var.set(str(r.price) if r.price else '')
        self.zeny_var.set(str(r.zeny_min) if r.zeny_min is not None else '')
        self.passive_var.set(1 if r.passive else 0)
        self.enabled_var.set(1 if r.enabled else 0)
        self._fill_shops(iid)
        self.shop_var.set(next((shop_label(n, p) for n, p in self._shops if n.where == r.npc), r.npc))
        new = r.ref is None
        self.ed_title.configure(text=('เพิ่ม: ' if new else 'แก้ไข: ') + RS.KIND_TH[r.key])
        notes = []
        if r.zeny_raw and r.zeny_min is None:
            notes.append(f'เงื่อนไขเงินเดิม "zeny {r.zeny_raw}" ไม่ใช่แบบ "มากกว่า X" — คงไว้ตามเดิมถ้าช่องเงินว่าง')
        if r.extra:
            notes.append('บรรทัดอื่นในบล็อกคงไว้: ' + ' · '.join(f'{k} {v}' for k, v in r.extra))
        self.ed_note.configure(text='\n'.join(notes))

    def _fill_shops(self, item_id: int | None) -> None:
        self._shops = self._shops_for(item_id) if item_id is not None else []
        self.shop_box['values'] = [shop_label(n, p) for n, p in self._shops]

    def _item_changed(self, keep_price: bool = False) -> None:
        if self.editing is None or self.editing.key != RS.BUY:
            return
        iid = self._id_of(self.item_var.get())
        self._fill_shops(iid)
        if iid is not None and not self._shops:
            self.ed_note.configure(text='ไม่พบร้านที่ขายไอเทมนี้ในฐานข้อมูล — พิมพ์ตำแหน่งร้าน "แผนที่ x y" และราคาเอง')
            return
        current = self.shop_var.get()
        if self._shops and (not keep_price or not current):
            self.shop_var.set(shop_label(*self._shops[0]))
            self._shop_changed()

    def _shop_changed(self) -> None:
        text = self.shop_var.get()
        for n, p in self._shops:
            if shop_label(n, p) == text:
                self.price_var.set(str(p))
                if n.map != self.save_map:
                    self.ed_note.configure(text=f'⚠ ร้านนี้อยู่ที่ {n.map} ไม่ใช่เมืองเซฟ ({self.save_map}) — บอทจะเดินทางไปซื้อที่นั่น')
                else:
                    self.ed_note.configure(text='')
                return

    def _new(self, key: str) -> None:
        if self.kc is None:
            return
        self.tv.selection_remove(self.tv.selection())
        r = RS.Rule(key, '', min_amount=2 if key == RS.BUY else 1, max_amount=10, enabled=True)
        self._load_editor(r)
        self.item_var.set('')
        self.shop_var.set('')
        self.item_box.focus_set()

    def _on_select(self) -> None:
        sel = self.tv.selection()
        if sel and sel[0].isdigit() and int(sel[0]) < len(self.rules):
            self._load_editor(self.rules[int(sel[0])])

    def _read_int(self, var: tk.StringVar, name: str) -> int | None:
        raw = var.get().strip().replace(',', '')
        if raw == '':
            return None
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f'"{name}" ต้องเป็นตัวเลข') from None

    def _apply(self) -> None:
        r = self.editing
        if r is None or self.kc is None:
            return
        try:
            text = self.item_var.get().strip()
            iid = self._id_of(text)
            if iid is not None and iid >= 100:
                value = str(iid)                # OpenKore matches 3+ digit values by item ID
            elif text and not _ITEM_RE.search(text):
                value = text
            else:
                raise ValueError('ไม่รู้จักไอเทมนี้ — เลือกจากรายการ หรือพิมพ์ ID / ชื่อตาม OpenKore')
            if r.ref is not None and r.ref.value.strip().lower() == text.lower():
                value = r.ref.value                 # unchanged item written by name: keep the name
            elif r.ref is not None and iid is not None and self._id_of(r.ref.value) == iid:
                value = r.ref.value
            r.value = value
            r.min_amount = self._read_int(self.min_var, 'เมื่อเหลือ ≤')
            r.max_amount = self._read_int(self.max_var, 'เติมถึง')
            r.enabled = bool(self.enabled_var.get())
            if r.key == RS.BUY:
                shop = self.shop_var.get().strip()
                match = next((n for n, p in self._shops if shop_label(n, p) == shop), None)
                r.npc = match.where if match else shop.split(' — ')[-1].split(' · ')[0].strip()
                r.price = self._read_int(self.price_var, 'ราคา')
                r.zeny_min = self._read_int(self.zeny_var, 'ซื้อเมื่อมีเงินมากกว่า')
            else:
                r.passive = bool(self.passive_var.get())
            RS.apply(self.kc, r)
        except ValueError as e:
            messagebox.showerror('ค่าไม่ถูกต้อง', str(e))
            return
        except LookupError as e:
            log.warning('restock edit failed: %s', e)
            messagebox.showerror('แก้ไม่ได้', f'{e}\nกด "โหลดจากไฟล์ใหม่" แล้วลองอีกครั้ง')
            return
        self.on_change()
        self.reload()
        for idx, x in enumerate(self.rules):
            if r.ref is not None and x.ref is not None and (x.ref.value, x.ref.ordinal) == (r.ref.value, r.ref.ordinal) \
                    and x.key == r.key:
                self.tv.selection_set((str(idx),))
                self.tv.see(str(idx))
                break
        self.ed_note.configure(text='ใช้ค่าแล้ว — กด 💾 บันทึก & ใช้งานทันที ด้านบนเพื่อเขียนลงไฟล์')

    def _selected(self) -> RS.Rule | None:
        sel = self.tv.selection()
        return self.rules[int(sel[0])] if sel and sel[0].isdigit() and int(sel[0]) < len(self.rules) else None

    def _toggle(self) -> None:
        r = self._selected()
        if r is None or self.kc is None:
            return
        r.enabled = not r.enabled
        try:
            RS.apply(self.kc, r)
        except (ValueError, LookupError) as e:
            r.enabled = not r.enabled
            messagebox.showerror('เปิด/ปิดไม่ได้', str(e))
            return
        self.on_change()
        self.reload()

    def _delete(self) -> None:
        r = self._selected()
        if r is None or self.kc is None:
            return
        name = self.tv.item(self.tv.selection()[0], 'text').strip()
        if not messagebox.askyesno('ลบ', f'ลบรายการ {RS.KIND_TH[r.key]} "{name}"?\n(ยังไม่เขียนลงไฟล์จนกว่าจะกดบันทึก)'):
            return
        try:
            RS.remove(self.kc, r)
        except LookupError as e:
            messagebox.showerror('ลบไม่ได้', str(e))
            return
        self.editing = None
        self.on_change()
        self.reload()
