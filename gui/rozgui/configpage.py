"""ตั้งค่าบอท page: form, sub-tabs, config blocks and raw keys; load / save config.txt."""
from __future__ import annotations

import functools
import os
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Final

from .bot import Bot
from .errlog import log
from .ingame import BasicTab, MonsterTab
from .itemtab import BuffItemTab, PotionTab
from .kconfig import Block, KConfig
from .logintab import AutoLoginTab
from .monctl import load as monctl_load
from .restocktab import RestockTab
from .rozdb import RozDB
from .skilltab import SkillTab
from .statskilltab import StatSkillTab
from .tabs3c import MoveTab, PickupTab
from .theme import ACCENT, FIELD, Fonts, PANEL, PANEL2, TEXT, WARN
from .tradetab import TradeTab
from .widgets import Scrollable


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


class ConfigPageMixin:
    """Mixin of App: uses the state that App.__init__ sets up."""

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
                                  dict(bg=PANEL2, fg=TEXT, activebackground=ACCENT, font=Fonts.F_BASE))
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
        menu = tk.Menu(mb, tearoff=0, bg=PANEL2, fg=TEXT, activebackground=ACCENT, font=Fonts.F_BASE)
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
        txt = tk.Text(frm, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief='flat', font=Fonts.F_MONO, padx=8, pady=6, height=10)
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