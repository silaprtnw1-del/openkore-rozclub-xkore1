"""Telegram / Discord notifications.

Sending happens on a background thread so a slow network never freezes the
window. Rules turn bot events + status changes into messages.
"""
from __future__ import annotations

import json
import queue
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, Callable, Final

from .errlog import log

if TYPE_CHECKING:
    from .bot import Bot

UA: Final[str] = 'ROZ-Bot-Control/1.0'


def _build_ssl_context() -> ssl.SSLContext:
    """TLS context with full certificate verification.

    Python only sees root CAs that Windows has already downloaded (Windows fetches
    roots lazily), so api.telegram.org's GoDaddy chain fails with the default
    context. truststore verifies through Windows itself, like a browser; certifi's
    Mozilla bundle is the fallback. Verification is never turned off.
    """
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        log.info('truststore not installed; trying certifi')
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError) as e:
        log.warning('certifi unavailable (%s); using the default trust store', e)
    return ssl.create_default_context()


SSL_CTX: Final[ssl.SSLContext] = _build_ssl_context()

# key -> (label shown in the GUI, enabled by default)
EVENT_TYPES: Final[dict[str, tuple[str, bool]]] = {
    'died':         ('ตัวละครตาย', True),
    'disconnected': ('หลุดจากเซิร์ฟเวอร์', True),
    'stopped':      ('บอทปิด / ไม่ตอบสนอง', True),
    'in_game':      ('เข้าเกมสำเร็จ', False),
    'pm':           ('มีคน PM (กระซิบ)', True),
    'gm_near':      ('เจอ GM ใกล้ตัว', True),
    'item':         ('ได้ไอเทมที่ระบุ', True),
    'level':        ('เลเวลอัพ (Base/Job)', True),
    'weight':       ('น้ำหนักเกินกำหนด', False),
    'ai_stuck':     ('AI ไม่ได้อยู่โหมดออโต้นานเกินไป', False),
}

DEFAULTS: Final[dict[str, Any]] = {
    'telegram_enabled': False,
    'telegram_token': '',
    'telegram_chat_id': '',
    'discord_enabled': False,
    'discord_webhook': '',
    'events': {k: v[1] for k, v in EVENT_TYPES.items()},
    'item_keywords': 'Card, การ์ด',
    'weight_percent': 90,
    'report_minutes': 0,
    'ai_stuck_minutes': 10,
}


def _post(url: str, data: dict[str, str] | None = None, json_body: dict[str, Any] | None = None,
          timeout: float = 15) -> dict[str, Any]:
    headers = {'User-Agent': UA}
    if json_body is not None:
        body: bytes | None = json.dumps(json_body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    elif data is not None:
        body = urllib.parse.urlencode(data).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    else:
        body = None
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        raw = r.read()
    if not raw:
        return {}           # Discord webhooks answer 204 No Content
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f'unexpected response type {type(parsed).__name__}')
    return parsed


def _num_setting(s: dict[str, Any], key: str, default: float) -> float:
    """Numeric setting with a fallback (settings.json may have been hand-edited)."""
    raw = s.get(key)
    if raw in (None, ''):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        log.warning('setting %s=%r is not a number, using %s', key, raw, default)
        return default


def _err_text(e: BaseException) -> str:
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = e.read().decode('utf-8', 'replace')[:200]
        except Exception as body_err:   # body is optional context; the status code still gets reported
            log.warning('could not read HTTP %s error body: %s', e.code, body_err)
            detail = ''
        return f'HTTP {e.code} {detail}'.strip()
    return str(e)


def describe_error(e: BaseException) -> str:
    """One Thai line for the GUI: what failed and what to check (token vs network vs SSL)."""
    if isinstance(e, urllib.error.HTTPError):       # subclass of URLError: check first
        text = _err_text(e)
        if e.code in (401, 403, 404):
            return f'{text} — Token หรือ Webhook ไม่ถูกต้อง'
        if e.code == 400:
            return f'{text} — Chat ID ไม่ถูกต้อง หรือยังไม่ได้กด /start ในแชทบอท'
        return text
    reason = e.reason if isinstance(e, urllib.error.URLError) else e
    if isinstance(reason, ssl.SSLError):
        return f'ตรวจใบรับรอง SSL ไม่ผ่าน ({reason}) — ไม่ใช่ปัญหาที่ Token'
    if isinstance(reason, (OSError, TimeoutError)):
        return f'เชื่อมต่อไม่ได้ ({reason}) — ตรวจอินเทอร์เน็ต / firewall'
    return str(e)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    _post(f'https://api.telegram.org/bot{token}/sendMessage',
          data={'chat_id': chat_id, 'text': text, 'disable_web_page_preview': 'true'})


