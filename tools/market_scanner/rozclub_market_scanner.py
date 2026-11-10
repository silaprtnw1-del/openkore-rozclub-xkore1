#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROZCLUB Market Scanner & OpenKore Drop Optimizer
Reverse-engineered from D:\\ROZCLUB\\d3d9.dll (RozclubMarket/1.0 & THAA 0x0CF0/0x0CF1)
"""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
import struct
import sys
import time
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# d3d9.dll RVA Constants (ImageBase = 0x70580000)
# ---------------------------------------------------------------------------
IMAGE_BASE = 0x70580000

RVA_MARKET_INIT  = 0x706661B0 - IMAGE_BASE  # void market_open_or_refresh()
RVA_MARKET_URL   = 0x70738E88 - IMAGE_BASE  # std::string (https://market.rozclub.com)
RVA_MARKET_TOKEN = 0x70738EA0 - IMAGE_BASE  # std::string (X-Roz-Token)
RVA_MARKET_OPEN1 = 0x70738EBC - IMAGE_BASE  # bool pending_open
RVA_MARKET_OPEN2 = 0x70738EBE - IMAGE_BASE  # bool window_visible
RVA_MAP_NAME     = 0x7073902C - IMAGE_BASE  # std::string (current map name)
RVA_HUNT_MOBS    = 0x7073908C - IMAGE_BASE  # std::vector<HuntMob> (stride 0x24)
RVA_MAP_MOBS     = 0x70739098 - IMAGE_BASE  # std::vector<MapMob>  (stride 0x1C)
RVA_MAP_DROPS    = 0x707390B0 - IMAGE_BASE  # std::vector<MapDrop> (stride 0x24)

# Win32 API definitions
TH32CS_SNAPPROCESS  = 0x00000002
TH32CS_SNAPMODULE   = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_VM_READ      = 0x0010
PROCESS_VM_WRITE     = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]

class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.CreateRemoteThread.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
]
kernel32.CreateRemoteThread.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

psapi.EnumProcessModulesEx.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD
]
psapi.EnumProcessModulesEx.restype = wintypes.BOOL
psapi.GetModuleFileNameExA.argtypes = [
    wintypes.HANDLE, wintypes.HMODULE, ctypes.c_char_p, wintypes.DWORD
]
psapi.GetModuleFileNameExA.restype = wintypes.DWORD


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32First.restype = wintypes.BOOL
kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32Next.restype = wintypes.BOOL

GAME_EXE_KEYWORDS = ("rozclub", "ragexe", "ragnarok")


def _game_pids_by_name():
    """Return PIDs whose executable name looks like the ROZCLUB client."""
    pids = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return pids
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = kernel32.Process32First(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.decode("ascii", errors="ignore").lower()
            if any(k in name for k in GAME_EXE_KEYWORDS):
                pids.append(entry.th32ProcessID)
            ok = kernel32.Process32Next(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return pids


def find_ragexe_and_d3d9():
    pids = []
    # 1. Check hwnd from D:\ROZCLUB\savedata\thaa_overlay.log first
    try:
        with open(r"D:\ROZCLUB\savedata\thaa_overlay.log", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "hwnd " in line:
                    hwnd_hex = line.split("hwnd ")[1].split(")")[0].strip()
                    hwnd = int(hwnd_hex, 16)
                    pid = wintypes.DWORD(0)
                    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
                    if pid.value and pid.value not in pids:
                        pids.append(pid.value)
    except Exception:
        pass

    # 2. Also look for the game by process name only (no longer opens every
    #    process on the machine).
    for pid in _game_pids_by_name():
        if pid not in pids:
            pids.append(pid)

    LIST_MODULES_ALL = 0x03
    for pid in pids:
        hproc = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not hproc:
            continue
        try:
            exe_buf = ctypes.create_string_buffer(260)
            if psapi.GetModuleFileNameExA(hproc, None, exe_buf, 260):
                exe_path = exe_buf.value.decode("ascii", errors="ignore").lower()
                if not any(k in exe_path for k in ("rozclub", "ragexe", "ragnarok")):
                    continue
            hmods = (wintypes.HMODULE * 1024)()
            cb_needed = wintypes.DWORD(0)
            if psapi.EnumProcessModulesEx(hproc, hmods, ctypes.sizeof(hmods), ctypes.byref(cb_needed), LIST_MODULES_ALL):
                mod_count = cb_needed.value // ctypes.sizeof(wintypes.HMODULE)
                for j in range(mod_count):
                    mbuf = ctypes.create_string_buffer(260)
                    if psapi.GetModuleFileNameExA(hproc, hmods[j], mbuf, 260):
                        mpath = mbuf.value.decode("ascii", errors="ignore").lower()
                        if mpath.endswith("\\d3d9.dll") and "system32" not in mpath and "syswow64" not in mpath:
                            return pid, hmods[j]
        finally:
            kernel32.CloseHandle(hproc)
    return None, None


class ProcessMemory:
    def __init__(self, pid, write_access=False):
        self.pid = pid
        access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
        if write_access:
            access |= PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_CREATE_THREAD
        self.hproc = kernel32.OpenProcess(access, False, pid)
        if not self.hproc and write_access:
            access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
            self.hproc = kernel32.OpenProcess(access, False, pid)
        if not self.hproc:
            raise RuntimeError(f"Cannot OpenProcess PID {pid} (err={ctypes.get_last_error()})")

    def close(self):
        if self.hproc:
            kernel32.CloseHandle(self.hproc)
            self.hproc = None

    def read_bytes(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        nread = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(self.hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(nread))
        if not ok or nread.value != size:
            return None
        return buf.raw

    def read_u32(self, addr):
        b = self.read_bytes(addr, 4)
        return struct.unpack("<I", b)[0] if b else 0

    def read_i32(self, addr):
        b = self.read_bytes(addr, 4)
        return struct.unpack("<i", b)[0] if b else 0

    def read_std_string(self, addr, max_len=4096):
        """Read GCC 32-bit libstdc++ SSO std::string (24 bytes: ptr, len, buf[16])"""
        hdr = self.read_bytes(addr, 8)
        if not hdr:
            return ""
        ptr, length = struct.unpack("<II", hdr)
        if length == 0 or length > max_len or ptr == 0:
            return ""
        raw = self.read_bytes(ptr, length)
        if not raw:
            return ""
        return raw.decode("utf-8", errors="replace")


def read_live_client_state(auto_request_token=True):
    pid, base = find_ragexe_and_d3d9()
    if not pid or not base:
        return None
    # Read-only access. The old code injected a thread into the game
    # (CreateRemoteThread on market_open_or_refresh) and wrote to its memory to
    # hide the Market window; that can crash the client and is easy for an
    # anti-cheat to spot, so it is no longer done.
    pm = ProcessMemory(pid, write_access=False)
    try:
        map_name = pm.read_std_string(base + RVA_MAP_NAME)
        market_token = ""
        # The token may arrive a moment after the plugin's 0x0CF0 request.
        for _ in range(30 if auto_request_token else 1):
            market_token = pm.read_std_string(base + RVA_MARKET_TOKEN)
            if market_token:
                break
            time.sleep(0.1)
        market_url = pm.read_std_string(base + RVA_MARKET_URL) or "https://market.rozclub.com"

        # Read map monsters (std::vector<MapMob>, stride 0x1C = 28 bytes: int32 id, std::string name)
        mobs = []
        vec_mobs = pm.read_bytes(base + RVA_MAP_MOBS, 12)
        if vec_mobs:
            start, finish, _ = struct.unpack("<III", vec_mobs)
            count = (finish - start) // 0x1C if finish >= start else 0
            if 0 < count <= 500:
                for i in range(count):
                    entry_addr = start + i * 0x1C
                    mob_id = pm.read_i32(entry_addr)
                    mob_name = pm.read_std_string(entry_addr + 4)
                    mobs.append({"id": mob_id, "name": mob_name})

        # Read map drops (std::vector<MapDrop>, stride 0x24 = 36 bytes: int32 id, int32 unk, int32 picked, std::string name)
        drops = []
        vec_drops = pm.read_bytes(base + RVA_MAP_DROPS, 12)
        if vec_drops:
            start, finish, _ = struct.unpack("<III", vec_drops)
            count = (finish - start) // 0x24 if finish >= start else 0
            if 0 < count <= 1000:
                for i in range(count):
                    entry_addr = start + i * 0x24
                    hdr = pm.read_bytes(entry_addr, 12)
                    if not hdr:
                        continue
                    item_id, unk, picked = struct.unpack("<iii", hdr)
                    item_name = pm.read_std_string(entry_addr + 12)
                    drops.append({
                        "id": item_id,
                        "picked": bool(picked),
                        "name": item_name,
                    })

        return {
            "pid": pid,
            "d3d9_base": base,
            "map_name": map_name,
            "market_url": market_url.rstrip("/"),
            "market_token": market_token,
            "mobs": mobs,
            "drops": drops,
        }
    finally:
        pm.close()


# ---------------------------------------------------------------------------
# RozclubMarket/1.0 HTTP API Client
# ---------------------------------------------------------------------------
# This file lives in <repo>\tools\market_scanner\ (moved from C:\Users\silap\rearo on 2026-11-10).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POTATO7_DIR = os.path.join(REPO_ROOT, "bots", "potato7")


def _openkore_root():
    """openkoreRoot from instances.json (the bot registry), else the usual install folder."""
    try:
        with open(os.path.join(REPO_ROOT, "instances.json"), "r", encoding="utf-8-sig") as f:
            root = json.load(f).get("openkoreRoot")
        if root:
            return str(root)
    except (OSError, ValueError) as e:
        print(f"[!] instances.json unreadable ({e}); using the default OpenKore folder")
    return r"C:\Users\silap\openkore"


# Raw server replies (no token) kept for debugging the response format.
RAW_DUMP_PATH = os.path.join(POTATO7_DIR, "logs", "rozclub_market_raw.txt")
_raw_samples = []


def _remember_raw(path, raw, keep=5):
    if len(_raw_samples) < keep:
        _raw_samples.append((path, raw))


def _write_raw_dump():
    if not _raw_samples:
        return
    try:
        with open(RAW_DUMP_PATH, "w", encoding="utf-8") as f:
            for path, raw in _raw_samples:
                f.write(f"===== GET {path} ({len(raw)} bytes)\n")
                f.write(raw[:4000])
                f.write("\n")
    except OSError:
        pass


class MarketAuthError(RuntimeError):
    """The market server rejected the request (missing or expired token)."""


class RozclubMarketClient:
    def __init__(self, base_url="https://market.rozclub.com", token=""):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _get(self, path):
        url = f"{self.base_url}{path}"
        headers = {
            "User-Agent": "RozclubMarket/1.0",
        }
        if self.token:
            headers["X-Roz-Token"] = self.token
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise MarketAuthError(
                    "HTTP 401 Unauthorized: X-Roz-Token is " + ("empty" if not self.token else "rejected (expired?)")
                    + ". Open the Market window in-game once, then run the command again.") from None
            raise RuntimeError(f"HTTP {e.code} {e.reason} for {path}") from None

    def get_price_guide(self, item_id, refine=0):
        """
        Calls /api/pguide?id=<item_id>&refine=<refine>
        Parsed according to d3d9.dll 0x7066f9e5:
        Line 0: ok \t <item_id> \t <min_str> \t <avg_str> \t <max_str> \t <count>
        Followed by active listing rows.
        """
        raw = self._get(f"/api/pguide?id={int(item_id)}&refine={int(refine)}")
        _remember_raw(f"/api/pguide?id={int(item_id)}&refine={int(refine)}", raw)
        lines = [line.strip("\r") for line in raw.splitlines() if line.strip()]
        if not lines:
            return None
        first = lines[0].split("\t")
        if first[0] != "ok":
            return {"ok": False, "error": first[1] if len(first) > 1 else raw}

        def parse_num(s):
            s_clean = "".join(ch for ch in s if ch.isdigit())
            return int(s_clean) if s_clean else 0

        min_str = first[2] if len(first) > 2 else "0"
        avg_str = first[3] if len(first) > 3 else "0"
        max_str = first[4] if len(first) > 4 else "0"
        count   = int(first[5]) if len(first) > 5 and first[5].isdigit() else 0

        return {
            "ok": True,
            "item_id": int(item_id),
            "min_str": min_str,
            "avg_str": avg_str,
            "max_str": max_str,
            "min_val": parse_num(min_str),
            "avg_val": parse_num(avg_str),
            "max_val": parse_num(max_str),
            "count": count,
        }

    def get_listing_price(self, item_id, name):
        """
        Price from the items currently listed on the market (/api/list search),
        cheapest first. /api/pguide is not used for this: it answered
        "ok <id> 0 3" even for Strawberry while 15 Strawberry listings existed.
        """
        res = self.list_market(page=1, query=name, sort="cheap")
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error")}
        prices = sorted(l["unit_price"] for l in res["listings"]
                        if l["item_id"] == int(item_id) and l["refine"] == 0 and l["unit_price"] > 0)
        if not prices:
            return {"ok": True, "item_id": int(item_id), "min_val": 0, "avg_val": 0, "max_val": 0,
                    "min_str": "-", "avg_str": "-", "count": 0}
        median = prices[len(prices) // 2]
        return {
            "ok": True,
            "item_id": int(item_id),
            "min_val": prices[0],
            "avg_val": median,
            "max_val": prices[-1],
            "min_str": f"{prices[0]:,}",
            "avg_str": f"{median:,}",
            "count": len(prices),
        }

    def list_market(self, page=1, query="", currency="", sort="", category="", min_p="", max_p=""):
        """
        Calls /api/list?p=<page>&q=<query>&cur=zeny|cash&sort=cheap|exp&type=<cat>&min=<min>&max=<max>
        Parsed according to d3d9.dll 0x70657500, 0x7066f714, and 0x70663f40.
        """
        path = f"/api/list?p={int(page)}"
        if query:
            path += f"&q={urllib.parse.quote(query)}"
        if currency in ("zeny", "cash"):
            path += f"&cur={currency}"
        if sort in ("cheap", "exp"):
            path += f"&sort={sort}"
        if category:
            path += f"&type={urllib.parse.quote(category)}"
        if min_p:
            path += f"&min={urllib.parse.quote(str(min_p))}"
        if max_p:
            path += f"&max={urllib.parse.quote(str(max_p))}"

        raw = self._get(path)
        _remember_raw(path, raw)
        lines = [line.strip("\r") for line in raw.splitlines() if line.strip()]
        if not lines:
            return {"ok": False, "error": "empty response"}
        first = lines[0].split("\t")
        if first[0] != "ok":
            return {"ok": False, "error": first[1] if len(first) > 1 else raw}

        total_items = int(first[1]) if len(first) > 1 and first[1].isdigit() else 0
        cur_page    = int(first[2]) if len(first) > 2 and first[2].isdigit() else 1
        total_pages = int(first[3]) if len(first) > 3 and first[3].isdigit() else 1

        listings = []
        categories = []
        for line in lines[1:]:
            cols = line.split("\t")
            if cols[0] == "cat" and len(cols) >= 3:
                categories.append((cols[1], cols[2]))
            elif cols[0] == "L" and len(cols) >= 12:
                # Column layout confirmed from a live reply (2026-11-06, 25 cols):
                # L, listing_id, item_id, amount, refine, grade, slots,
                # total_price, unit_price, seller, flag, item_name, category, ...
                # (the old mapping was shifted by one: it read the total as the
                # unit price and the seller name as the currency).
                def num(s):
                    return int(s) if s.lstrip("-").isdigit() else 0
                listings.append({
                    "listing_id": num(cols[1]),
                    "item_id":    num(cols[2]),
                    "amount":     num(cols[3]) or 1,
                    "refine":     num(cols[4]),
                    "grade":      num(cols[5]),
                    "slots":      num(cols[6]),
                    "total_price": num(cols[7]),
                    "unit_price": num(cols[8]),
                    "seller":     cols[9],
                    "item_name":  cols[11],
                    "category":   cols[12] if len(cols) > 12 else "",
                })

        return {
            "ok": True,
            "total_items": total_items,
            "page": cur_page,
            "total_pages": total_pages,
            "categories": categories,
            "listings": listings,
        }


# Items that must ALWAYS be kept in Kafra Storage (0 1 0) and High-Priority Looted (2)
ALWAYS_KEEP_KEYWORDS = (
    "strawberry",
    "card",
    "oridecon",
    "elunium",
    "blue herb",
    "white herb",
    "old blue box",
    "old purple box",
    "old card album",
    "gift box",
    "treasure box",
    "emperium",
    "gold",
    "yggdrasil",  # Yggdrasil Berry / Seed / Leaf: valuable even with no market listings
)

# Essential player consumables that should NEVER be sold or stored from inventory
CONSUMABLE_KEEP_LINES = [
    "# --- Essential Consumables (Keep in Inventory, Never Store or Sell) ---",
    "# Account-bound novice wings: keep all of them (they cannot be stored or sold)",
    "12323 1000 0 0",
    "[Not For Sale] Novice Fly Wing 1000 0 0",
    "12324 1000 0 0",
    "Novice Butterfly Wing 1000 0 0",
    "# Other account-bound Novice items the Kafra refuses (11518 Novice Blue Potion, 11614, 23487,",
    "# 12325 Novice Magnifier, 1243 Novice Main-Gauche): keep, never store or sell",
    "11518 1000 0 0",
    "11614 1000 0 0",
    "23487 1000 0 0",
    "12325 1000 0 0",
    "1243 1000 0 0",
    "11615 1000 0 0",
    "23489 1000 0 0",
    "Butterfly Wing 10 0 0",
    "602 10 0 0",
    "Fly Wing 10 1 0",
    "601 10 1 0",
    "Red Potion 10 1 0",
    "501 10 1 0",
    "Orange Potion 50 0 0",
    "502 50 0 0",
    "Yellow Potion 50 0 0",
    "503 50 0 0",
    "White Potion 50 0 0",
    "504 50 0 0",
    "Blue Potion 10 0 0",
    "505 10 0 0",
    "Green Potion 15 0 0",
    "506 15 0 0",
    "Novice Potion 100 0 0",
    "569 100 0 0",
    "Concentration Potion 15 0 0",
    "645 15 0 0",
    "Awakening Potion 15 0 0",
    "656 15 0 0",
    "Berserk Potion 15 0 0",
    "657 15 0 0",
]


_KEEP_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in ALWAYS_KEEP_KEYWORDS) + r")s?\b")


def is_valuable_drop(r, min_zeny):
    name_lower = r["name"].lower()
    # Whole-word match, so "gold" no longer catches "Golden ..." items.
    if _KEEP_RE.search(name_lower):
        return True
    if "[" in r["name"] and "]" in r["name"]:
        # Slotted equipment
        return True
    return r["min_val"] >= min_zeny


def _ids_in_lines(lines):
    """Item IDs already set by the fixed lines, so drops never override them."""
    ids = set()
    for line in lines:
        m = re.match(r"^(\d+)\s", line)
        if m:
            ids.add(int(m.group(1)))
    return ids


def _backup(path):
    """Keep a copy of the file before it is overwritten."""
    if os.path.exists(path):
        shutil.copy2(path, path + time.strftime(".bak-%Y%m%d-%H%M%S"))


# Section owned by the ROZ Bot Control GUI (gui/rozgui/monctl.py uses the same markers).
GUI_BEGIN = "# >>> ROZ Bot Control (GUI) - managed by the GUI, edit there >>>"
GUI_END = "# <<< ROZ Bot Control (GUI) <<<"


def _keep_gui_block(path):
    """The GUI section of the current file (markers included), or [] if there is none.

    Re-appended after a rescan so the user's own pickup choices survive. It goes
    last on purpose: OpenKore keeps the last line for a key, so the GUI wins.
    """
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            old = f.read().splitlines()
    except FileNotFoundError:
        return []
    block, inside = [], False
    for line in old:
        if line.strip() == GUI_BEGIN:
            inside = True
        if inside:
            block.append(line)
            if line.strip() == GUI_END:
                break
    if not block or block[-1].strip() != GUI_END:
        if block:
            print("[!] GUI section in pickupitems.txt has no end marker; not copying it.")
        return []
    return [""] + block + [""]


def update_openkore_pickupitems(ranked_drops, min_zeny, pickupitems_path):
    """
    Updates OpenKore pickupitems.txt based on live market prices:
    - Market-valuable items (>= min_zeny, Strawberry, Cards, Ores, Slotted): 2 (High Priority immediate loot)
    - Low-value trash drops (< min_zeny): 1 (Normal loot after combat to sell to NPC)
    """
    lines = [
        "# ===========================================================================",
        f"# Auto-generated by ROZCLUB Market Scanner (Min Store Price >= {min_zeny:,} Zeny)",
        "# 2 = High Priority (Loot immediately & Store in Kafra)",
        "# 1 = Normal Priority (Loot after combat & Sell to NPC for Zeny)",
        "# ===========================================================================",
        "",
        "# --- Always High Priority ---",
        "Strawberry 2",
        "578 2",
        "Blue Herb 2",
        "510 2",
        "Oridecon 2",
        "984 2",
        "Elunium 2",
        "985 2",
        "Rough Oridecon 2",
        "756 2",
        "Rough Elunium 2",
        "757 2",
        "",
        "# --- Live Map Drops (Evaluated from RozclubMarket/1.0) ---",
    ]
    seen_ids = _ids_in_lines(lines)
    for r in ranked_drops:
        if r["id"] in seen_ids:
            continue
        seen_ids.add(r["id"])
        valuable = is_valuable_drop(r, min_zeny)
        mode = 2 if valuable else 1
        tag = "VALUABLE -> STORE" if valuable else "TRASH -> SELL NPC"
        comment = f"# [{tag}] Market Min: {r['min_str']} | Avg: {r['avg_str']} ({r['count']} listings)"
        lines.append(f"{r['id']} {mode:<3} {comment} - {r['name']}")
        lines.append(f"{r['name']} {mode}")

    lines.extend([
        "",
        "# Fallback: pick up all other drops normally",
        "all 1",
        "",
    ])
    lines.extend(_keep_gui_block(pickupitems_path))
    _backup(pickupitems_path)
    with open(pickupitems_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def update_openkore_items_control(ranked_drops, min_zeny, items_control_path):
    """
    Updates OpenKore items_control.txt based on live market prices:
    - Valuable Market Items (>= min_zeny, Strawberry, Cards, Ores): 0 1 0 (Store in Kafra, NEVER sell)
    - Low-Value Map Trash (< min_zeny): 0 0 1 (Sell to NPC when weight reaches threshold)
    - Consumables (Butterfly Wing, Fly Wing, Potions): keep in inventory (0 0)
    """
    lines = [
        "# ===========================================================================",
        f"# Auto-generated by ROZCLUB Market Scanner (Min Store Price >= {min_zeny:,} Zeny)",
        "# Syntax: <item name/ID> <keep_in_inventory> <store_in_kafra> <sell_to_npc>",
        "# ===========================================================================",
        "",
        *CONSUMABLE_KEEP_LINES,
        "",
        "# --- Always Store Valuable Items in Kafra (0 1 0) ---",
        "Strawberry 0 1 0",
        "578 0 1 0",
        "Blue Herb 0 1 0",
        "510 0 1 0",
        "White Herb 0 1 0",
        "509 0 1 0",
        "Oridecon 0 1 0",
        "984 0 1 0",
        "Rough Oridecon 0 1 0",
        "756 0 1 0",
        "Elunium 0 1 0",
        "985 0 1 0",
        "Rough Elunium 0 1 0",
        "757 0 1 0",
        "Old Blue Box 0 1 0",
        "603 0 1 0",
        "Old Purple Box 0 1 0",
        "617 0 1 0",
        "Empty Bottle 0 1 0",
        "713 0 1 0",
        "Poison Spore 0 1 0",
        "7033 0 1 0",
        "",
        "# --- Live Map Drops (Evaluated from RozclubMarket/1.0) ---",
    ]
    # Previously a hand-written list that missed 713 (Empty Bottle) and 7033
    # (Poison Spore), so those got a second, conflicting "sell" line.
    seen_ids = _ids_in_lines(lines)
    for r in ranked_drops:
        if r["id"] in seen_ids:
            continue
        seen_ids.add(r["id"])
        valuable = is_valuable_drop(r, min_zeny)
        if valuable:
            ctrl = "0 1 0"
            comment = f"# STORE IN KAFRA (Min: {r['min_str']} | Avg: {r['avg_str']} | Listings: {r['count']})"
        else:
            ctrl = "0 0 1"
            comment = f"# SELL TO NPC (Min: {r['min_str']} | Listings: {r['count']})"
        lines.append(f"{r['id']} {ctrl}   {comment} - {r['name']}")
        lines.append(f"{r['name']} {ctrl}")

    # Common field trash fallback (sell to NPC), only for items the live
    # drop list above did not already classify -- before, these came last
    # and overrode a "store" decision made from market prices.
    fallback_trash = [
        ("Jellopy", 909), ("Sticky Mucus", 938), ("Mushroom Spore", 921),
        ("Tree Root", 902), ("Resin", 907), ("Wooden Block", 1019),
        ("Pointed Scale", 906), ("Garlet", 910), ("Clover", 705),
        ("Feather", 949), ("Fluff", 914), ("Chrysalis", 915), ("Shell", 935),
        ("Red Herb", 507), ("Yellow Herb", 508), ("Green Herb", 511),
        ("Apple", 512),
    ]
    lines.extend(["", "# --- Common Field Trash Fallback (Sell to NPC: 0 0 1) ---"])
    for name, item_id in fallback_trash:
        if item_id in seen_ids:
            continue
        lines.extend([f"{name} 0 0 1", f"{item_id} 0 0 1"])
    lines.extend([
        "",
        "# Default: Store any other unknown items/cards/equips in Kafra Storage (NEVER sell)",
        "all 0 1 0",
        "",
    ])
    # Keep the ROZ Bot Control "ขาย / ฝาก" section (last, so the user's choices win).
    lines.extend(_keep_gui_block(items_control_path))
    _backup(items_control_path)
    with open(items_control_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ROZCLUB Market Scanner & Map Drop Optimizer")
    parser.add_argument("--token", default="", help="Override X-Roz-Token manually")
    parser.add_argument("--search", default="", help="Search item name on market")
    parser.add_argument("--top", action="store_true", help="Show top expensive items currently on market")
    parser.add_argument("--min-zeny", type=int, default=1000, help="Minimum Zeny value to recommend picking up")
    parser.add_argument("--apply", action="store_true", help="Automatically write optimized pickupitems.txt to OpenKore")
    args = parser.parse_args()

    state = read_live_client_state(auto_request_token=not bool(args.token))
    if state:
        print(f"[+] Connected to ragexe.exe (PID {state['pid']}, d3d9.dll @ 0x{state['d3d9_base']:08X})")
        print(f"[+] Current Map   : {state['map_name'] or '(not in map)'}")
        print(f"[+] Market Server : {state['market_url']}")
        tok = args.token or state["market_token"]
        if tok:
            print(f"[+] X-Roz-Token   : {tok[:8]}...{tok[-6:]} (len={len(tok)})")
        else:
            print("[!] X-Roz-Token   : (empty)")
        print(f"[+] Map Monsters  : {len(state['mobs'])} types -> " + ", ".join(f"{m['name']} ({m['id']})" for m in state["mobs"]))
        print(f"[+] Map Drops     : {len(state['drops'])} items")
    else:
        print("[!] ragexe.exe is not currently running; using https://market.rozclub.com")
        tok = args.token
        state = {"market_url": "https://market.rozclub.com", "mobs": [], "drops": [], "map_name": ""}

    client = RozclubMarketClient(state["market_url"], tok)

    if args.search:
        print(f"\n=== Searching Market for '{args.search}' ===")
        res = client.list_market(page=1, query=args.search, sort="cheap")
        if not res.get("ok"):
            print(f"[-] Market API Error: {res.get('error')}")
            return
        for row in res["listings"]:
            print(f"  [{row['item_id']}] {row['item_name']} x{row['amount']} -> {row['unit_price']:,} z each "
                  f"({row['total_price']:,} z total) (Seller: {row['seller']})")
        return

    if args.top or not state["drops"]:
        print("\n=== Top Expensive Zeny Listings on ROZCLUB Market ===")
        try:
            res = client.list_market(page=1, currency="zeny", sort="exp")
            if res.get("ok"):
                print(f"Total Active Zeny Listings: {res['total_items']:,} (Page {res['page']}/{res['total_pages']})")
                for row in res["listings"][:20]:
                    refine_str = f"+{row['refine']} " if row["refine"] > 0 else ""
                    slots_str = f" [{row['slots']}]" if row["slots"] > 0 else ""
                    print(f"  [{row['item_id']:<6}] {refine_str}{row['item_name']}{slots_str} x{row['amount']} -> {row['unit_price']:,} z each (Seller: {row['seller']})")
            else:
                print(f"[-] Market API Response: {res.get('error')}")
        except Exception as e:
            print(f"[-] Market API Request Error: {e}")

    if state["drops"]:
        print(f"\n=== Scanning Market Prices for {len(state['drops'])} Drops on {state['map_name']} ===")
        ranked = []
        failures = []
        for d in state["drops"]:
            try:
                pg = client.get_listing_price(d["id"], d["name"])
            except MarketAuthError as e:
                # Every other request would fail the same way: stop here.
                print(f"[-] {e}")
                if args.apply:
                    print("[!] Not updating pickupitems.txt / items_control.txt (no price data).")
                return 2
            except Exception as e:
                pg = {"ok": False, "error": str(e)}
            if not (pg and pg.get("ok")):
                failures.append((d, pg.get("error") if pg else "no response"))
            if pg and pg.get("ok"):
                ranked.append({
                    **d,
                    "min_val": pg["min_val"],
                    "avg_val": pg["avg_val"],
                    "max_val": pg["max_val"],
                    "min_str": pg["min_str"],
                    "avg_str": pg["avg_str"],
                    "count": pg["count"],
                })
            else:
                ranked.append({
                    **d,
                    "min_val": 0,
                    "avg_val": 0,
                    "max_val": 0,
                    "min_str": "-",
                    "avg_str": "-",
                    "count": 0,
                    "err": pg.get("error") if pg else "no response",
                })

        ranked.sort(key=lambda x: (x["min_val"], x["avg_val"], x["count"]), reverse=True)
        print(f"{'Item ID':<8} | {'Item Name':<28} | {'Min Price':>12} | {'Median':>12} | {'Listings':>8} | {'OpenKore Action'}")
        print("-" * 98)
        for r in ranked:
            valuable = is_valuable_drop(r, args.min_zeny)
            act = "PRIORITY LOOT (2) + STORE KAFRA" if valuable else "LOOT (1) + SELL TO NPC"
            print(f"{r['id']:<8} | {r['name'][:28]:<28} | {r['min_str']:>12} | {r['avg_str']:>12} | {r['count']:>8} | {act}")

        if failures:
            print(f"\n[!] {len(failures)}/{len(state['drops'])} price lookups failed, e.g. "
                  f"{failures[0][0]['name']} ({failures[0][0]['id']}): {failures[0][1]}")

        if args.apply and ranked and all(r["count"] == 0 for r in ranked):
            # Seen 2026-11-06: every drop came back "0 listings, avg 3", i.e. the
            # reply was not parsed as real prices. Don't rewrite the files from that.
            print("[!] Market returned no listings for any drop (reply format not understood?); "
                  "not updating pickupitems.txt / items_control.txt. Raw replies saved to:")
            print(f"    {RAW_DUMP_PATH}")
            return 4

        if args.apply and failures:
            # Before, failed lookups were treated as "price 0" and the files
            # were rewritten anyway, which marked valuable drops as NPC trash.
            print("[!] Not updating pickupitems.txt / items_control.txt because some prices are missing.")
            return 3

        if args.apply:
            control_dirs = [
                # potato7's profile (moved to bots\potato7 on 2026-11-10)
                os.path.join(POTATO7_DIR, "control"),
                os.path.join(_openkore_root(), "control"),
            ]
            for cdir in control_dirs:
                if os.path.exists(cdir):
                    try:
                        p_pickup = os.path.join(cdir, "pickupitems.txt")
                        p_ctrl   = os.path.join(cdir, "items_control.txt")
                        update_openkore_pickupitems(ranked, args.min_zeny, p_pickup)
                        update_openkore_items_control(ranked, args.min_zeny, p_ctrl)
                        print(f"[+] Updated pickupitems.txt & items_control.txt -> {cdir}")
                    except Exception as e:
                        print(f"[!] Could not update {cdir}: {e}")


if __name__ == "__main__":
    try:
        rc = main() or 0
    except MarketAuthError as e:
        print(f"[-] {e}")
        rc = 2
    finally:
        _write_raw_dump()
    sys.exit(rc)
