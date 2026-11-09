"""Potion and ไอเทมบัฟ tabs: the in-game "bag + auto slots" layout, but click-to-add.

Both edit `useSelf_item` blocks in the shared KConfig in place (skillcfg.edit),
so hand-written blocks keep their other lines. A block counts as
  potion -> has an hp/sp condition and no whenStatusInactive
  buff   -> has whenStatusInactive, or no hp/sp condition at all
Conditions verified in OpenKore Misc.pm checkSelfCondition / Utils.pm inRange.
"""
from __future__ import annotations

import functools
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Final

from . import skillcfg as S
from .errlog import log
from .icons import IconCache
from .kconfig import KConfig

KEY: Final[str] = 'useSelf_item'
OK_GREEN: Final[str] = '#3ecf8e'
MUTED: Final[str] = '#8e96aa'
WARN: Final[str] = '#f5b942'
# OpenKore item type 0 = healing item (what the in-game Potion bag shows).
HEALING_TYPE: Final[int] = 0
# ASPD potions share one buff: list all three so one is not drunk while another is active.
ASPD_STATUS: Final[str] = 'Concentration Potion, Awakening Potion, Berserk Potion'
ITEM_STATUS: Final[dict[int, str]] = {645: ASPD_STATUS, 22542: ASPD_STATUS, 656: ASPD_STATUS, 657: ASPD_STATUS}
BUFF_DEFAULT_SECS: Final[int] = 300


def _tokens(value: str) -> list[str]:
    return [t.strip() for t in value.split(',') if t.strip()]


