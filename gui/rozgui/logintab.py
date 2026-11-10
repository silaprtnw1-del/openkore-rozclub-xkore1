"""ตั้งค่าล็อกอินอัตโนมัติต่อบอท (XKore 1) และปุ่มทดสอบแบบมีคนดู."""
from __future__ import annotations

import functools
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from . import relogin
from .bot import Bot
from .errlog import log

if TYPE_CHECKING:
    from .app import App


class AutoLoginTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, app: App) -> None:
        super().__init__(parent, style='Panel.TFrame', padding=(16, 10))
        self.app = app
        self.bot: Bot | None = None
        self._testing = False

        top = ttk.Frame(self, style='Panel.TFrame')
        top.pack(fill='x')
        ttk.Label(top, text='ล็อกอินอัตโนมัติเมื่อหลุด (XKore 1)', style='Big.TLabel').pack(side='left')
        self.name_lbl = ttk.Label(top, text='', style='PanelMuted.TLabel')
        self.name_lbl.pack(side='right')

        self.admin_lbl = ttk.Label(self, text='', style='PanelMuted.TLabel', wraplength=900, justify='left')
        self.admin_lbl.pack(anchor='w', pady=(4, 0))
        self.admin_btn = ttk.Button(self, text='🔑 เปิดโปรแกรมใหม่แบบ Administrator', command=self._relaunch_admin)

        body = ttk.Frame(self, style='Panel.TFrame')
        body.pack(fill='x', pady=(10, 4))
        body.columnconfigure(0, weight=1, uniform='a')
        body.columnconfigure(1, weight=1, uniform='a')

        acc = ttk.LabelFrame(body, text=' บัญชีเกม ', padding=(12, 8))
        acc.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        acc.columnconfigure(1, weight=1)
        self.enabled_var = tk.IntVar(value=0)
        ttk.Checkbutton(acc, text='เปิดใช้ล็อกอินอัตโนมัติ', variable=self.enabled_var).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        ttk.Label(acc, text='Username', style='Panel.TLabel').grid(row=1, column=0, sticky='w', pady=3)
        self.user_var = tk.StringVar()
        ttk.Entry(acc, textvariable=self.user_var, width=28).grid(row=1, column=1, sticky='ew', pady=3)
        ttk.Label(acc, text='Password', style='Panel.TLabel').grid(row=2, column=0, sticky='w', pady=3)
        self.pass_var = tk.StringVar()
        ttk.Entry(acc, textvariable=self.pass_var, show='•', width=28).grid(row=2, column=1, sticky='ew', pady=3)
        ttk.Label(acc, text='ตัวละครช่องที่', style='Panel.TLabel').grid(row=3, column=0, sticky='w', pady=3)
        self.slot_var = tk.StringVar(value='1')
        ttk.Spinbox(acc, from_=1, to=12, textvariable=self.slot_var, width=6).grid(row=3, column=1, sticky='w', pady=3)
        ttk.Label(acc, text='เซิร์ฟเวอร์ช่องที่', style='Panel.TLabel').grid(row=4, column=0, sticky='w', pady=3)
        self.server_var = tk.StringVar(value='1')
        ttk.Spinbox(acc, from_=1, to=20, textvariable=self.server_var, width=6).grid(
            row=4, column=1, sticky='w', pady=3)
        ttk.Label(acc, text='นับจากบนลงล่าง (1 = แรก) ทั้งหน้าเลือกเซิร์ฟเวอร์และตัวละคร',
                  style='PanelMuted.TLabel').grid(row=5, column=1, sticky='w')

        tim = ttk.LabelFrame(body, text=' เวลา / การลองใหม่ ', padding=(12, 8))
        tim.grid(row=0, column=1, sticky='nsew', padx=(6, 0))
        tim.columnconfigure(1, weight=1)
        self.login_delay = tk.StringVar(value='4')
        self.server_delay = tk.StringVar(value='6')
        self.char_delay = tk.StringVar(value='8')
        self.map_timeout = tk.StringVar(value='30')
        self.retries = tk.StringVar(value='3')
        self.offline_secs = tk.StringVar(value='20')
        self.cooldown = tk.StringVar(value='300')
        self.boot_delay = tk.StringVar(value='20')
        rows = (
            ('รอเกมโหลดหลังกดเริ่มบอท (วินาที)', self.boot_delay, 3, 180, 1),
            ('รอหน้า login (วินาที)', self.login_delay, 1, 60, 1),
            # Upper bounds: each step moves on as soon as OpenKore reports the next screen.
            ('รอหน้าเลือกบริการได้สูงสุด (วินาที)', self.server_delay, 1, 60, 1),
            ('รอหน้าเลือกตัวละครได้สูงสุด (วินาที)', self.char_delay, 1, 120, 1),
            ('รอเข้าเกมสูงสุด (วินาที)', self.map_timeout, 5, 180, 5),
            ('ลองใหม่สูงสุด (ครั้ง)', self.retries, 1, 10, 1),
            ('ถือว่าหลุดเมื่อออฟไลน์ (วินาที)', self.offline_secs, 5, 600, 5),
            ('พักก่อนลองใหม่ (วินาที)', self.cooldown, 30, 3600, 30),
        )
        for r, (label, var, lo, hi, step) in enumerate(rows):
            ttk.Label(tim, text=label, style='Panel.TLabel').grid(row=r, column=0, sticky='w', pady=3)
            ttk.Spinbox(tim, from_=lo, to=hi, increment=step, textvariable=var, width=8).grid(
                row=r, column=1, sticky='w', pady=3)

        ttk.Label(self, style='PanelMuted.TLabel', wraplength=920, justify='left', text=(
            '• กด "บันทึก" ของแท็บนี้ (ไม่ใช่ปุ่มบันทึกด้านบน) · รหัสผ่านเข้ารหัส DPAPI ที่ '
            '%APPDATA%\\ROZBotControl\\accounts.json (ไม่อยู่ใน git)\n'
            '• ต้องเปิดด้วย Start-GUI-Admin.cmd และไม่ล็อกจอ/ไม่สลีป; ถ้าเกมปิดสนิทระบบยังเปิดใหม่ไม่ได้\n'
            '• อัตโนมัติจะไล่ login → เลือกบริการ → เลือกตัวละคร → เข้าเกม; เริ่มเองหลังกด "เริ่มบอท" '
            '(รอเกมโหลดตามเวลาที่ตั้ง) และเมื่อเห็นกล่อง Disconnected/Error')).pack(anchor='w', pady=(6, 2))

        btns = ttk.Frame(self, style='Panel.TFrame')
        btns.pack(fill='x', pady=(4, 2))
        ttk.Button(btns, text='💾 บันทึก', style='Accent.TButton', command=self.save).pack(side='left', padx=2)
        self.btn_test = ttk.Button(btns, text='🧪 ทดสอบล็อกอินตอนนี้', command=self.test)
        self.btn_test.pack(side='left', padx=2)
        ttk.Button(btns, text='📂 เปิดโฟลเดอร์ภาพดีบัก', command=self._open_debug).pack(side='left', padx=2)
        self.status = ttk.Label(btns, text='', style='PanelMuted.TLabel')
        self.status.pack(side='left', padx=12)

        outf = ttk.Frame(self, style='Panel.TFrame')
        outf.pack(fill='both', expand=True, pady=(4, 0))
        outf.columnconfigure(0, weight=1)
        self.out = tk.Text(outf, height=5, bg='#15171c', fg='#e8eaf0', relief='flat',
                           font=('Consolas', 9), padx=8, pady=6, state='disabled', wrap='word')
        vsb = ttk.Scrollbar(outf, orient='vertical', command=self.out.yview)
        self.out.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky='ns')
        self.out.grid(row=0, column=0, sticky='nsew')

        self._update_admin()

    # ------------------------------------------------------------- settings
    def fill(self, bot: Bot) -> None:
        self.bot = bot
        s = relogin.load_settings(bot.name)
        self.name_lbl.configure(text=f'บอท: {bot.name}')
        self.enabled_var.set(1 if s.enabled else 0)
        self.user_var.set(s.username)
        self.pass_var.set(s.password)
        self.slot_var.set(str(s.char_slot))
        self.server_var.set(str(s.server_slot))
        self.login_delay.set(f'{s.login_delay:g}')
        self.server_delay.set(f'{s.server_delay:g}')
        self.char_delay.set(f'{s.char_delay:g}')
        self.map_timeout.set(f'{s.map_timeout:g}')
        self.retries.set(str(s.retries))
        self.offline_secs.set(f'{s.offline_seconds:g}')
        self.cooldown.set(f'{s.cooldown_seconds:g}')
        self.boot_delay.set(f'{s.boot_delay:g}')
        self._set_status('')
        self._update_admin()
        self._clear_out()

    def _collect(self) -> relogin.LoginSettings:
        def num(var: tk.StringVar, label: str, lo: float, hi: float) -> float:
            try:
                value = float(var.get().strip())
            except ValueError:
                raise ValueError(f'ช่อง "{label}" ต้องเป็นตัวเลข')
            if not lo <= value <= hi:
                raise ValueError(f'ช่อง "{label}" ต้องอยู่ระหว่าง {lo:g}–{hi:g}')
            return value

        s = relogin.LoginSettings(
            enabled=bool(self.enabled_var.get()),
            username=self.user_var.get().strip(),
            password=self.pass_var.get(),
            char_slot=int(num(self.slot_var, 'ตัวละครช่องที่', 1, 12)),
            server_slot=int(num(self.server_var, 'เซิร์ฟเวอร์ช่องที่', 1, 20)),
            login_delay=num(self.login_delay, 'รอหน้า login', 1, 60),
            server_delay=num(self.server_delay, 'รอหน้าเลือกเซิร์ฟเวอร์', 1, 60),
            char_delay=num(self.char_delay, 'รอหน้าเลือกตัวละคร', 1, 120),
            map_timeout=num(self.map_timeout, 'รอเข้าเกมสูงสุด', 5, 180),
            retries=int(num(self.retries, 'ลองใหม่สูงสุด', 1, 10)),
            offline_seconds=num(self.offline_secs, 'ถือว่าหลุดเมื่อออฟไลน์', 5, 600),
            cooldown_seconds=num(self.cooldown, 'พักก่อนลองใหม่', 30, 3600),
            boot_delay=num(self.boot_delay, 'รอเกมโหลดหลังกดเริ่มบอท', 3, 180),
        )
        if s.enabled and not s.has_credentials():
            raise ValueError('เปิดใช้ล็อกอินอัตโนมัติแล้ว ต้องใส่ Username และ Password')
        return s

    def save(self, quiet: bool = False) -> bool:
        if self.bot is None:
            return False
        try:
            s = self._collect()
        except ValueError as e:
            messagebox.showerror('ค่าไม่ถูกต้อง', str(e), parent=self)
            return False
        try:
            relogin.save_settings(self.bot.name, s)
        except OSError as e:
            messagebox.showerror('บันทึกไม่ได้', str(e), parent=self)
            return False
        self.app.reset_recovery(self.bot.name)
        if not quiet:
            self._set_status('บันทึกแล้ว', '#3ecf8e')
            self.app.toast(f'{self.bot.name}: บันทึกการล็อกอินอัตโนมัติแล้ว', 'ok')
        return True

    # ------------------------------------------------------------- testing
    def test(self) -> None:
        if self._testing or self.bot is None:
            return
        bot = self.bot
        if self.app._recovery_active is not None:
            messagebox.showinfo('กำลังทำงานอื่นอยู่',
                                f'กำลังกู้คืนบอท {self.app._recovery_active} อยู่ — รอให้เสร็จก่อนแล้วกดทดสอบอีกครั้ง',
                                parent=self)
            return
        if not relogin.is_admin():
            messagebox.showwarning(
                'ต้องเปิดแบบ Administrator',
                'Windows จะบล็อกการส่งคีย์บอร์ดเข้าเกมถ้าโปรแกรมไม่ได้รันเป็น Administrator\n\n'
                'ปิดโปรแกรมแล้วเปิดด้วย Start-GUI-Admin.cmd (กด Yes ที่หน้าต่าง UAC)',
                parent=self)
            return
        if not self.save(quiet=True):
            return
        s = relogin.load_settings(bot.name)
        if not s.has_credentials():
            messagebox.showinfo('ยังไม่มีบัญชี', 'ใส่ Username และ Password ก่อน', parent=self)
            return
        if bot.online:
            messagebox.showinfo(
                'บอทออนไลน์อยู่',
                'การทดสอบต้องทำตอนบอทอยู่หน้า login\n\n'
                'ให้ logout ตัวละครในเกมก่อน (หรือรอตอนหลุด) แล้วกดทดสอบอีกครั้ง\n'
                'ระบบจะไม่ส่งคีย์เข้าเกมขณะบอทออนไลน์เพื่อความปลอดภัย', parent=self)
            return
        pid = bot.cached_game_pid()
        if not (pid and relogin.has_window(pid)):
            pid = bot.discover_game_pid()
            if pid:
                bot.remember_game_pid(pid)
        if not pid or not relogin.has_window(pid):
            messagebox.showinfo(
                'ไม่พบหน้าต่างเกม',
                'หาเกมของบอทนี้ไม่พบ — เปิดเกมและล็อกอินด้วยมือก่อน แล้วค่อยทดสอบ\n'
                '(ถ้าเกมเพิ่งเปิดใหม่ ให้เริ่มบอทผ่าน GUI หรือรอสักครู่)', parent=self)
            return

        self._testing = True
        self.btn_test.state(['disabled'])
        self._set_status('กำลังทดสอบ...', '#f5b942')
        self._clear_out()
        self.app.begin_login_test(bot.name)
        self._log(f'เริ่มทดสอบกับบอท {bot.name} (game pid {pid})')

        def log_cb(msg: str) -> None:
            self.app._call_soon(functools.partial(self._log, msg))

        runner = relogin.LoginRunner(
            bot.name, pid, s, log_cb,
            lambda: int((bot.status or {}).get('state', 0)),
            get_chars=bot.account_chars)

        def work() -> None:
            try:
                ok = runner.run(lambda: bot.online, lambda: False)
            except Exception:
                log.exception('%s: login test crashed', bot.name)
                ok = False
            self.app._call_soon(lambda: self._done(bot.name, ok, runner.debug_dir))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, name: str, ok: bool, debug_dir: str) -> None:
        self._testing = False
        self.btn_test.state(['!disabled'])
        self.app.end_login_test(name)
        if ok:
            self._set_status('เข้าเกมแล้ว', '#3ecf8e')
            self._log('✅ ทดสอบสำเร็จ — เข้าเกมแล้ว')
            messagebox.showinfo('ทดสอบสำเร็จ', f'{name} ล็อกอินและเข้าเกมได้แล้ว', parent=self)
        else:
            self._set_status('ทดสอบไม่สำเร็จ', '#ff5d5d')
            self._log('❌ ทดสอบไม่สำเร็จ — ดูขั้นตอนด้านบนและภาพในโฟลเดอร์ดีบัก')
            messagebox.showwarning(
                'ทดสอบไม่สำเร็จ',
                'ดูบันทึกในแท็บนี้และภาพหน้าจอใน:\n'
                f'{debug_dir}\n\n'
                'ตรวจ Username/Password, ช่องตัวละคร และดีเลย์ (หน้า login/เลือกตัวละครอาจช้ากว่าที่ตั้ง)',
                parent=self)

    # ------------------------------------------------------------------ misc
    def _log(self, msg: str) -> None:
        self.out.configure(state='normal')
        self.out.insert('end', f'{msg}\n')
        self.out.see('end')
        self.out.configure(state='disabled')

    def _clear_out(self) -> None:
        self.out.configure(state='normal')
        self.out.delete('1.0', 'end')
        self.out.configure(state='disabled')

    def _set_status(self, text: str, color: str = '#8e96aa') -> None:
        self.status.configure(text=text, foreground=color)

    def _update_admin(self) -> None:
        if relogin.is_admin():
            self.admin_lbl.configure(text='✅ โปรแกรมมีสิทธิ์ Administrator — ส่งคีย์บอร์ดเข้าเกมได้',
                                     foreground='#3ecf8e')
            self.admin_btn.pack_forget()
        else:
            self.admin_lbl.configure(
                text='⚠ ยังไม่ได้เปิดแบบ Administrator — ปุ่มทดสอบ/ล็อกอินอัตโนมัติจะใช้ไม่ได้ '
                     '(Windows บล็อก SendInput ไปยังเกมที่ elevated)',
                foreground='#f5b942')
            self.admin_btn.pack(anchor='w', pady=(4, 0))

    def _relaunch_admin(self) -> None:
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'roz_gui.pyw')
        if relogin.relaunch_as_admin(script):
            self.app.destroy()
        else:
            messagebox.showerror('เปิดใหม่ไม่สำเร็จ', 'กด Yes ที่หน้าต่าง UAC เพื่อเปิดแบบ Administrator',
                                 parent=self)

    def _open_debug(self) -> None:
        try:
            os.makedirs(relogin.DEBUG_DIR, exist_ok=True)
            os.startfile(relogin.DEBUG_DIR)
        except OSError as e:
            messagebox.showerror('เปิดโฟลเดอร์ไม่ได้', str(e), parent=self)
