"""Auto login for XKore 1 clients.

In XKore 1 the game client performs the account login and the character
selection; OpenKore only relays packets (`Network/XKore.pm` waits for the
client, and `plugins/reconnect` explicitly skips XKore 1/3).  So when the
client is kicked back to the login screen, only the client window can log in
again.  This module drives that window with Win32 SendInput.

Credentials are encrypted with Windows DPAPI and kept in
%APPDATA%\\ROZBotControl\\accounts.json -- never in config.txt (tracked by git)
and never in the GUI log.

Requirements: the GUI must run as Administrator. Windows UIPI blocks SendInput
from a lower-integrity process to the elevated game window. The Windows session
must stay unlocked while the sequence runs.
"""
from __future__ import annotations

import base64
import binascii
import ctypes
import ctypes.wintypes as w
import importlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Final

from .errlog import log

# --------------------------------------------------------------------- paths
SETTINGS_DIR: Final[str] = os.path.join(
    os.environ.get('APPDATA') or os.path.expanduser('~'), 'ROZBotControl')
ACCOUNTS_PATH: Final[str] = os.path.join(SETTINGS_DIR, 'accounts.json')
DEBUG_DIR: Final[str] = os.path.join(SETTINGS_DIR, 'relogin-debug')

# ROZCLUB kicks the first map-server entry back to the login screen once; the next
# login plays normally. One attempt therefore allows two full login passes.
LOGIN_PASSES: Final[int] = 2
ONLINE_HOLD_SECONDS: Final[float] = 20.0   # in game this long = really in, not about to be kicked
KICK_BOX_CLOSE_SECONDS: Final[float] = 2.0   # after OK on the kick box, before the login_delay wait
KICK_CONFIRM_SECONDS: Final[float] = 6.0   # state 1 this long after reaching the map = back at login
UI_SETTLE_SECONDS: Final[float] = 1.0      # let the game draw a screen before pressing keys on it

# ------------------------------------------------------------------ settings
@dataclass
class LoginSettings:
    """Per-bot auto-login settings (also stored in accounts.json)."""

    enabled: bool = False
    username: str = ''
    password: str = ''
    char_slot: int = 1
    server_slot: int = 1
    login_delay: float = 4.0
    server_delay: float = 6.0
    char_delay: float = 8.0
    map_timeout: float = 30.0
    retries: int = 3
    offline_seconds: float = 20.0
    cooldown_seconds: float = 300.0
    boot_delay: float = 20.0          # after "start bot": let the client reach its login screen

    def has_credentials(self) -> bool:
        return bool(self.username.strip() and self.password)


# ------------------------------------------------------------------ DPAPI
class _Blob(ctypes.Structure):
    _fields_ = [('cbData', w.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


_crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(_Blob), w.LPCWSTR, ctypes.POINTER(_Blob), ctypes.c_void_p,
    ctypes.c_void_p, w.DWORD, ctypes.POINTER(_Blob)]
_crypt32.CryptProtectData.restype = w.BOOL
_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(_Blob), ctypes.POINTER(w.LPWSTR), ctypes.POINTER(_Blob), ctypes.c_void_p,
    ctypes.c_void_p, w.DWORD, ctypes.POINTER(_Blob)]
_crypt32.CryptUnprotectData.restype = w.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array[ctypes.c_char]]:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf


def _dpapi(data: bytes, protect: bool) -> bytes:
    inp, _keep = _blob(data)
    out = _Blob()
    if protect:
        ok = _crypt32.CryptProtectData(
            ctypes.byref(inp), None, None, None, None, 1, ctypes.byref(out))
        err = 'CryptProtectData'
    else:
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(inp), None, None, None, None, 1, ctypes.byref(out))
        err = 'CryptUnprotectData'
    if not ok:
        raise OSError(ctypes.get_last_error(), err)
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(out.pbData)


def protect_password(password: str) -> str:
    """DPAPI-encrypt a password for accounts.json (base64)."""
    return base64.b64encode(_dpapi(password.encode('utf-16-le'), True)).decode('ascii')


def unprotect_password(token: str) -> str:
    return _dpapi(base64.b64decode(token.encode('ascii')), False).decode('utf-16-le')


# ------------------------------------------------------------- accounts.json
_cache: dict[str, tuple[float, LoginSettings]] = {}


def _read_accounts() -> dict[str, Any]:
    try:
        with open(ACCOUNTS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()}
        return {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning('cannot read %s (%s); using defaults', ACCOUNTS_PATH, e)
        return {}


def _write_accounts(data: dict[str, Any]) -> None:
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    tmp = ACCOUNTS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ACCOUNTS_PATH)
    _cache.clear()


