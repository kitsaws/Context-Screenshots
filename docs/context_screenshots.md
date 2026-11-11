# `context_screenshots.py` — CLI Runner & Detached Background Service

`context_screenshots.py` provides command-line control for developers and terminal users who want to run, inspect, or manage the service directly with Python.

---

## Responsibilities

1. **Windows Console Unicode Safety**
   * Reconfigures `sys.stdout` and `sys.stderr` to UTF-8 with `errors='replace'` so window titles or log output containing symbols never trigger `UnicodeEncodeError` in legacy Windows codepages.

2. **Logging (`setup_logging`)**
   * Writes INFO-level timestamped logs to `context_screenshots.log` in the project directory, and mirrors output to `stdout` when running in foreground mode (`verbose=True`).

3. **Background Process Lifecycle (`--start`, `--stop`, `--status`, `--run-silent`)**
   * Tracks the active Python background process using `.context_screenshots.pid` alongside `is_process_running(pid)` (verifying via `psutil.Process` that the PID still belongs to a running Python process and cleaning stale PID files automatically).
   * **`start_background()`:** Prefers `pythonw.exe` if present next to `sys.executable` and launches `context_screenshots.py --run-silent` using Windows flags `DETACHED_PROCESS (0x00000008) | CREATE_NO_WINDOW (0x08000000)` so no console window appears.
   * **`stop_background()`:** Gracefully calls `proc.terminate()` (waiting up to `3s`), falling back to `proc.kill()`, and removes `.context_screenshots.pid`.

4. **Configuration & Destination Commands (`--show-config`, `--set-output`, `--reset-output`)**
   * **`--status`:** Displays running/stopped state, active PID, watched source folders, and active output root mode (`Custom (user setting)` vs `Auto-detected default`). Uses `create_if_missing=False` to avoid filesystem side effects while inspecting status.
   * **`--show-config`:** Calls `describe_watch_sources()` to print each monitored path together with the exact discovery source (e.g., Snipping Tool `settings.dat`, `User Shell Folders`, or default fallback) and `%APPDATA%\ContextScreenshots\settings.json` location.
   * **`--set-output DIR` / `--reset-output`:** Updates `%APPDATA%\ContextScreenshots\settings.json`. Note that a running `ContextScreenshots.exe` or service instance automatically detects changes to `settings.json` on the next processed screenshot.

5. **Windows Startup Management (`--install-startup`, `--uninstall-startup`)**
   * Writes or removes `ContextScreenshots.vbs` inside `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`, launching `pythonw.exe context_screenshots.py --run-silent` invisibly at boot.

