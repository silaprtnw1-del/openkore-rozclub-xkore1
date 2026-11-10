"""แจ้งเตือน page: Telegram / Discord settings."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from .errlog import log
from .notify import DEFAULTS as NOTIFY_DEFAULTS, describe_error, EVENT_TYPES, telegram_find_chats
from .widgets import Scrollable


class NotifyPageMixin:
    """Mixin of App: uses the state that App.__init__ sets up."""

    # --------------------------------------------------------------- notify
    def _build_notify(self) -> None:
        sc = Scrollable(self.tab_noti)
        sc.pack(fill='both', expand=True)
        f = sc.inner
        n = self.settings['notify']
        self.nv: dict[str, tk.Variable] = {}

        def entry(parent: ttk.LabelFrame, key: str, row: int, label: str,
                  show: str | None = None, width: int = 60) -> ttk.Entry:
            ttk.Label(parent, text=label, style='Panel.TLabel').grid(row=row, column=0, sticky='w', pady=4, padx=(0, 10))
            v = tk.StringVar(value=str(n.get(key, '')))
            e = ttk.Entry(parent, textvariable=v, width=width, show=show or '')
            e.grid(row=row, column=1, sticky='ew', pady=4)
            self.nv[key] = v
            return e

        cols = ttk.Frame(f)
        cols.pack(fill='x', padx=12, pady=8)
        cols.columnconfigure(0, weight=1, uniform='n')
        cols.columnconfigure(1, weight=1, uniform='n')

        tg = ttk.LabelFrame(cols, text=' ✈️ Telegram ', padding=12)
        tg.grid(row=0, column=0, sticky='nsew', padx=6, pady=6)
        tg.columnconfigure(1, weight=1)
        self.nv['telegram_enabled'] = tk.IntVar(value=1 if n.get('telegram_enabled') else 0)
        ttk.Checkbutton(tg, text='เปิดใช้ Telegram', variable=self.nv['telegram_enabled']).grid(row=0, column=0, columnspan=2, sticky='w')
        entry(tg, 'telegram_token', 1, 'Bot Token', show='•', width=40)
        entry(tg, 'telegram_chat_id', 2, 'Chat ID', width=40)
        ttk.Button(tg, text='🔍 หา Chat ID ให้อัตโนมัติ', command=self.find_chat_id).grid(row=3, column=1, sticky='w', pady=4)
        ttk.Label(tg, style='PanelMuted.TLabel', justify='left', wraplength=420, text=(
            'วิธีตั้งค่า:\n1. ใน Telegram คุยกับ @BotFather แล้วพิมพ์ /newbot ตั้งชื่อบอท\n'
            '2. คัดลอก Token ที่ได้มาใส่ช่อง Bot Token\n3. เปิดแชทกับบอทของคุณ แล้วส่งข้อความอะไรก็ได้ 1 ข้อความ\n'
            '4. กด "หา Chat ID ให้อัตโนมัติ" แล้วกดบันทึก')).grid(row=4, column=0, columnspan=2, sticky='w', pady=(8, 0))

        dc = ttk.LabelFrame(cols, text=' 💬 Discord ', padding=12)
        dc.grid(row=0, column=1, sticky='nsew', padx=6, pady=6)
        dc.columnconfigure(1, weight=1)
        self.nv['discord_enabled'] = tk.IntVar(value=1 if n.get('discord_enabled') else 0)
        ttk.Checkbutton(dc, text='เปิดใช้ Discord', variable=self.nv['discord_enabled']).grid(row=0, column=0, columnspan=2, sticky='w')
        entry(dc, 'discord_webhook', 1, 'Webhook URL', show='•', width=40)
        ttk.Label(dc, style='PanelMuted.TLabel', justify='left', wraplength=420, text=(
            'วิธีตั้งค่า:\n1. ใน Discord ไปที่ห้องที่อยากให้แจ้งเตือน → ตั้งค่าห้อง (รูปเฟือง)\n'
            '2. Integrations → Webhooks → New Webhook\n3. กด Copy Webhook URL แล้ววางในช่องด้านบน')).grid(
            row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))

        ev = ttk.LabelFrame(f, text=' 🔔 แจ้งเตือนเมื่อ ', padding=12)
        ev.pack(fill='x', padx=18, pady=6)
        self.nv_events: dict[str, tk.IntVar] = {}
        for i, (k, (label, default)) in enumerate(EVENT_TYPES.items()):
            v = tk.IntVar(value=1 if n.get('events', {}).get(k, default) else 0)
            ttk.Checkbutton(ev, text=label, variable=v).grid(row=i // 3, column=i % 3, sticky='w', padx=(0, 30), pady=3)
            self.nv_events[k] = v

        opt = ttk.LabelFrame(f, text=' ⚙️ รายละเอียด ', padding=12)
        opt.pack(fill='x', padx=18, pady=6)
        opt.columnconfigure(1, weight=1)
        entry(opt, 'item_keywords', 0, 'ไอเทมที่ต้องการแจ้ง (คั่นด้วย ,)', width=50)
        ttk.Label(opt, text='เช่น Card, Elunium, Oridecon — ถ้าชื่อไอเทมที่เก็บได้มีคำเหล่านี้จะแจ้งเตือน',
                  style='PanelMuted.TLabel').grid(row=1, column=1, sticky='w')
        entry(opt, 'weight_percent', 2, 'แจ้งเมื่อน้ำหนักเกิน (%)', width=8)
        entry(opt, 'ai_stuck_minutes', 3, 'แจ้งเมื่อ AI ไม่ได้ออโต้นาน (นาที)', width=8)
        entry(opt, 'report_minutes', 4, 'ส่งสรุปสถานะทุก ๆ (นาที, 0 = ไม่ส่ง)', width=8)

        btns = ttk.Frame(f)
        btns.pack(fill='x', padx=18, pady=(12, 0), before=cols)   # keep Save/Test visible without scrolling
        ttk.Button(btns, text='💾 บันทึกการแจ้งเตือน', style='Accent.TButton', command=self.save_notify).pack(side='left', padx=2)
        ttk.Button(btns, text='📨 ส่งข้อความทดสอบ', command=self.test_notify).pack(side='left', padx=2)
        ttk.Label(btns, text='Token / Webhook เก็บไว้ในเครื่องที่ %APPDATA%\\ROZBotControl\\settings.json (นอกโปรเจกต์) — อย่าแชร์ไฟล์นี้',
                  style='Muted.TLabel').pack(side='right')

    def _collect_notify(self) -> dict[str, Any]:
        n = dict(self.settings['notify'])
        for k, v in self.nv.items():
            if isinstance(v, tk.IntVar):
                n[k] = bool(v.get())
            else:
                n[k] = v.get().strip()
        for k in ('weight_percent', 'ai_stuck_minutes', 'report_minutes'):
            try:
                n[k] = float(n[k]) if n[k] not in ('', None) else NOTIFY_DEFAULTS[k]
            except ValueError:
                label = {'weight_percent': 'แจ้งเมื่อน้ำหนักเกิน', 'ai_stuck_minutes': 'แจ้งเมื่อ AI ไม่ได้ออโต้นาน',
                         'report_minutes': 'ส่งสรุปสถานะทุก ๆ'}[k]
                raise ValueError(f'ช่อง "{label}" ต้องเป็นตัวเลข')
        n['events'] = {k: bool(v.get()) for k, v in self.nv_events.items()}
        return n

    def save_notify(self, quiet: bool = False) -> bool:
        try:
            self.settings['notify'] = self._collect_notify()
        except ValueError as e:
            messagebox.showerror('ค่าไม่ถูกต้อง', str(e))
            return False
        if not self._save_settings():
            return False
        if not quiet:
            chans = self.notifier.channels_ready()
            self.toast('บันทึกการแจ้งเตือนแล้ว' + (f' (ใช้งาน: {", ".join(chans)})' if chans else ' — ยังไม่ได้เปิดช่องทางใด'), 'ok')
        return True

    def test_notify(self) -> None:
        if self.save_notify(quiet=True):
            self.notifier.notify('✅ ทดสอบแจ้งเตือนจาก ROZ Bot Control สำเร็จ!', force=True)
            self.toast('กำลังส่งข้อความทดสอบ...', 'muted')

    def _notify_result(self, ok: bool, msg: str) -> None:
        self._call_soon(lambda: self.toast(msg, 'ok' if ok else 'bad'))

    def find_chat_id(self) -> None:
        token = self.nv['telegram_token'].get().strip()
        if not token:
            messagebox.showinfo('Telegram', 'ใส่ Bot Token ก่อน')
            return
        self.toast('กำลังค้นหา Chat ID...', 'muted')

        def work() -> None:
            try:
                chats = telegram_find_chats(token)
            except Exception as e:      # network/HTTP/JSON: report it, never kill the thread silently
                log.warning('telegram getUpdates failed: %s', e)
                msg = f'ค้นหาไม่สำเร็จ: {describe_error(e)}'   # bind now: `e` is cleared after except
                self._call_soon(lambda: self.toast(msg, 'bad'))
                return
            self._call_soon(lambda: self._chat_found(chats))
        threading.Thread(target=work, daemon=True).start()

    def _chat_found(self, chats: list[tuple[str, str]]) -> None:
        if not chats:
            messagebox.showinfo('Telegram', 'ยังไม่พบแชท\nเปิด Telegram แล้วส่งข้อความหาบอทของคุณก่อน 1 ข้อความ จากนั้นกดอีกครั้ง')
            return
        cid, name = chats[-1]
        if len(chats) > 1:
            listing = '\n'.join(f'{c}  {n}' for c, n in chats)
            ans = simpledialog.askstring('เลือก Chat ID', f'พบหลายแชท:\n{listing}\n\nใส่ Chat ID ที่ต้องการ', initialvalue=cid, parent=self)
            if not ans:
                return
            cid = ans.strip()
        self.nv['telegram_chat_id'].set(cid)
        self.nv['telegram_enabled'].set(1)
        self.toast(f'พบ Chat ID {cid} ({name}) — กดบันทึกการแจ้งเตือน', 'ok')