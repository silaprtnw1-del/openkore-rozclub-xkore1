"""The "add bot" dialog (wraps `roz.ps1 new`)."""
from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Final

from .bot import run_roz
from .settings import ROOT_DIR
from .theme import BAD, BG, Fonts, MUTED, OK, PANEL, TEXT, WARN

if TYPE_CHECKING:
    from .app import App


_NAME_RE: Final[re.Pattern[str]] = re.compile(r'^[a-z0-9_][a-z0-9_-]*$')


def roz_error_text(out: str) -> str:
    """Thai hint for the usual roz.ps1 new/remove failures ('' if unknown)."""
    low = out.lower()
    if 'folder already exists' in low:
        return 'มีโฟลเดอร์โปรไฟล์ชื่อนี้อยู่แล้ว — เปลี่ยนชื่อบอท'
    if 'already exists' in low:
        return 'ชื่อบอทนี้มีอยู่แล้ว — เปลี่ยนชื่อ'
    if 'already used by another instance' in low or 'is already used' in low:
        return 'Port นี้ถูกใช้อยู่ — เลือกพอร์ตอื่น หรือให้เลือกอัตโนมัติ'
    if 'needs -follow' in low:
        return 'Support ต้องเลือกบอทที่จะเดินตาม'
    if 'is running' in low:
        return 'บอทตัวนี้ยังรันอยู่ — ปิดบอทก่อนแล้วค่อยลบ'
    if 'bad name' in low:
        return 'ชื่อบอทไม่ถูกต้อง — ใช้ a-z, 0-9, _ และ -'
    return ''


