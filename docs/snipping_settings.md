# `snipping_settings.py` — User Preferences & Dynamic Snipping Tool Detection

`snipping_settings.py` handles two jobs cleanly and portably across any Windows PC without hardcoding usernames or `OneDrive` paths:
1. Persisting user preferences (custom screenshot save root) in `%APPDATA%\ContextScreenshots\settings.json`.
2. Dynamically discovering where Windows Snipping Tool (`Win + Shift + S` / `PrtScn`) saves screenshots.

---

## 1. Persistent User Settings (`settings.json`)

* **`get_settings_path()`:** Resolves `%APPDATA%\ContextScreenshots\settings.json` (falling back to `~/AppData/Roaming/ContextScreenshots/settings.json`).
* **`load_user_settings()` / `save_user_settings()`:** Reads JSON safely and performs atomic writes using a `.tmp` sibling file + `os.replace()` to prevent corrupted settings if interrupted.
* **`get_custom_output_dir()` / `set_custom_output_dir(path)`:** Expands environment variables (`%USERPROFILE%`, etc.) and `~`, creates the destination folder via `mkdir(parents=True, exist_ok=True)` when setting a custom root, or sets `"output_dir": null` when resetting to default.

---

## 2. Dynamic Snipping Tool Folder Resolution

`describe_watch_sources(create_if_missing=False)` and `resolve_watch_folders(create_if_missing=True)` discover screenshot source folders in priority order and deduplicate paths case-insensitively on Windows:

### Step 1: Snipping Tool's Own Custom Folder (`get_snipping_tool_custom_folder`)
When a user changes Snipping Tool's *"Automatically save original screenshots"* folder in Windows 11 Settings, Windows stores the setting inside the Store app's private registry hive rather than Explorer Shell Folders:
1. `_find_screensketch_packages()` searches `%LOCALAPPDATA%\Packages\` for `Microsoft.ScreenSketch_8wekyb3d8bbwe` (or any `Microsoft.ScreenSketch_*` folder).
2. `_read_appkey_value()` copies `Settings\settings.dat` (plus `.LOG1`/`.LOG2` transaction logs if present) into a temporary directory so Snipping Tool's live hive is never locked, then loads it privately with `advapi32.RegLoadAppKeyW` and reads `LocalState\AutoSaveScreenshotsLocation` (`winreg.QueryValueEx`). Always closes handles with `RegCloseKey` before temp cleanup.
3. `decode_uwp_app_data_string()` parses Windows Runtime `ApplicationData` strings (`REG_BINARY` type `0x5F5E10C`), scanning on 2-byte UTF-16LE boundaries to stop cleanly at `\x00\x00` before the trailing 8-byte `FILETIME`.
4. If the decoded value is a GUID token (`{...}`), `_resolve_persisted_storage_token()` looks up `FilePath` under `HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData\<PFN>\PersistedStorageItemTable\ManagedByApp\<GUID>` (and `MostRecentlyUsed`).
5. `resolve_volume_guid_path()` converts UWP `\\?\Volume{...}\...` paths into drive-letter paths (e.g., `C:\...`) via `kernel32.GetVolumePathNamesForVolumeNameW`.

### Step 2: Windows Known Folders & Explorer Shell Folders (`get_windows_screenshots_folders`)
Queries Windows directly (supporting OneDrive Known Folder Move automatically without hardcoding `OneDrive`):
1. `shell32.SHGetKnownFolderPath` for `FOLDERID_Screenshots` (`{B7BEDE81-DF94-4682-A7D8-57A52620B86F}`).
2. `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders` (and `Shell Folders`) for `{B7BEDE81-...}`.
3. Redirected Pictures entries (`My Pictures` and `{0DDD015D-B06C-45D5-8C4C-F59713854639}`) + `\Screenshots`.
4. `SHGetKnownFolderPath(FOLDERID_Pictures)` (`{33E28130-4E1E-4676-835A-98395C3BC3BB}`) + `\Screenshots`.

### Step 3: Default Fallback & Permission Safety
* Appends `Path.home() / "Pictures" / "Screenshots"`.
* `_safe_exists()` catches `OSError` / `PermissionError` on locked directories so discovery never crashes in restricted environments.
* If `create_if_missing=True` and no candidate directory exists yet on a fresh profile, creates the highest-priority folder cleanly.

