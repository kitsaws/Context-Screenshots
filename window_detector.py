"""
Detects which application and window a screenshot was taken from,
handling dual/multi-monitor setups, background games, and transparent overlays.
"""
import ctypes
from ctypes import wintypes
import re
from typing import Optional, Dict, List, Tuple
import psutil
import logging

from config import FRIENDLY_APP_NAMES, IGNORE_PROCESSES, KNOWN_OVERLAY_TITLES, OVERLAY_PROCESSES

logger = logging.getLogger("ContextScreenshots")

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

# Set DPI awareness for exact pixel matching
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000


def is_overlay_window(process_name: str, title: str, ex_style: int) -> bool:
    """
    Check if a window is an overlay or HUD (e.g. Discord Voice Overlay, GeForce Overlay, Steam Overlay).
    These windows sit on top of games/applications and should NOT be identified as the main app.
    """
    p_lower = process_name.lower().strip()
    t_lower = title.lower().strip()

    # Known overlay background executables
    if p_lower in OVERLAY_PROCESSES:
        return True

    # Discord Overlay specifically
    if p_lower == 'discord.exe' and ('overlay' in t_lower or not title):
        return True

    # Known overlay window titles
    for ot in KNOWN_OVERLAY_TITLES:
        if ot in t_lower:
            return True

    # WS_EX_TRANSPARENT explicitly indicates a click-through overlay
    if ex_style & WS_EX_TRANSPARENT:
        return True

    return False


def get_all_monitors() -> List[Tuple[int, int, int, int]]:
    """Return bounding rectangles of all physical monitors: [(left, top, right, bottom), ...]"""
    monitors = []

    def mon_cb(hmon, hdc, lprect, lparam):
        r = lprect.contents
        monitors.append((r.left, r.top, r.right, r.bottom))
        return True

    MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(mon_cb), 0)
    return monitors


def get_visible_windows() -> List[Dict]:
    """
    Enumerate all visible top-level windows in Z-order (top-to-bottom)
    across all monitors on the interactive desktop, filtering out overlays.
    """
    windows = []
    hdesk = user32.OpenDesktopW('Default', 0, False, 0x01FF)

    def inspect_hwnd(hwnd):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return

        # Check if cloaked (suspended or hidden on other virtual desktop)
        cloaked = wintypes.DWORD()
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value != 0:
            return

        # Get visual bounds without invisible dropshadows
        rect = wintypes.RECT()
        res = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
        if res != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 20 or h <= 20:
            return

        # Window text
        length = user32.GetWindowTextLengthW(hwnd)
        title = ''
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()

        # Process name
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            pname = psutil.Process(pid.value).name().lower()
        except Exception:
            pname = 'unknown'

        if pname in IGNORE_PROCESSES:
            return

        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

        # Skip transparent overlays (Discord overlay, Steam overlay, etc.)
        if is_overlay_window(pname, title, ex_style):
            return

        # Extended window style: skip small tooltips without titles
        if not title and (ex_style & WS_EX_TOOLWINDOW):
            return

        windows.append({
            'hwnd': hwnd,
            'title': title,
            'process_name': pname,
            'rect': (rect.left, rect.top, rect.right, rect.bottom),
            'w': w,
            'h': h
        })

    if hdesk:
        DESKTOPENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, lparam):
            inspect_hwnd(hwnd)
            return True
        user32.EnumDesktopWindows(hdesk, DESKTOPENUMPROC(enum_cb), 0)
        user32.CloseDesktop(hdesk)
    else:
        # Fallback to standard EnumWindows
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, lparam):
            inspect_hwnd(hwnd)
            return True
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    return windows


def compute_overlap_area(rect1: Tuple[int, int, int, int], rect2: Tuple[int, int, int, int]) -> int:
    """Calculate intersection area between two rectangles (left, top, right, bottom)."""
    x_left = max(rect1[0], rect2[0])
    y_top = max(rect1[1], rect2[1])
    x_right = min(rect1[2], rect2[2])
    y_bottom = min(rect1[3], rect2[3])

    if x_right <= x_left or y_bottom <= y_top:
        return 0
    return (x_right - x_left) * (y_bottom - y_top)


