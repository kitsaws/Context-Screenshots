"""
Watches for new screenshots from Snipping Tool, detects their source window,
and organizes them into application-specific subfolders.
"""
import os
import stat
import time
import shutil
import logging
import threading
from pathlib import Path
from typing import Optional
from PIL import Image
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from mouse_tracker import MouseTracker
from window_detector import identify_window_from_snip
from config import FILE_READY_TIMEOUT_SEC, ORGANIZED_DESTINATION_DIR, get_custom_output_dir

logger = logging.getLogger("ContextScreenshots")


def get_writable_dest_root(preferred_dir: Path) -> Path:
    """
    Determine the destination root directory for organized screenshot subfolders.
    Prefers user-configured output directory, then preferred_dir (when writable),
    then local Windows Pictures fallbacks.
    """
    custom_dir = get_custom_output_dir()
    if custom_dir:
        try:
            custom_dir.mkdir(parents=True, exist_ok=True)
            return custom_dir
        except Exception as exc:
            logger.warning(f"Custom output directory '{custom_dir}' is not writable: {exc}")

    if ORGANIZED_DESTINATION_DIR:
        custom = Path(ORGANIZED_DESTINATION_DIR).resolve()
        try:
            custom.mkdir(parents=True, exist_ok=True)
            return custom
        except Exception:
            pass

    # Test if preferred_dir can create subdirectories
    test_marker = preferred_dir / "._test_writable"
    try:
        test_marker.mkdir(parents=True, exist_ok=True)
        test_marker.rmdir()
        return preferred_dir
    except Exception:
        pass

    # Fallback 1: Native local Windows Pictures/Screenshots (standard NTFS, always writable)
    for fallback_root in (
        Path.home() / "Pictures" / "Screenshots",
        Path.home() / "Pictures" / "Organized Screenshots",
    ):
        try:
            fallback_root.mkdir(parents=True, exist_ok=True)
            marker = fallback_root / "._test_writable"
            marker.mkdir(parents=True, exist_ok=True)
            marker.rmdir()
            return fallback_root
        except Exception:
            pass

    return preferred_dir


def wait_until_file_ready(filepath: Path, timeout: float = FILE_READY_TIMEOUT_SEC) -> bool:
    """
    Wait until Snipping Tool finishes writing the screenshot PNG and releases file locks.
    """
    start_time = time.time()
    last_size = -1

    while time.time() - start_time < timeout:
        try:
            if filepath.exists():
                size = filepath.stat().st_size
                if size > 0 and size == last_size:
                    # Verify image header can be parsed
                    with Image.open(filepath) as img:
                        img.verify()
                    return True
                last_size = size
        except Exception:
            pass
        time.sleep(0.15)

    return False


