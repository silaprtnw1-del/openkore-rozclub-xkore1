"""โปรแกรม page: start options, add / remove bot instances."""
from __future__ import annotations

import collections
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .addbot import AddBotDialog, roz_error_text
from .bot import Bot, load_registry, run_roz
from .errlog import log
from .settings import ROOT_DIR
from .theme import PANEL2, TEXT
from .widgets import BotCard


class ProgramPageMixin:
    """Mixin of App: uses the state that App.__init__ sets up."""

    # -------------------------------------------------------------- program
    def _build_program(self) -> None:
        f = self.tab_prog
        lf = ttk.LabelFrame(f, text=' 🖥️ หน้าต่าง OpenKore (console) ตอนเริ่มบอท ', padding=12)
        lf.pack(fill='x', padx=18, pady=(16, 6))
        self.console_style = tk.StringVar(value=self.settings.get('console_style', 'Hidden'))
        for val, text in (('Hidden', 'ซ่อนทั้งหมด (แนะนำ) — ดู log ในแท็บ 📜 บันทึก · ปิดบอทจากโปรแกรมนี้'),
                          ('Minimized', 'ย่อไว้ที่ taskbar'),
                          ('Normal', 'แสดงตามปกติ')):
            ttk.Radiobutton(lf, text=text, value=val, variable=self.console_style,
                            command=self._save_prog).pack(anchor='w', pady=2)
        ttk.Label(lf, style='PanelMuted.TLabel', text='มีผลกับการเริ่มบอทครั้งถัดไปจากโปรแกรมนี้').pack(anchor='w', pady=(6, 0))

        lf2 = ttk.LabelFrame(f, text=' 🧰 เครื่องมือ ', padding=12)
        lf2.pack(fill='x', padx=18, pady=6)
        row = ttk.Frame(lf2, style='Panel.TFrame')
        row.pack(fill='x')
        ttk.Button(row, text='📄 ดูผลการเริ่มบอทครั้งล่าสุด', command=self.show_start_log).pack(side='left', padx=2)
        ttk.Button(row, text='📂 เปิดโฟลเดอร์โปรไฟล์', command=lambda: self._open_path(ROOT_DIR)).pack(side='left', padx=2)
        ttk.Button(row, text='🔁 โหลดรายชื่อบอท (instances.json) ใหม่', command=self.reload_registry).pack(side='left', padx=2)

        lf3 = ttk.LabelFrame(f, text=' ℹ️ วิธีทำงาน ', padding=12)
        lf3.pack(fill='x', padx=18, pady=6)
        ttk.Label(lf3, style='PanelMuted.TLabel', justify='left', wraplength=900, text=(
            '• โปรแกรมนี้คุยกับบอทผ่านปลั๊กอิน gui_ipc (plugins\\gui_ipc) ซึ่งจะถูกโหลดเมื่อเริ่มบอทผ่านโปรแกรมนี้ หรือ roz.cmd\n'
            '• โปรไฟล์ของบอทแต่ละตัวอยู่ที่ bots\\<ชื่อ>\\ (control, tables, logs) · รายชื่อบอทอยู่ใน instances.json\n'
            '• ปุ่ม ➕ เพิ่มบอท / ➖ ลบบอท ที่แถบซ้ายเรียก scripts\\roz.ps1 new / remove ให้ทันที (ไม่ต้องปิดโปรแกรม)\n'
            '• ล็อกอินอัตโนมัติ (แท็บตั้งค่า) ต้องเปิด GUI ด้วย Start-GUI-Admin.cmd และไม่ล็อกจอ/ไม่สลีป\n'
            '• ล็อกอินอัตโนมัติจะทำงานเมื่อเห็นกล่อง Disconnected/Error ของเกม (กดทดสอบเองได้ตอนอยู่หน้า login)\n'
            '• ปุ่มเริ่มบอทจะขอสิทธิ์ Administrator (UAC) เพราะเกม Ragnarok.exe ต้องใช้สิทธิ์นี้\n'
            '• ทุกครั้งที่บันทึกการตั้งค่า จะสำรอง config.txt ไว้เป็น config.txt.bak-วันที่-gui (เก็บ 15 ไฟล์ล่าสุด)\n'
            '• การแจ้งเตือนทำงานเฉพาะตอนเปิดโปรแกรมนี้ไว้ (ย่อหน้าต่างไว้ได้)')).pack(anchor='w')

    def _save_prog(self) -> None:
        self.settings['console_style'] = self.console_style.get()
        if self._save_settings():
            self.toast('บันทึกแล้ว', 'ok')

    def show_start_log(self) -> None:
        path = os.path.join(ROOT_DIR, 'logs', 'gui-start.log')
        if os.path.exists(path):
            self._notepad(path)
        else:
            messagebox.showinfo('ยังไม่มี', 'ยังไม่เคยเริ่มบอทจากโปรแกรมนี้')

    def reload_registry(self, select: str | None = None) -> None:
        """Re-read instances.json and rebuild the sidebar (after roz new/remove)."""
        try:
            reg = load_registry(ROOT_DIR)
        except (OSError, ValueError) as e:
            log.exception('cannot reload instances.json')
            self.toast(f'โหลดรายชื่อบอทไม่ได้: {e}', 'bad')
            return
        instances = [i for i in reg.get('instances', []) if isinstance(i, dict) and i.get('name')]
        old = self.bot_by_name
        bots: list[Bot] = []
        for inst in instances:
            name = str(inst['name'])
            bots.append(old.get(name) or Bot(ROOT_DIR, inst))
        self.registry = reg
        self.bots = bots
        self.bot_by_name = {b.name: b for b in bots}
        self.feeds = {b.name: self.feeds.get(b.name, collections.deque(maxlen=300)) for b in bots}
        for name in list(self.pending_start):
            if name not in self.bot_by_name:
                del self.pending_start[name]
        for card in self.cards.values():
            card.destroy()
        self.cards = {}
        for b in self.bots:
            card = BotCard(self.card_box, self, b)
            card.pack(fill='x', pady=1)
            card.refresh(b.name == self.selected)
            self.cards[b.name] = card
        if select and select in self.bot_by_name:
            self.select_bot(select)
        elif self.selected is not None and self.selected in self.bot_by_name:
            self.cards[str(self.selected)].refresh(True)
        elif self.bots:
            self.select_bot(self.bots[0].name, force=True)
        else:
            self.selected = None
            self._clear_bot_view()
            self.toast('ไม่มีบอทใน instances.json — กด ➕ เพิ่มบอท', 'warn')

    def add_bot(self) -> None:
        dlg = self.add_dialog
        if dlg is not None:
            try:
                alive = bool(dlg.winfo_exists())
            except tk.TclError:
                alive = False
            if alive:
                dlg.lift()
                dlg.focus_set()
                return
        self.add_dialog = AddBotDialog(self)

    def remove_bot(self) -> None:
        b = self.cur_bot()
        if not b:
            self.toast('ไม่มีบอทให้ลบ', 'warn')
            return
        if self._removing:
            return
        if self._recovery_active == b.name:
            messagebox.showwarning('กำลังล็อกอินอัตโนมัติ',
                                   f'ระบบกำลังล็อกอิน {b.name} อยู่ — รอให้เสร็จก่อนแล้วค่อยลบ')
            return
        if b.running:
            messagebox.showwarning('ลบบอท', f'{b.name} กำลังรันอยู่ — ปิดบอท (⏹ ปิดบอท หรือ ✖ บังคับปิด) ก่อนแล้วค่อยลบ')
            return
        if self.kc_bot == b.name and self._config_dirty():
            if not messagebox.askyesno('ยังไม่ได้บันทึก', f'ทิ้งการแก้ไขที่ยังไม่ได้บันทึกของ {b.name}?'):
                return
        ans = messagebox.askyesnocancel(
            'ลบบอท',
            f'เอา {b.name} ออกจาก instances.json?\n\n'
            'Yes = ลบโฟลเดอร์โปรไฟล์ด้วย\nNo = เก็บโฟลเดอร์ไว้\nCancel = ยกเลิก')
        if ans is None:
            return
        args = ['remove', b.name] + (['-DeleteFiles'] if ans else [])
        self._removing = True
        self.btn_remove.state(['disabled'])
        self.toast(f'กำลังลบ {b.name}...', 'muted')

        def work() -> None:
            code, out = run_roz(ROOT_DIR, args)
            self._call_soon(lambda: self._removed(b.name, bool(ans), code, out))
        threading.Thread(target=work, daemon=True).start()

    def _removed(self, name: str, deleted: bool, code: int, out: str) -> None:
        self._removing = False
        self.btn_remove.state(['!disabled'])
        if code != 0:
            log.warning('roz remove %s failed: %s', name, out)
            hint = roz_error_text(out)
            messagebox.showerror('ลบบอทไม่สำเร็จ', (hint + '\n\n' if hint else '') + out)
            return
        self.reload_registry()
        self.toast(f'ลบ {name} แล้ว', 'ok')
        messagebox.showinfo('ลบบอท', f'นำ {name} ออกจากรายชื่อแล้ว'
                            + (' และลบโฟลเดอร์โปรไฟล์' if deleted else ' (เก็บโฟลเดอร์ไว้)'))

    def _clear_bot_view(self) -> None:
        """No bot left in the registry: reset the overview/config panels."""
        self.kc = None
        self.kc_bot = None
        self.c_title.configure(text='ยังไม่มีบอท')
        self.c_path.configure(text='')
        self.c_dirty.configure(text='')
        self.o_name.configure(text='-')
        self.o_state.configure(text='', bg=PANEL2, fg=TEXT)
        self.o_where.configure(text='')
        self.o_sub.configure(text='กด ➕ เพิ่มบอท ที่แถบซ้ายเพื่อสร้างบอทตัวแรก')
        for bar in (self.b_hp, self.b_sp, self.b_exp, self.b_job, self.b_w):
            bar.set(0, 0)
        for v in self.tiles.values():
            v.configure(text='-', fg=TEXT)