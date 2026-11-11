# `window_detector.py` — 3-Tier Application & Window Identification

`window_detector.py` correlates screenshot geometry and focus history against live Windows desktop windows to return `(app_name, clean_title)` without reading any image pixels.

---

## 1. Desktop Enumeration & Overlay Filtering

* **`get_all_monitors()`:** Enumerates physical display bounding rectangles via `user32.EnumDisplayMonitors`.
* **`get_visible_windows()`:**
  * Opens the interactive desktop (`OpenDesktopW('Default', ...)`) and enumerates windows in top-to-bottom Z-order via `EnumDesktopWindows` (falling back to `EnumWindows`).
  * Skips invisible, minimized (`IsIconic`), tiny (`w <= 20 or h <= 20`), DWM-cloaked (`DwmGetWindowAttribute` `DWMWA_CLOAKED != 0` — hidden virtual desktops or suspended UWP apps), `IGNORE_PROCESSES`, and untitled `WS_EX_TOOLWINDOW` tooltips.
  * Computes visual bounds using `DWMWA_EXTENDED_FRAME_BOUNDS` (strips invisible Windows 11 drop-shadow borders).
* **`is_overlay_window(process_name, title, ex_style)`:** Filters out `OVERLAY_PROCESSES`, untitled or overlay `discord.exe` windows, `KNOWN_OVERLAY_TITLES`, and click-through windows carrying `WS_EX_TRANSPARENT`.

---

## 2. The 3-Tier Identification Pipeline (`identify_window_from_snip`)

### Tier 1: Last Active Foreground Window *(Prevents Background Apps/Games from Stealing Focus)*
Checks `last_active_window` (excluding `explorer.exe`, `unknown`, and overlays) against the screenshot:
1. **Rectangular Drag (`snip_rect`):** Computes intersection area (`compute_overlap_area`). If `overlap / snip_area >= 0.55`, the active foreground window wins immediately—even if a fullscreen game is running behind a browser.
2. **Window Snip Click (`click_pt`):** If the click coordinate lies inside `active_rect`, active window wins.
3. **Fullscreen / Print Screen (`image_size`):** If image dimensions match any monitor within `+-4px` and `active_rect` overlaps that monitor, active window wins.

### Tier 2: Spatial Z-Order Geometry *(Handles Second Monitors & Background Snips)*
Triggered if you dragged or clicked on a window that wasn't currently focused (e.g., an app on a second monitor):
1. **Drag Overlap:** Scans visible windows in top-to-bottom Z-order; selects the first non-overlay, non-`explorer.exe` window covering `>= 45%` of `snip_rect` (or the largest overlap area).
2. **Click Containment:** Picks the topmost visible window containing `click_pt` (ignoring `Program Manager`).
3. **Fullscreen Monitor Match:** Matches monitor bounds `+-4px` and picks the topmost non-`explorer.exe` window overlapping that monitor.

### Tier 3: Safe Fallbacks
1. `last_active_window` (if valid non-`explorer.exe` process).
2. Topmost titled non-`explorer.exe` window on desktop.
3. `("General", "")` when no window matches.

---

## 3. Filename Sanitization (`clean_window_title` & `get_friendly_app_name`)

`clean_window_title(title, app_name)` keeps filenames clean and Windows-safe:
* Strips leading notification badges like `(1)` or `[99+]`.
* Strips redundant trailing app names (`- Google Chrome`, `- Brave`, `- Microsoft Edge`, `- Mozilla Firefox`, `- Visual Studio Code`, `- Antigravity IDE`, or `- <app_name>`).
* Replaces forbidden Windows filename characters (`\ / * ? : " < > |`) with `-`.
* Strips non-ASCII symbols/emojis (`[^\x20-\x7E]+`), collapses whitespace, and caps length at `65` characters.

