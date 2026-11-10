"""สเตตัส / สกิล tab (Tkinter Frame for auto raising stats and skills)."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from . import autoraise as A
from .kconfig import KConfig


def _extract_handle(raw: str) -> str:
    """Extract handle from 'Name (HANDLE)' or bare 'HANDLE'."""
    m = re.search(r'\(([^)]+)\)', raw)
    return m.group(1).strip() if m else raw.strip()


def _format_current_stats(cs: A.CharStats | None) -> str:
    """Format character's current stats text for current_lbl."""
    if cs is None:
        return 'ยังไม่รู้ค่าสเตตัส — บอทต้องเข้าเกมก่อน (ปลั๊กอินเขียน char.json ทุก 5 วินาที)'

    stat_parts: list[str] = []
    for stat in A.STATS:
        name = stat.upper()
        base_val = cs.base.get(stat, 1)
        bonus_val = cs.bonus.get(stat, 0)
        if bonus_val > 0:
            b_str = f'(+{bonus_val})'
        elif bonus_val < 0:
            b_str = f'({bonus_val})'
        else:
            b_str = ''
        stat_parts.append(f'{name} {base_val}{b_str}')

    stats_str = '  '.join(stat_parts)
    return f'ตอนนี้ (Lv {cs.level}): {stats_str} · แต้มว่าง {cs.points_free} · แต้มสกิล {cs.points_skill}'


class StatSkillTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(parent, style='Panel.TFrame', padding=(16, 10))
        self.on_change = on_change

        self._stats: list[tuple[str, int]] = []
        self._skills: list[tuple[str, int]] = []
        self._errors: list[str] = []
        self._char_stats: A.CharStats | None = None
        self._char_json: dict[str, Any] | None = None
        self._tree_skills: dict[str, dict[str, Any]] = {}
        self._dirty = False

        ttk.Label(
            self,
            text='อัปสเตตัส / สกิล — กำหนดลำดับการอัปสเตตัสและสกิลอัตโนมัติ',
            style='Big.TLabel',
        ).pack(anchor='w')

        self.current_lbl = ttk.Label(self, text='', style='Panel.TLabel')
        self.current_lbl.pack(anchor='w', pady=(4, 2))

        self.error_lbl = ttk.Label(self, text='', style='PanelMuted.TLabel', wraplength=900, justify='left')
        self.error_lbl.pack(anchor='w', pady=(0, 4))

        panes = ttk.Frame(self, style='Panel.TFrame')
        panes.pack(fill='both', expand=True, pady=(4, 0))
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(0, weight=1)

        # ------------------------------------------------------------- Stats Frame
        stat_frame = ttk.LabelFrame(panes, text=' สเตตัส ', padding=(12, 8))
        stat_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 6))

        self.stats_on_var = tk.IntVar(value=0)
        self.base_only_var = tk.IntVar(value=0)

        stat_toggles = ttk.Frame(stat_frame, style='Panel.TFrame')
        stat_toggles.pack(fill='x', pady=(0, 6))
        ttk.Checkbutton(
            stat_toggles,
            text='อัปสเตตัสอัตโนมัติ',
            variable=self.stats_on_var,
            command=self._on_toggle,
        ).pack(anchor='w')
        ttk.Checkbutton(
            stat_toggles,
            text='นับเฉพาะค่าพื้นฐาน (ไม่นับโบนัสจากของ/บัฟ)',
            variable=self.base_only_var,
            command=self._on_toggle,
        ).pack(anchor='w', pady=(2, 0))

        stat_input = ttk.Frame(stat_frame, style='Panel.TFrame')
        stat_input.pack(fill='x', pady=(0, 6))
        ttk.Label(stat_input, text='สเตตัส', style='Panel.TLabel').pack(side='left', padx=(0, 4))
        self._stat_choice = ttk.Combobox(
            stat_input,
            values=[s.upper() for s in A.STATS],
            state='readonly',
            width=6,
        )
        self._stat_choice.set('STR')
        self._stat_choice.pack(side='left', padx=(0, 8))

        ttk.Label(stat_input, text='เป้าหมาย', style='Panel.TLabel').pack(side='left', padx=(0, 4))
        self._stat_val_var = tk.StringVar(value='10')
        self._stat_spin = ttk.Spinbox(
            stat_input,
            from_=1,
            to=99,
            textvariable=self._stat_val_var,
            width=5,
        )
        self._stat_spin.pack(side='left', padx=(0, 8))

        ttk.Button(stat_input, text='➕ เพิ่ม', command=self._on_add_stat_clicked).pack(side='left')

        self.stat_tv = ttk.Treeview(
            stat_frame,
            columns=('stat', 'target', 'cost', 'reach'),
            show='headings',
            height=8,
        )
        self.stat_tv.heading('stat', text='สเตตัส')
        self.stat_tv.heading('target', text='เป้าหมาย')
        self.stat_tv.heading('cost', text='ใช้แต้ม')
        self.stat_tv.heading('reach', text='ถึงได้ตอนนี้')
        self.stat_tv.column('stat', width=70, anchor='center')
        self.stat_tv.column('target', width=80, anchor='center')
        self.stat_tv.column('cost', width=80, anchor='center')
        self.stat_tv.column('reach', width=90, anchor='center')
        self.stat_tv.pack(fill='both', expand=True, pady=(0, 6))

        stat_btn_bar = ttk.Frame(stat_frame, style='Panel.TFrame')
        stat_btn_bar.pack(fill='x', pady=(0, 4))
        ttk.Button(stat_btn_bar, text='▲', width=3, command=self._on_stat_up).pack(side='left', padx=(0, 4))
        ttk.Button(stat_btn_bar, text='▼', width=3, command=self._on_stat_down).pack(side='left', padx=(0, 4))
        ttk.Button(stat_btn_bar, text='🗑 ลบ', command=self._on_stat_delete).pack(side='left')

        self.stat_summary_lbl = ttk.Label(stat_frame, text='', style='PanelMuted.TLabel', wraplength=400, justify='left')
        self.stat_summary_lbl.pack(anchor='w', pady=(2, 0))

        # ------------------------------------------------------------ Skills Frame
        skill_frame = ttk.LabelFrame(panes, text=' สกิล ', padding=(12, 8))
        skill_frame.grid(row=0, column=1, sticky='nsew', padx=(6, 0))

        self.skills_on_var = tk.IntVar(value=0)

        skill_toggles = ttk.Frame(skill_frame, style='Panel.TFrame')
        skill_toggles.pack(fill='x', pady=(0, 6))
        ttk.Checkbutton(
            skill_toggles,
            text='อัปสกิลอัตโนมัติ',
            variable=self.skills_on_var,
            command=self._on_toggle,
        ).pack(anchor='w')

        skill_input = ttk.Frame(skill_frame, style='Panel.TFrame')
        skill_input.pack(fill='x', pady=(0, 6))
        ttk.Label(skill_input, text='สกิล', style='Panel.TLabel').pack(side='left', padx=(0, 4))
        self.skill_box = ttk.Combobox(skill_input, width=22)
        self.skill_box.pack(side='left', fill='x', expand=True, padx=(0, 8))

        ttk.Label(skill_input, text='เลเวล', style='Panel.TLabel').pack(side='left', padx=(0, 4))
        self._skill_lvl_var = tk.StringVar(value='10')
        self._skill_spin = ttk.Spinbox(
            skill_input,
            from_=1,
            to=10,
            textvariable=self._skill_lvl_var,
            width=4,
        )
        self._skill_spin.pack(side='left', padx=(0, 8))

        ttk.Button(skill_input, text='➕ เพิ่ม', command=self._on_add_skill_clicked).pack(side='left')

        self.skill_tv = ttk.Treeview(
            skill_frame,
            columns=('skill', 'target', 'now'),
            show='headings',
            height=8,
        )
        self.skill_tv.heading('skill', text='สกิล')
        self.skill_tv.heading('target', text='เลเวลเป้าหมาย')
        self.skill_tv.heading('now', text='ตอนนี้')
        self.skill_tv.column('skill', width=200, anchor='w')
        self.skill_tv.column('target', width=90, anchor='center')
        self.skill_tv.column('now', width=70, anchor='center')
        self.skill_tv.pack(fill='both', expand=True, pady=(0, 6))

        skill_btn_bar = ttk.Frame(skill_frame, style='Panel.TFrame')
        skill_btn_bar.pack(fill='x', pady=(0, 4))
        ttk.Button(skill_btn_bar, text='▲', width=3, command=self._on_skill_up).pack(side='left', padx=(0, 4))
        ttk.Button(skill_btn_bar, text='▼', width=3, command=self._on_skill_down).pack(side='left', padx=(0, 4))
        ttk.Button(skill_btn_bar, text='🗑 ลบ', command=self._on_skill_delete).pack(side='left')

        skill_note = ttk.Label(skill_frame, text='บอทจะอัปสกิลตามลำดับก่อนหลังในรายการนี้', style='PanelMuted.TLabel')
        skill_note.pack(anchor='w', pady=(2, 0))

        self._render()

    # -------------------------------------------------------------- Properties
    @property
    def settings(self) -> A.RaiseSettings:
        return A.RaiseSettings(
            stats_on=bool(self.stats_on_var.get()),
            stats=list(self._stats),
            base_only=bool(self.base_only_var.get()),
            skills_on=bool(self.skills_on_var.get()),
            skills=list(self._skills),
            errors=list(self._errors),
        )

    # ---------------------------------------------------------- Public methods
    def is_dirty(self) -> bool:
        return self._dirty

    def fill(self, kc: KConfig | None, char_json: dict[str, Any] | None) -> None:
        if kc is not None:
            s = A.load(kc)
        else:
            s = A.RaiseSettings()

        self._stats = list(s.stats)
        self._skills = list(s.skills)
        self._errors = list(s.errors)

        self.stats_on_var.set(1 if s.stats_on else 0)
        self.base_only_var.set(1 if s.base_only else 0)
        self.skills_on_var.set(1 if s.skills_on else 0)

        self._char_stats = A.char_stats(char_json)
        self._char_json = char_json

        self._tree_skills = {}
        tree_entries: list[tuple[str, str]] = []
        if char_json and isinstance(char_json.get('tree'), list):
            for entry in char_json['tree']:
                if isinstance(entry, dict) and entry.get('handle'):
                    h = entry['handle']
                    name = entry.get('name') or h
                    self._tree_skills[h] = entry
                    tree_entries.append((name, f'{name} ({h})'))

        if char_json and isinstance(char_json.get('skills'), list):
            for entry in char_json['skills']:
                if isinstance(entry, dict) and entry.get('handle'):
                    h = entry['handle']
                    if h not in self._tree_skills:
                        self._tree_skills[h] = entry

        tree_entries.sort(key=lambda x: x[0].lower())
        self.skill_box['values'] = [item[1] for item in tree_entries]
        if self.skill_box['values']:
            self.skill_box.current(0)
        else:
            self.skill_box.set('')

        self._render()
        self._dirty = False

    def add_stat(self, stat: str, value: int) -> None:
        stat_lower = stat.strip().lower()
        if stat_lower not in A.STATS:
            raise ValueError(f'สเตตัสไม่ถูกต้อง: {stat}')
        if not isinstance(value, int) or value < 1 or value > 99:
            raise ValueError(f'ค่าสเตตัสต้องอยู่ระหว่าง 1 ถึง 99 (ได้รับ {value})')

        self._stats.append((stat_lower, value))
        self._dirty = True
        self._render()
        self.on_change()

    def remove_stat(self, index: int) -> None:
        if 0 <= index < len(self._stats):
            del self._stats[index]
            self._dirty = True
            self._render()
            self.on_change()

    def move_stat(self, index: int, delta: int) -> None:
        new_idx = index + delta
        if 0 <= index < len(self._stats) and 0 <= new_idx < len(self._stats) and index != new_idx:
            self._stats[index], self._stats[new_idx] = self._stats[new_idx], self._stats[index]
            self._dirty = True
            self._render()
            self.on_change()

    def add_skill(self, handle: str, level: int) -> None:
        h = _extract_handle(handle)
        if not h:
            raise ValueError('ชื่อสกิลต้องไม่ว่างเปล่า')
        if not isinstance(level, int) or level < 1 or level > 10:
            raise ValueError(f'เลเวลสกิลต้องอยู่ระหว่าง 1 ถึง 10 (ได้รับ {level})')

        self._skills.append((h, level))
        self._dirty = True
        self._render()
        self.on_change()

    def remove_skill(self, index: int) -> None:
        if 0 <= index < len(self._skills):
            del self._skills[index]
            self._dirty = True
            self._render()
            self.on_change()

    def move_skill(self, index: int, delta: int) -> None:
        new_idx = index + delta
        if 0 <= index < len(self._skills) and 0 <= new_idx < len(self._skills) and index != new_idx:
            self._skills[index], self._skills[new_idx] = self._skills[new_idx], self._skills[index]
            self._dirty = True
            self._render()
            self.on_change()

    def apply_config(self, kc: KConfig) -> None:
        if not self._dirty:
            # Untouched: write nothing. A list in the file that does not parse loads as []
            # and would otherwise be overwritten by an empty one on every save.
            return
        s = self.settings
        A.apply(kc, s)
        self._dirty = False

    def _on_toggle(self) -> None:
        self._dirty = True
        self.on_change()

    # --------------------------------------------------------- Internal render
    def _render(self) -> None:
        self.current_lbl.configure(text=_format_current_stats(self._char_stats))

        if self._errors:
            self.error_lbl.configure(text='คำเตือน: ' + ' · '.join(self._errors))
        else:
            self.error_lbl.configure(text='')

        for r in self.stat_tv.get_children():
            self.stat_tv.delete(r)

        if self._char_stats is not None:
            plans, _ = A.plan_stats(self._char_stats.base, self._char_stats.points_free, self._stats)
            for p in plans:
                self.stat_tv.insert('', 'end', values=(p.stat.upper(), p.target, p.cost, p.reach))
            total_cost = sum(p.cost for p in plans)
            self.stat_summary_lbl.configure(
                text=f'แต้มที่ต้องใช้ทั้งหมด: {total_cost} · แต้มว่าง: {self._char_stats.points_free} · แต้มที่ใช้ไปแล้วคืนไม่ได้ — ตรวจลำดับก่อนเปิด'
            )
        else:
            for stat, target in self._stats:
                self.stat_tv.insert('', 'end', values=(stat.upper(), target, '', ''))
            self.stat_summary_lbl.configure(text='แต้มที่ใช้ไปแล้วคืนไม่ได้ — ตรวจลำดับก่อนเปิด')

        for r in self.skill_tv.get_children():
            self.skill_tv.delete(r)

        for handle, target_lv in self._skills:
            tree_info = self._tree_skills.get(handle)
            if tree_info:
                name = tree_info.get('name') or handle
                skill_label = f'{name} ({handle})'
                now_lv = tree_info.get('lv', '')
            else:
                skill_label = handle
                now_lv = ''
            self.skill_tv.insert('', 'end', values=(skill_label, target_lv, now_lv))

    # --------------------------------------------------------- Button handlers
    def _on_add_stat_clicked(self) -> None:
        stat = self._stat_choice.get().strip()
        raw_val = self._stat_spin.get().strip()
        try:
            val = int(raw_val)
        except ValueError:
            messagebox.showerror('ค่าไม่ถูกต้อง', f'ค่าสเตตัสต้องเป็นตัวเลข 1..99 (ได้รับ {raw_val!r})')
            return
        try:
            self.add_stat(stat, val)
        except ValueError as e:
            messagebox.showerror('ค่าไม่ถูกต้อง', str(e))

    def _on_add_skill_clicked(self) -> None:
        raw_skill = self.skill_box.get().strip()
        raw_lvl = self._skill_spin.get().strip()
        try:
            lvl = int(raw_lvl)
        except ValueError:
            messagebox.showerror('ค่าไม่ถูกต้อง', f'เลเวลสกิลต้องเป็นตัวเลข 1..10 (ได้รับ {raw_lvl!r})')
            return
        try:
            self.add_skill(raw_skill, lvl)
        except ValueError as e:
            messagebox.showerror('ค่าไม่ถูกต้อง', str(e))

    def _selected_stat_index(self) -> int | None:
        sel = self.stat_tv.selection()
        if not sel:
            return None
        try:
            return self.stat_tv.index(sel[0])
        except (tk.TclError, IndexError):
            return None

    def _on_stat_up(self) -> None:
        idx = self._selected_stat_index()
        if idx is not None and idx > 0:
            self.move_stat(idx, -1)
            children = self.stat_tv.get_children()
            if 0 <= idx - 1 < len(children):
                self.stat_tv.selection_set(children[idx - 1])

    def _on_stat_down(self) -> None:
        idx = self._selected_stat_index()
        if idx is not None and idx < len(self._stats) - 1:
            self.move_stat(idx, 1)
            children = self.stat_tv.get_children()
            if 0 <= idx + 1 < len(children):
                self.stat_tv.selection_set(children[idx + 1])

    def _on_stat_delete(self) -> None:
        idx = self._selected_stat_index()
        if idx is not None:
            self.remove_stat(idx)
            children = self.stat_tv.get_children()
            if children:
                new_sel = min(idx, len(children) - 1)
                self.stat_tv.selection_set(children[new_sel])

    def _selected_skill_index(self) -> int | None:
        sel = self.skill_tv.selection()
        if not sel:
            return None
        try:
            return self.skill_tv.index(sel[0])
        except (tk.TclError, IndexError):
            return None

    def _on_skill_up(self) -> None:
        idx = self._selected_skill_index()
        if idx is not None and idx > 0:
            self.move_skill(idx, -1)
            children = self.skill_tv.get_children()
            if 0 <= idx - 1 < len(children):
                self.skill_tv.selection_set(children[idx - 1])

    def _on_skill_down(self) -> None:
        idx = self._selected_skill_index()
        if idx is not None and idx < len(self._skills) - 1:
            self.move_skill(idx, 1)
            children = self.skill_tv.get_children()
            if 0 <= idx + 1 < len(children):
                self.skill_tv.selection_set(children[idx + 1])

    def _on_skill_delete(self) -> None:
        idx = self._selected_skill_index()
        if idx is not None:
            self.remove_skill(idx)
            children = self.skill_tv.get_children()
            if children:
                new_sel = min(idx, len(children) - 1)
                self.skill_tv.selection_set(children[new_sel])