def _num(raw: object, default: float, lo: float, hi: float) -> float:
    try:
        value = float(raw)       # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def load_settings(bot: str) -> LoginSettings:
    """Read one bot's settings (cached by accounts.json mtime)."""
    try:
        mtime = os.path.getmtime(ACCOUNTS_PATH)
    except OSError:
        mtime = 0.0
    hit = _cache.get(bot)
    if hit and hit[0] == mtime:
        return hit[1]
    data = _read_accounts()
    bots = data.get('bots')
    raw = bots.get(bot, {}) if isinstance(bots, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    s = LoginSettings(
        enabled=bool(raw.get('enabled')),
        username=str(raw.get('username') or ''),
        char_slot=int(_num(raw.get('char_slot'), 1, 1, 12)),
        server_slot=int(_num(raw.get('server_slot'), 1, 1, 20)),
        login_delay=_num(raw.get('login_delay'), 4.0, 1.0, 60.0),
        server_delay=_num(raw.get('server_delay'), 6.0, 1.0, 60.0),
        char_delay=_num(raw.get('char_delay'), 8.0, 1.0, 120.0),
        map_timeout=_num(raw.get('map_timeout'), 30.0, 5.0, 180.0),
        retries=int(_num(raw.get('retries'), 3, 1, 10)),
        offline_seconds=_num(raw.get('offline_seconds'), 20.0, 5.0, 600.0),
        cooldown_seconds=_num(raw.get('cooldown_seconds'), 300.0, 30.0, 3600.0),
        boot_delay=_num(raw.get('boot_delay'), 20.0, 3.0, 180.0),
    )
    token = str(raw.get('password') or '')
    if token:
        try:
            s.password = unprotect_password(token)
        except (OSError, ValueError, binascii.Error) as e:
            log.warning('cannot decrypt the password of %s: %s', bot, e)
    _cache[bot] = (mtime, s)
    return s


def save_settings(bot: str, s: LoginSettings) -> None:
    data = _read_accounts()
    bots = data.setdefault('bots', {})
    if not isinstance(bots, dict):
        bots = data['bots'] = {}
    bots[bot] = {
        'enabled': bool(s.enabled),
        'username': s.username.strip(),
        'password': protect_password(s.password) if s.password else '',
        'char_slot': int(s.char_slot),
        'server_slot': int(s.server_slot),
        'login_delay': float(s.login_delay),
        'server_delay': float(s.server_delay),
        'char_delay': float(s.char_delay),
        'map_timeout': float(s.map_timeout),
        'retries': int(s.retries),
        'offline_seconds': float(s.offline_seconds),
        'cooldown_seconds': float(s.cooldown_seconds),
        'boot_delay': float(s.boot_delay),
    }
    _write_accounts(data)


# ------------------------------------------------------------------- Win32
user32 = ctypes.WinDLL('user32', use_last_error=True)

SW_RESTORE: Final[int] = 9
GA_ROOT: Final[int] = 2
BM_CLICK: Final[int] = 0x00F5
WM_LBUTTONDOWN: Final[int] = 0x0201
WM_LBUTTONUP: Final[int] = 0x0202
MK_LBUTTON: Final[int] = 0x0001
MOUSEEVENTF_LEFTDOWN: Final[int] = 0x0002
MOUSEEVENTF_LEFTUP: Final[int] = 0x0004
VK_TAB: Final[int] = 0x09
VK_RETURN: Final[int] = 0x0D
VK_SHIFT: Final[int] = 0x10
VK_CONTROL: Final[int] = 0x11
VK_MENU: Final[int] = 0x12
VK_ESCAPE: Final[int] = 0x1B
VK_LEFT: Final[int] = 0x25
VK_UP: Final[int] = 0x26
VK_RIGHT: Final[int] = 0x27
VK_DOWN: Final[int] = 0x28
VK_SPACE: Final[int] = 0x20
VK_CAPITAL: Final[int] = 0x14
KEYEVENTF_KEYUP: Final[int] = 0x0002
KEYEVENTF_UNICODE: Final[int] = 0x0004
INPUT_MOUSE: Final[int] = 0
INPUT_KEYBOARD: Final[int] = 1


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', w.WORD), ('wScan', w.WORD), ('dwFlags', w.DWORD),
                ('time', w.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', w.LONG), ('dy', w.LONG), ('mouseData', w.DWORD), ('dwFlags', w.DWORD),
                ('time', w.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', w.DWORD), ('wParamL', w.WORD), ('wParamH', w.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [('ki', _KEYBDINPUT), ('mi', _MOUSEINPUT), ('hi', _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type', w.DWORD), ('u', _INPUTUNION)]


WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
EnumChildProc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, w.LPARAM]
user32.EnumChildWindows.argtypes = [w.HWND, EnumChildProc, w.LPARAM]
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user32.GetForegroundWindow.restype = w.HWND
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [w.HWND]
user32.IsWindowVisible.argtypes = [w.HWND]
user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
user32.VkKeyScanW.argtypes = [w.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short
user32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.SendMessageW.restype = w.LPARAM
user32.GetWindowThreadProcessId.restype = w.DWORD
_kernel32.GetCurrentThreadId.restype = w.DWORD
user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = ctypes.c_short
user32.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
user32.GetAncestor.argtypes = [w.HWND, w.UINT]
user32.GetAncestor.restype = w.HWND
user32.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
user32.GetDlgItem.restype = w.HWND
user32.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]

