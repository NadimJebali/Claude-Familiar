"""Windows system-tray icon + menu (pure ctypes, no dependencies).

Tkinter has no native tray support, so this talks to Win32 directly: it registers
a window class with our own ``WndProc``, creates a hidden top-level window to own
the icon, and adds a notification-area icon via ``Shell_NotifyIconW``. Clicks on
the icon arrive as our ``WM_TRAYICON`` message; left-click toggles the cards,
right-click pops a small menu.

Everything runs on the Tk thread: Tk's own Windows message loop (the one
``mainloop`` is already pumping) dispatches messages to *our* window's WndProc
too, so no separate message pump is needed — and menu callbacks therefore run on
the Tk thread and may touch Tk safely.

This module is Windows-only and is imported lazily, only when
``osplatform.IS_WINDOWS`` (Linux/macOS have no tray here — see the README).

CRITICAL: the WndProc, WNDCLASS and NOTIFYICONDATA Python objects are held as
instance attributes. If the WndProc callback object were garbage-collected while
Windows still held a pointer to it, the next dispatched message would crash.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from . import icon

# --- Win32 constants -------------------------------------------------------
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1          # our private callback message for the icon
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205

NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
IDI_APPLICATION = 32512

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_RETURNCMD = 0x0100           # TrackPopupMenu returns the chosen id directly
TPM_RIGHTBUTTON = 0x0002

# Menu command ids (any nonzero distinct ints).
_ID_TOGGLE = 1
_ID_SETTINGS = 2
_ID_QUIT = 3
_ID_PET = 4

LRESULT = ctypes.c_ssize_t
WNDPROCTYPE = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

_user32 = ctypes.windll.user32
_shell32 = ctypes.windll.shell32
_kernel32 = ctypes.windll.kernel32


# --- Win32 structures ------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    """The full modern ``NOTIFYICONDATAW``; ``cbSize`` is set to ``sizeof(self)``
    so Windows accepts the current version on Vista+."""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROCTYPE),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def _configure_signatures() -> None:
    """Set restype/argtypes so pointers aren't truncated on 64-bit Windows."""
    _user32.DefWindowProcW.restype = LRESULT
    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    _user32.RegisterClassW.restype = wintypes.ATOM
    _user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    _user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    _user32.DestroyWindow.argtypes = [wintypes.HWND]
    _user32.LoadImageW.restype = wintypes.HANDLE
    _user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                   wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                   wintypes.UINT]
    _user32.LoadIconW.restype = wintypes.HICON
    _user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    _user32.CreatePopupMenu.restype = wintypes.HMENU
    _user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT,
                                    ctypes.c_size_t, wintypes.LPCWSTR]
    _user32.TrackPopupMenu.restype = ctypes.c_int
    _user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       wintypes.HWND, wintypes.LPVOID]
    _user32.DestroyMenu.argtypes = [wintypes.HMENU]
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM]
    _shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    _shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                           ctypes.POINTER(NOTIFYICONDATAW)]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


_configure_signatures()


def _make_int_resource(value: int) -> wintypes.LPCWSTR:
    """``MAKEINTRESOURCE``: pass a small integer where an LPCWSTR is expected."""
    return ctypes.cast(ctypes.c_void_p(value), wintypes.LPCWSTR)


