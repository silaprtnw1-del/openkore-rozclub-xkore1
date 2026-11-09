"""ROZ Bot Control - double-click Start-GUI.cmd (or run: pythonw gui\\roz_gui.pyw)."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CRASH_LOG: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gui-crash.log')


def _report_crash() -> None:
    """pythonw has no console: write the traceback to a file and tell the user where it is."""
    try:
        with open(CRASH_LOG, 'w', encoding='utf-8') as f:
            traceback.print_exc(file=f)
    except OSError:
        traceback.print_exc()       # last resort; stderr may be None under pythonw
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f'ROZ Bot Control เปิดไม่สำเร็จ\nดูรายละเอียดที่:\n{CRASH_LOG}',
                                         'ROZ Bot Control', 0x10)
    except (ImportError, AttributeError, OSError):
        traceback.print_exc()       # the crash itself is already in CRASH_LOG


try:
    from rozgui.app import main
    main()
except Exception:
    _report_crash()