# Character select (ROZCLUB client, 1024x768 game area, measured on the 2026-11-10 03:22
# screenshot): 5 x 3 cards per page; centre of card 1's portrait at (101, 177) in client
# coordinates, cards 157 px apart across and 195 px down. The highlighted card is not
# always card 1 (card 2 on 03:22), so the bot clicks the card, checks which card is
# highlighted, corrects with the arrow keys, and only then presses Enter.
CHAR_CLIENT_SIZE: Final[tuple[int, int]] = (1024, 768)
CHAR_COLS: Final[int] = 5
CHAR_ROWS: Final[int] = 3
CHAR_CARD_ORIGIN: Final[tuple[int, int]] = (101, 177)
CHAR_CARD_STEP: Final[tuple[int, int]] = (157, 195)
# A card that is neither highlighted nor under the mouse has a 1 px grey frame
# (132,140,148); the highlighted one is framed gold/cyan. Checked on the 03:22-12:27
# screenshots. The mouse is parked on the empty strip below the cards while checking.
CHAR_FRAME_GREY: Final[tuple[int, int, int]] = (132, 140, 148)
CHAR_PARK_POINT: Final[tuple[int, int]] = (512, 745)


def char_card_point(slot: int) -> tuple[int, int]:
    """Client coordinates of the centre of character card `slot` (1 = top-left) on page 1."""
    if not 1 <= slot <= CHAR_COLS * CHAR_ROWS:
        raise ValueError(f'ช่องตัวละคร {slot} อยู่นอกหน้าแรก (1-{CHAR_COLS * CHAR_ROWS})')
    col, row = (slot - 1) % CHAR_COLS, (slot - 1) // CHAR_COLS
    return CHAR_CARD_ORIGIN[0] + col * CHAR_CARD_STEP[0], CHAR_CARD_ORIGIN[1] + row * CHAR_CARD_STEP[1]


def client_size(hwnd: int) -> tuple[int, int]:
    rect = w.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return 0, 0
    return rect.right - rect.left, rect.bottom - rect.top


def _send_mouse(flags: int) -> None:
    inp = _INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0))
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) != 1:
        raise OSError(ctypes.get_last_error(), 'SendInput (mouse) failed')


def click_client(hwnd: int, x: int, y: int, park: tuple[int, int] | None = None) -> bool:
    """Left-click at client coordinates of `hwnd`, then put the mouse back where it was,
    or leave it at client point `park` (a hovered card would look highlighted)."""
    pt = w.POINT(x, y)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return False
    rest = w.POINT()
    if park is not None:
        rest = w.POINT(*park)
        has_rest = bool(user32.ClientToScreen(hwnd, ctypes.byref(rest)))
    else:
        has_rest = bool(user32.GetCursorPos(ctypes.byref(rest)))
    try:
        user32.SetCursorPos(pt.x, pt.y)
        time.sleep(0.08)
        _send_mouse(MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.06)
        _send_mouse(MOUSEEVENTF_LEFTUP)
        time.sleep(0.3)                  # the game may read the cursor on its next frame
    finally:
        if has_rest:
            user32.SetCursorPos(rest.x, rest.y)
    return True


def grab_client(hwnd: int) -> Any | None:
    """The game area of `hwnd` as an RGB PIL image; None (logged) if it cannot be read."""
    pt = w.POINT(0, 0)
    width, height = client_size(hwnd)
    if width < 10 or height < 10 or not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        log.warning('relogin: cannot locate the game area of hwnd %s', hwnd)
        return None
    try:
        image_grab = importlib.import_module('PIL.ImageGrab')
        img = image_grab.grab(bbox=(pt.x, pt.y, pt.x + width, pt.y + height), all_screens=True)
        return img.convert('RGB')
    except (ImportError, OSError, ValueError) as e:
        log.warning('relogin: cannot capture the game area: %s', e)
        return None


def highlighted_cards(img: Any) -> list[int]:
    """Slots (1-15) whose card frame is not the plain grey one, on a 1024x768 capture."""
    def grey(p: tuple[int, int, int]) -> bool:
        return all(abs(c - g) <= 12 for c, g in zip(p, CHAR_FRAME_GREY))
    out: list[int] = []
    for slot in range(1, CHAR_COLS * CHAR_ROWS + 1):
        cx, cy = char_card_point(slot)
        lines = [[(cx + dx, cy + dy) for dx in range(-82, -66)] for dy in (-40, 7, 60)]      # left edge
        lines += [[(cx + dx, cy + dy) for dy in range(-90, -74)] for dx in (-30, 0, 30)]     # top edge
        if not any(any(grey(img.getpixel(p)) for p in line) for line in lines):
            out.append(slot)
    return out
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.c_size_t]


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    cls: str
    visible: bool
    rect: tuple[int, int, int, int]

    @property
    def area(self) -> int:
        left, top, right, bottom = self.rect
        return max(0, right - left) * max(0, bottom - top)


