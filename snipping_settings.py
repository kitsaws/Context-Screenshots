"""
Settings persistence and dynamic Windows Snipping Tool folder resolution.

Reads Snipping Tool's own saved location (settings.dat + PersistedStorageItemTable)
and Windows Shell / Known Folders without hardcoding user-specific or OneDrive paths,
and persists user preferences such as a custom screenshot output root directory.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import winreg

logger = logging.getLogger("ContextScreenshots")

# Windows Known Folder GUIDs
FOLDERID_SCREENSHOTS = "{B7BEDE81-DF94-4682-A7D8-57A52620B86F}"
FOLDERID_PICTURES = "{33E28130-4E1E-4676-835A-98395C3BC3BB}"
# Windows 10/11 localized "Pictures" entry in User Shell Folders (often redirected by OneDrive)
USER_SHELL_LOCAL_PICTURES_GUID = "{0DDD015D-B06C-45D5-8C4C-F59713854639}"

USER_SHELL_FOLDERS_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
SHELL_FOLDERS_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"

DEFAULT_SCREENSKETCH_PFN = "Microsoft.ScreenSketch_8wekyb3d8bbwe"
VOLUME_GUID_RE = re.compile(r"^(\\\\\?\\Volume\{[0-9a-fA-F-]+\}\\?)(.*)$", re.IGNORECASE)
TOKEN_GUID_RE = re.compile(r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$")

KEY_READ_FLAGS = 0x20019
REG_PROCESS_APPKEY = 0x00000001
ERROR_MORE_DATA = 234


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def get_settings_path() -> Path:
    """Return the path to the persistent user settings JSON file in %APPDATA%."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
    return base / "ContextScreenshots" / "settings.json"


def load_user_settings() -> dict:
    """Load persistent user settings from %APPDATA%\\ContextScreenshots\\settings.json."""
    settings_path = get_settings_path()
    if not settings_path.exists():
        return {}
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(f"Failed to read user settings from {settings_path}: {exc}")
        return {}


def save_user_settings(settings: dict) -> Path:
    """Persist user settings atomically to %APPDATA%\\ContextScreenshots\\settings.json."""
    settings_path = get_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings, indent=2)

    tmp_path = settings_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, settings_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        settings_path.write_text(payload, encoding="utf-8")
    return settings_path


def get_custom_output_dir() -> Path | None:
    """Return the user-configured output root directory if set, else None."""
    raw = load_user_settings().get("output_dir")
    if not raw or not isinstance(raw, str):
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw.strip()))
    if not expanded:
        return None
    return Path(expanded)


def set_custom_output_dir(output_dir: str | Path | None) -> Path | None:
    """
    Set or clear the persistent custom screenshot output root directory.
    Passing None or empty string resets to auto-detected default.
    """
    settings = load_user_settings()
    if output_dir is None or str(output_dir).strip() == "":
        settings["output_dir"] = None
        save_user_settings(settings)
        return None

    expanded = os.path.expandvars(os.path.expanduser(str(output_dir).strip()))
    target = Path(expanded).resolve()
    target.mkdir(parents=True, exist_ok=True)
    settings["output_dir"] = str(target)
    save_user_settings(settings)
    return target


def _normalize_windows_path(path_str: str) -> str:
    """Clean extended-length Windows path prefixes into standard user-friendly paths."""
    cleaned = os.path.expandvars(path_str.strip().strip('"'))
    if cleaned.lower().startswith("\\\\?\\volume{"):
        cleaned = resolve_volume_guid_path(cleaned)
    elif cleaned.lower().startswith("\\\\?\\unc\\"):
        cleaned = "\\\\" + cleaned[8:]
    elif cleaned.startswith("\\\\?\\") and len(cleaned) > 6 and cleaned[5] == ":":
        cleaned = cleaned[4:]
    return cleaned