def clean_window_title(title: str, app_name: str) -> str:
    """
    Sanitize and clean window title for safe filename use:
    - Removes notification numbers e.g. (1), (99+)
    - Strips redundant app suffixes
    - Replaces forbidden filesystem characters
    - Strips emojis to avoid Windows charmap encoding errors
    - Truncates to safe length
    """
    if not title:
        return ""

    # Strip leading notifications e.g. (1) or [5]
    cleaned = re.sub(r'^[\(\[]\s*[\d\+,\.]+\s*[\)\]]\s*', '', title).strip()

    # Strip redundant suffixes
    suffixes = [
        f" - {app_name}",
        " - Google Chrome",
        " - Brave",
        " - Microsoft Edge",
        " - Mozilla Firefox",
        " - Visual Studio Code",
        " - Antigravity IDE",
    ]
    for suf in suffixes:
        if cleaned.lower().endswith(suf.lower()):
            cleaned = cleaned[:-len(suf)].strip()
            break

    # Replace invalid Windows filename characters: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/*?:"<>|]', '-', cleaned)
    # Strip emojis and non-ASCII characters to prevent Windows console/filesystem charmap errors
    cleaned = re.sub(r'[^\x20-\x7E]+', ' ', cleaned)
    # Collapse consecutive spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -.')

    # Max 65 characters to stay safely within MAX_PATH
    return cleaned[:65].strip()


def get_friendly_app_name(process_name: str) -> str:
    """Map executable name to clean friendly name (e.g. brave.exe -> Brave)."""
    p_lower = process_name.lower()
    if p_lower in FRIENDLY_APP_NAMES:
        return FRIENDLY_APP_NAMES[p_lower]

    name_without_ext = p_lower[:-4] if p_lower.endswith('.exe') else p_lower
    return name_without_ext.capitalize()