def _window_info(hwnd: int) -> WindowInfo:
    n = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, title, n + 1)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    pid = w.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    rect = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return WindowInfo(hwnd, pid.value, title.value, cls.value, bool(user32.IsWindowVisible(hwnd)),
                      (rect.left, rect.top, rect.right, rect.bottom))


def list_windows(pid: int | None = None) -> list[WindowInfo]:
    """Top-level windows of the desktop (all, or only one process)."""
    out: list[WindowInfo] = []

    def cb(hwnd: int, _lparam: int) -> bool:
        info = _window_info(hwnd)
        if pid is None or info.pid == pid:
            out.append(info)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


_IGNORE_CLASSES: Final[frozenset[str]] = frozenset({
    'IME', 'MSCTFIME UI', 'GDI+ Hook Window Class', 'ConsoleWindowClass',
    'TkTopLevel', 'Default IME',
})


def find_game_window(pid: int) -> int:
    """The client's main window for one process (0 if not found)."""
    candidates = [x for x in list_windows(pid) if x.cls == 'Ragnarok' or x.title == 'Ragnarok']
    if not candidates:
        return 0
    candidates.sort(key=lambda x: (x.visible, x.area), reverse=True)
    return candidates[0].hwnd


def find_dialogs(pid: int, main_hwnd: int) -> list[WindowInfo]:
    """Visible popups of the game process (top-level and child dialogs)."""
    out = []
    seen: set[int] = set()
    for x in list_windows(pid):
        if x.hwnd == main_hwnd or not x.visible or x.cls in _IGNORE_CLASSES or x.area < 1000:
            continue
        out.append(x)
        seen.add(x.hwnd)
    for x in _child_dialogs(main_hwnd):
        if x.hwnd not in seen:
            out.append(x)
    out.sort(key=lambda x: x.area, reverse=True)
    return out


def focus_window(hwnd: int) -> bool:
    """Restore + bring a window to the foreground (best effort)."""
    if not hwnd:
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        if user32.GetForegroundWindow() != hwnd:
            fg = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg, None)
            cur_tid = _kernel32.GetCurrentThreadId()
            if fg_tid and fg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, True)
                user32.SetForegroundWindow(hwnd)
                user32.AttachThreadInput(cur_tid, fg_tid, False)
        time.sleep(0.25)
        return is_foreground(hwnd)
    except OSError:
        return False


def is_foreground(hwnd: int) -> bool:
    """The game window (or one of its child popups) is the active window."""
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    return fg == hwnd or bool(user32.GetAncestor(fg, GA_ROOT) == hwnd)


def _send_key(vk: int, up: bool) -> None:
    flags = KEYEVENTF_KEYUP if up else 0
    inp = _INPUT(type=INPUT_KEYBOARD,
                 ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0))
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
    if sent != 1:
        raise OSError(ctypes.get_last_error(),
                      'SendInput failed — เปิด GUI แบบ Administrator หรือหน้าต่างเกมไม่ได้โฟกัส')


def _send_unicode(ch: str, up: bool) -> None:
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    inp = _INPUT(type=INPUT_KEYBOARD,
                 ki=_KEYBDINPUT(wVk=0, wScan=ord(ch), dwFlags=flags, time=0, dwExtraInfo=0))
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) != 1:
        raise OSError(ctypes.get_last_error(), 'SendInput (unicode) failed')


def press(vk: int, hold: float = 0.03) -> None:
    _send_key(vk, False)
    time.sleep(hold)
    _send_key(vk, True)
    time.sleep(0.03)


def caps_lock_on() -> bool:
    return bool(user32.GetKeyState(VK_CAPITAL) & 1)


def chord(modifier: int, vk: int) -> None:
    _send_key(modifier, False)
    time.sleep(0.03)
    press(vk)
    _send_key(modifier, True)
    time.sleep(0.05)


def type_text(text: str) -> None:
    """Type like a keyboard. Uses virtual keys so DirectInput clients see it."""
    for ch in text:
        if ch == '\n':
            press(VK_RETURN)
            continue
        scan = user32.VkKeyScanW(ch)
        if scan == -1:
            _send_unicode(ch, False)
            _send_unicode(ch, True)
            continue
        vk = scan & 0xFF
        shift = (scan >> 8) & 0xFF
        if shift & 2:
            _send_key(VK_CONTROL, False)
        if shift & 4:
            _send_key(VK_MENU, False)
        if shift & 1:
            _send_key(VK_SHIFT, False)
        press(vk)
        if shift & 1:
            _send_key(VK_SHIFT, True)
        if shift & 4:
            _send_key(VK_MENU, True)
        if shift & 2:
            _send_key(VK_CONTROL, True)
        time.sleep(0.01)


