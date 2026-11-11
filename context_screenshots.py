"""
Context-Aware Screenshots - Background Runner & CLI

Usage:
    python context_screenshots.py                  # Run in foreground (live logs)
    python context_screenshots.py --start          # Run silently in background
    python context_screenshots.py --stop           # Stop background service
    python context_screenshots.py --status         # Check if running
    python context_screenshots.py --show-config    # Show detected folders & output path
    python context_screenshots.py --set-output DIR # Save organized screenshots into DIR
    python context_screenshots.py --reset-output   # Reset save folder to auto-detected default
    python context_screenshots.py --install-startup # Run automatically when Windows boots
    python context_screenshots.py --uninstall-startup
"""
import sys
import os
import time
import argparse
import logging
import subprocess
from pathlib import Path
import psutil

from config import (
    resolve_screenshots_folders,
    describe_watch_sources,
    get_custom_output_dir,
    set_custom_output_dir,
    get_settings_path,
)
from mouse_tracker import MouseTracker
from organizer import ScreenshotOrganizer, get_writable_dest_root

# Ensure Windows terminal doesn't crash on emoji or Unicode prints
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
PID_FILE = BASE_DIR / ".context_screenshots.pid"
LOG_FILE = BASE_DIR / "context_screenshots.log"


def setup_logging(verbose: bool = False):
    handlers = [
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
    if verbose:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers
    )