class ItemSlotsTab(ttk.Frame):
    title = ''
    subtitle = ''
    bag_title = 'กระเป๋า — คลิกไอเทมเพื่อเพิ่มเป็นช่องอัตโนมัติ'
    slots_title = 'ช่องอัตโนมัติ'
    empty_bag = '(ไม่มีไอเทมประเภทนี้ในกระเป๋า)'

    def __init__(self, parent: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(parent, style='Panel.TFrame')
        self.on_change = on_change
        self.kc: KConfig | None = None
        self.inventory: list[dict[str, Any]] = []
        self.names: Callable[[str], str] = lambda t: t
        self.icons: IconCache | None = None      # set by the app once Tk exists
        canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg='#1d2027')
        vsb = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        self.body = ttk.Frame(canvas, style='Panel.TFrame', padding=(16, 10))
        win = canvas.create_window((0, 0), window=self.body, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        self.body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(win, width=e.width))

    # ------------------------------------------------------------- subclass API
    def is_mine(self, ref: S.SkillRef) -> bool:
        raise NotImplementedError

    def bag_filter(self, item: dict[str, Any]) -> bool:
        raise NotImplementedError

    def new_slot(self, item_id: int) -> dict[str, str]:
        raise NotImplementedError

    def slot_controls(self, row: ttk.Frame, ref: S.SkillRef) -> None:
        raise NotImplementedError

    # --------------------------------------------------------------------- fill
    def fill(self, kc: KConfig | None, char_json: dict[str, Any] | None, names: Callable[[str], str]) -> None:
        self.kc = kc
        items = (char_json or {}).get('items') or []
        self.inventory = [i for i in items if isinstance(i, dict) and not i.get('equipped')]
        self.names = names
        self.render()

    def _amount(self, value: str) -> int:
        total = 0
        toks = {t.lower() for t in _tokens(value)}
        for it in self.inventory:
            if str(it.get('id')) in toks or str(it.get('name', '')).lower() in toks \
                    or self.names(str(it.get('id'))).lower() in toks:
                try:
                    total += int(it.get('amount') or 0)
                except (TypeError, ValueError):
                    continue
        return total

    def _label(self, value: str) -> str:
        # 505 and 11518 can both be "Blue Potion" on this server: show each name once.
        return ', '.join(dict.fromkeys(self.names(t) for t in _tokens(value)))

    # ------------------------------------------------------------------- render
    def render(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        b = self.body
        ttk.Label(b, text=self.title, style='Big.TLabel').pack(anchor='w')
        ttk.Label(b, text=self.subtitle, style='PanelMuted.TLabel', wraplength=860, justify='left').pack(anchor='w')
        if self.kc is None:
            ttk.Label(b, text='อ่าน config ไม่ได้', style='PanelMuted.TLabel').pack(anchor='w')
            return
        bag = ttk.LabelFrame(b, text=f' 🎒 {self.bag_title} ', padding=(10, 6))
        bag.pack(fill='x', pady=(10, 4))
        cand = [i for i in self.inventory if self.bag_filter(i)]
        if not self.inventory:
            ttk.Label(bag, style='PanelMuted.TLabel', text=(
                'ยังไม่มีข้อมูลกระเป๋า — ต้องให้บอทอยู่ในเกม (ปลั๊กอิน gui_ipc v3) · เพิ่มด้วย ID ด้านล่างได้')).pack(anchor='w')
        elif not cand:
            ttk.Label(bag, text=self.empty_bag, style='PanelMuted.TLabel').pack(anchor='w')
        else:
            flow = ttk.Frame(bag, style='Panel.TFrame')
            flow.pack(fill='x')
            for n, it in enumerate(cand):
                iid = int(it.get('id') or 0)
                text = f'×{it.get("amount", 0)}  {self.names(str(iid))}'   # amount first: long names get cut
                btn = ttk.Button(flow, text=text, compound='left', command=functools.partial(self._add, iid))
                btn.grid(row=n // 4, column=n % 4, sticky='ew', padx=3, pady=3)
                if self.icons:
                    self.icons.attach(btn, iid)
            for c in range(4):
                flow.columnconfigure(c, weight=1, uniform='bag')
        add = ttk.Frame(bag, style='Panel.TFrame')
        add.pack(fill='x', pady=(6, 0))
        ttk.Label(add, text='หรือเพิ่มด้วย ID ไอเทม:', style='Panel.TLabel').pack(side='left')
        id_var = tk.StringVar()
        ttk.Entry(add, textvariable=id_var, width=10).pack(side='left', padx=6)
        ttk.Button(add, text='เพิ่ม', command=functools.partial(self._add_from_entry, id_var)).pack(side='left')

        slots = ttk.LabelFrame(b, text=f' ⚙️ {self.slots_title} ', padding=(10, 6))
        slots.pack(fill='x', pady=4)
        mine = [r for r in S.all_refs(self.kc, KEY) if self.is_mine(r)]
        if not mine:
            ttk.Label(slots, text='ยังไม่มีช่อง — คลิกไอเทมในกระเป๋าด้านบนเพื่อเพิ่ม', style='PanelMuted.TLabel').pack(anchor='w')
        grid = ttk.Frame(slots, style='Panel.TFrame')
        grid.pack(fill='x')
        grid.columnconfigure(2, weight=1)      # the name column takes the slack, so controls line up
        for r, ref in enumerate(mine):
            on = tk.IntVar(value=1 if ref.enabled else 0)
            ttk.Checkbutton(grid, variable=on, command=functools.partial(self._toggle, ref, on)).grid(
                row=r, column=0, sticky='w', pady=4)
            icon = ttk.Label(grid, style='Panel.TLabel')
            icon.grid(row=r, column=1, padx=(2, 0))
            first = next((t for t in _tokens(ref.value) if t.isdigit()), None)
            if self.icons and first:
                self.icons.attach(icon, int(first))
            amt = self._amount(ref.value)
            name = ttk.Frame(grid, style='Panel.TFrame')
            name.grid(row=r, column=2, sticky='w', padx=(6, 12))
            ttk.Label(name, text=self._label(ref.value), style='Panel.TLabel', wraplength=380, justify='left',
                      foreground=('' if ref.enabled else MUTED)).pack(anchor='w')
            ttk.Label(name, text=f'มีในกระเป๋า {amt} ชิ้น' if self.inventory else '', style='PanelMuted.TLabel',
                      foreground=(WARN if self.inventory and amt == 0 else '')).pack(anchor='w')
            ctl = ttk.Frame(grid, style='Panel.TFrame')
            ctl.grid(row=r, column=3, sticky='w')
            self.slot_controls(ctl, ref)
            ttk.Button(grid, text='เอาออก', command=functools.partial(self._remove, ref)).grid(
                row=r, column=4, sticky='e', padx=(8, 0))

    # ------------------------------------------------------------------ actions
    def _add(self, item_id: int) -> None:
        if item_id <= 0:
            return
        self._apply(lambda kc: S.create(kc, KEY, str(item_id), {**self.new_slot(item_id), 'disabled': '0'}))

    def _add_from_entry(self, var: tk.StringVar) -> None:
        raw = var.get().strip()
        if raw.isdigit():
            self._add(int(raw))

    def _toggle(self, ref: S.SkillRef, var: tk.IntVar) -> None:
        self._apply(lambda kc: S.edit(kc, ref, {'disabled': '0' if var.get() else '1'}))

    def _fresh(self, ref: S.SkillRef) -> S.SkillRef | None:
        if self.kc is None:
            return None
        return next((r for r in S.all_refs(self.kc, KEY) if r.value == ref.value and r.ordinal == ref.ordinal), None)

    def _remove(self, ref: S.SkillRef) -> None:
        self._apply(lambda kc: S.delete(kc, ref))

    def _apply(self, fn: Callable[[KConfig], None], rerender: bool = True) -> None:
        if self.kc is None:
            return
        try:
            fn(self.kc)
        except LookupError as e:        # the block moved: the file was changed elsewhere
            log.warning('item slot edit skipped: %s', e)
            rerender = True
        self.on_change()
        if rerender:
            self.render()

    def _spin(self, parent: tk.Misc, value: int, lo: int, hi: int, step: int,
              commit: Callable[[int], None], width: int = 5) -> None:
        var = tk.StringVar(value=str(value))
        sb = ttk.Spinbox(parent, textvariable=var, from_=lo, to=hi, increment=step, width=width)
        sb.pack(side='left', padx=(2, 12))
        last = [str(value)]

        def fire(*_: object) -> None:
            v = var.get().strip()
            if v == last[0]:
                return
            try:
                n = int(float(v))
            except ValueError:
                var.set(last[0])
                return
            if not lo <= n <= hi:
                var.set(last[0])
                return
            last[0] = v
            commit(n)
        sb.configure(command=fire)
        sb.bind('<FocusOut>', fire)
        sb.bind('<Return>', fire)


class PotionTab(ItemSlotsTab):
    title = 'ตั้งค่าไอเทมฟื้นฟู'
    subtitle = ('บอทจะดื่มเมื่อ HP หรือ SP ต่ำกว่าค่าที่ตั้งไว้ · 0 = ไม่ใช้เงื่อนไขนั้น · '
                'ถ้าตั้งทั้ง HP และ SP ในช่องเดียว จะดื่มเมื่อต่ำกว่าทั้งสองอย่างพร้อมกัน '
                '(อยากให้ดื่มแยกกัน ให้เพิ่มเป็น 2 ช่อง)')
    slots_title = 'ช่องยาอัตโนมัติ'

    def is_mine(self, ref: S.SkillRef) -> bool:
        return (ref.get('hp') is not None or ref.get('sp') is not None) and ref.get('whenStatusInactive') is None

    def bag_filter(self, item: dict[str, Any]) -> bool:
        try:
            return int(item.get('type', -1)) == HEALING_TYPE
        except (TypeError, ValueError):
            return False

    def new_slot(self, item_id: int) -> dict[str, str]:
        return {'hp': '< 50%', 'timeout': '0.5'}

    def slot_controls(self, row: ttk.Frame, ref: S.SkillRef) -> None:
        for key, label in (('hp', 'HP ต่ำกว่า %'), ('sp', 'SP ต่ำกว่า %')):
            raw = ref.get(key)
            n = S.pct(raw)
            ttk.Label(row, text=label, style='Panel.TLabel').pack(side='left')
            if raw is not None and n is None:       # e.g. '20..50%': show, don't overwrite
                ttk.Label(row, text=raw, style='PanelMuted.TLabel').pack(side='left', padx=(2, 12))
                continue
            self._spin(row, n or 0, 0, 99, 5, functools.partial(self._set_pct, ref, key))

    def _set_pct(self, ref: S.SkillRef, key: str, n: int) -> None:
        cur = self._fresh(ref)                  # current lines, not the copy from the last render
        if cur is None:
            self.render()
            return
        other = 'sp' if key == 'hp' else 'hp'
        changes: dict[str, str | None]
        rerender = False
        if n == 0 and cur.get(other) is None:
            # Removing the only condition would make OpenKore drink it nonstop, and the block would
            # no longer look like a potion. Keep the threshold and switch the slot off instead.
            changes = {'disabled': '1'}
            rerender = True                     # show it unchecked, with its threshold back
        else:
            changes = {key: f'< {n}%' if n > 0 else None}
        # Otherwise no re-render: rebuilding under a spin arrow would lose the click.
        self._apply(lambda kc: S.edit(kc, cur, changes), rerender=rerender)


class BuffItemTab(ItemSlotsTab):
    title = 'ตั้งค่าไอเทมบัฟ'
    subtitle = ('ไอเทมที่รู้ระยะเวลาบัฟ ระบบจะเช็กสถานะและใช้ใหม่ทันทีเมื่อบัฟหมด · '
                'ไอเทมอื่นตั้งวินาทีได้เอง')
    slots_title = 'ช่องไอเทมบัฟอัตโนมัติ'

    def is_mine(self, ref: S.SkillRef) -> bool:
        return ref.get('whenStatusInactive') is not None or (ref.get('hp') is None and ref.get('sp') is None)

    def bag_filter(self, item: dict[str, Any]) -> bool:
        try:
            return int(item.get('id') or 0) in ITEM_STATUS
        except (TypeError, ValueError):
            return False

    def new_slot(self, item_id: int) -> dict[str, str]:
        st = ITEM_STATUS.get(item_id)
        base = {'notInTown': '1'}
        return {'whenStatusInactive': st, 'timeout': '5', **base} if st else {'timeout': str(BUFF_DEFAULT_SECS), **base}

    def slot_controls(self, row: ttk.Frame, ref: S.SkillRef) -> None:
        if ref.get('whenStatusInactive'):
            ttk.Label(row, text='อัตโนมัติ: ใช้ใหม่ทันทีเมื่อบัฟหมด', style='Panel.TLabel',
                      foreground=OK_GREEN).pack(side='left', padx=(0, 12))
        else:
            ttk.Label(row, text='ใช้ทุก ๆ (วินาที)', style='Panel.TLabel').pack(side='left')
            secs = S.pct(ref.get('timeout')) or BUFF_DEFAULT_SECS
            self._spin(row, secs, 5, 3600, 30, functools.partial(self._set_attr, ref, 'timeout'), width=6)
        for key, label in (('onAction', 'เฉพาะตอนตีมอน'), ('inLockOnly', 'เฉพาะในแผนที่ฟาร์ม')):
            cur = ref.get(key)
            on = tk.IntVar(value=1 if cur not in (None, '', '0') else 0)
            ttk.Checkbutton(row, text=label, variable=on,
                            command=functools.partial(self._set_flag, ref, key, on)).pack(side='left', padx=(0, 8))

    def _set_attr(self, ref: S.SkillRef, key: str, n: int) -> None:
        self._apply(lambda kc: S.edit(kc, ref, {key: str(n)}), rerender=False)

    def _set_flag(self, ref: S.SkillRef, key: str, var: tk.IntVar) -> None:
        val = ('attack' if key == 'onAction' else '1') if var.get() else None
        self._apply(lambda kc: S.edit(kc, ref, {key: val}), rerender=False)