def click_default_button(dialog: int) -> bool:
    """Press the default OK button of a standard message box, else Enter."""
    buttons: list[int] = []

    def cb(hwnd: int, _lparam: int) -> bool:
        info = _window_info(hwnd)
        if info.cls == 'Button':
            buttons.append(hwnd)
        return True

    user32.EnumChildWindows(dialog, EnumChildProc(cb), 0)
    if buttons:
        user32.SendMessageW(buttons[0], BM_CLICK, 0, 0)
        return True
    return False


def click_dialog_button(dialog: int, button_id: int = 1) -> bool:
    """Click a standard dialog button by control id (IDOK = 1)."""
    button = user32.GetDlgItem(dialog, button_id)
    if button:
        user32.SendMessageW(button, BM_CLICK, 0, 0)
        return True
    return False


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def has_window(pid: int) -> bool:
    return bool(pid and find_game_window(pid))


def has_dialog(pid: int) -> bool:
    """A disconnected/error popup is visible for the game (safe to dismiss)."""
    main = find_game_window(pid)
    return bool(main and find_dialogs(pid, main))


def _is_server_title(title: str) -> bool:
    low = title.lower()
    return 'เซิร์ฟเวอร์' in title or 'server' in low


def _child_dialogs(parent: int) -> list[WindowInfo]:
    """Dialogs drawn as child windows of the game window (some clients do this)."""
    out: list[WindowInfo] = []

    def cb(hwnd: int, _lparam: int) -> bool:
        info = _window_info(hwnd)
        if not info.visible or info.area < 1000:
            return True
        low = info.title.lower()
        named = info.cls == 'Ragnarok' and (
            _is_server_title(info.title)
            or any(k in low for k in ('disconnect', 'error', 'หลุด', 'ข้อผิดพลาด')))
        if info.cls == '#32770' or named:
            out.append(info)
        return True

    user32.EnumChildWindows(parent, EnumChildProc(cb), 0)
    return out


def find_server_dialog(pid: int, main_hwnd: int) -> WindowInfo | None:
    """The Win32 'select server' dialog the client shows after login."""
    for d in find_dialogs(pid, main_hwnd):
        if _is_server_title(d.title):
            return d
    return None


def screenshot(hwnd: int, path: str) -> bool:
    """Save a debug screenshot of the window (best effort, never raises)."""
    try:
        ImageGrab = importlib.import_module('PIL.ImageGrab')
        info = _window_info(hwnd)
        left, top, right, bottom = info.rect
        if right - left < 10 or bottom - top < 10 or left < -10000:
            return False
        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)
        return True
    except Exception as e:       # debug aid only: a screenshot must never stop the login
        log.warning('relogin screenshot failed: %s', e)
        return False