def resolve_volume_guid_path(path_str: str) -> str:
    """
    Convert a UWP storage path with a \\\\?\\Volume{...}\\ prefix into a normal
    drive-letter path using kernel32.GetVolumePathNamesForVolumeNameW.
    """
    match = VOLUME_GUID_RE.match(path_str.strip())
    if not match:
        return path_str

    vol_root = match.group(1).rstrip("\\") + "\\"
    remainder = match.group(2).lstrip("\\/")

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_vol_paths = kernel32.GetVolumePathNamesForVolumeNameW
        get_vol_paths.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_vol_paths.restype = wintypes.BOOL

        buf_len = 512
        buf = ctypes.create_unicode_buffer(buf_len)
        needed = wintypes.DWORD(0)

        ok = get_vol_paths(vol_root, buf, buf_len, ctypes.byref(needed))
        if not ok and ctypes.get_last_error() == ERROR_MORE_DATA and needed.value > buf_len:
            buf = ctypes.create_unicode_buffer(needed.value)
            ok = get_vol_paths(vol_root, buf, needed.value, ctypes.byref(needed))

        if ok and buf.value:
            mount = buf.value
            if len(mount) == 2 and mount[1] == ":":
                mount += "\\"
            return str(Path(mount) / remainder) if remainder else mount
    except Exception as exc:
        logger.debug(f"Could not resolve volume GUID '{vol_root}': {exc}")

    return path_str


def decode_uwp_app_data_string(raw_value) -> str | None:
    """
    Decode a UWP ApplicationData binary value from settings.dat.
    UWP ApplicationData strings (registry type 0x5F5E10C) are encoded as
    UTF-16LE bytes terminated by \\x00\\x00, followed by an 8-byte FILETIME.
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        stripped = raw_value.strip("\x00 \r\n\t")
        return stripped or None
    if not isinstance(raw_value, (bytes, bytearray)):
        return None

    data = bytes(raw_value)
    if len(data) < 2:
        return None

    # Find the first even-aligned UTF-16LE null terminator (excludes trailing FILETIME)
    end_idx = None
    for i in range(0, len(data) - 1, 2):
        if data[i : i + 2] == b"\x00\x00":
            end_idx = i
            break

    if end_idx is None:
        # Fallback: strip trailing 8-byte FILETIME if payload looks long enough
        candidate = data[:-8] if len(data) > 10 else data
        candidate = candidate[: len(candidate) - (len(candidate) % 2)]
        text = candidate.decode("utf-16-le", errors="ignore").strip("\x00 \r\n\t")
        return text or None

    if end_idx == 0:
        return None

    try:
        text = data[:end_idx].decode("utf-16-le").strip("\x00 \r\n\t")
        return text or None
    except Exception:
        return None


def _get_known_folder_path(folder_guid: str) -> Path | None:
    """Resolve a Windows Known Folder GUID via SHGetKnownFolderPath."""
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=False)
        ole32 = ctypes.WinDLL("ole32", use_last_error=False)

        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

        guid = _GUID.from_buffer_copy(uuid.UUID(folder_guid).bytes_le)
        ptr = ctypes.c_void_p()
        hr = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(ptr))
        if hr == 0 and ptr.value:
            try:
                path_str = ctypes.wstring_at(ptr.value)
                if path_str:
                    return Path(_normalize_windows_path(path_str))
            finally:
                ole32.CoTaskMemFree(ptr)
    except Exception as exc:
        logger.debug(f"SHGetKnownFolderPath({folder_guid}) unavailable: {exc}")
    return None


def _read_hkcu_string(subkey: str, value_name: str) -> str | None:
    """Read a string value from HKCU safely."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            if isinstance(val, str) and val.strip():
                return _normalize_windows_path(val)
    except OSError:
        pass
    return None


def _safe_exists(path: Path) -> bool:
    """Return True if path exists, swallowing PermissionError/OSError on restricted dirs."""
    try:
        return path.exists()
    except OSError:
        return False


def _find_screensketch_packages() -> list[tuple[str, Path]]:
    """Locate Snipping Tool (Microsoft.ScreenSketch) UWP package directories."""
    local_appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    packages_dir = Path(local_appdata) / "Packages"
    found: list[tuple[str, Path]] = []

    default_pkg = packages_dir / DEFAULT_SCREENSKETCH_PFN
    if _safe_exists(default_pkg):
        found.append((DEFAULT_SCREENSKETCH_PFN, default_pkg))

    try:
        if _safe_exists(packages_dir):
            for child in packages_dir.iterdir():
                if child.is_dir() and child.name.lower().startswith("microsoft.screensketch_"):
                    if all(pfn.lower() != child.name.lower() for pfn, _ in found):
                        found.append((child.name, child))
    except OSError as exc:
        logger.debug(f"Could not enumerate Packages directory: {exc}")

    return found