def get_unique_destination(folder: Path, base_name: str, ext: str = ".png") -> Path:
    """
    Generate a non-conflicting destination path.
    """
    candidate = folder / f"{base_name}{ext}"
    if not candidate.exists():
        return candidate

    counter = 1
    while True:
        candidate = folder / f"{base_name} ({counter}){ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def _try_unlink_source(src_path: Path, dest_path: Path) -> None:
    """
    Safely delete src_path only if dest_path already exists with a matching non-zero size.
    Clears any DOS read-only flag on src_path before unlinking.
    """
    if not src_path.exists():
        return
    if not dest_path.exists():
        raise FileNotFoundError(f"Destination missing before cleanup: {dest_path}")

    src_size = src_path.stat().st_size
    dst_size = dest_path.stat().st_size
    if src_size <= 0 or dst_size != src_size:
        raise IOError(f"Size mismatch between source ({src_size}) and destination ({dst_size})")

    try:
        os.chmod(src_path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    src_path.unlink(missing_ok=True)


def _cleanup_source_with_retries(
    src_path: Path,
    dest_path: Path,
    delays: tuple[float, ...] = (0.5, 1.5, 3.0, 5.0),
) -> bool:
    """Retry removing the original file after copy fallback (handles brief OneDrive/Snipping locks)."""
    last_err: Exception | None = None
    for delay in delays:
        if delay > 0:
            time.sleep(delay)
        if not src_path.exists():
            return True
        try:
            _try_unlink_source(src_path, dest_path)
            logger.info(f"Removed original screenshot after copy: {src_path.name}")
            return True
        except Exception as exc:
            last_err = exc

    if src_path.exists():
        logger.warning(
            f"Could not delete original screenshot '{src_path}': {last_err}. "
            "Windows/OneDrive may be blocking deletion in that folder."
        )
    return False


class ScreenshotHandler(FileSystemEventHandler):
    def __init__(self, watch_dir: Path, tracker: MouseTracker):
        super().__init__()
        self.watch_dir = watch_dir.resolve()
        self._last_custom_dir = get_custom_output_dir()
        self.dest_root = get_writable_dest_root(self.watch_dir)
        self.tracker = tracker
        self._processed = set()

    def reload_dest_root(self) -> Path:
        """Recompute destination root from current user settings."""
        self._last_custom_dir = get_custom_output_dir()
        self.dest_root = get_writable_dest_root(self.watch_dir)
        return self.dest_root

    def get_dest_root(self) -> Path:
        """Return active destination root, reloading automatically if user setting changed."""
        if get_custom_output_dir() != self._last_custom_dir:
            return self.reload_dest_root()
        return self.dest_root

    def on_created(self, event):
        self._handle_event(event.src_path)

    def on_moved(self, event):
        self._handle_event(event.dest_path)

    def _handle_event(self, src_path_str: str):
        try:
            src_path = Path(src_path_str).resolve()

            # Only process files directly inside the monitored root, not in subdirectories
            if src_path.parent != self.watch_dir:
                return

            if src_path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
                return

            # Avoid processing same file twice
            if src_path in self._processed:
                return

            self._process_screenshot(src_path)
        except Exception as e:
            logger.exception(f"Unexpected error in _handle_event: {e}")

    def _process_screenshot(self, src_path: Path):
        self._processed.add(src_path)

        # Wait until Snipping Tool finishes writing
        if not wait_until_file_ready(src_path):
            logger.warning(f"File did not become ready in time: {src_path.name}")
            return

        try:
            with Image.open(src_path) as img:
                img_w, img_h = img.size
        except Exception as e:
            logger.error(f"Failed to open image {src_path.name}: {e}")
            return

        # Try to match with recent mouse drag
        matching_drag = self.tracker.find_matching_drag(img_w, img_h)
        snip_rect = matching_drag['rect'] if matching_drag else None

        # If no drag matched, check recent click (Window Snip Mode)
        recent_click = self.tracker.get_recent_click()
        click_pt = recent_click['pt'] if recent_click else None

        # Identify application and window
        last_active = self.tracker.get_last_active_window()
        app_name, clean_title = identify_window_from_snip(
            snip_rect=snip_rect,
            click_pt=click_pt,
            image_size=(img_w, img_h),
            last_active_window=last_active
        )

        dest_root = self.get_dest_root()
        dest_folder = dest_root / app_name
        try:
            # Build destination folder: <dest_root>/<app_name>/
            dest_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create subfolder {dest_folder}: {e}")
            # Fallback to local user Pictures/Screenshots directly
            dest_folder = Path.home() / "Pictures" / "Screenshots" / app_name
            dest_folder.mkdir(parents=True, exist_ok=True)

        original_stem = src_path.stem

        # Build clean filename
        if clean_title:
            new_stem = f"{original_stem} - {clean_title}"
        else:
            new_stem = original_stem

        dest_path = get_unique_destination(dest_folder, new_stem, ext=src_path.suffix)

        # Move the screenshot into the subfolder (retry briefly for transient locks, else copy + retry delete)
        moved = False
        last_move_err: Exception | None = None
        for attempt_delay in (0.0, 0.35, 0.75):
            if attempt_delay > 0:
                time.sleep(attempt_delay)
            try:
                shutil.move(str(src_path), str(dest_path))
                logger.info(f"Organized: {src_path.name} -> [{app_name}] {dest_path.name}")
                print(f"[OK] Organized: {src_path.name} -> {app_name}/{dest_path.name}")
                moved = True
                break
            except Exception as e:
                last_move_err = e

        if not moved:
            logger.warning(f"shutil.move failed ({last_move_err}), attempting copy fallback...")
            try:
                shutil.copy2(str(src_path), str(dest_path))
                logger.info(f"Organized (copied): {src_path.name} -> [{app_name}] {dest_path.name}")
                print(f"[OK] Organized: {src_path.name} -> {app_name}/{dest_path.name}")

                # Attempt immediate delete, then background retries if still locked
                try:
                    _try_unlink_source(src_path, dest_path)
                    logger.info(f"Removed original screenshot: {src_path.name}")
                except Exception:
                    cleanup_thread = threading.Thread(
                        target=_cleanup_source_with_retries,
                        args=(src_path, dest_path),
                        daemon=True,
                    )
                    cleanup_thread.start()
            except Exception as copy_err:
                logger.error(f"Failed to move or copy {src_path.name} to {dest_path}: {copy_err}")
                print(f"[!] Failed to organize {src_path.name}: {copy_err}")


class ScreenshotOrganizer:
    def __init__(self, watch_dirs: list, tracker: MouseTracker):
        self.watch_dirs = watch_dirs
        self.tracker = tracker
        self.observer = Observer()
        self.handlers = []

    def start(self):
        self.tracker.start()
        for d in self.watch_dirs:
            p = Path(d)
            if p.exists():
                handler = ScreenshotHandler(p, self.tracker)
                self.handlers.append(handler)
                self.observer.schedule(handler, str(p), recursive=False)
                dest_info = handler.dest_root
                logger.info(f"Watching folder: {p} (Dest: {dest_info})")
                print(f"[*] Watching: {p}")
                print(f"    -> Organizing to: {dest_info}/<App>/")
        self.observer.start()

    def reload_dest_root(self) -> list[Path]:
        """Refresh output destination roots for all active watch handlers."""
        updated = []
        for handler in self.handlers:
            new_dest = handler.reload_dest_root()
            updated.append(new_dest)
            logger.info(f"Updated destination root for {handler.watch_dir}: {new_dest}")
        return updated

    def stop(self):
        self.observer.stop()
        self.tracker.stop()
        self.observer.join()