# ---------------------------------------------------------------- sequence
class LoginRunner:
    """One supervised login attempt inside the game client window."""

    def __init__(self, bot_name: str, game_pid: int, settings: LoginSettings,
                 log_cb: Callable[[str], None] | None = None,
                 get_state: Callable[[], int] | None = None,
                 get_chars: Callable[[], list[str]] | None = None) -> None:
        self.bot_name = bot_name
        self.game_pid = game_pid
        self.s = settings
        self.log_cb = log_cb or (lambda m: log.info('[relogin] %s', m))
        self.get_state = get_state
        self.get_chars = get_chars        # ["0:potato7", ...] from status.json, once OpenKore has seen the list
        stamp = time.strftime('%Y%m%d-%H%M%S')
        self.debug_dir = os.path.join(DEBUG_DIR, f'{bot_name}-{stamp}')
        self._shot_no = 0
        self.hwnd = 0

    def log(self, msg: str) -> None:
        self.log_cb(msg)
        log.info('[relogin:%s] %s', self.bot_name, msg)

    def shot(self, name: str) -> None:
        self._shot_no += 1
        path = os.path.join(self.debug_dir, f'{self._shot_no:02d}-{name}.png')
        if screenshot(self.hwnd or find_game_window(self.game_pid), path):
            self.log(f'ภาพหน้าจอ: {path}')

    def wait(self, seconds: float, cancel: Callable[[], bool]) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if cancel():
                return False
            time.sleep(0.1)
        return True

    def dismiss_dialog(self, main: int, cancel: Callable[[], bool]) -> None:
        # Only Windows popups are found here. ROZCLUB draws its service list and its
        # 'connection failed' box inside the game (select_service() handles those with
        # Enter); a Windows window titled like a server list is still left alone.
        dialogs = self._non_server_dialogs(main)
        if not dialogs:
            self.log('ไม่พบกล่องข้อความ — ดำเนินการต่อ')
            return
        for d in dialogs[:3]:
            self.log(f'พบกล่องข้อความ: class={d.cls} title={d.title!r}')
            focus_window(d.hwnd)
            if not click_dialog_button(d.hwnd):
                if not click_default_button(d.hwnd):
                    press(VK_RETURN)
            self.wait(0.5, cancel)
            if cancel():
                return
        # Re-check with the same filter: an unfiltered list would include the server
        # dialog, and pressing Enter/Space on it here would pick a server out of order.
        left = self._non_server_dialogs(main)
        if left:
            self.log('กล่องยังอยู่ — ลองกด Enter/Space อีกครั้ง')
            focus_window(left[0].hwnd)
            press(VK_RETURN)
            self.wait(0.6, cancel)
            if self._non_server_dialogs(main):
                press(VK_SPACE)
                self.wait(0.6, cancel)

    def _non_server_dialogs(self, main: int) -> list[WindowInfo]:
        """Disconnected / Error / Event popups — everything except the server-selection dialog."""
        return [d for d in find_dialogs(self.game_pid, main) if not _is_server_title(d.title)]

    # ------------------------------------------------------------------ state-driven flow
    # OpenKore follows the client's packets (src/Network/Receive.pm):
    #   1 login screen · 2 service list (account_server_info) · 3 character select
    #   (received_characters) · 4 loading the map (received_character_ID_and_Map)
    #   · 5 in game (map_loaded) · -1 in game, OpenKore joined late.
    # The service list and character select are drawn by the game itself, not as
    # Windows dialogs, so each step waits for the state instead of looking for windows.

    def _state(self) -> int:
        return self.get_state() if self.get_state is not None else 0

    def _wait_state(self, accept: Callable[[int], bool], timeout: float,
                    cancel: Callable[[], bool]) -> int | None:
        """Poll the OpenKore state until `accept(state)`; the state, or None on timeout/cancel."""
        end = time.time() + timeout
        while time.time() < end:
            if cancel():
                return None
            st = self._state()
            if accept(st):
                return st
            time.sleep(0.25)
        return None

    def _focused(self, main: int, what: str) -> bool:
        if focus_window(main) and is_foreground(main):
            return True
        self.log(f'โฟกัสหน้าต่างเกมไม่สำเร็จตอน{what} — ยกเลิก (ไม่ส่งคีย์ไปหน้าต่างอื่น)')
        self.shot('nofocus')
        return False

    def select_service(self, main: int, cancel: Callable[[], bool]) -> bool:
        """Service list ('เลือกบริการ', state 2) -> character select (state 3), the way a player
        does it: Enter as soon as the list shows. Waiting too long on this screen makes the
        client give up with 'เชื่อมต่อเซิร์ฟเวอร์ล้มเหลว' (seen 2026-11-10 03:05, ~14 s)."""
        for attempt in (1, 2):
            if not self.wait(UI_SETTLE_SECONDS, cancel) or not self._focused(main, 'เลือกบริการ'):
                return False
            for _ in range(max(0, self.s.server_slot - 1)):
                press(VK_DOWN)
                self.wait(0.12, cancel)
            press(VK_RETURN)
            self.log(f'เลือกบริการช่อง {self.s.server_slot} (กด Enter) — รอหน้าเลือกตัวละคร')
            if self._wait_state(lambda s: s >= 3 or s == -1, self.s.char_delay, cancel) is not None:
                return True
            self.shot(f'service-{attempt}')
            if attempt == 1:
                # The in-game 'connection failed' box sits on the list: Enter closes it, then retry.
                self.log('ยังไม่ถึงหน้าเลือกตัวละคร — กด Enter ปิดกล่องข้อความแล้วลองใหม่')
                press(VK_RETURN)
        self.log('เลือกบริการไม่สำเร็จ 2 รอบ — เซิร์ฟเวอร์อาจเต็ม/ปิด หรือบัญชียังค้างจากรอบก่อน')
        return False

    def run(self, is_online: Callable[[], bool], cancel: Callable[[], bool]) -> bool:
        """Log in, and once more if the server kicks the first map login back to the login screen.

        ROZCLUB kicks the first entry to the map server back to the login screen once;
        the second login then plays normally (user, 2026-11-10). So one attempt allows
        LOGIN_PASSES full passes, and success means staying in game for ONLINE_HOLD_SECONDS.
        """
        if not is_admin():
            self.log('ไม่ใช่ Administrator — Windows จะบล็อกการส่งคีย์ไปยังเกม')
            return False
        main = find_game_window(self.game_pid)
        if not main:
            self.log(f'ไม่พบหน้าต่างเกมของ pid {self.game_pid}')
            return False
        self.hwnd = main
        self.log(f'หน้าต่างเกม hwnd={main}')
        for pass_no in range(1, LOGIN_PASSES + 1):
            result = self._login_pass(main, is_online, cancel, after_kick=pass_no > 1)
            if result != 'kicked':
                return result == 'online'
            if pass_no < LOGIN_PASSES:
                self.log('โดนเตะกลับหน้า login หลังเข้า map (ปกติของเซิร์ฟนี้ครั้งแรก) — ล็อกอินใหม่อีกรอบ')
        self.log(f'โดนเตะกลับหน้า login {LOGIN_PASSES} รอบติด — หยุด (กันบัญชีโดนล็อก)')
        self.shot('kicked-again')
        return False

    def _login_pass(self, main: int, is_online: Callable[[], bool], cancel: Callable[[], bool],
                    after_kick: bool = False) -> str:
        """One login -> service -> character pass. Returns 'online', 'kicked' or 'fail'."""
        state = self._state()
        self.log(f'สถานะ OpenKore ตอนเริ่ม: {state}')
        if state == 5 or state == -1:
            self.log('บอทออนไลน์อยู่แล้ว — ไม่ต้องล็อกอิน')
            return 'online'
        if state == 4:
            self.log('กำลังโหลดแผนที่อยู่แล้ว — รอเข้าเกม')
            return self._await_map(is_online, cancel)
        if not self._focused(main, 'เริ่ม'):
            return 'fail'
        self.shot('before')
        self.dismiss_dialog(main, cancel)              # Windows popups only; in-game boxes are handled by Enter
        if after_kick and state <= 1:
            # The kick leaves the map on screen under the in-game box 'เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ' [OK];
            # the login screen appears only after OK. Typing before that went nowhere (2026-11-10 12:06).
            press(VK_RETURN)
            self.log('ปิดกล่อง "เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ" (กด Enter) — รอหน้า login')
            if not self.wait(KICK_BOX_CLOSE_SECONDS, cancel):
                return 'fail'
            self.shot('after-kick-box')
        if state <= 1:
            if not self.wait(self.s.login_delay, cancel) or not self._focused(main, 'ล็อกอิน'):
                return 'fail'
            if caps_lock_on():
                self.log('Caps Lock เปิดอยู่ — ปิดให้ก่อนพิมพ์')
                press(VK_CAPITAL)
                self.wait(0.2, cancel)
            self.shot('login')
            chord(VK_CONTROL, ord('A'))
            type_text(self.s.username)
            press(VK_TAB)
            chord(VK_CONTROL, ord('A'))
            type_text(self.s.password)
            press(VK_RETURN)
            self.log('พิมพ์ username/password แล้วกด Enter — รอหน้าเลือกบริการ')
            state = self._wait_state(lambda s: s >= 2 or s == -1, self.s.server_delay, cancel) or 0
            if state < 2 and state != -1:
                self.log('ไม่ถึงหน้าเลือกบริการ (ตรวจ username/password หรือเซิร์ฟเวอร์ปิด)')
                self.shot('login-failed')
                return 'fail'
        if state == 2:
            self.shot('service')
            if not self.select_service(main, cancel):
                return 'fail'
        if self._state() == 3:
            if not self.wait(UI_SETTLE_SECONDS, cancel) or not self._focused(main, 'เลือกตัวละคร'):
                return 'fail'
            self.shot('char-select')
            if not self._slot_has_character(cancel):
                return 'fail'
            # The client picks the character itself: when OpenKore sent char_login for a
            # card other than the highlighted one, the server cut the connection
            # ('Server shutting down', kiminoto slot 2, 2026-11-10 12:22 and 12:27).
            if not self._click_char_card(main, cancel):
                return 'fail'
            press(VK_RETURN)
            self.log(f'เลือกตัวละครช่อง {self.s.char_slot} (การ์ดถูกเลือกแล้ว กด Enter)')
        return self._await_map(is_online, cancel)

    def _slot_has_character(self, cancel: Callable[[], bool]) -> bool:
        """Refuse an empty slot: Enter / a click there opens 'สร้างตัวละคร' instead of logging in.
        Unknown list (old plugin, status not updated yet) -> allow, as before."""
        if self.get_chars is None:
            return True
        chars: list[str] = []
        for _ in range(8):                           # status.json refreshes once per second
            chars = self.get_chars()
            if chars or not self.wait(0.5, cancel):
                break
        if not chars:
            return True
        slots = {c.split(':', 1)[0]: c.split(':', 1)[-1] for c in chars}
        if str(self.s.char_slot - 1) in slots:
            return True
        listing = ', '.join(f'ช่อง {int(k) + 1} = {v}' for k, v in sorted(slots.items(), key=lambda kv: int(kv[0])))
        self.log(f'ช่อง {self.s.char_slot} ไม่มีตัวละคร (บัญชีนี้มี: {listing}) — แก้ "ตัวละครช่องที่" ในแท็บนี้')
        return False

    def _click_char_card(self, main: int, cancel: Callable[[], bool]) -> bool:
        """Highlight the character's card: click it, check on screen which card is
        highlighted, and correct with the arrow keys. True only when exactly the wanted
        card is highlighted, so Enter never starts another card (an empty one on
        2026-11-10 03:22 opened 'สร้างตัวละคร')."""
        size = client_size(main)
        if size != CHAR_CLIENT_SIZE:
            self.log(f'พื้นที่เกมขนาด {size[0]}x{size[1]} ไม่ใช่ {CHAR_CLIENT_SIZE[0]}x{CHAR_CLIENT_SIZE[1]} '
                     '— ตำแหน่งการ์ดวัดไว้ที่ความละเอียดนี้ จึงไม่เลือก (ตั้งเกมเป็น 1024x768 หรือเลือกตัวละครเอง)')
            return False
        slot = self.s.char_slot
        try:
            x, y = char_card_point(slot)
        except ValueError as e:
            self.log(str(e))
            return False
        if not click_client(main, x, y, park=CHAR_PARK_POINT):
            self.log('คลิกการ์ดตัวละครไม่สำเร็จ')
            return False
        for attempt in range(3):
            if not self.wait(0.4, cancel):
                return False
            img = grab_client(main)
            if img is None:
                self.log('อ่านภาพหน้าเลือกตัวละครไม่ได้ — ไม่กด Enter')
                return False
            lit = highlighted_cards(img)
            if lit == [slot]:
                self.shot('char-selected')
                return True
            if len(lit) != 1 or attempt == 2:
                break
            # Arrow keys from the highlighted card to the wanted one (user: arrows work here).
            cur = lit[0]
            dc = (slot - 1) % CHAR_COLS - (cur - 1) % CHAR_COLS
            dr = (slot - 1) // CHAR_COLS - (cur - 1) // CHAR_COLS
            self.log(f'การ์ดที่ถูกเลือกคือช่อง {cur} — กดลูกศรไปช่อง {slot}')
            if not self._focused(main, 'เลือกตัวละคร'):
                return False
            for vk, n in ((VK_RIGHT if dc > 0 else VK_LEFT, abs(dc)), (VK_DOWN if dr > 0 else VK_UP, abs(dr))):
                for _ in range(n):
                    press(vk)
                    self.wait(0.15, cancel)
        found = ', '.join(map(str, lit)) if lit else 'ไม่พบ'
        self.log(f'การ์ดที่ถูกเลือก: {found} ไม่ใช่ช่อง {slot} — ไม่กด Enter (กันเข้าตัวผิด/หน้าสร้างตัวละคร)')
        self.shot('char-wrong-card')
        return False

    def _await_map(self, is_online: Callable[[], bool], cancel: Callable[[], bool]) -> str:
        """After choosing the character: 'online' once in game for ONLINE_HOLD_SECONDS;
        'kicked' if the map was reached (state 4/5/-1) and the client then sat at the login
        screen (state 1) for KICK_CONFIRM_SECONDS; 'fail' otherwise within map_timeout."""
        deadline = time.time() + self.s.map_timeout
        online_since: float | None = None
        reached_map = False
        low_since: float | None = None
        while True:
            if cancel():
                return 'fail'
            now = time.time()
            state = self._state()
            if state in (4, 5, -1):
                reached_map = True
            if is_online():
                low_since = None
                if online_since is None:
                    online_since = now
                    self.log(f'เข้าเกมแล้ว — รอดูว่าอยู่ได้ {ONLINE_HOLD_SECONDS:g} วินาที (เซิร์ฟนี้เตะครั้งแรก)')
                if now - online_since >= ONLINE_HOLD_SECONDS:
                    self.log('อยู่ในเกมได้ตามปกติแล้ว')
                    self.shot('online')
                    return 'online'
                deadline = max(deadline, online_since + ONLINE_HOLD_SECONDS + 5)   # holding is not a timeout
            else:
                if online_since is not None:
                    self.log('หลุดออกจากเกมระหว่างรอ')
                    online_since = None
                if reached_map and state == 1:
                    if low_since is None:
                        low_since = now
                    if now - low_since >= KICK_CONFIRM_SECONDS:
                        self.shot('kicked')
                        return 'kicked'
                else:
                    low_since = None
            if now >= deadline:
                self.log(f'รอเข้าเกมไม่สำเร็จ (สถานะล่าสุด {state}) — ตรวจช่องตัวละคร/ดีเลย์')
                self.shot('timeout')
                return 'fail'
            self.wait(0.5, cancel)


def relaunch_as_admin(script: str) -> bool:
    """Start this GUI again via UAC (True when the new process was launched)."""
    try:
        import sys
        res = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', sys.executable, f'"{script}"', None, 1)
        if res <= 32:
            log.error('ShellExecuteW(runas) failed: %s', res)
            return False
        return True
    except OSError:
        log.exception('cannot relaunch as Administrator')
        return False