def _read_appkey_value(hive_path: Path, subkey: str, value_name: str):
    """
    Load an isolated UWP settings.dat hive using advapi32.RegLoadAppKeyW
    and query a value inside it. Copies to a temp dir first to avoid locking
    Snipping Tool's live settings hive.
    """
    if not _safe_exists(hive_path):
        return None

    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=False)
        advapi32.RegLoadAppKeyW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.HKEY),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        advapi32.RegLoadAppKeyW.restype = wintypes.LONG
        advapi32.RegCloseKey.argtypes = [wintypes.HKEY]
        advapi32.RegCloseKey.restype = wintypes.LONG
    except Exception as exc:
        logger.debug(f"RegLoadAppKeyW unavailable: {exc}")
        return None

    def _try_load(target_hive: Path):
        hkey = wintypes.HKEY()
        for options in (REG_PROCESS_APPKEY, 0):
            rc = advapi32.RegLoadAppKeyW(str(target_hive), ctypes.byref(hkey), KEY_READ_FLAGS, options, 0)
            if rc == 0 and hkey.value:
                try:
                    if subkey:
                        with winreg.OpenKey(hkey.value, subkey, 0, winreg.KEY_READ) as sk:
                            val, _ = winreg.QueryValueEx(sk, value_name)
                            return val
                    else:
                        val, _ = winreg.QueryValueEx(hkey.value, value_name)
                        return val
                except OSError:
                    return None
                finally:
                    advapi32.RegCloseKey(hkey)
        return None

    # Copy settings.dat (+ transaction logs if any) into an isolated temp folder
    try:
        with tempfile.TemporaryDirectory(prefix="ctx_snip_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            tmp_hive = tmp_root / hive_path.name
            shutil.copy2(hive_path, tmp_hive)
            for suffix in (".LOG1", ".LOG2", ".log1", ".log2"):
                log_file = Path(str(hive_path) + suffix)
                if log_file.exists():
                    try:
                        shutil.copy2(log_file, tmp_root / log_file.name)
                    except OSError:
                        pass
            result = _try_load(tmp_hive)
            if result is not None:
                return result
    except OSError as exc:
        logger.debug(f"Could not copy settings.dat ({hive_path}): {exc}")

    # Direct fallback in case copying failed
    return _try_load(hive_path)


def _resolve_persisted_storage_token(package_family: str, token: str) -> Path | None:
    """Resolve a UWP FutureAccessList/MRU GUID token via AppModel PersistedStorageItemTable."""
    token_clean = token.strip()
    token_variants = [token_clean]
    if not token_clean.startswith("{"):
        token_variants.append(f"{{{token_clean}}}")

    base = (
        rf"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
        rf"\AppModel\SystemAppData\{package_family}\PersistedStorageItemTable"
    )
    for table in ("ManagedByApp", "MostRecentlyUsed"):
        for tok in token_variants:
            file_path = _read_hkcu_string(rf"{base}\{table}\{tok}", "FilePath")
            if file_path:
                return Path(_normalize_windows_path(file_path))
    return None


def get_snipping_tool_custom_folder() -> Path | None:
    """
    Read Snipping Tool's custom 'Automatically save screenshots' folder from
    its UWP Settings\\settings.dat (AutoSaveScreenshotsLocation).
    Returns None if Snipping Tool is using the default Windows Screenshots folder
    or if settings cannot be read.
    """
    for pfn, pkg_dir in _find_screensketch_packages():
        try:
            settings_dat = pkg_dir / "Settings" / "settings.dat"
            if not _safe_exists(settings_dat):
                continue

            raw_val = _read_appkey_value(settings_dat, "LocalState", "AutoSaveScreenshotsLocation")
            if raw_val is None:
                raw_val = _read_appkey_value(settings_dat, "", "AutoSaveScreenshotsLocation")

            location = decode_uwp_app_data_string(raw_val)
            if not location:
                continue

            # A GUID token references PersistedStorageItemTable\ManagedByApp\<GUID>
            if TOKEN_GUID_RE.match(location):
                resolved = _resolve_persisted_storage_token(pfn, location)
                if resolved:
                    return resolved
                continue

            normalized = _normalize_windows_path(location)
            if Path(normalized).is_absolute():
                return Path(normalized)
        except Exception as exc:
            logger.debug(f"Could not read Snipping Tool settings for {pfn}: {exc}")

    return None


def get_windows_screenshots_folders() -> list[tuple[str, Path]]:
    """
    Discover Windows Screenshots folders dynamically from Known Folders and
    Explorer User Shell Folders (without hardcoding OneDrive).
    """
    candidates: list[tuple[str, Path]] = []

    # 1. Windows Known Folder API: FOLDERID_Screenshots
    kf_screenshots = _get_known_folder_path(FOLDERID_SCREENSHOTS)
    if kf_screenshots:
        candidates.append(("Windows Screenshots folder (Known Folder API)", kf_screenshots))

    # 2. Explorer User Shell Folders: custom Screenshots location GUID
    for reg_key in (USER_SHELL_FOLDERS_SUBKEY, SHELL_FOLDERS_SUBKEY):
        reg_screenshots = _read_hkcu_string(reg_key, FOLDERID_SCREENSHOTS)
        if reg_screenshots:
            candidates.append(("Windows Screenshots folder (User Shell Folders)", Path(reg_screenshots)))

    # 3. Redirected / active Pictures folder + \Screenshots (handles OneDrive or custom Pictures automatically)
    for reg_key in (USER_SHELL_FOLDERS_SUBKEY, SHELL_FOLDERS_SUBKEY):
        for val_name in ("My Pictures", USER_SHELL_LOCAL_PICTURES_GUID):
            pic_dir = _read_hkcu_string(reg_key, val_name)
            if pic_dir:
                candidates.append(
                    (f"Windows Pictures\\Screenshots ({val_name})", Path(pic_dir) / "Screenshots")
                )

    # 4. Known Folder API: FOLDERID_Pictures + \Screenshots
    kf_pictures = _get_known_folder_path(FOLDERID_PICTURES)
    if kf_pictures:
        candidates.append(("Windows Pictures\\Screenshots (Known Folder API)", kf_pictures / "Screenshots"))

    # Deduplicate while preserving priority order
    deduped: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for source, path in candidates:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key not in seen:
            seen.add(key)
            deduped.append((source, path))
    return deduped


def describe_watch_sources(create_if_missing: bool = False) -> list[tuple[str, Path]]:
    """
    Resolve all active screenshot watch folders along with their discovery source labels.
    Order reflects priority (Snipping Tool custom location first, then Windows defaults).
    """
    ordered_candidates: list[tuple[str, Path]] = []

    custom_snip = get_snipping_tool_custom_folder()
    if custom_snip:
        ordered_candidates.append(("Snipping Tool custom setting (settings.dat)", custom_snip))

    ordered_candidates.extend(get_windows_screenshots_folders())

    local_fallback = Path.home() / "Pictures" / "Screenshots"
    ordered_candidates.append(("Default user Pictures\\Screenshots", local_fallback))

    # Deduplicate preserving order
    unique: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for source, path in ordered_candidates:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key not in seen:
            seen.add(key)
            unique.append((source, path))

    existing = [(src, p) for src, p in unique if _safe_exists(p)]
    if existing:
        return existing

    primary_source, primary_path = unique[0]
    if create_if_missing:
        try:
            primary_path.mkdir(parents=True, exist_ok=True)
            return [(primary_source, primary_path)]
        except OSError:
            try:
                local_fallback.mkdir(parents=True, exist_ok=True)
                return [("Default user Pictures\\Screenshots", local_fallback)]
            except OSError as exc:
                logger.warning(f"Could not create default screenshots folder '{local_fallback}': {exc}")

    return unique


def resolve_watch_folders(create_if_missing: bool = True) -> list[Path]:
    """Return deduplicated list of active Snipping Tool / Windows Screenshots folders."""
    return [path for _, path in describe_watch_sources(create_if_missing=create_if_missing)]
