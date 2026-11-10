"""ทีม tab for managing team follow roles, parties, and lock maps across bots."""
from __future__ import annotations

import dataclasses
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any, Callable

from . import team as T
from .errlog import log
from .kconfig import KConfig


@dataclass
class TeamSource:
    bot: str
    config_path: str
    status: dict[str, Any] | None          # None = not running
    send: Callable[..., bool] | None       # send(*commands) to a running bot, None when not running


class TeamTab(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        provider: Callable[[], list[TeamSource]],
        on_saved: Callable[[list[str]], None],
    ) -> None:
        super().__init__(parent, style='Panel.TFrame', padding=(16, 10))
        self.provider = provider
        self.on_saved = on_saved

        self._sources: list[TeamSource] = []
        self._originals: dict[str, T.TeamMember] = {}
        self._edited: dict[str, T.TeamMember] = {}
        self._unreadable: dict[str, str] = {}
        self._selected_bot: str | None = None
        self._updating_editor = False

        # Header Title
        ttk.Label(
            self,
            text='ทีมบอท — ดูทุกตัวในหน้าเดียว ตั้งใครตามใคร ปาร์ตี้ และแผนที่ฟาร์ม',
            style='Big.TLabel',
        ).pack(anchor='w')

        # Warnings / Errors label
        self.warnings_lbl = ttk.Label(
            self,
            text='',
            style='PanelMuted.TLabel',
            wraplength=900,
            justify='left',
        )
        self.warnings_lbl.pack(anchor='w', pady=(2, 6))

        # Table (Treeview)
        table_frame = ttk.Frame(self, style='Panel.TFrame')
        table_frame.pack(fill='both', expand=True, pady=(0, 6))

        cols = ('char', 'lv', 'map', 'hp', 'role', 'lock', 'party', 'pattack', 'ploot', 'pauto')
        self.tv = ttk.Treeview(
            table_frame,
            columns=cols,
            show='tree headings',
            selectmode='browse',
            height=8,
        )
        self.tv.heading('#0', text='บอท', anchor='w')
        self.tv.column('#0', width=110, anchor='w')

        for c, text, wdt in (
            ('char', 'ตัวละคร', 110),
            ('lv', 'Lv', 45),
            ('map', 'อยู่ที่', 100),
            ('hp', 'HP%', 55),
            ('role', 'บทบาท', 130),
            ('lock', 'แผนที่ฟาร์ม', 100),
            ('party', 'ปาร์ตี้', 100),
            ('pattack', 'ช่วยตีปาร์ตี้', 80),
            ('ploot', 'เก็บของปาร์ตี้', 80),
            ('pauto', 'คำเชิญปาร์ตี้', 95),
        ):
            self.tv.heading(c, text=text, anchor='w')
            self.tv.column(c, width=wdt, anchor='w')

        sb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        self.tv.bind('<<TreeviewSelect>>', self._on_tree_select)

        # Buttons bar (Refresh / Save)
        btn_bar = ttk.Frame(self, style='Panel.TFrame')
        btn_bar.pack(fill='x', pady=(0, 6))
        ttk.Button(btn_bar, text='🔄 โหลดใหม่', command=self._on_refresh_clicked).pack(side='left', padx=(0, 8))
        ttk.Button(btn_bar, text='💾 บันทึกทีม', command=self._on_save_clicked).pack(side='left')

        # Editor LabelFrame
        ed = ttk.LabelFrame(self, text=' แก้ไขการตั้งค่าบอท ', padding=(12, 8))
        ed.pack(fill='x', pady=(0, 4))
        self.ed = ed

        self.ed_title = ttk.Label(ed, text='เลือกบอทในตารางด้านบนเพื่อแก้ไข', style='Panel.TLabel')
        self.ed_title.grid(row=0, column=0, columnspan=6, sticky='w', pady=(0, 6))

        # Row 1: Role radios + Follow leader + Follow distance
        ttk.Label(ed, text='บทบาท:', style='Panel.TLabel').grid(row=1, column=0, sticky='w', padx=(0, 4), pady=2)
        role_frame = ttk.Frame(ed, style='Panel.TFrame')
        role_frame.grid(row=1, column=1, sticky='w', padx=(0, 16), pady=2)

        self.role_var = tk.StringVar(value=T.SOLO)
        self.solo_rb = ttk.Radiobutton(
            role_frame,
            text='ตีเอง',
            value=T.SOLO,
            variable=self.role_var,
            command=self._ui_role_changed,
        )
        self.solo_rb.pack(side='left', padx=(0, 6))
        self.follow_rb = ttk.Radiobutton(
            role_frame,
            text='ตาม',
            value=T.FOLLOW,
            variable=self.role_var,
            command=self._ui_role_changed,
        )
        self.follow_rb.pack(side='left')

        ttk.Label(ed, text='ตามใคร:', style='Panel.TLabel').grid(row=1, column=2, sticky='w', padx=(0, 4), pady=2)
        self.leader_var = tk.StringVar()
        self.leader_box = ttk.Combobox(ed, textvariable=self.leader_var, width=15)
        self.leader_box.grid(row=1, column=3, sticky='w', padx=(0, 16), pady=2)
        self.leader_box.bind('<<ComboboxSelected>>', lambda e: self._ui_leader_changed())
        self.leader_box.bind('<FocusOut>', lambda e: self._ui_leader_changed())

        ttk.Label(ed, text='ระยะตามไม่เกิน:', style='Panel.TLabel').grid(row=1, column=4, sticky='w', padx=(0, 4), pady=2)
        self.dist_var = tk.StringVar()
        self.dist_spin = ttk.Spinbox(ed, from_=1, to=20, textvariable=self.dist_var, width=5)
        self.dist_spin.grid(row=1, column=5, sticky='w', pady=2)
        self.dist_spin.bind('<FocusOut>', lambda e: self._ui_dist_changed())
        self.dist_spin.bind('<Return>', lambda e: self._ui_dist_changed())
        self.dist_spin.configure(command=self._ui_dist_changed)

        # Row 2: Farm map + Copy leader map button
        ttk.Label(ed, text='แผนที่ฟาร์ม:', style='Panel.TLabel').grid(row=2, column=0, sticky='w', padx=(0, 4), pady=4)
        self.lock_map_var = tk.StringVar()
        self.lock_map_entry = ttk.Entry(ed, textvariable=self.lock_map_var, width=16)
        self.lock_map_entry.grid(row=2, column=1, sticky='w', padx=(0, 8), pady=4)
        self.lock_map_entry.bind('<FocusOut>', lambda e: self._ui_lock_map_changed())
        self.lock_map_entry.bind('<Return>', lambda e: self._ui_lock_map_changed())

        self.copy_map_btn = ttk.Button(ed, text='ใช้แผนที่เดียวกับหัวหน้า', command=self._ui_copy_map_clicked)
        self.copy_map_btn.grid(row=2, column=2, columnspan=2, sticky='w', padx=(0, 16), pady=4)

        # Row 3: Party attack / party loot / party auto
        party_frame = ttk.Frame(ed, style='Panel.TFrame')
        party_frame.grid(row=3, column=0, columnspan=6, sticky='w', pady=(4, 0))

        self.party_attack_var = tk.IntVar(value=0)
        self.party_attack_cb = ttk.Checkbutton(
            party_frame,
            text='ช่วยตีมอนที่ตีปาร์ตี้',
            variable=self.party_attack_var,
            command=self._ui_party_changed,
        )
        self.party_attack_cb.pack(side='left', padx=(0, 12))

        self.party_loot_var = tk.IntVar(value=0)
        self.party_loot_cb = ttk.Checkbutton(
            party_frame,
            text='เก็บของของปาร์ตี้',
            variable=self.party_loot_var,
            command=self._ui_party_changed,
        )
        self.party_loot_cb.pack(side='left', padx=(0, 16))

        ttk.Label(party_frame, text='คำเชิญปาร์ตี้:', style='Panel.TLabel').pack(side='left', padx=(0, 4))
        self.party_auto_var = tk.StringVar()
        self.party_auto_box = ttk.Combobox(
            party_frame,
            textvariable=self.party_auto_var,
            values=list(T.PARTY_AUTO_TH.values()),
            state='readonly',
            width=10,
        )
        self.party_auto_box.pack(side='left')
        self.party_auto_box.bind('<<ComboboxSelected>>', lambda e: self._ui_party_auto_changed())

        self._clear_editor()

    # ---------------------------------------------------------------- Public API
    def refresh(self) -> None:
        """Reload team configuration from provider sources."""
        self._sources = self.provider()
        self._originals.clear()
        self._edited.clear()
        self._unreadable.clear()

        for src in self._sources:
            try:
                kc = KConfig(src.config_path)
                m = T.read_member(src.bot, kc, src.status)
                self._originals[src.bot] = m
                self._edited[src.bot] = dataclasses.replace(m)
            except OSError as e:
                log.warning('cannot read config for %s: %s', src.bot, e)
                self._unreadable[src.bot] = str(e)

        self._render()
        self._update_warnings()

        if self._selected_bot and self._selected_bot in self._edited:
            self._load_bot_into_editor(self._selected_bot)
        else:
            self._selected_bot = None
            self._clear_editor()

    def leader_choices(self, bot: str) -> list[str]:
        """Return non-empty character names of other team members."""
        return [
            m.char
            for b, m in self._edited.items()
            if b != bot and m.char
        ]

    def set_role(self, bot: str, role: str, target: str = '') -> None:
        """Set a bot's role (solo or follow) and target character."""
        if bot in self._unreadable:
            raise ValueError(f'{bot}: อ่าน config ไม่ได้ จึงแก้ค่าไม่ได้')
        if bot not in self._edited:
            raise ValueError(f'ไม่รู้จักบอท {bot}')
        if role not in (T.SOLO, T.FOLLOW):
            raise ValueError(f'บทบาทไม่ถูกต้อง: {role}')

        m = self._edited[bot]
        m.role = role
        if role == T.FOLLOW:
            m.follow_target = target
        # Solo keeps the old leader name, so switching back to "ตาม" restores it
        # (changes() never writes followTarget for a solo bot).

        self._update_row(bot)
        self._update_warnings()
        self._sync_editor_if_selected(bot)

    def set_follow_dist(self, bot: str, dist: int | None) -> None:
        """Set follow distance for a bot."""
        if bot in self._unreadable:
            raise ValueError(f'{bot}: อ่าน config ไม่ได้ จึงแก้ค่าไม่ได้')
        if bot not in self._edited:
            raise ValueError(f'ไม่รู้จักบอท {bot}')

        self._edited[bot].follow_dist = dist
        self._update_row(bot)
        self._update_warnings()
        self._sync_editor_if_selected(bot)

    def set_lock_map(self, bot: str, lock_map: str) -> None:
        """Set lock map for a bot."""
        if bot in self._unreadable:
            raise ValueError(f'{bot}: อ่าน config ไม่ได้ จึงแก้ค่าไม่ได้')
        if bot not in self._edited:
            raise ValueError(f'ไม่รู้จักบอท {bot}')

        self._edited[bot].lock_map = lock_map.strip()
        self._update_row(bot)
        self._update_warnings()
        self._sync_editor_if_selected(bot)

    def copy_leader_map(self, bot: str) -> None:
        """Set the bot's lock_map to its leader's lock_map."""
        if bot in self._unreadable:
            raise ValueError(f'{bot}: อ่าน config ไม่ได้ จึงแก้ค่าไม่ได้')
        if bot not in self._edited:
            raise ValueError(f'ไม่รู้จักบอท {bot}')

        m = self._edited[bot]
        if m.role != T.FOLLOW:
            raise ValueError(f'{bot} ไม่ได้ตั้งให้ตามใคร')
        if not m.follow_target:
            raise ValueError(f'{bot} ยังไม่ได้เลือกว่าจะตามใคร')

        leader: T.TeamMember | None = None
        for other_m in self._edited.values():
            if other_m.char == m.follow_target:
                leader = other_m
                break

        if leader is None:
            raise ValueError(f'หัวหน้า "{m.follow_target}" ไม่ใช่บอทในทีม')

        m.lock_map = leader.lock_map
        self._update_row(bot)
        self._update_warnings()
        self._sync_editor_if_selected(bot)

    def set_party(
        self,
        bot: str,
        attack: bool | None = None,
        loot: bool | None = None,
        auto: int | None = None,
    ) -> None:
        """Update party behavior flags and auto invite policy."""
        if bot in self._unreadable:
            raise ValueError(f'{bot}: อ่าน config ไม่ได้ จึงแก้ค่าไม่ได้')
        if bot not in self._edited:
            raise ValueError(f'ไม่รู้จักบอท {bot}')

        m = self._edited[bot]
        if attack is not None:
            m.party_attack = bool(attack)
        if loot is not None:
            m.party_loot = bool(loot)
        if auto is not None:
            if auto not in (0, 1, 2):
                raise ValueError(f'ค่าคำเชิญปาร์ตี้ต้องเป็น 0, 1 หรือ 2 (ได้ {auto})')
            m.party_auto = auto

        self._update_row(bot)
        self._update_warnings()
        self._sync_editor_if_selected(bot)

    def is_dirty(self) -> bool:
        """Check if any edited member differs from its original loaded state."""
        for src in self._sources:
            bot = src.bot
            if bot in self._unreadable or bot not in self._edited or bot not in self._originals:
                continue
            if T.changes(self._originals[bot], self._edited[bot]):
                return True
        return False

    def save(self) -> list[str]:
        """Validate and write all changed configurations to disk."""
        valid_members = [
            self._edited[src.bot]
            for src in self._sources
            if src.bot in self._edited and src.bot not in self._unreadable
        ]
        errors = T.validate(valid_members)
        if errors:
            raise ValueError('\n'.join(errors))

        saved: list[str] = []
        for src in self._sources:
            bot = src.bot
            if bot in self._unreadable or bot not in self._edited or bot not in self._originals:
                continue
            ch = T.changes(self._originals[bot], self._edited[bot])
            if not ch:
                continue
            kc = KConfig(src.config_path)
            T.apply(kc, ch)
            kc.save()
            if src.send is not None:
                if not src.send('reload config'):
                    log.warning('send("reload config") returned False for %s', bot)
            saved.append(bot)

        self.refresh()
        if saved:
            self.on_saved(saved)
        return saved

    # ---------------------------------------------------------------- Internal Rendering
    def _row_values(self, bot: str) -> tuple[str, ...]:
        if bot in self._unreadable or bot not in self._edited:
            return ('–', '–', '–', '–', 'อ่าน config ไม่ได้', '–', '–', '–', '–', '–')

        m = self._edited[bot]
        char_val = m.char if m.char else '–'
        lv_val = str(m.level) if m.level > 0 else '–'
        map_val = m.map if m.map else '–'
        hp_val = f'{m.hp_pct}%' if m.hp_pct is not None else '–'
        if m.role == T.FOLLOW:
            role_val = f'ตาม {m.follow_target}' if m.follow_target else 'ตาม'
        else:
            role_val = 'ตีเอง'
        lock_val = m.lock_map if m.lock_map else '–'
        party_val = m.party if m.party else '–'
        pattack_val = '✓' if m.party_attack else '–'
        ploot_val = '✓' if m.party_loot else '–'
        pauto_val = T.PARTY_AUTO_TH.get(m.party_auto, '–')

        return (
            char_val,
            lv_val,
            map_val,
            hp_val,
            role_val,
            lock_val,
            party_val,
            pattack_val,
            ploot_val,
            pauto_val,
        )

    def _render(self) -> None:
        for item in self.tv.get_children():
            self.tv.delete(item)
        for src in self._sources:
            bot = src.bot
            self.tv.insert('', 'end', iid=bot, text=bot, values=self._row_values(bot))

    def _update_row(self, bot: str) -> None:
        if self.tv.exists(bot):
            self.tv.item(bot, values=self._row_values(bot))

    def _update_warnings(self) -> None:
        lines: list[str] = []
        for bot, err in self._unreadable.items():
            lines.append(f'{bot}: อ่าน config ไม่ได้ ({err})')

        valid_members = [
            self._edited[src.bot]
            for src in self._sources
            if src.bot in self._edited and src.bot not in self._unreadable
        ]
        errs = T.validate(valid_members)
        lines.extend(errs)

        warns = T.warnings(valid_members)
        lines.extend(warns)

        self.warnings_lbl.configure(text='\n'.join(lines))

    # ---------------------------------------------------------------- Editor Helpers
    def _on_tree_select(self, event: tk.Event[Any] | None = None) -> None:
        sel = self.tv.selection()
        if not sel:
            self._selected_bot = None
            self._clear_editor()
            return
        bot = sel[0]
        self._selected_bot = bot
        self._load_bot_into_editor(bot)

    def _clear_editor(self) -> None:
        self._updating_editor = True
        try:
            self.ed_title.configure(text='เลือกบอทในตารางด้านบนเพื่อแก้ไข')
            self.role_var.set(T.SOLO)
            self.leader_var.set('')
            self.leader_box.configure(values=[])
            self.dist_var.set('')
            self.lock_map_var.set('')
            self.party_attack_var.set(0)
            self.party_loot_var.set(0)
            self.party_auto_var.set(T.PARTY_AUTO_TH.get(0, 'ไม่ตอบ'))
            self._set_editor_state('disabled')
        finally:
            self._updating_editor = False

    def _load_bot_into_editor(self, bot: str) -> None:
        self._updating_editor = True
        try:
            if bot in self._unreadable:
                self.ed_title.configure(text=f'แก้ไข — {bot} (อ่าน config ไม่ได้)')
                self._set_editor_state('disabled')
                return

            if bot not in self._edited:
                self._set_editor_state('disabled')
                return

            m = self._edited[bot]
            title_text = f'แก้ไข — {bot}' + (f' ({m.char})' if m.char else '')
            self.ed_title.configure(text=title_text)
            self._set_editor_state('normal')

            self.role_var.set(m.role)
            self.leader_box.configure(values=self.leader_choices(bot))
            self.leader_var.set(m.follow_target)
            self.dist_var.set(str(m.follow_dist) if m.follow_dist is not None else '')
            self.lock_map_var.set(m.lock_map)
            self.party_attack_var.set(1 if m.party_attack else 0)
            self.party_loot_var.set(1 if m.party_loot else 0)
            self.party_auto_var.set(T.PARTY_AUTO_TH.get(m.party_auto, 'ไม่ตอบ'))
        finally:
            self._updating_editor = False

    def _sync_editor_if_selected(self, bot: str) -> None:
        if self._selected_bot == bot:
            self._load_bot_into_editor(bot)

    def _set_editor_state(self, state: str) -> None:
        for w in (
            self.solo_rb,
            self.follow_rb,
            self.leader_box,
            self.dist_spin,
            self.lock_map_entry,
            self.copy_map_btn,
            self.party_attack_cb,
            self.party_loot_cb,
        ):
            try:
                w.configure(state=state)
            except tk.TclError as e:
                log.warning('failed to configure widget state %s: %s', state, e)

        try:
            self.party_auto_box.configure(state='readonly' if state == 'normal' else 'disabled')
        except tk.TclError as e:
            log.warning('failed to configure party_auto_box state: %s', e)

    # ---------------------------------------------------------------- UI Actions
    def _ui_role_changed(self) -> None:
        if self._updating_editor or not self._selected_bot:
            return
        role = self.role_var.get()
        target = self.leader_var.get().strip() if role == T.FOLLOW else ''
        try:
            self.set_role(self._selected_bot, role, target)
        except ValueError as e:
            messagebox.showerror('ข้อผิดพลาด', str(e))

    def _ui_leader_changed(self) -> None:
        if self._updating_editor or not self._selected_bot:
            return
        role = self.role_var.get()
        target = self.leader_var.get().strip()
        if role == T.FOLLOW:
            try:
                self.set_role(self._selected_bot, T.FOLLOW, target)
            except ValueError as e:
                messagebox.showerror('ข้อผิดพลาด', str(e))

    def _ui_dist_changed(self) -> None:
        if self._updating_editor or not self._selected_bot:
            return
        raw = self.dist_var.get().strip()
        dist: int | None = None
        if raw:
            try:
                dist = int(raw)
            except ValueError:
                messagebox.showerror('ค่าไม่ถูกต้อง', f'ระยะตามต้องเป็นตัวเลข 1–20 (ได้ {raw!r})')
                self._load_bot_into_editor(self._selected_bot)
                return
        try:
            self.set_follow_dist(self._selected_bot, dist)
        except ValueError as e:
            messagebox.showerror('ข้อผิดพลาด', str(e))

    def _ui_lock_map_changed(self) -> None:
        if self._updating_editor or not self._selected_bot:
            return
        try:
            self.set_lock_map(self._selected_bot, self.lock_map_var.get().strip())
        except ValueError as e:
            messagebox.showerror('ข้อผิดพลาด', str(e))

    def _ui_copy_map_clicked(self) -> None:
        if not self._selected_bot:
            return
        try:
            self.copy_leader_map(self._selected_bot)
            if self._selected_bot in self._edited:
                self.lock_map_var.set(self._edited[self._selected_bot].lock_map)
        except ValueError as e:
            messagebox.showerror('ข้อผิดพลาด', str(e))

    def _ui_party_changed(self) -> None:
        if self._updating_editor or not self._selected_bot:
            return
        try:
            self.set_party(
                self._selected_bot,
                attack=bool(self.party_attack_var.get()),
                loot=bool(self.party_loot_var.get()),
            )
        except ValueError as e:
            messagebox.showerror('ข้อผิดพลาด', str(e))

    def _ui_party_auto_changed(self) -> None:
        if self._updating_editor or not self._selected_bot:
            return
        th_val = self.party_auto_var.get()
        code = 0
        for k, v in T.PARTY_AUTO_TH.items():
            if v == th_val:
                code = k
                break
        try:
            self.set_party(self._selected_bot, auto=code)
        except ValueError as e:
            messagebox.showerror('ข้อผิดพลาด', str(e))

    def _on_refresh_clicked(self) -> None:
        if self.is_dirty():
            if not messagebox.askyesno('ยืนยันโหลดใหม่', 'มีการเปลี่ยนแปลงที่ยังไม่ได้บันทึก ต้องการโหลดใหม่หรือไม่?'):
                return
        self.refresh()

    def _on_save_clicked(self) -> None:
        try:
            saved = self.save()
            if saved:
                messagebox.showinfo('บันทึกสำเร็จ', f'บันทึกการตั้งค่าทีมสำเร็จ ({len(saved)} บอท): {", ".join(saved)}')
        except (ValueError, OSError) as e:
            messagebox.showerror('ไม่สามารถบันทึกได้', str(e))
