"""ภาพรวม page: bot status, feed and start / stop / kill controls."""
from __future__ import annotations

import functools
import os
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import relogin
from .bot import Bot, launch_roz_start
from .errlog import log
from .notify import summary_line
from .settings import ROOT_DIR
from .theme import BAD, BG, C_EXP, C_HP, C_JOB, C_SP, C_W, Fonts, MUTED, OK, PANEL2, STATE_COLORS, TEXT, WARN
from .widgets import Bar, fmt_int


class OverviewMixin:
    """Mixin of App: uses the state that App.__init__ sets up."""

    # ------------------------------------------------------------- overview
    def _build_overview(self) -> None:
        f = self.tab_over
        padx = 18
        head = ttk.Frame(f, style='Panel.TFrame')
        head.pack(fill='x', pady=(16, 4), padx=padx)
        self.o_name = ttk.Label(head, text='-', style='PanelTitle.TLabel')
        self.o_name.pack(side='left')
        self.o_state = tk.Label(head, text='', bg=PANEL2, fg=TEXT, font=Fonts.F_SMALLB, padx=10, pady=3)
        self.o_state.pack(side='left', padx=12)
        self.o_where = ttk.Label(head, text='', style='Big.TLabel')
        self.o_where.pack(side='right')
        self.o_sub = ttk.Label(f, text='', style='PanelMuted.TLabel')
        self.o_sub.pack(fill='x', padx=padx)

        bars = ttk.Frame(f, style='Panel.TFrame')
        bars.pack(fill='x', pady=(12, 6), padx=padx)
        self.b_hp = Bar(bars, 'HP', C_HP)
        self.b_sp = Bar(bars, 'SP', C_SP)
        self.b_exp = Bar(bars, 'Base EXP', C_EXP)
        self.b_job = Bar(bars, 'Job EXP', C_JOB)
        self.b_w = Bar(bars, 'น้ำหนัก', C_W)
        for b in (self.b_hp, self.b_sp, self.b_exp, self.b_job, self.b_w):
            b.pack(fill='x', pady=3)

        tiles = ttk.Frame(f, style='Panel.TFrame')
        tiles.pack(fill='x', pady=6, padx=padx)
        self.tiles: dict[str, tk.Label] = {}
        names = [('zeny', 'Zeny'), ('eph', 'Base EXP / ชม.'), ('jph', 'Job EXP / ชม.'), ('zgain', 'Zeny ที่ได้ (รอบนี้)'),
                 ('mon', 'มอนรอบตัว'), ('ply', 'ผู้เล่นรอบตัว'), ('lock', 'แผนที่ฟาร์ม'), ('act', 'กำลังทำ')]
        for i, (k, lab) in enumerate(names):
            box = tk.Frame(tiles, bg=PANEL2, padx=12, pady=8)
            box.grid(row=i // 4, column=i % 4, sticky='nsew', padx=3, pady=3)
            tk.Label(box, text=lab, bg=PANEL2, fg=MUTED, font=Fonts.F_SMALL, anchor='w').pack(fill='x')
            v = tk.Label(box, text='-', bg=PANEL2, fg=TEXT, font=Fonts.F_BIG, anchor='w')
            v.pack(fill='x')
            self.tiles[k] = v
        for c in range(4):
            tiles.columnconfigure(c, weight=1, uniform='t')

        ctl = ttk.Frame(f, style='Panel.TFrame')
        ctl.pack(fill='x', pady=(10, 4), padx=padx)
        row1 = ttk.Frame(ctl, style='Panel.TFrame')
        row1.pack(fill='x', pady=2)
        ttk.Label(row1, text='บอท', style='PanelMuted.TLabel', width=8).pack(side='left')
        self.btn_start = ttk.Button(row1, text='▶ เริ่มบอท', style='Ok.TButton', command=self.start_selected)
        self.btn_start.pack(side='left', padx=2)
        ttk.Button(row1, text='⏹ ปิดบอท', command=self.stop_selected).pack(side='left', padx=2)
        ttk.Button(row1, text='✖ บังคับปิด', style='Danger.TButton', command=self.kill_selected).pack(side='left', padx=2)
        ttk.Label(row1, text='   AI', style='PanelMuted.TLabel').pack(side='left', padx=(16, 6))
        ttk.Button(row1, text='▶ ออโต้', style='Accent.TButton', command=lambda: self.cmd('ai on', 'เปิด AI ออโต้')).pack(side='left', padx=2)
        ttk.Button(row1, text='⏸ หยุดชั่วคราว', command=lambda: self.cmd('ai manual', 'AI โหมด manual')).pack(side='left', padx=2)
        ttk.Button(row1, text='⏹ ปิด AI', command=lambda: self.cmd('ai off', 'ปิด AI')).pack(side='left', padx=2)

        row2 = ttk.Frame(ctl, style='Panel.TFrame')
        row2.pack(fill='x', pady=2)
        ttk.Label(row2, text='สั่งงาน', style='PanelMuted.TLabel', width=8).pack(side='left')
        for label, command, desc in (('🌀 วาร์ป', 'tele', 'วาร์ป'), ('🏠 กลับจุดเซฟ', 'respawn', 'กลับจุดเซฟ'),
                                     ('📦 ไปฝากของ', 'autostorage', 'ไปฝากของ'), ('💰 ไปขายของ', 'autosell', 'ไปขายของ'),
                                     ('🛒 ไปซื้อของ', 'autobuy', 'ไปซื้อของ')):
            ttk.Button(row2, text=label, command=functools.partial(self.cmd, command, desc)).pack(side='left', padx=2)
        ttk.Button(row2, text='🪑 นั่ง/ยืน', command=self.toggle_sit).pack(side='left', padx=2)
        ttk.Button(row2, text='🔄 โหลด config ใหม่', command=lambda: self.cmd('reload config', 'โหลด config ใหม่')).pack(side='left', padx=2)

        row3 = ttk.Frame(ctl, style='Panel.TFrame')
        row3.pack(fill='x', pady=(6, 2))
        ttk.Label(row3, text='คำสั่ง', style='PanelMuted.TLabel', width=8).pack(side='left')
        self.cmd_var = tk.StringVar()
        e = ttk.Entry(row3, textvariable=self.cmd_var)
        e.pack(side='left', fill='x', expand=True, padx=2)
        e.bind('<Return>', lambda ev: self.send_custom())
        ttk.Button(row3, text='ส่ง', style='Accent.TButton', command=self.send_custom).pack(side='left', padx=2)

        ttk.Label(f, text='เหตุการณ์ล่าสุด', style='Panel.TLabel', font=Fonts.F_BOLD).pack(anchor='w', pady=(12, 4), padx=padx)
        self.feed = tk.Text(f, bg=BG, fg=TEXT, relief='flat', height=8, wrap='word', padx=10, pady=8,
                            font=Fonts.F_BASE, state='disabled', cursor='arrow')
        self.feed.pack(fill='both', expand=True, pady=(0, 14), padx=padx)
        for tag, color in (('ok', OK), ('bad', BAD), ('warn', WARN), ('info', '#7cc7ff'), ('muted', MUTED), ('time', '#5b6273')):
            self.feed.tag_configure(tag, foreground=color)

    def add_feed(self, bot_name: str, text: str, kind: str = 'muted', ts: float | None = None) -> None:
        self.feeds[bot_name].append((ts or time.time(), text, kind))
        if bot_name == self.selected:
            self._feed_append(ts or time.time(), text, kind)

    def _feed_append(self, ts: float, text: str, kind: str) -> None:
        self.feed.configure(state='normal')
        self.feed.insert('1.0', f'{text}\n', kind)
        self.feed.insert('1.0', time.strftime('%H:%M:%S  ', time.localtime(ts)), 'time')
        if int(self.feed.index('end-1c').split('.')[0]) > 300:
            self.feed.delete('300.0', 'end')
        self.feed.configure(state='disabled')

    def refresh_overview(self) -> None:
        b = self.cur_bot()
        if not b:
            return
        text, kind = b.state_text()
        self.o_state.configure(text=text, bg=STATE_COLORS[kind], fg='#0f1115' if kind != 'off' else TEXT)
        s = b.status if b.running else None
        if s and s.get('online'):
            self.o_name.configure(text=f'{s.get("char") or b.name}')
            job = s.get('job') or ''
            party = f' · ปาร์ตี้ {s["party"]}' if s.get('party') else ''
            self.o_sub.configure(text=f'บอท {b.name} · {job} · Base Lv {s.get("level")} / Job Lv {s.get("level_job")}{party}')
            self.o_where.configure(text=f'📍 {s.get("map")}  ({s.get("x")}, {s.get("y")})')
            self.b_hp.set(s.get('hp'), s.get('hp_max'), 'ตาย' if s.get('dead') else ('นั่งพัก' if s.get('sit') else ''))
            self.b_sp.set(s.get('sp'), s.get('sp_max'))
            self.b_exp.set(s.get('exp'), s.get('exp_max'))
            self.b_job.set(s.get('exp_job'), s.get('exp_job_max'))
            self.b_w.set(s.get('weight'), s.get('weight_max'))
            st = b.stats
            self.tiles['zeny'].configure(text=fmt_int(s.get('zeny')))
            warm = st.hours() > 0.01
            self.tiles['eph'].configure(text=fmt_int(st.per_hour(st.base_gain)) if warm else 'กำลังคำนวณ…')
            self.tiles['jph'].configure(text=fmt_int(st.per_hour(st.job_gain)) if warm else 'กำลังคำนวณ…')
            zg = st.zeny_gain()
            self.tiles['zgain'].configure(text=('+' if zg > 0 else '') + fmt_int(zg),
                                          fg=OK if zg > 0 else (BAD if zg < 0 else TEXT))
            self.tiles['mon'].configure(text=str(s.get('monsters', 0)))
            gms = s.get('gms') or []
            self.tiles['ply'].configure(text=f'{s.get("players", 0)}' + (f'  ⚠ GM {len(gms)}' if gms else ''),
                                        fg=BAD if gms else TEXT)
            self.tiles['lock'].configure(text=s.get('lockMap') or '-')
            self.tiles['act'].configure(text=s.get('action') or 'ว่าง')
        else:
            self.o_name.configure(text=b.name)
            self.o_where.configure(text='')
            if b.running:
                self.o_sub.configure(text=f'OpenKore เปิดอยู่ (port {b.port}) · รอเข้าเกม — ล็อกอินในหน้าต่างเกม')
            elif b.name in self.pending_start:
                self.o_sub.configure(text='กำลังเปิดบอท... (กด Yes ที่หน้าต่าง UAC แล้วรอสักครู่)')
            else:
                self.o_sub.configure(text=f'บอทปิดอยู่ · port {b.port} · กด "เริ่มบอท" เพื่อเปิด OpenKore + เกม')
            for bar in (self.b_hp, self.b_sp, self.b_exp, self.b_job, self.b_w):
                bar.set(0, 0)
            for v in self.tiles.values():
                v.configure(text='-', fg=TEXT)

    # --------------------------------------------------------- bot actions
    def cur_bot(self) -> Bot | None:
        return self.bot_by_name.get(self.selected)

    def cmd(self, command: str, desc: str | None = None, bot: Bot | None = None) -> None:
        b = bot or self.cur_bot()
        if not b:
            return
        if not b.running:
            self.toast(f'{b.name}: บอทยังไม่ได้เปิด สั่งงานไม่ได้', 'warn')
            return
        if b.send(command):
            self.add_feed(b.name, f'➡ สั่ง: {desc or command}', 'info')
            self.toast(f'{b.name}: ส่งคำสั่ง "{command}" แล้ว', 'ok')
        else:
            self.toast(f'{b.name}: เขียนไฟล์คำสั่งไม่ได้', 'bad')

    def send_custom(self) -> None:
        c = self.cmd_var.get().strip()
        if c:
            self.cmd(c)
            self.cmd_var.set('')

    def toggle_sit(self) -> None:
        b = self.cur_bot()
        if b and b.status:
            self.cmd('stand' if b.status.get('sit') else 'sit')

    def start_selected(self) -> None:
        b = self.cur_bot()
        if b:
            self.start_bots([b])

    def start_all(self) -> None:
        self.start_bots([b for b in self.bots if not b.running])

    def start_bots(self, bots: list[Bot]) -> None:
        bots = [b for b in bots if not b.running and b.name not in self.pending_start]
        if not bots:
            self.toast('บอทที่เลือกเปิดอยู่แล้ว หรือกำลังเปิด', 'warn')
            return
        style = str(self.settings.get('console_style', 'Hidden'))
        if not launch_roz_start(ROOT_DIR, [b.name for b in bots], style):
            self.toast('เปิด PowerShell ไม่ได้ — ดูรายละเอียดใน gui\\gui-error.log', 'bad')
            return
        now = time.time()
        for b in bots:
            self.pending_start[b.name] = now
            self.add_feed(b.name, '▶ กำลังเปิดบอท... กด Yes ที่หน้าต่าง UAC', 'info')
        self.toast('กำลังเปิดบอท — กด Yes ที่หน้าต่าง UAC (สิทธิ์ Administrator)', 'ok')

    def stop_selected(self) -> None:
        b = self.cur_bot()
        if b and b.running and messagebox.askyesno('ปิดบอท', f'ปิด OpenKore ของ {b.name}?\n(หน้าต่างเกมจะหลุดการเชื่อมต่อ)'):
            self._was_online.discard(b.name)        # a stop, not a disconnect: no auto login
            self._user_stop[b.name] = time.time()
            self.cmd('quit', 'ปิดบอท')

    def kill_selected(self) -> None:
        b = self.cur_bot()
        if not b or not b.status:
            return
        game_pid = b.cached_game_pid()
        if game_pid and not relogin.find_game_window(game_pid):
            game_pid = 0            # gone, or the pid now belongs to another program: never kill that
        game_line = (f'และปิดเกม (pid {game_pid}) ด้วย' if game_pid
                     else '(ไม่พบหน้าต่างเกมของบอทนี้ — ปิดเฉพาะ OpenKore)')
        if messagebox.askyesno('บังคับปิด', f'บังคับปิด OpenKore ของ {b.name} (pid {b.status.get("pid")}) {game_line}?\n'
                                             'ใช้เมื่อบอทค้างและกดปิดปกติไม่ได้ — จะมีหน้าต่าง UAC ถาม'):
            self._was_online.discard(b.name)
            self._user_stop[b.name] = time.time()
            if b.force_kill(game_pid):
                self.add_feed(b.name, '✖ สั่งบังคับปิด' + (' (OpenKore + เกม)' if game_pid else ''), 'bad')
            else:
                self.toast(f'{b.name}: บังคับปิดไม่ได้ — ดูรายละเอียดใน gui\\gui-error.log', 'bad')

    def send_summary(self) -> None:
        lines = ['📊 สรุปสถานะบอท'] + [summary_line(b) for b in self.bots]
        self.notifier.notify('\n'.join(lines), force=True)
        self.toast('กำลังส่งสรุป...', 'ok')

    def _check_pending(self, b: Bot) -> None:
        t = self.pending_start.get(b.name)
        if t is None:
            return
        if b.running:
            del self.pending_start[b.name]
            s = relogin.load_settings(b.name)
            if s.enabled and s.has_credentials() and relogin.is_admin():
                self._startup_login[b.name] = time.time()
                self._game_seen.pop(b.name, None)
                self.add_feed(b.name, f'✅ OpenKore เปิดแล้ว — จะล็อกอินให้อัตโนมัติเมื่อเกมโหลดเสร็จ '
                                      f'(รอ {s.boot_delay:g} วินาที)', 'ok')
            elif s.enabled and s.has_credentials():
                self.add_feed(b.name, '✅ OpenKore เปิดแล้ว — ล็อกอินอัตโนมัติไม่ได้เพราะ GUI ไม่ได้เปิดแบบ '
                                      'Administrator (ใช้ Start-GUI-Admin.cmd) — ล็อกอินในเกมเองก่อน', 'warn')
            else:
                self.add_feed(b.name, '✅ OpenKore เปิดแล้ว — ล็อกอินในหน้าต่างเกมได้เลย', 'ok')
        elif time.time() - t > 100:
            del self.pending_start[b.name]
            err = self._start_log_errors()
            self.add_feed(b.name, '❌ เปิดบอทไม่สำเร็จ' + (f': {err}' if err else ' (ไม่เห็นสถานะจากบอท)'), 'bad')
            self.toast(f'{b.name}: เปิดบอทไม่สำเร็จ ดูรายละเอียดในแท็บ โปรแกรม', 'bad')

    @staticmethod
    def _start_log_errors() -> str:
        """Last ERROR/WARNING line of the PowerShell transcript ('' if none or unreadable)."""
        path = os.path.join(ROOT_DIR, 'logs', 'gui-start.log')
        try:
            with open(path, 'rb') as f:
                raw = f.read()
        except FileNotFoundError:
            return ''
        except OSError as e:
            log.warning('cannot read %s: %s', path, e)
            return ''
        # PowerShell 5.1 transcripts are UTF-16 LE with a BOM; fall back to UTF-8.
        text = raw.decode('utf-16', errors='replace') if raw.startswith(b'\xff\xfe') \
            else raw.decode('utf-8', errors='replace')
        errs = [l for l in text.splitlines() if 'ERROR' in l or 'WARNING' in l]
        return errs[-1].strip() if errs else ''