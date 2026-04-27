from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback) -> None:
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type != b"windows_generic_MSG":
            return False, 0
        msg = MSG.from_address(int(message))
        if msg.message == WM_HOTKEY:
            self.callback()
            return True, 0
        return False, 0


class GlobalHotkeyManager(QObject):
    triggered = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkey_id = 1
        self._registered = False
        self._filter = _HotkeyFilter(self.triggered.emit)

    def register(self, hotkey_text: str) -> None:
        self.unregister()
        modifiers, key_code = self._parse_hotkey(hotkey_text)
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication 尚未初始化。")
        app.installNativeEventFilter(self._filter)
        if not ctypes.windll.user32.RegisterHotKey(None, self._hotkey_id, modifiers, key_code):
            raise RuntimeError(f"无法注册全局热键：{hotkey_text}")
        self._registered = True

    def unregister(self) -> None:
        if self._registered:
            ctypes.windll.user32.UnregisterHotKey(None, self._hotkey_id)
            app = QApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._filter)
            self._registered = False

    @staticmethod
    def _parse_hotkey(hotkey_text: str) -> tuple[int, int]:
        modifiers = 0
        key_code = None
        special_keys = {
            "space": 0x20,
            "tab": 0x09,
            "esc": 0x1B,
            "escape": 0x1B,
            "enter": 0x0D,
            "return": 0x0D,
            "insert": 0x2D,
            "delete": 0x2E,
            "del": 0x2E,
            "home": 0x24,
            "end": 0x23,
            "pageup": 0x21,
            "pgup": 0x21,
            "pagedown": 0x22,
            "pgdn": 0x22,
            "left": 0x25,
            "up": 0x26,
            "right": 0x27,
            "down": 0x28,
        }
        for part in (segment.strip().lower() for segment in hotkey_text.split("+")):
            if part in {"ctrl", "control"}:
                modifiers |= MOD_CONTROL
            elif part == "shift":
                modifiers |= MOD_SHIFT
            elif part == "alt":
                modifiers |= MOD_ALT
            elif part in {"win", "meta"}:
                modifiers |= MOD_WIN
            elif len(part) == 1 and part.isalpha():
                key_code = ord(part.upper())
            elif len(part) == 1 and part.isdigit():
                key_code = ord(part)
            elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 12:
                key_code = 0x70 + int(part[1:]) - 1
            elif part in special_keys:
                key_code = special_keys[part]
            else:
                key_enum = getattr(Qt.Key, f"Key_{part.upper()}", None)
                if key_enum is not None:
                    key_code = int(key_enum)
        if key_code is None:
            raise ValueError(f"不支持的热键：{hotkey_text}")
        return modifiers, key_code