class SystemTray:
    """A notification-area icon with a small popup menu.

    Callbacks (any may be omitted) run on the Tk thread:
      * ``on_toggle``   — left-click, or the "Show / hide cards" item
      * ``on_pet``      — the "Pet…" item
      * ``on_settings`` — the "Settings…" item
      * ``on_quit``     — the "Quit" item
    """

    def __init__(self, tooltip: str = "Claude Familiar", *,
                 on_toggle=None, on_pet=None, on_settings=None, on_quit=None) -> None:
        # Set sentinels first so dispose() is safe even if construction fails.
        self._hwnd = None
        self._nid = None
        self._added = False
        self._class_atom = 0

        self._on_toggle = on_toggle or (lambda: None)
        self._on_pet = on_pet or (lambda: None)
        self._on_settings = on_settings or (lambda: None)
        self._on_quit = on_quit or (lambda: None)

        self._hinstance = _kernel32.GetModuleHandleW(None)
        # Unique per process so re-creating in one process can't clash with a
        # still-registered class from a previous instance.
        self._class_name = f"ClaudeFamiliarTray_{os.getpid()}"

        # Hold these Python objects alive for the icon's lifetime (see module doc).
        self._wndproc = WNDPROCTYPE(self._handle_message)
        self._wndclass = WNDCLASS()
        self._wndclass.lpfnWndProc = self._wndproc
        self._wndclass.hInstance = self._hinstance
        self._wndclass.lpszClassName = self._class_name

        self._class_atom = _user32.RegisterClassW(ctypes.byref(self._wndclass))
        # A 0 atom usually means the class already exists; CreateWindowExW by name
        # still works in that case, so don't hard-fail here.

        self._hwnd = _user32.CreateWindowExW(
            0, self._class_name, "Claude Familiar", 0,
            0, 0, 0, 0, None, None, self._hinstance, None,
        )
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        self._nid = NOTIFYICONDATAW()
        self._nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self._nid.hWnd = self._hwnd
        self._nid.uID = 1
        self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self._nid.uCallbackMessage = WM_TRAYICON
        self._nid.hIcon = self._load_icon()
        self._nid.szTip = tooltip

        if not _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid)):
            self.dispose()
            raise ctypes.WinError(ctypes.get_last_error())
        self._added = True

    # --- icon -------------------------------------------------------------
    def _load_icon(self):
        """The mascot .ico (generated on demand), falling back to the stock app
        icon so the tray always has *something* to show."""
        path = icon.ICON_PATH
        if not path.exists():
            try:
                icon.ensure_ico()
            except OSError:
                pass
        handle = 0
        if path.exists():
            handle = _user32.LoadImageW(
                None, str(path), IMAGE_ICON, 0, 0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
        if not handle:
            handle = _user32.LoadIconW(None, _make_int_resource(IDI_APPLICATION))
        return handle

    # --- message handling -------------------------------------------------
    def _handle_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            event = lparam & 0xFFFF      # low word carries the mouse message
            if event == WM_LBUTTONUP:
                self._safe(self._on_toggle)
            elif event == WM_RBUTTONUP:
                self._show_menu()
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self) -> None:
        """Build and track the popup; with TPM_RETURNCMD it returns the chosen id
        directly, so there's no WM_COMMAND to handle."""
        menu = _user32.CreatePopupMenu()
        if not menu:
            return
        _user32.AppendMenuW(menu, MF_STRING, _ID_PET, "Pet…")
        _user32.AppendMenuW(menu, MF_STRING, _ID_TOGGLE, "Show / hide cards")
        _user32.AppendMenuW(menu, MF_STRING, _ID_SETTINGS, "Settings…")
        _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        _user32.AppendMenuW(menu, MF_STRING, _ID_QUIT, "Quit")

        pt = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        # Standard dance so the menu dismisses correctly when clicked elsewhere.
        _user32.SetForegroundWindow(self._hwnd)
        cmd = _user32.TrackPopupMenu(
            menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, 0, self._hwnd, None
        )
        _user32.PostMessageW(self._hwnd, 0, 0, 0)
        _user32.DestroyMenu(menu)

        if cmd == _ID_PET:
            self._safe(self._on_pet)
        elif cmd == _ID_TOGGLE:
            self._safe(self._on_toggle)
        elif cmd == _ID_SETTINGS:
            self._safe(self._on_settings)
        elif cmd == _ID_QUIT:
            self._safe(self._on_quit)

    @staticmethod
    def _safe(callback) -> None:
        """Never let a callback error escape into the Win32 message dispatch."""
        try:
            callback()
        except Exception as exc:  # noqa: BLE001 — a tray click must not crash Tk
            print("[mascot] tray callback error:", exc)

    # --- teardown ---------------------------------------------------------
    def dispose(self) -> None:
        """Remove the icon and free the window/class. Idempotent."""
        if self._added and self._nid is not None:
            try:
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            except Exception:
                pass
            self._added = False
        if self._hwnd:
            try:
                _user32.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None
        if self._class_name:
            try:
                _user32.UnregisterClassW(self._class_name, self._hinstance)
            except Exception:
                pass
            self._class_name = ""
