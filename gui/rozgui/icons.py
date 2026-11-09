"""Item icons from rozclub.com (icons/hd/<id>.webp), cached on disk.

Downloads run on one background thread; Tk images are only ever created on the
Tk thread (via `call_soon`). Widgets that asked for an icon before it arrived
are updated in place when it does, so nothing re-renders under the user.
Optional: without Pillow (needed for WebP) or network, get() just returns None.
"""
from __future__ import annotations

import functools
import io
import os
import queue
import threading
import tkinter as tk
import urllib.error
import urllib.request
from typing import Any, Callable, Final

from .errlog import log, warn_once
from .notify import SSL_CTX, UA

ICON_URL: Final[str] = 'https://rozclub.com/database/icons/hd/{id}.webp'
ICON_DIR: Final[str] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache', 'icons')
TIMEOUT: Final[float] = 15

HAVE_PIL: bool
try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except ImportError:          # icons are a nicety: run without them
    HAVE_PIL = False


class IconCache:
    def __init__(self, call_soon: Callable[[Callable[[], None]], None], size: int = 32) -> None:
        self.call_soon = call_soon
        self.size = size
        self.images: dict[int, Any] = {}             # id -> ImageTk.PhotoImage (kept alive here)
        self.missing: set[int] = set()
        self.waiting: dict[int, list[Callable[[Any], None]]] = {}
        self.queued: set[int] = set()
        self.q: queue.SimpleQueue[int] = queue.SimpleQueue()
        if HAVE_PIL:
            os.makedirs(ICON_DIR, exist_ok=True)
            threading.Thread(target=self._worker, daemon=True).start()
        else:
            log.warning('Pillow not installed: item icons disabled')

    # ------------------------------------------------------------ Tk thread
    def attach(self, widget: tk.Widget, item_id: int) -> None:
        """Show the icon on `widget` (a Label/Button) now, or as soon as it is downloaded."""
        def put(img: Any) -> None:
            if widget.winfo_exists():
                widget.configure(image=img)         # type: ignore[call-arg]
        self.request(item_id, put)

    def request(self, item_id: int, deliver: Callable[[Any], None]) -> None:
        """Call `deliver(image)` on the Tk thread now or once downloaded (never if there is none)."""
        if not HAVE_PIL or item_id <= 0 or item_id in self.missing:
            return
        img = self.images.get(item_id)
        if img is not None:
            deliver(img)
            return
        self.waiting.setdefault(item_id, []).append(deliver)
        if item_id not in self.queued:
            self.queued.add(item_id)
            self.q.put(item_id)

    def _ready(self, item_id: int, data: bytes | None) -> None:
        self.queued.discard(item_id)
        callbacks = self.waiting.pop(item_id, [])
        if data is None:
            self.missing.add(item_id)
            return
        try:
            im = Image.open(io.BytesIO(data)).convert('RGBA')
            im.thumbnail((self.size, self.size), Image.Resampling.LANCZOS)
            img = ImageTk.PhotoImage(im)
        except (OSError, ValueError) as e:
            warn_once(f'icon:{item_id}', 'icon %s unreadable: %s', item_id, e)
            self.missing.add(item_id)
            return
        self.images[item_id] = img
        for cb in callbacks:
            try:
                cb(img)
            except tk.TclError:
                continue                            # widget destroyed by a re-render meanwhile

    # -------------------------------------------------------- worker thread
    def _worker(self) -> None:
        while True:
            item_id = self.q.get()
            data = self._fetch(item_id)
            self.call_soon(functools.partial(self._ready, item_id, data))

    @staticmethod
    def _fetch(item_id: int) -> bytes | None:
        path = os.path.join(ICON_DIR, f'{item_id}.webp')
        marker = os.path.join(ICON_DIR, f'{item_id}.none')
        try:
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    return f.read()
            if os.path.exists(marker):
                return None
        except OSError as e:
            warn_once(f'iconread:{item_id}', 'icon cache read failed for %s: %s', item_id, e)
        try:
            req = urllib.request.Request(ICON_URL.format(id=item_id), headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as r:
                data: bytes = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:                       # no icon for this id: remember, don't ask again
                try:
                    open(marker, 'w').close()
                except OSError as oe:
                    warn_once(f'iconmark:{item_id}', 'cannot write %s: %s', marker, oe)
            else:
                warn_once(f'iconhttp:{e.code}', 'icon download HTTP %s (id %s)', e.code, item_id)
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            warn_once('iconnet', 'icon download failed (offline?): %s', e)
            return None
        try:
            tmp = path + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, path)
        except OSError as e:
            warn_once('iconwrite', 'cannot cache icon %s: %s', item_id, e)
        return data
