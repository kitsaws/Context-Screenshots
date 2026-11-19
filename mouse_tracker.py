"""
Mouse drag and click tracking across multi-monitor setups,
with real-time active foreground window tracking.
"""
import time
import threading
from collections import deque
import ctypes
from ctypes import wintypes
import psutil
from pynput import mouse

from config import SNIP_HOST_PROCESSES
from window_detector import get_process_name_for_hwnd, is_overlay_window

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

# Ensure per-monitor DPI awareness so mouse coordinates match physical screen pixels
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

DWMWA_EXTENDED_FRAME_BOUNDS = 9


class MouseTracker:
    def __init__(self, max_history: int = 30):
        self.max_history = max_history
        self.drags = deque(maxlen=max_history)
        self.clicks = deque(maxlen=max_history)
        self._press_point = None
        self._press_time = 0.0
        self._lock = threading.Lock()
        self._listener = None
        self._running = False
        self._fg_thread = None
        self.last_active_window = None

    def start(self):
        """Start listening for mouse drag/click events and foreground window tracking."""
        self._running = True
        if self._listener is None or not self._listener.is_alive():
            self._listener = mouse.Listener(on_click=self._on_click)
            self._listener.daemon = True
            self._listener.start()

        if self._fg_thread is None or not self._fg_thread.is_alive():
            self._fg_thread = threading.Thread(target=self._track_foreground_loop, daemon=True)
            self._fg_thread.start()

    def stop(self):
        """Stop listening for mouse events and tracking."""
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def _track_foreground_loop(self):
        """
        Continuously record the user's active foreground window.
        When Snipping Tool opens (ScreenClippingHost), we DO NOT overwrite the
        last active window, so we remember what the user was actually using!
        """
        while self._running:
            try:
                hwnd = user32.GetForegroundWindow()
                if hwnd and user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd):
                    pname, _ = get_process_name_for_hwnd(hwnd)

                    # If the foreground window is Snipping Tool / Shell overlay, DO NOT overwrite!
                    if pname and pname not in SNIP_HOST_PROCESSES:
                        length = user32.GetWindowTextLengthW(hwnd)
                        title = ""
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buff, length + 1)
                            title = buff.value.strip()

                        ex_style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
                        if not is_overlay_window(pname, title, ex_style):
                            rect = wintypes.RECT()
                            res = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
                            if res != 0:
                                user32.GetWindowRect(hwnd, ctypes.byref(rect))

                            w = rect.right - rect.left
                            h = rect.bottom - rect.top
                            if w > 50 and h > 50:
                                with self._lock:
                                    self.last_active_window = {
                                        'hwnd': hwnd,
                                        'process_name': pname,
                                        'title': title,
                                        'rect': (rect.left, rect.top, rect.right, rect.bottom),
                                        'time': time.time()
                                    }
            except Exception:
                pass
            time.sleep(0.12)

    def get_last_active_window(self):
        """Return the most recent active application window before snipping."""
        with self._lock:
            if self.last_active_window:
                return dict(self.last_active_window)
        return None

    def _on_click(self, x: int, y: int, button, pressed: bool):
        if button != mouse.Button.left:
            return

        now = time.time()
        with self._lock:
            if pressed:
                self._press_point = (x, y)
                self._press_time = now
            else:
                if self._press_point is not None:
                    x1, y1 = self._press_point
                    x2, y2 = x, y
                    w = abs(x2 - x1)
                    h = abs(y2 - y1)
                    rect = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

                    if w > 10 and h > 10:
                        self.drags.append({
                            'rect': rect,
                            'w': w,
                            'h': h,
                            'time': now,
                            'duration': now - self._press_time
                        })
                    else:
                        self.clicks.append({
                            'pt': (x2, y2),
                            'time': now
                        })
                    self._press_point = None

    def find_matching_drag(self, target_w: int, target_h: int, tolerance: int = 12, max_age: float = 8.0):
        """
        Match a saved screenshot's dimensions (target_w, target_h) to a recent mouse drag rectangle.
        Returns None if no drag matches the image size (never falls back to an unrelated drag).
        """
        now = time.time()
        with self._lock:
            candidates = []
            for d in reversed(self.drags):
                age = now - d['time']
                if age <= max_age:
                    dw = abs(d['w'] - target_w)
                    dh = abs(d['h'] - target_h)
                    if dw <= tolerance and dh <= tolerance:
                        candidates.append((dw + dh, d))

            if candidates:
                candidates.sort(key=lambda item: item[0])
                return candidates[0][1]

            # Scaling factor checks: DPI scaling (e.g. 1.25x, 1.5x, 1.75x, 2.0x, 0.8x, 0.67x)
            for scale in [1.25, 1.5, 1.75, 2.0, 0.8, 0.67]:
                scaled_w = int(target_w / scale)
                scaled_h = int(target_h / scale)
                for d in reversed(self.drags):
                    if (now - d['time']) <= max_age:
                        dw = abs(d['w'] - scaled_w)
                        dh = abs(d['h'] - scaled_h)
                        if dw <= tolerance and dh <= tolerance:
                            return d

        return None

    def get_recent_click(self, max_age: float = 3.5):
        """Return the most recent single click point within max_age seconds."""
        now = time.time()
        with self._lock:
            for c in reversed(self.clicks):
                if (now - c['time']) <= max_age:
                    return c
        return None
        with self._lock:
            for c in reversed(self.clicks):
                if (now - c['time']) <= max_age:
                    return c
        return None
