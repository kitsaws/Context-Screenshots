# `organizer.py` — Watchdog Monitor, Routing & Cleanup Pipeline

`organizer.py` connects filesystem events (`watchdog`) to `MouseTracker`, `window_detector`, and `snipping_settings`, safely moving screenshots into `<OutputRoot>/<AppName>/`.

---

## 1. Output Destination Resolution (`get_writable_dest_root`)

Determines the root directory where `<AppName>` subfolders are created:
1. **User Custom Output Root:** Checks `get_custom_output_dir()` from `%APPDATA%\ContextScreenshots\settings.json`. If set, creates/uses that folder directly.
2. **Static Config Override:** Honors `config.ORGANIZED_DESTINATION_DIR` if explicitly customized in source.
3. **Writability Probe on Watch Folder:** Tests whether `preferred_dir` supports creating child directories by creating/removing a temporary `._test_writable` probe folder. *(OneDrive cloud-placeholder directories with `IO_REPARSE_TAG_CLOUD_FILE` often reject `mkdir` with `WinError 2`.)*
4. **Local Fallbacks:** Falls back cleanly to `~/Pictures/Screenshots`, then `~/Pictures/Organized Screenshots` (testing writability).

**Live Reload (`ScreenshotHandler.get_dest_root` & `ScreenshotOrganizer.reload_dest_root`):**
Each `ScreenshotHandler` tracks `_last_custom_dir`. Whenever the user changes or resets the folder from the System Tray or CLI, `get_dest_root()` detects the change and updates the destination immediately without requiring a service restart.

---

## 2. Screenshot Processing Lifecycle (`ScreenshotHandler._process_screenshot`)

1. **Event Filtering (`_handle_event`):**
   * Responds to `on_created` and `on_moved` on direct children of `self.watch_dir` only (`src_path.parent == self.watch_dir` and `observer.schedule(..., recursive=False)`), preventing subfolder moves from re-triggering events.
   * Accepts `.png`, `.jpg`, and `.jpeg` extensions and deduplicates via `self._processed`.
2. **Write Completion Check (`wait_until_file_ready`):**
   * Polls every `0.15s` up to `FILE_READY_TIMEOUT_SEC` (`8.0s`) until file size is non-zero, stops changing between consecutive checks, and `PIL.Image.open(filepath).verify()` succeeds.
3. **Context Identification:**
   * Reads `(img_w, img_h)` dimensions.
   * Queries `tracker.find_matching_drag(img_w, img_h)`, `tracker.get_recent_click()`, and `tracker.get_last_active_window()`.
   * Passes those signals to `identify_window_from_snip(...)` to get `(app_name, clean_title)`.
4. **Collision-Safe Naming (`get_unique_destination`):**
   * Builds `<original_stem> - <clean_title>.<ext>` (or `<original_stem>.<ext>` if no title).
   * Appends ` (1)`, ` (2)`, etc. if a filename already exists.
5. **Move & Duplicate Prevention:**
   * **Retry Move:** Attempts `shutil.move(src_path, dest_path)` over delays `(0.0, 0.35, 0.75)` seconds to tolerate brief Snipping Tool / antivirus locks.
   * **Copy + Verified Cleanup Fallback:** If `shutil.move` fails (e.g., cross-drive or persistent `WinError 5`), copies with `shutil.copy2` so the organized file is available immediately, then calls `_try_unlink_source(src_path, dest_path)`:
     * Verifies `dest_path` exists with matching non-zero byte size before deleting.
     * Clears any read-only DOS bit (`os.chmod`).
     * Unlinks `src_path` immediately, or spawns a daemon `_cleanup_source_with_retries` thread (`0.5s`, `1.5s`, `3.0s`, `5.0s`). If Windows/OneDrive still denies deletion after retries, logs an actionable warning to `context_screenshots.log`.

