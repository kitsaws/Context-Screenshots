"""
Context-Aware Screenshots - Application Entrypoint & System Tray App

Designed to run either as a standalone system tray app (default when double-clicked)
or as a command-line utility.
"""
import sys
import os
import time
import queue
import ctypes
import threading
from pathlib import Path
import subprocess
import logging
from PIL import Image

import pystray
from pystray import MenuItem as item

from config import (
    resolve_screenshots_folders,
    get_custom_output_dir,
    set_custom_output_dir,
)
from mouse_tracker import MouseTracker
from organizer import ScreenshotOrganizer, get_writable_dest_root

# Base paths
if getattr(sys, 'frozen', False):
    # Running inside PyInstaller bundled exe
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent

LOG_FILE = BASE_DIR / "context_screenshots.log"
ICON_PATH = BASE_DIR / "icon.ico"
MUTEX_NAME = "Local\\ContextScreenshotsSingleInstanceMutex"

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def setup_logging():
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        encoding='utf-8'
    )


def acquire_mutex():
    """Ensure only one instance runs at a time."""
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return mutex


def get_startup_shortcut_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "ContextScreenshots.vbs"


def is_startup_enabled() -> bool:
    return get_startup_shortcut_path().exists()


def toggle_startup(icon, item):
    shortcut = get_startup_shortcut_path()
    if shortcut.exists():
        try:
            shortcut.unlink()
            if hasattr(icon, 'notify'):
                icon.notify("Removed from Windows Startup.", "Context Screenshots")
        except Exception as e:
            logging.error(f"Failed to remove startup: {e}")
    else:
        try:
            exe_path = sys.executable if getattr(sys, 'frozen', False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
            vbs_content = f'Set WshShell = CreateObject("WScript.Shell")\nWshShell.Run """{exe_path}""", 0, False\n'
            shortcut.write_text(vbs_content, encoding='utf-8')
            if hasattr(icon, 'notify'):
                icon.notify("Added to Windows Startup. It will launch on boot.", "Context Screenshots")
        except Exception as e:
            logging.error(f"Failed to add startup: {e}")


_picker_req_queue: queue.Queue = queue.Queue()
_picker_thread: threading.Thread | None = None
_picker_init_lock = threading.Lock()
_picker_busy_lock = threading.Lock()


def _sh_browse_for_folder(title: str) -> str | None:
    """Fallback Windows folder browser via Shell API if tkinter is unavailable."""
    try:
        from win32com.shell import shell, shellcon
        pidl, _, _ = shell.SHBrowseForFolder(
            0, None, title, shellcon.BIF_RETURNONLYFSDIRS | shellcon.BIF_NEWDIALOGSTYLE
        )
        if pidl:
            path_fn = getattr(shell, "SHGetPathFromIDListW", shell.SHGetPathFromIDList)
            result = path_fn(pidl)
            if isinstance(result, bytes):
                return result.decode("utf-8", errors="ignore")
            return result or None
    except Exception as exc:
        logging.error(f"SHBrowseForFolder fallback failed: {exc}")
    return None


def _folder_picker_loop():
    """Dedicated single-thread Tcl/Tk apartment for Windows native folder picker."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
    except Exception as exc:
        logging.warning(f"Failed to initialize tkinter folder picker: {exc}")
        root = None
        filedialog = None

    while True:
        initial_dir, title, reply_q = _picker_req_queue.get()
        if root is None or filedialog is None:
            reply_q.put(_sh_browse_for_folder(title))
            continue
        try:
            root.lift()
            root.focus_force()
            selected = filedialog.askdirectory(
                parent=root,
                initialdir=initial_dir,
                title=title,
                mustexist=True,
            )
            root.update_idletasks()
            reply_q.put(selected or None)
        except Exception as exc:
            logging.warning(f"tkinter folder picker failed, trying Shell fallback: {exc}")
            reply_q.put(_sh_browse_for_folder(title))


def pick_directory(initial_dir: str, title: str) -> str | None:
    """Open a folder selection dialog on the persistent UI worker thread."""
    global _picker_thread
    if not _picker_busy_lock.acquire(blocking=False):
        return None
    try:
        with _picker_init_lock:
            if _picker_thread is None or not _picker_thread.is_alive():
                _picker_thread = threading.Thread(
                    target=_folder_picker_loop,
                    name="FolderPickerThread",
                    daemon=True,
                )
                _picker_thread.start()

        reply_q: queue.Queue = queue.Queue(maxsize=1)
        _picker_req_queue.put((initial_dir, title, reply_q))
        return reply_q.get()
    finally:
        _picker_busy_lock.release()


def get_active_output_dir(folders: list[Path] | None = None) -> Path:
    """Return the active root folder where organized screenshots are saved."""
    custom = get_custom_output_dir()
    if custom:
        try:
            custom.mkdir(parents=True, exist_ok=True)
            return custom
        except Exception:
            pass
    watch_folders = folders if folders is not None else resolve_screenshots_folders()
    if watch_folders:
        return get_writable_dest_root(watch_folders[0])
    return Path.home() / "Pictures" / "Screenshots"


def open_screenshots_folder(icon, item, folders=None):
    dest = get_active_output_dir(folders)
    os.startfile(str(dest))


def open_log_file(icon, item):
    if LOG_FILE.exists():
        os.startfile(str(LOG_FILE))


def load_icon_image():
    if ICON_PATH.exists():
        try:
            return Image.open(ICON_PATH)
        except Exception:
            pass

    # Fallback generated icon
    from PIL import ImageDraw
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((6, 16, 58, 54), radius=8, fill=(33, 150, 243, 255))
    draw.rectangle((22, 10, 42, 16), fill=(25, 118, 210, 255))
    draw.ellipse((20, 22, 44, 46), fill=(255, 255, 255, 255))
    draw.ellipse((24, 26, 40, 42), fill=(33, 150, 243, 255))
    return img


def run_tray_app():
    setup_logging()
    logger = logging.getLogger("ContextScreenshots")
    logger.info("Application starting...")

    # Single instance check
    mutex = acquire_mutex()
    if not mutex:
        user32.MessageBoxW(
            0,
            "Context Screenshots is already running in your system tray (near the clock).",
            "Context Screenshots",
            0x40  # MB_ICONINFORMATION
        )
        sys.exit(0)

    # Initialize tracker and organizer
    folders = resolve_screenshots_folders()
    tracker = MouseTracker()
    organizer = ScreenshotOrganizer(folders, tracker)
    organizer.start()

    logger.info("Background organizer started successfully.")

    # Tray menu
    icon_img = load_icon_image()

    def on_change_save_folder(icon, item):
        try:
            current_dir = get_active_output_dir(folders)
            selected = pick_directory(
                initial_dir=str(current_dir),
                title="Select Root Folder for Organized Screenshots",
            )
            if not selected:
                return
            saved = set_custom_output_dir(selected)
            organizer.reload_dest_root()
            if hasattr(icon, 'update_menu'):
                icon.update_menu()
            logger.info(f"Save folder changed to: {saved}")
            if hasattr(icon, 'notify'):
                icon.notify(
                    f"Screenshots will now be saved to:\n{saved}",
                    "Save Folder Updated"
                )
        except Exception as exc:
            logger.error(f"Failed to change save folder: {exc}")
            if hasattr(icon, 'notify'):
                icon.notify(f"Could not set folder: {exc}", "Context Screenshots Error")

    def on_reset_save_folder(icon, item):
        try:
            set_custom_output_dir(None)
            updated = organizer.reload_dest_root()
            default_dest = updated[0] if updated else get_active_output_dir(folders)
            if hasattr(icon, 'update_menu'):
                icon.update_menu()
            logger.info(f"Save folder reset to default: {default_dest}")
            if hasattr(icon, 'notify'):
                icon.notify(
                    f"Save folder reset to default:\n{default_dest}",
                    "Save Folder Reset"
                )
        except Exception as exc:
            logger.error(f"Failed to reset save folder: {exc}")

    def on_exit(icon, item):
        logger.info("Exiting application...")
        organizer.stop()
        icon.stop()
        if mutex:
            kernel32.CloseHandle(mutex)

    menu = pystray.Menu(
        item('📁 Open Screenshots Folder', lambda ic, it: open_screenshots_folder(ic, it, folders), default=True),
        item('📂 Change Save Folder...', on_change_save_folder),
        item(
            '🔄 Reset Save Folder to Default',
            on_reset_save_folder,
            enabled=lambda it: get_custom_output_dir() is not None,
        ),
        pystray.Menu.SEPARATOR,
        item('🚀 Run on Windows Startup', toggle_startup, checked=lambda it: is_startup_enabled()),
        item('📄 View Logs', open_log_file),
        pystray.Menu.SEPARATOR,
        item('❌ Exit', on_exit)
    )

    icon = pystray.Icon(
        "ContextScreenshots",
        icon_img,
        "Context-Aware Screenshots (Running)",
        menu=menu
    )

    # Show balloon notification on first launch
    def show_launch_toast():
        time.sleep(0.5)
        try:
            if hasattr(icon, 'notify'):
                icon.notify(
                    "Context Screenshots is running.\nSnips (Win+Shift+S) will be organized automatically.",
                    "Context Screenshots Active"
                )
        except Exception:
            pass

    toast_thread = threading.Thread(target=show_launch_toast, daemon=True)
    toast_thread.start()

    try:
        # icon.run() blocks and pumps Windows messages for the tray icon
        icon.run()
    finally:
        organizer.stop()
        if mutex:
            kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    run_tray_app()