def is_process_running(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and "python" in proc.name().lower()
    except Exception:
        return False


def get_running_pid() -> int | None:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if is_process_running(pid):
                return pid
            else:
                PID_FILE.unlink(missing_ok=True)
        except Exception:
            PID_FILE.unlink(missing_ok=True)
    return None


def run_service(verbose: bool = True):
    """Core loop running the file watcher and mouse tracker."""
    setup_logging(verbose=verbose)
    logger = logging.getLogger("ContextScreenshots")
    logger.info("Context-Aware Screenshots service starting...")

    # Write PID
    PID_FILE.write_text(str(os.getpid()))

    folders = resolve_screenshots_folders()
    if not folders:
        print("[!] No screenshots folder found.")
        logger.error("No screenshots folder found.")
        return

    tracker = MouseTracker()
    organizer = ScreenshotOrganizer(folders, tracker)

    try:
        organizer.start()
        print("[*] Context-Aware Screenshots is running. Take a screenshot with Snipping Tool to test!")
        print("[*] Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping service...")
    finally:
        organizer.stop()
        PID_FILE.unlink(missing_ok=True)
        logger.info("Context-Aware Screenshots service stopped.")
        print("[*] Service stopped cleanly.")


def start_background():
    running_pid = get_running_pid()
    if running_pid:
        print(f"[!] Context-Aware Screenshots is already running in background (PID: {running_pid}).")
        return

    python_exe = sys.executable
    # Use pythonw.exe if available for a completely invisible process
    pythonw = Path(python_exe).parent / "pythonw.exe"
    executable = str(pythonw) if pythonw.exists() else python_exe

    script_path = str(BASE_DIR / "context_screenshots.py")

    # Launch detached process with no console window
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    creation_flags = DETACHED_PROCESS | CREATE_NO_WINDOW

    proc = subprocess.Popen(
        [executable, script_path, "--run-silent"],
        creationflags=creation_flags,
        close_fds=True
    )

    PID_FILE.write_text(str(proc.pid))
    print(f"[+] Started Context-Aware Screenshots in background (PID: {proc.pid}).")
    print(f"    Logs written to: {LOG_FILE}")


def stop_background():
    running_pid = get_running_pid()
    if not running_pid:
        print("[-] Context-Aware Screenshots is not currently running.")
        return

    try:
        proc = psutil.Process(running_pid)
        proc.terminate()
        proc.wait(timeout=3)
        print(f"[+] Stopped background process (PID: {running_pid}).")
    except Exception:
        try:
            proc.kill()
            print(f"[+] Killed background process (PID: {running_pid}).")
        except Exception as e:
            print(f"[!] Error stopping process: {e}")
    finally:
        PID_FILE.unlink(missing_ok=True)


def _get_active_dest_summary(folders: list[Path]) -> tuple[Path, str]:
    custom = get_custom_output_dir()
    if custom:
        return custom, "Custom (user setting)"
    dest = get_writable_dest_root(folders[0]) if folders else (Path.home() / "Pictures" / "Screenshots")
    return dest, "Auto-detected default"


def check_status():
    running_pid = get_running_pid()
    folders = resolve_screenshots_folders(create_if_missing=False)
    dest, dest_mode = _get_active_dest_summary(folders)
    if running_pid:
        print(f"[+] STATUS: RUNNING (PID: {running_pid})")
        print("    Monitored folders:")
        for f in folders:
            print(f"      - {f}")
        print(f"    Output root ({dest_mode}): {dest}")
        print(f"    Log file: {LOG_FILE}")
    else:
        print("[-] STATUS: STOPPED (not running)")
        print("    Monitored folders (when started):")
        for f in folders:
            print(f"      - {f}")
        print(f"    Output root ({dest_mode}): {dest}")


def show_config():
    sources = describe_watch_sources()
    folders = [p for _, p in sources]
    dest, dest_mode = _get_active_dest_summary(folders)
    print("Context-Aware Screenshots Configuration")
    print("=" * 42)
    print(f"Settings file : {get_settings_path()}")
    print(f"Output root   : {dest} [{dest_mode}]")
    print("Watch folders (source -> path):")
    for label, path in sources:
        print(f"  - [{label}] {path}")


def install_startup():
    startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    if not startup_dir.exists():
        print(f"[!] Windows Startup folder not found: {startup_dir}")
        return

    vbs_path = startup_dir / "ContextScreenshots.vbs"
    python_exe = sys.executable
    pythonw = Path(python_exe).parent / "pythonw.exe"
    exe = str(pythonw) if pythonw.exists() else python_exe
    script = str(BASE_DIR / "context_screenshots.py")

    # VBS script launches pythonw silently without flashing command prompt window
    vbs_content = f'''Set WshShell = CreateObject("WScript.Shell")\nWshShell.Run """{exe}"" ""{script}"" --run-silent", 0, False\n'''
    vbs_path.write_text(vbs_content, encoding='utf-8')

    print(f"[+] Added to Windows Startup: {vbs_path}")
    print("    It will now automatically start in background when Windows boots.")


def uninstall_startup():
    startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    vbs_path = startup_dir / "ContextScreenshots.vbs"
    if vbs_path.exists():
        vbs_path.unlink()
        print(f"[+] Removed from Windows Startup: {vbs_path}")
    else:
        print("[-] Not currently registered in Windows Startup.")


def main():
    parser = argparse.ArgumentParser(description="Context-Aware Screenshots Background Service")
    parser.add_argument("--start", action="store_true", help="Start service silently in background")
    parser.add_argument("--stop", action="store_true", help="Stop background service")
    parser.add_argument("--status", action="store_true", help="Check service status")
    parser.add_argument("--show-config", action="store_true", help="Show detected Snipping Tool watch folders and active save root")
    parser.add_argument("--set-output", metavar="DIR", help="Set custom root folder where organized screenshots are saved")
    parser.add_argument("--reset-output", action="store_true", help="Reset save folder back to auto-detected default")
    parser.add_argument("--run-silent", action="store_true", help="Internal flag: run silently without stdout")
    parser.add_argument("--install-startup", action="store_true", help="Auto-start with Windows")
    parser.add_argument("--uninstall-startup", action="store_true", help="Remove from Windows startup")

    args = parser.parse_args()

    if args.start:
        start_background()
    elif args.stop:
        stop_background()
    elif args.status:
        check_status()
    elif args.show_config:
        show_config()
    elif args.set_output:
        try:
            saved = set_custom_output_dir(args.set_output)
            print(f"[+] Output root set to: {saved}")
            print("    (If ContextScreenshots.exe is running in tray, new screenshots use this immediately.)")
        except Exception as e:
            print(f"[!] Failed to set output directory '{args.set_output}': {e}")
            sys.exit(1)
    elif args.reset_output:
        set_custom_output_dir(None)
        dest, _ = _get_active_dest_summary(resolve_screenshots_folders(create_if_missing=False))
        print(f"[+] Output root reset to auto-detected default: {dest}")
    elif args.install_startup:
        install_startup()
    elif args.uninstall_startup:
        uninstall_startup()
    elif args.run_silent:
        run_service(verbose=False)
    else:
        # Default foreground run
        run_service(verbose=True)


if __name__ == "__main__":
    main()