def send_discord(webhook: str, text: str) -> None:
    attempts = 3
    for i in range(attempts):
        try:
            _post(webhook, json_body={'content': text[:1990], 'username': 'ROZ Bot'})
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < attempts - 1:   # rate limited: back off, then retry
                time.sleep(2)
                continue
            raise


def telegram_find_chats(token: str) -> list[tuple[str, str]]:
    """Chats that recently messaged the bot: [(chat_id, name), ...]."""
    res = _post(f'https://api.telegram.org/bot{token}/getUpdates', data={'limit': '50'})
    seen: dict[str, str] = {}
    for u in res.get('result', []):
        msg = u.get('message') or u.get('channel_post') or u.get('my_chat_member') or {}
        chat = msg.get('chat') or {}
        if 'id' in chat:
            name = chat.get('title') or ' '.join(filter(None, [chat.get('first_name'), chat.get('last_name')])) \
                or chat.get('username') or ''
            seen[str(chat['id'])] = name
    return list(seen.items())


class Notifier:
    def __init__(self, get_settings: Callable[[], dict[str, Any]],
                 on_result: Callable[[bool, str], None] | None = None) -> None:
        self.get_settings = get_settings
        self.on_result = on_result or (lambda ok, msg: None)
        self.q: queue.Queue[tuple[str, bool]] = queue.Queue()
        self.recent: dict[str, float] = {}   # dedupe key -> time
        threading.Thread(target=self._worker, daemon=True).start()

    def channels_ready(self, s: dict[str, Any] | None = None) -> list[str]:
        s = s or self.get_settings()
        out: list[str] = []
        if s.get('telegram_enabled') and s.get('telegram_token') and s.get('telegram_chat_id'):
            out.append('telegram')
        if s.get('discord_enabled') and s.get('discord_webhook'):
            out.append('discord')
        return out

    def notify(self, text: str, dedupe: str | None = None, window: float = 60, force: bool = False) -> None:
        """Queue a message. Same dedupe key within `window` seconds is dropped."""
        if dedupe:
            now = time.time()
            if now - self.recent.get(dedupe, 0) < window:
                return
            self.recent[dedupe] = now
            if len(self.recent) > 500:      # keep memory flat: drop keys older than an hour
                self.recent = {k: t for k, t in self.recent.items() if now - t < 3600}
        self.q.put((text, force))

    def _worker(self) -> None:
        while True:
            text, force = self.q.get()
            s = self.get_settings()
            chans = self.channels_ready(s)
            if not chans:
                if force:
                    self.on_result(False, 'ยังไม่ได้เปิดช่องทางแจ้งเตือน (ใส่ Token / Webhook และติ๊กเปิดใช้งาน)')
                continue
            for ch in chans:
                try:
                    if ch == 'telegram':
                        send_telegram(s['telegram_token'].strip(), s['telegram_chat_id'].strip(), text)
                    else:
                        send_discord(s['discord_webhook'].strip(), text)
                    if force:
                        self.on_result(True, f'ส่งไป {ch} สำเร็จ')
                except Exception as e:      # network problems must never kill the thread
                    reason = describe_error(e)
                    log.warning('notify via %s failed: %s', ch, reason)
                    self.on_result(False, f'ส่งไป {ch} ไม่สำเร็จ: {reason}')
            time.sleep(0.4)


def _fmt_int(n: Any) -> str:
    try:
        return f'{int(n):,}'
    except (TypeError, ValueError):
        return str(n)