class AddBotDialog(tk.Toplevel):
    """➕ เพิ่มบอท: fills in `roz.ps1 new`, then reloads the sidebar list."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.app = app
        self.title('เพิ่มบอท')
        self.configure(bg=PANEL)
        self.transient(app)
        self.resizable(False, False)
        self._running = False
        # (label shown in a combobox, value passed to roz.ps1). For Support the value
        # must be the CHARACTER name (followTarget), not the instance name.
        self._chars: list[tuple[str, str]] = []
        for b in app.bots:
            st = b.status if b.running else None
            char = str(st.get('char') or '') if st else ''
            if not char:                      # offline: last known character from char.json
                cj = b.read_char()
                char = str(cj.get('char') or '') if cj else ''
            label = f'{b.name} — {char}' if char and char != b.name else b.name
            self._chars.append((label, char or b.name))
        self._bots: list[tuple[str, str]] = [(f'{b.name} — {b.role or "bot"}', b.name) for b in app.bots]

        body = ttk.Frame(self, style='Panel.TFrame', padding=16)
        body.pack(fill='both', expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text='ชื่อบอท', style='Panel.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 4))
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(body, textvariable=self.name_var, width=36)
        self.name_entry.grid(row=0, column=1, sticky='ew', pady=(0, 4))
        ttk.Label(body, text='ใช้ได้เฉพาะ a-z, 0-9, _ และ - · เริ่มด้วยตัวอักษรหรือ _',
                  style='PanelMuted.TLabel').grid(row=1, column=1, sticky='w')

        mode = ttk.LabelFrame(body, text=' แบบ ', padding=(10, 6))
        mode.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(12, 4))
        mode.columnconfigure(1, weight=1)
        self.mode_var = tk.StringVar(value='clone' if app.bots else 'support')
        self.rb_clone = ttk.Radiobutton(mode, text='คัดลอกการตั้งค่าจากบอทที่มีอยู่', value='clone',
                                        variable=self.mode_var, command=self._mode_changed)
        self.rb_clone.grid(row=0, column=0, sticky='w', pady=2)
        self.clone_var = tk.StringVar(value=self._bots[0][0] if self._bots else '')
        self.clone_box = ttk.Combobox(mode, textvariable=self.clone_var, state='readonly',
                                      values=[lab for lab, _ in self._bots], width=28)
        self.clone_box.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=2)
        self.rb_support = ttk.Radiobutton(mode, text='Support — เดินตาม ฮีล และบัฟบอทที่เลือก',
                                          value='support', variable=self.mode_var, command=self._mode_changed)
        self.rb_support.grid(row=1, column=0, sticky='w', pady=2)
        self.follow_var = tk.StringVar(value=self._chars[0][0] if self._chars else '')
        self.follow_box = ttk.Combobox(mode, textvariable=self.follow_var, state='readonly',
                                       values=[lab for lab, _ in self._chars], width=28)
        self.follow_box.grid(row=1, column=1, sticky='w', padx=(10, 0), pady=2)
        ttk.Label(mode, text='บอทสายตี (farmer) ต้องคัดลอกจากบอทที่มีอยู่ เพราะ roz.ps1 มีแม่แบบแค่สาย Support',
                  style='PanelMuted.TLabel', wraplength=520, justify='left').grid(
            row=2, column=0, columnspan=2, sticky='w', pady=(6, 0))
        if not app.bots:
            ttk.Label(mode, text='ยังไม่มีบอทให้คัดลอกหรือเดินตาม — ต้องมีบอทอย่างน้อย 1 ตัวก่อน',
                      style='PanelMuted.TLabel', foreground=WARN, wraplength=520,
                      justify='left').grid(row=3, column=0, columnspan=2, sticky='w', pady=(6, 0))

        portf = ttk.LabelFrame(body, text=' Port ', padding=(10, 6))
        portf.grid(row=3, column=0, columnspan=2, sticky='ew', pady=4)
        self.port_auto = tk.IntVar(value=1)
        self.rb_auto = ttk.Radiobutton(portf, text='เลือกให้อัตโนมัติ', value=1,
                                       variable=self.port_auto, command=self._port_changed)
        self.rb_auto.grid(row=0, column=0, sticky='w')
        self.rb_manual = ttk.Radiobutton(portf, text='กำหนดเอง', value=0,
                                         variable=self.port_auto, command=self._port_changed)
        self.rb_manual.grid(row=0, column=1, sticky='w', padx=(18, 0))
        self.port_var = tk.StringVar(value=str(self._next_port()))
        self.port_spin = ttk.Spinbox(portf, from_=1024, to=65535, increment=1,
                                     textvariable=self.port_var, width=8, command=self._update_preview)
        self.port_spin.grid(row=0, column=2, sticky='w', padx=(8, 0))
        self.port_spin.configure(state='disabled')

        self.preview = ttk.Label(body, text='', style='PanelMuted.TLabel', font=Fonts.F_MONO,
                                 wraplength=560, justify='left')
        self.preview.grid(row=4, column=0, columnspan=2, sticky='w', pady=(6, 2))

        outf = ttk.Frame(body, style='Panel.TFrame')
        outf.grid(row=5, column=0, columnspan=2, sticky='nsew', pady=(6, 2))
        outf.columnconfigure(0, weight=1)
        self.out = tk.Text(outf, height=8, width=64, bg=BG, fg=TEXT, relief='flat',
                           font=Fonts.F_MONO, padx=8, pady=6, state='disabled', wrap='word')
        vsb = ttk.Scrollbar(outf, orient='vertical', command=self.out.yview)
        self.out.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky='ns')
        self.out.grid(row=0, column=0, sticky='nsew')

        self.status_lbl = ttk.Label(body, text='', style='PanelMuted.TLabel', foreground=MUTED,
                                    wraplength=560, justify='left')
        self.status_lbl.grid(row=6, column=0, columnspan=2, sticky='w', pady=(4, 0))

        btns = ttk.Frame(body, style='Panel.TFrame')
        btns.grid(row=7, column=0, columnspan=2, sticky='e', pady=(10, 0))
        self.btn_cancel = ttk.Button(btns, text='ยกเลิก', command=self._cancel)
        self.btn_cancel.pack(side='right', padx=(6, 0))
        self.btn_ok = ttk.Button(btns, text='สร้างบอท', style='Accent.TButton', command=self._submit)
        self.btn_ok.pack(side='right')

        self.name_var.trace_add('write', lambda *a: self._update_preview())
        self.clone_var.trace_add('write', lambda *a: self._update_preview())
        self.follow_var.trace_add('write', lambda *a: self._update_preview())
        self.port_var.trace_add('write', lambda *a: self._update_preview())
        self.name_entry.bind('<Return>', lambda e: self._submit())
        self.bind('<Escape>', lambda e: self._cancel())
        self.wm_protocol('WM_DELETE_WINDOW', self._cancel)
        self._mode_changed()
        self._update_preview()
        self.update_idletasks()
        x = app.winfo_rootx() + max(0, (app.winfo_width() - self.winfo_width()) // 2)
        y = app.winfo_rooty() + max(0, (app.winfo_height() - self.winfo_height()) // 3)
        self.geometry(f'+{x}+{y}')
        self.grab_set()
        self.name_entry.focus_set()

    # ------------------------------------------------------------------ form
    def _next_port(self) -> int:
        used = {b.port for b in self.app.bots}
        port = max(used, default=1023) + 1
        while port in used:
            port += 1
        return port

    @staticmethod
    def _pick(choices: list[tuple[str, str]], label: str) -> str:
        return next((value for lab, value in choices if lab == label), '')

    def _update_preview(self) -> None:
        if not hasattr(self, 'preview'):
            return
        name = self.name_var.get().strip() or '<ชื่อ>'
        if self.mode_var.get() == 'clone':
            src = self._pick(self._bots, self.clone_var.get()) or '<บอทต้นแบบ>'
            args = f'new {name} -CloneFrom {src}'
        else:
            fol = self._pick(self._chars, self.follow_var.get()) or '<บอทที่จะเดินตาม>'
            args = f'new {name} -Follow {fol}'
        if not self.port_auto.get():
            args += f' -Port {self.port_var.get().strip() or "<port>"}'
        self.preview.configure(text=f'คำสั่ง:  roz.ps1 {args}')

    def _mode_changed(self) -> None:
        clone = self.mode_var.get() == 'clone'
        self.clone_box.configure(state='readonly' if clone else 'disabled')
        self.follow_box.configure(state='disabled' if clone else 'readonly')
        self._update_preview()

    def _port_changed(self) -> None:
        self.port_spin.configure(state='disabled' if self.port_auto.get() else 'normal')
        self._update_preview()

    def _args(self) -> list[str]:
        name = self.name_var.get().strip()
        if not name:
            raise ValueError('ใส่ชื่อบอท')
        if not _NAME_RE.match(name):
            raise ValueError('ชื่อบอทใช้ได้เฉพาะ a-z, 0-9, _ และ - (เริ่มด้วยตัวอักษรหรือ _)')
        if any(b.name.lower() == name.lower() for b in self.app.bots):
            raise ValueError(f'มีบอทชื่อ {name} อยู่แล้ว')
        args = ['new', name]
        if self.mode_var.get() == 'clone':
            src = self._pick(self._bots, self.clone_var.get())
            if not src:
                raise ValueError('เลือกบอทที่จะคัดลอกการตั้งค่า')
            args += ['-CloneFrom', src]
        else:
            fol = self._pick(self._chars, self.follow_var.get())
            if not fol:
                raise ValueError('เลือกบอทที่จะเดินตาม')
            args += ['-Follow', fol]
        if not self.port_auto.get():
            raw = self.port_var.get().strip()
            if not raw.isdigit():
                raise ValueError('Port ต้องเป็นตัวเลข 1024–65535')
            port = int(raw)
            if not 1024 <= port <= 65535:
                raise ValueError('Port ต้องอยู่ระหว่าง 1024–65535')
            if any(b.port == port for b in self.app.bots):
                raise ValueError(f'Port {port} ถูกใช้โดยบอทอื่นแล้ว')
            args += ['-Port', str(port)]
        return args

    # ------------------------------------------------------------------ run
    def _submit(self) -> None:
        if self._running:
            return
        try:
            args = self._args()
        except ValueError as e:
            self._status(str(e), BAD)
            return
        name = args[1]
        self._running = True
        self._inputs(False)
        self._status('กำลังสร้างบอท... (roz.ps1 new)', MUTED)
        self._append(f'> roz.ps1 {" ".join(args)}\n')

        def work() -> None:
            code, out = run_roz(ROOT_DIR, args)
            self.app._call_soon(lambda: self._done(name, code, out))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, name: str, code: int, out: str) -> None:
        self._running = False
        self._append((out or '(ไม่มีข้อความจาก roz.ps1)') + '\n')
        if code == 0:
            self._status(f'สร้างบอท {name} แล้ว — กด ▶ เริ่มบอท ที่แถบซ้ายเพื่อล็อกอิน', OK)
            self.grab_release()
            self.app.reload_registry(select=name)
            self.btn_cancel.pack_forget()
            self.btn_ok.configure(text='ปิด', command=self._close)
            self.btn_ok.state(['!disabled'])
        else:
            hint = roz_error_text(out)
            self._status(f'สร้างไม่สำเร็จ (exit {code})' + (f'\n{hint}' if hint else ''), BAD)
            self._inputs(True)

    def _inputs(self, enabled: bool) -> None:
        for w in (self.name_entry, self.rb_clone, self.rb_support, self.rb_auto, self.rb_manual):
            w.configure(state='normal' if enabled else 'disabled')
        if enabled:
            self._mode_changed()
            self._port_changed()
            self.btn_ok.state(['!disabled'])
            self.btn_cancel.state(['!disabled'])
        else:
            for w in (self.clone_box, self.follow_box, self.port_spin):
                w.configure(state='disabled')
            self.btn_ok.state(['disabled'])
            self.btn_cancel.state(['disabled'])

    def _status(self, text: str, color: str) -> None:
        self.status_lbl.configure(text=text, foreground=color)

    def _append(self, text: str) -> None:
        self.out.configure(state='normal')
        self.out.insert('end', text)
        self.out.see('end')
        self.out.configure(state='disabled')

    def _close(self) -> None:
        if self._running:
            return
        if self.app.add_dialog is self:
            self.app.add_dialog = None
        self.destroy()

    def _cancel(self) -> None:
        self._close()