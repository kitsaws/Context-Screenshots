# `config.py` — Application Mappings, Overlay Filters & Constants

`config.py` centralizes lookup tables, exclusion rules, matching tolerances, and exposes watch/settings helpers imported across the app.

---

## Key Data Structures

1. **`FRIENDLY_APP_NAMES`**
   * Maps lowercase Windows executable names (`process_name`) to human-readable subfolder names across categories:
     * **Browsers:** `chrome.exe` -> `Chrome`, `brave.exe` -> `Brave`, `msedge.exe` -> `Edge`, `firefox.exe` -> `Firefox`, `opera.exe` -> `Opera`
     * **Dev & Productivity:** `code.exe` -> `VS Code`, `devenv.exe` -> `Visual Studio`, `antigravity ide.exe` -> `Antigravity IDE`, `windowsterminal.exe` -> `Terminal`, `cmd.exe`, `powershell.exe` / `pwsh.exe`, `postman.exe`, `notion.exe`, `obsidian.exe`, `figma.exe`
     * **Communication & Media:** `discord.exe`, `spotify.exe`, `slack.exe`, `telegram.exe`, `whatsapp.exe`
     * **Office & System:** `explorer.exe`, `winword.exe`, `excel.exe`, `powerpnt.exe`, `acrobat.exe`
     * **Games & Launchers:** `genshinimpact.exe` / `yuanshen.exe` -> `Genshin Impact`, `honkaistarrail.exe` / `starrail.exe` -> `Honkai Star Rail`, `zenlesszonezero.exe`, `valorant.exe` / `valorant-win64-shipping.exe`, `riotclientux.exe` / `riot client.exe`, `steam.exe`, `league of legends.exe` / `leagueclient.exe`, `overwatch.exe`, `cs2.exe`, `dota2.exe`, `minecraft.exe` / `javaw.exe` -> `Minecraft`
   * Processes not in `FRIENDLY_APP_NAMES` automatically fall back to stripping `.exe` and capitalizing the process name (`get_friendly_app_name()` in `window_detector.py`).

2. **Host & Overlay Exclusions**
   * **`SNIP_HOST_PROCESSES`:** Windows capture and shell flyouts (`screenclippinghost.exe`, `snippingtool.exe`, `shellexperiencehost.exe`, `searchhost.exe`, `startmenuexperiencehost.exe`, `textinputhost.exe`, `taskmgr.exe`, `lockapp.exe`). Ignored during active-window tracking so opening Snipping Tool doesn't overwrite the app behind it.
   * **`OVERLAY_PROCESSES`:** Game/HUD overlay executables (`gameoverlayui.exe`, `gamebar.exe`, `gamebarft.exe`, `nvidia share.exe`, `rtss.exe`, `rtsshooks.exe`, `overwolf.exe`, `screensplitterhook64app.exe`).
   * **`KNOWN_OVERLAY_TITLES`:** Substring matches for overlay windows (`discord overlay`, `geforce in-game overlay`, `steam overlay`, `xbox game bar`, `game bar`, `rtss`, etc.).
   * **`IGNORE_PROCESSES`:** Union `SNIP_HOST_PROCESSES | OVERLAY_PROCESSES` skipped during Z-order window enumeration.

3. **Tolerances & Watch Folder Delegation**
   * `DRAG_MATCH_TOLERANCE_PX = 8`, `DRAG_MAX_AGE_SEC = 10.0`, `FILE_READY_TIMEOUT_SEC = 8.0`.
   * `ORGANIZED_DESTINATION_DIR = None` (legacy static override; runtime configuration is persisted dynamically via `snipping_settings`).
   * `resolve_screenshots_folders(create_if_missing=True)` delegates to `snipping_settings.resolve_watch_folders()`.

