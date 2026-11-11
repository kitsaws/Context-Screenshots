# `app.py` — System Tray GUI & Standalone Executable Entrypoint

`app.py` is the main GUI entrypoint packaged into `dist\ContextScreenshots.exe` via PyInstaller (`console=False`). It provides a silent background system tray experience with no terminal window.

---

## Responsibilities

1. **Portable Path Resolution (`BASE_DIR`)**
   * Detects whether execution is frozen inside PyInstaller (`getattr(sys, 'frozen', False)`) or running directly from Python source.
   * Places `context_screenshots.log` next to `ContextScreenshots.exe` (when frozen) or next to `app.py` (when running from source).

2. **Single-Instance Enforcement (`acquire_mutex`)**
   * Creates a Windows named mutex `Local\ContextScreenshotsSingleInstanceMutex` via `kernel32.CreateMutexW`.
   * Checks `GetLastError() == 183` (`ERROR_ALREADY_EXISTS`). If already running, displays a Win32 `MessageBoxW` notice and exits cleanly rather than spawning duplicate file watchers or mouse hooks.

3. **Dedicated Folder Picker Thread (`pick_directory` / `_folder_picker_loop`)**
   * Tcl/Tk requires UI calls to stay on the thread where `tk.Tk()` was created, while `pystray` menu callbacks run from the tray event loop.
   * A single persistent daemon thread (`FolderPickerThread`) owns a hidden, topmost `tk.Tk()` root and communicates via `queue.Queue` pairs (`_picker_req_queue` and per-call `reply_q`).
   * A non-blocking `_picker_busy_lock` prevents opening overlapping dialogs if the user clicks the menu repeatedly.
   * Falls back to Windows Shell `_sh_browse_for_folder` (`win32com.shell.shell.SHBrowseForFolder`) if `tkinter` fails to initialize.

4. **System Tray Menu & Live Folder Reload (`run_tray_app`)**
   * **Open Screenshots Folder *(default double-click)*:** Resolves `get_active_output_dir(folders)` and launches it in Windows File Explorer with `os.startfile`.
   * **Change Save Folder...:** Opens `pick_directory(...)`, writes the selection via `set_custom_output_dir()`, calls `organizer.reload_dest_root()` so subsequent screenshots immediately go to the new root without restarting, refreshes menu state with `icon.update_menu()`, and displays a Windows tray notification.
   * **Reset Save Folder to Default:** Enabled dynamically (`enabled=lambda it: get_custom_output_dir() is not None`). Clears `"output_dir"` back to `None` and calls `organizer.reload_dest_root()`.
   * **Run on Windows Startup:** Creates or deletes `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ContextScreenshots.vbs`, launching the app silently (`windowStyle = 0`) on Windows sign-in.
   * **View Logs:** Opens `context_screenshots.log` in the default text editor.
   * **Exit:** Stops `ScreenshotOrganizer`, exits `icon.run()`, and closes the Windows mutex handle.

5. **Tray Icon Loading (`load_icon_image`)**
   * Loads `icon.ico` if present next to `BASE_DIR`, or draws a fallback 64x64 RGBA camera icon programmatically with `PIL.ImageDraw`.

