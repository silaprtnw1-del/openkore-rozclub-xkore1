"""สกิล tab, laid out like the ROZCLUB in-game auto-hunt window.

Every edit is applied straight to the shared KConfig (see skillcfg), so the
advanced block editor and this tab always show the same thing.
"""
from __future__ import annotations

import functools
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Final

from . import skillcfg as S
from .errlog import log
from .kconfig import KConfig

MUTED: Final[str] = '#8e96aa'
WARN: Final[str] = '#f5b942'


def _lvl(v: str) -> str:
    return str(int(float(v)))


def _ge(v: str) -> str | None:
    return S.ge(int(float(v)))


def _le(v: str) -> str | None:
    return S.le(int(float(v)))


def _secs(v: str) -> str | None:
    return None if float(v) == 0 else f'{float(v):g}'


class SkillTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, on_change: Callable[[], None]) -> None:
        super().__init__(parent, style='Panel.TFrame')
        self.on_change = on_change
        self.kc: KConfig | None = None
        self.skills: list[S.LearnedSkill] = []
        self.statuses: dict[str, str] = {}
        self.party: list[str] = []
        canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg='#1d2027')
        vsb = ttk.Scrollbar(self, orient='vertical', command=canvas.yview)
        self.body = ttk.Frame(canvas, style='Panel.TFrame', padding=(16, 10))
        win = canvas.create_window((0, 0), window=self.body, anchor='nw')
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')
        self.body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(win, width=e.width))
        self._canvas = canvas

    # ------------------------------------------------------------------ fill
    def fill(self, kc: KConfig | None, char_json: dict[str, Any] | None, statuses: dict[str, str],
             party: list[str]) -> None:
        self.kc = kc
        self.skills = S.parse_learned(char_json)
        self.statuses = statuses
        self.party = party
        self.render()

    def _learned(self, handle: str) -> S.LearnedSkill | None:
        return next((s for s in self.skills if s.handle == handle), None)

    # ---------------------------------------------------------------- render
    def render(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        b = self.body
        ttk.Label(b, text='ตั้งค่าสกิล — สกิลโจมตี / สกิลบัฟ / สกิลฟื้นฟู', style='Big.TLabel').pack(anchor='w')
        if self.kc is None:
            ttk.Label(b, text='อ่าน config ไม่ได้', style='PanelMuted.TLabel').pack(anchor='w')
            return
        if not self.skills:
            ttk.Label(b, style='PanelMuted.TLabel', wraplength=860, justify='left', text=(
                'ยังไม่มีข้อมูลสกิลของตัวละคร — ต้องให้บอทอยู่ในเกมและโหลดปลั๊กอิน gui_ipc เวอร์ชันใหม่ '
                '(พิมพ์ plugin reload gui_ipc ในหน้าต่าง OpenKore) แสดงเฉพาะสกิลที่ตั้งไว้ใน config แล้ว')).pack(anchor='w', pady=4)
        self._attack_section(b)
        self._buff_section(b)
        self._heal_section(b)

    # ----------------------------------------------------------- attack skills
    def _attack_section(self, parent: ttk.Frame) -> None:
        assert self.kc is not None
        lf = ttk.LabelFrame(parent, text=' 🗡️ สกิลโจมตี ', padding=(10, 6))
        lf.pack(fill='x', pady=(10, 4))
        ttk.Label(lf, style='PanelMuted.TLabel', wraplength=860, justify='left', text=(
            'บอทใช้สกิลที่ติ๊กไว้ตามลำดับ 1 → … กับมอนตัวเดียว (ตัวละ 1 ครั้ง) ยังไม่ตายก็ใช้สกิลถัดไป มอนตัวใหม่เริ่มสกิล 1 · '
            '0 = ไม่จำกัด, HP 100 = ทุกระดับ')).grid(row=0, column=0, columnspan=9, sticky='w', pady=(0, 4))
        # order = file order of attackSkillSlot blocks, then learned enemy skills without a block
        refs = [S.SkillRef(bk.key, bk.value) for bk in self.kc.blocks if bk.key == S.ATTACK]
        handles: list[str] = []
        for r in refs:
            h = self._handle_of(r.value)
            if h not in handles:
                handles.append(h)
        for s in self.skills:
            if s.target == S.T_ENEMY and s.handle not in handles:
                handles.append(s.handle)
        if not handles:
            ttk.Label(lf, text='ยังไม่มีสกิลโจมตีที่เรียนไว้', style='PanelMuted.TLabel').grid(row=2, column=0, columnspan=9, sticky='w')
            return
        heads = ('ใช้', 'สกิล', 'Lv', 'ลำดับ', 'ใช้เมื่อ SP ≥ %', 'มอนรอบตัว ≥ (3 ช่อง)', 'ใช้เมื่อ HP ≤ %', 'Delay (วิ)', '')
        for c, h in enumerate(heads):
            ttk.Label(lf, text=h, style='PanelMuted.TLabel').grid(row=1, column=c, sticky='w', padx=4)
        refs_by_handle = {h: self._ref(S.ATTACK, h) for h in handles}
        enabled_order = [h for h in handles if (rr := refs_by_handle[h]) is not None and rr.enabled]
        for i, h in enumerate(handles, start=2):
            ref = refs_by_handle[h]
            sk = self._learned(h)
            on = tk.IntVar(value=1 if ref and ref.enabled else 0)
            ttk.Checkbutton(lf, variable=on, command=functools.partial(self._from_var, on, functools.partial(self._toggle_attack, h))).grid(row=i, column=0)
            name = sk.name if sk else h
            ttk.Label(lf, text=name + ('' if sk else '  (ยังไม่เรียน)'), style='Panel.TLabel',
                      foreground=('' if sk else MUTED)).grid(row=i, column=1, sticky='w', padx=4)
            maxlv = sk.lv if sk else 10
            self._spin(lf, i, 2, (ref.get('lvl') if ref else None) or str(maxlv), 1, maxlv, 1, ref is not None,
                       self._commit(S.ATTACK, h, 'lvl', _lvl))
            pos = enabled_order.index(h) + 1 if h in enabled_order else None
            od = ttk.Frame(lf, style='Panel.TFrame')
            od.grid(row=i, column=3, sticky='w', padx=4)
            ttk.Label(od, text=str(pos) if pos else '-', style='Panel.TLabel', width=2).pack(side='left')
            for txt, d in (('▲', -1), ('▼', 1)):
                btn = ttk.Button(od, text=txt, width=2, command=functools.partial(self._move, h, d))
                btn.pack(side='left', padx=1)
                if pos is None:
                    btn.state(['disabled'])
            self._spin(lf, i, 4, str(S.pct(ref.get('sp')) or 0) if ref else '0', 0, 100, 5, ref is not None,
                       self._commit(S.ATTACK, h, 'sp', _ge))
            mc = ref.get('monstersCount') if ref else None
            self._spin(lf, i, 5, str(S.pct(mc) or 0), 0, 20, 1, ref is not None,
                       self._commit_monsters(h))
            hp = S.pct(ref.get('hp')) if ref else None
            self._spin(lf, i, 6, str(hp if hp is not None else 100), 1, 100, 5, ref is not None,
                       self._commit(S.ATTACK, h, 'hp', _le))
            self._spin(lf, i, 7, (ref.get('timeout') if ref else None) or '0', 0, 60, 0.5, ref is not None,
                       self._commit(S.ATTACK, h, 'timeout', _secs))

    def _handle_of(self, value: str) -> str:
        v = value.strip()
        for s in self.skills:
            if v.lower() in (s.handle.lower(), s.name.lower()):
                return s.handle
        return v

    def _ref(self, key: str, handle: str) -> S.SkillRef | None:
        assert self.kc is not None
        refs = S.find_refs(self.kc, key, handle, self._learned(handle))
        return refs[0] if refs else None

    def _toggle_attack(self, handle: str, on: bool) -> None:
        sk = self._learned(handle)
        self._apply(lambda kc: S.set_enabled(kc, self._ref(S.ATTACK, handle), S.ATTACK, handle, on,
                                             {'lvl': str(sk.lv if sk else 1), 'maxUses': '1'}), rerender=True)

    def _move(self, handle: str, delta: int) -> None:
        assert self.kc is not None
        order = [self._handle_of(bk.value) for bk in self.kc.blocks if bk.key == S.ATTACK]
        if handle not in order:
            return
        i = order.index(handle)
        j = max(0, min(len(order) - 1, i + delta))
        if i == j:
            return
        order[i], order[j] = order[j], order[i]
        values = []
        for h in order:
            ref = self._ref(S.ATTACK, h)
            values.append(ref.value if ref else h)
        self._apply(lambda kc: S.reorder(kc, S.ATTACK, values), rerender=True)

    def _edit_monsters(self, handle: str, n: int) -> None:
        self._edit(S.ATTACK, handle, {'monstersCount': f'>= {n}' if n > 0 else None,
                                      'monstersCountDist': S.NEAR_DIST if n > 0 else None})

    # ------------------------------------------------------------- buff skills
    def _buff_section(self, parent: ttk.Frame) -> None:
        assert self.kc is not None
        lf = ttk.LabelFrame(parent, text=' ✨ สกิลบัฟ (ร่ายซ้ำอัตโนมัติเมื่อหมดเวลา) ', padding=(10, 6))
        lf.pack(fill='x', pady=4)
        heads = ('ตัวเอง', 'สกิล', 'Lv', 'ใช้เมื่อ SP ≥ %', 'ปาร์ตี้', 'เช็กสถานะ')
        for c, h in enumerate(heads):
            ttk.Label(lf, text=h, style='PanelMuted.TLabel').grid(row=0, column=c, sticky='w', padx=4)
        handles = [s.handle for s in self.skills if s.target in (S.T_SELF, S.T_ACTORS)
                   and s.handle not in S.HEAL_SKILLS and s.handle not in S.NOT_BUFFS]
        for key in (S.SELF, S.PARTY):
            for bk in self.kc.blocks:
                h = self._handle_of(bk.value)
                if bk.key == key and h not in handles and h not in S.HEAL_SKILLS:
                    handles.append(h)
        if not handles:
            ttk.Label(lf, text='ยังไม่มีสกิลบัฟที่เรียนไว้', style='PanelMuted.TLabel').grid(row=1, column=0, columnspan=6, sticky='w')
            return
        for i, h in enumerate(handles, start=1):
            sk = self._learned(h)
            ref = self._ref(S.SELF, h)
            pref = self._ref(S.PARTY, h)
            on = tk.IntVar(value=1 if ref and ref.enabled else 0)
            ttk.Checkbutton(lf, variable=on, command=functools.partial(self._from_var, on, functools.partial(self._toggle_buff, S.SELF, h))).grid(row=i, column=0)
            ttk.Label(lf, text=(sk.name if sk else h) + ('' if sk else '  (ยังไม่เรียน)'), style='Panel.TLabel',
                      foreground=('' if sk else MUTED)).grid(row=i, column=1, sticky='w', padx=4)
            maxlv = sk.lv if sk else 10
            lv_src = ref or pref
            self._spin(lf, i, 2, (lv_src.get('lvl') if lv_src else None) or str(maxlv), 1, maxlv, 1, lv_src is not None,
                       self._commit_both(h, 'lvl', _lvl))
            self._spin(lf, i, 3, str(S.pct(ref.get('sp')) or 0) if ref else '0', 0, 100, 5, ref is not None,
                       self._commit(S.SELF, h, 'sp', _ge))
            pon = tk.IntVar(value=1 if pref and pref.enabled else 0)
            pc = ttk.Checkbutton(lf, variable=pon, command=functools.partial(self._from_var, pon, functools.partial(self._toggle_buff, S.PARTY, h)))
            pc.grid(row=i, column=4)
            if not self.party and pref is None:
                pc.state(['disabled'])
            st = S.status_for(h, self.statuses)
            note = self.statuses.get(st, st) if st else f'⚠ ไม่รู้จักสถานะ — ร่ายทุก {S.BUFF_FALLBACK_TIMEOUT} วิ'
            ttk.Label(lf, text=note, style='PanelMuted.TLabel', foreground=('' if st else WARN)).grid(row=i, column=5, sticky='w', padx=4)

    def _toggle_buff(self, key: str, handle: str, on: bool) -> None:
        sk = self._learned(handle)
        st = S.status_for(handle, self.statuses)
        defaults: dict[str, str] = {'lvl': str(sk.lv if sk else 1)}
        if key == S.SELF:
            defaults.update({'whenStatusInactive': st} if st else {'timeout': S.BUFF_FALLBACK_TIMEOUT})
            defaults['notWhileSitting'] = '1'
        else:
            defaults.update({'target_whenStatusInactive': st} if st else {'target_timeout': S.BUFF_FALLBACK_TIMEOUT})
            defaults['notWhileSitting'] = '1'
        self._apply(lambda kc: S.set_enabled(kc, self._ref(key, handle), key, handle, on, defaults), rerender=True)

    def _edit_both(self, handle: str, changes: dict[str, str | None]) -> None:
        for key in (S.SELF, S.PARTY):
            if self._ref(key, handle):
                self._edit(key, handle, changes)

    # ------------------------------------------------------------- heal skills
    def _heal_section(self, parent: ttk.Frame) -> None:
        assert self.kc is not None
        lf = ttk.LabelFrame(parent, text=' 💚 สกิลฮีล ', padding=(10, 6))
        lf.pack(fill='x', pady=4)
        handles = [s.handle for s in self.skills if s.handle in S.HEAL_SKILLS]
        for key in (S.SELF, S.PARTY):
            for bk in self.kc.blocks:
                h = self._handle_of(bk.value)
                if bk.key == key and h in S.HEAL_SKILLS and h not in handles:
                    handles.append(h)
        if not handles:
            ttk.Label(lf, text='ยังไม่มีสกิลฮีลที่เรียนไว้', style='PanelMuted.TLabel').grid(row=0, column=0, sticky='w')
            return
        heads = ('สกิล', 'Lv', 'ฮีลตัวเอง', 'เมื่อ HP ≤ %', 'ฮีลปาร์ตี้', 'เมื่อ HP เพื่อน ≤ %')
        for c, h in enumerate(heads):
            ttk.Label(lf, text=h, style='PanelMuted.TLabel').grid(row=0, column=c, sticky='w', padx=4)
        for i, h in enumerate(handles, start=1):
            sk = self._learned(h)
            ref = self._ref(S.SELF, h)
            pref = self._ref(S.PARTY, h)
            ttk.Label(lf, text=sk.name if sk else h, style='Panel.TLabel').grid(row=i, column=0, sticky='w', padx=4)
            maxlv = sk.lv if sk else 10
            lv_src = ref or pref
            self._spin(lf, i, 1, (lv_src.get('lvl') if lv_src else None) or str(maxlv), 1, maxlv, 1, lv_src is not None,
                       self._commit_both(h, 'lvl', _lvl))
            on = tk.IntVar(value=1 if ref and ref.enabled else 0)
            ttk.Checkbutton(lf, variable=on, command=functools.partial(self._from_var, on, functools.partial(self._toggle_heal, S.SELF, h))).grid(row=i, column=2)
            hp = S.pct(ref.get('hp')) if ref else None
            self._spin(lf, i, 3, str(hp if hp is not None else 50), 1, 99, 5, ref is not None,
                       self._commit(S.SELF, h, 'hp', _le))
            pon = tk.IntVar(value=1 if pref and pref.enabled else 0)
            pc = ttk.Checkbutton(lf, variable=pon, command=functools.partial(self._from_var, pon, functools.partial(self._toggle_heal, S.PARTY, h)))
            pc.grid(row=i, column=4)
            if not self.party and pref is None:
                pc.state(['disabled'])
            php = S.pct(pref.get('target_hp')) if pref else None
            self._spin(lf, i, 5, str(php if php is not None else 60), 1, 99, 5, pref is not None,
                       self._commit(S.PARTY, h, 'target_hp', _le))

    def _toggle_heal(self, key: str, handle: str, on: bool) -> None:
        sk = self._learned(handle)
        lv = str(sk.lv if sk else 1)
        defaults = ({'lvl': lv, 'hp': '<= 50%', 'notWhileSitting': '0'} if key == S.SELF
                    else {'lvl': lv, 'target_hp': '<= 60%'})
        self._apply(lambda kc: S.set_enabled(kc, self._ref(key, handle), key, handle, on, defaults), rerender=True)

    # ----------------------------------------------------------------- helpers
    def _spin(self, parent: tk.Misc, row: int, col: int, value: str, lo: float, hi: float, step: float,
              enabled: bool, commit: Callable[[str], None]) -> None:
        var = tk.StringVar(value=value)
        sb = ttk.Spinbox(parent, textvariable=var, from_=lo, to=hi, increment=step, width=6)
        sb.grid(row=row, column=col, sticky='w', padx=4, pady=2)
        if not enabled:
            sb.state(['disabled'])
            return
        last = [value]

        def fire(*_: object) -> None:
            v = var.get().strip()
            if v == last[0]:
                return
            try:
                f = float(v)
            except ValueError:
                var.set(last[0])
                return
            if not lo <= f <= hi:
                var.set(last[0])
                return
            last[0] = v
            commit(v)
        sb.configure(command=fire)
        sb.bind('<FocusOut>', fire)
        sb.bind('<Return>', fire)

    @staticmethod
    def _from_var(var: tk.IntVar, fn: Callable[[bool], None]) -> None:
        fn(bool(var.get()))

    def _commit(self, key: str, handle: str, attr: str, conv: Callable[[str], str | None]) -> Callable[[str], None]:
        def commit(v: str) -> None:
            self._edit(key, handle, {attr: conv(v)})
        return commit

    def _commit_both(self, handle: str, attr: str, conv: Callable[[str], str | None]) -> Callable[[str], None]:
        def commit(v: str) -> None:
            self._edit_both(handle, {attr: conv(v)})
        return commit

    def _commit_monsters(self, handle: str) -> Callable[[str], None]:
        def commit(v: str) -> None:
            self._edit_monsters(handle, int(float(v)))
        return commit

    def _edit(self, key: str, handle: str, changes: dict[str, str | None]) -> None:
        ref = self._ref(key, handle)
        if ref is None:
            return
        self._apply(lambda kc: S.edit(kc, ref, changes), rerender=False)

    def _apply(self, fn: Callable[[KConfig], None], rerender: bool) -> None:
        if self.kc is None:
            return
        try:
            fn(self.kc)
        except LookupError as e:          # block vanished: the file was changed by something else
            log.warning('skill edit skipped: %s', e)
            rerender = True
        self.on_change()
        if rerender:
            self.render()