class Rules:
    """Decides which bot events / state changes become notifications."""

    def __init__(self, notifier: Notifier, get_settings: Callable[[], dict[str, Any]]) -> None:
        self.n = notifier
        self.get_settings = get_settings
        self.was_running: dict[str, bool] = {}
        self.weight_alerted: dict[str, bool] = {}
        self.not_auto_since: dict[str, float] = {}
        self.last_report = time.time()

    def _on(self, key: str) -> bool:
        return self.get_settings().get('events', {}).get(key, EVENT_TYPES[key][1])

    def handle_event(self, bot: Bot, ev: dict[str, Any]) -> None:
        t = ev.get('type')
        who = f"[{bot.name}]"
        ch = ev.get('char') or bot.name
        mp = ev.get('map') or '?'
        if t == 'died' and self._on('died'):
            self.n.notify(f'💀 {who} {ch} ตายที่ {mp}', dedupe=f'{bot.name}:died')
        elif t == 'disconnected' and self._on('disconnected'):
            self.n.notify(f'🔌 {who} {ch} หลุดจากเซิร์ฟเวอร์ ({mp})', dedupe=f'{bot.name}:dc', window=120)
        elif t == 'in_game' and self._on('in_game'):
            self.n.notify(f'✅ {who} {ch} เข้าเกมแล้ว', dedupe=f'{bot.name}:in', window=120)
        elif t == 'pm' and self._on('pm'):
            self.n.notify(f'💬 {who} PM จาก {ev.get("from", "?")}: {ev.get("msg", "")}')
        elif t == 'gm_near' and self._on('gm_near'):
            self.n.notify(f'👮 {who} เจอ GM/Staff ใกล้ตัว: {ev.get("who", "?")} ที่ {mp}',
                          dedupe=f'{bot.name}:gm:{ev.get("who")}', window=600)
        elif t == 'item' and self._on('item'):
            item = str(ev.get('item', ''))
            kws = [k.strip().lower() for k in str(self.get_settings().get('item_keywords', '')).split(',') if k.strip()]
            if kws and any(k in item.lower() for k in kws):
                self.n.notify(f'💎 {who} {ch} ได้ {item} x{ev.get("amount", 1)} ที่ {mp}')
        elif t in ('base_level', 'job_level') and self._on('level'):
            kind = 'Base' if t == 'base_level' else 'Job'
            self.n.notify(f'🎉 {who} {ch} {kind} Level {ev.get("level")}!')

    def check_status(self, bot: Bot) -> None:
        s = self.get_settings()
        name = bot.name
        running = bot.running
        was = self.was_running.get(name)
        if was and not running and self._on('stopped'):
            self.n.notify(f'⚠️ [{name}] บอทปิดไปแล้ว หรือไม่ตอบสนองเกิน 20 วินาที', dedupe=f'{name}:stop', window=300)
        self.was_running[name] = running
        st = bot.status
        if not bot.online or st is None:
            self.not_auto_since.pop(name, None)
            return
        # weight
        wmax = st.get('weight_max') or 0
        if wmax and self._on('weight'):
            pct = st.get('weight', 0) * 100 / wmax
            limit = _num_setting(s, 'weight_percent', 90)
            if pct >= limit and not self.weight_alerted.get(name):
                self.weight_alerted[name] = True
                self.n.notify(f'🎒 [{name}] น้ำหนัก {pct:.0f}% (เกิน {limit:.0f}%)')
            elif pct < limit - 5:
                self.weight_alerted[name] = False
        # AI left out of auto mode
        if st.get('ai') != 'auto':
            since = self.not_auto_since.setdefault(name, time.time())
            mins = _num_setting(s, 'ai_stuck_minutes', 10)
            if self._on('ai_stuck') and time.time() - since > mins * 60:
                self.n.notify(f'⏸️ [{name}] AI อยู่โหมด {st.get("ai")} มานานกว่า {mins:.0f} นาที',
                              dedupe=f'{name}:aistuck', window=3600)
        else:
            self.not_auto_since.pop(name, None)

    def maybe_report(self, bots: list[Bot]) -> None:
        mins = _num_setting(self.get_settings(), 'report_minutes', 0)
        if mins <= 0 or time.time() - self.last_report < mins * 60:
            return
        self.last_report = time.time()
        lines = ['📊 สรุปสถานะบอท']
        for b in bots:
            lines.append(summary_line(b))
        self.n.notify('\n'.join(lines))


def summary_line(b: Bot) -> str:
    s = b.status
    if not b.running or s is None:
        return f'• {b.name}: ปิดอยู่'
    if not s.get('online'):
        return f'• {b.name}: ยังไม่เข้าเกม'
    exp_pct = s['exp'] * 100 / s['exp_max'] if s.get('exp_max') else 0
    eph = b.stats.per_hour(b.stats.base_gain)
    return (f'• {b.name} ({s.get("char")}) Lv {s.get("level")}/{s.get("level_job")} '
            f'{exp_pct:.1f}% | {s.get("map")} | HP {s.get("hp")}/{s.get("hp_max")} | '
            f'{_fmt_int(s.get("zeny"))}z | EXP/ชม. {_fmt_int(eph)}')