def identify_window_from_snip(
    snip_rect: Optional[Tuple[int, int, int, int]] = None,
    click_pt: Optional[Tuple[int, int]] = None,
    image_size: Optional[Tuple[int, int]] = None,
    last_active_window: Optional[Dict] = None
) -> Tuple[str, str]:
    """
    Determine the application name and clean window title for a screenshot.
    Uses a 3-tier strategy:
    1. Active foreground window (if snip falls inside it, prevents background games/windows from stealing).
    2. Overlap geometry across visible windows (skipping transparent overlays like Discord Overlay).
    3. Fallback to active window or prominent desktop window.
    """
    windows = get_visible_windows()

    # ---------------------------------------------------------
    # Tier 1: Check Last Active Foreground Window
    # If the user was focused on Chrome, and the snip falls inside Chrome,
    # Chrome wins immediately, regardless of background games like Genshin!
    # ---------------------------------------------------------
    if last_active_window and last_active_window.get('rect'):
        active_rect = last_active_window['rect']
        pname = last_active_window.get('process_name', '')
        title = last_active_window.get('title', '')

        if pname not in {'explorer.exe', 'unknown'} and not is_overlay_window(pname, title, 0):
            # Check rectangular snip inside active window
            if snip_rect:
                snip_w = snip_rect[2] - snip_rect[0]
                snip_h = snip_rect[3] - snip_rect[1]
                snip_area = max(1, snip_w * snip_h)
                overlap = compute_overlap_area(active_rect, snip_rect)
                overlap_ratio = overlap / snip_area

                # If >= 55% of the snip was taken inside the active window
                if overlap_ratio >= 0.55:
                    app_name = get_friendly_app_name(pname)
                    clean_title = clean_window_title(title, app_name)
                    logger.info(f"Target identified via Active Foreground Window: {app_name} ({clean_title}) [overlap={overlap_ratio:.2f}]")
                    return app_name, clean_title

            # Check click point inside active window (Window Snip Mode)
            if click_pt:
                cx, cy = click_pt
                if active_rect[0] <= cx <= active_rect[2] and active_rect[1] <= cy <= active_rect[3]:
                    app_name = get_friendly_app_name(pname)
                    clean_title = clean_window_title(title, app_name)
                    logger.info(f"Target identified via Click inside Active Window: {app_name} ({clean_title})")
                    return app_name, clean_title

            # Check fullscreen snip matching active window monitor
            if image_size:
                img_w, img_h = image_size
                monitors = get_all_monitors()
                for mon in monitors:
                    mw = mon[2] - mon[0]
                    mh = mon[3] - mon[1]
                    if abs(mw - img_w) <= 4 and abs(mh - img_h) <= 4:
                        if compute_overlap_area(active_rect, mon) > 0:
                            app_name = get_friendly_app_name(pname)
                            clean_title = clean_window_title(title, app_name)
                            logger.info(f"Target identified via Fullscreen Active Window: {app_name} ({clean_title})")
                            return app_name, clean_title

    # ---------------------------------------------------------
    # Tier 2: Spatial Overlap across Visible Windows (Overlays Skipped)
    # Triggered if snip was on another screen (dual monitors) or outside active window.
    # ---------------------------------------------------------
    if snip_rect:
        snip_w = snip_rect[2] - snip_rect[0]
        snip_h = snip_rect[3] - snip_rect[1]
        snip_area = max(1, snip_w * snip_h)

        best_window = None
        max_overlap = 0

        for win in windows:
            overlap = compute_overlap_area(win['rect'], snip_rect)
            if overlap > 0:
                overlap_ratio = overlap / snip_area
                # If this window covers the majority of the snip (> 45%) and is top-most in Z-order
                if overlap_ratio >= 0.45:
                    best_window = win
                    break
                elif overlap > max_overlap:
                    max_overlap = overlap
                    best_window = win

        if best_window and best_window['process_name'] != 'explorer.exe':
            app_name = get_friendly_app_name(best_window['process_name'])
            clean_title = clean_window_title(best_window['title'], app_name)
            logger.info(f"Target identified via Geometric Overlap: {app_name} ({clean_title})")
            return app_name, clean_title

    # Match via click coordinate (Window Snip Mode on background/other screen)
    if click_pt:
        cx, cy = click_pt
        for win in windows:
            r = win['rect']
            if r[0] <= cx <= r[2] and r[1] <= cy <= r[3]:
                if win['process_name'] != 'explorer.exe' or win['title'] != 'Program Manager':
                    app_name = get_friendly_app_name(win['process_name'])
                    clean_title = clean_window_title(win['title'], app_name)
                    logger.info(f"Target identified via Click Point: {app_name} ({clean_title})")
                    return app_name, clean_title

    # Match via Fullscreen Snip
    if image_size:
        img_w, img_h = image_size
        monitors = get_all_monitors()
        matching_monitor = None
        for mon in monitors:
            mw = mon[2] - mon[0]
            mh = mon[3] - mon[1]
            if abs(mw - img_w) <= 4 and abs(mh - img_h) <= 4:
                matching_monitor = mon
                break

        if matching_monitor:
            for win in windows:
                if compute_overlap_area(win['rect'], matching_monitor) > 0:
                    if win['process_name'] != 'explorer.exe':
                        app_name = get_friendly_app_name(win['process_name'])
                        clean_title = clean_window_title(win['title'], app_name)
                        logger.info(f"Target identified via Fullscreen Monitor: {app_name} ({clean_title})")
                        return app_name, clean_title

    # ---------------------------------------------------------
    # Tier 3: Fallback
    # ---------------------------------------------------------
    if last_active_window and last_active_window.get('process_name') not in {'explorer.exe', 'unknown', ''}:
        app_name = get_friendly_app_name(last_active_window['process_name'])
        clean_title = clean_window_title(last_active_window.get('title', ''), app_name)
        logger.info(f"Target identified via Fallback Active Window: {app_name} ({clean_title})")
        return app_name, clean_title

    for win in windows:
        if win['process_name'] not in {'explorer.exe', 'unknown'} and win['title']:
            app_name = get_friendly_app_name(win['process_name'])
            clean_title = clean_window_title(win['title'], app_name)
            logger.info(f"Target identified via Topmost Visible Window: {app_name} ({clean_title})")
            return app_name, clean_title

    return "General", ""
