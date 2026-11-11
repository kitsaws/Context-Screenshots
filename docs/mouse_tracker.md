# `mouse_tracker.py` — Input Geometry & Foreground Focus Tracker

`mouse_tracker.py` runs lightweight background tracking to answer two questions when a screenshot appears on disk:
1. **Where on the screen(s) did the user drag or click?**
2. **Which real application had focus right before Snipping Tool appeared?**

---

## How It Works

1. **Per-Monitor DPI Awareness (`DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2`)**
   * Calls `user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))` at module import so raw `pynput` cursor coordinates match physical display pixels cleanly even across monitors with mixed DPI scaling (e.g., 100% + 125%/150%).

2. **Mouse Drag & Click Listener (`MouseTracker._on_click`)**
   * Uses `pynput.mouse.Listener` (daemon thread) to record left mouse button press and release coordinates (`x, y`).
   * Calculates bounding box `rect = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))`, width `w`, and height `h`:
     * If `w > 10 and h > 10`: recorded in `self.drags` (`deque(maxlen=30)`) with `rect`, `w`, `h`, `time`, and `duration`.
     * Otherwise: recorded in `self.clicks` (`deque(maxlen=30)`) as a click point `pt` (used for Window Snip Mode).
   * All shared structures are synchronized via `self._lock = threading.Lock()`.

3. **Active Foreground Window Poller (`MouseTracker._track_foreground_loop`)**
   * Polls `user32.GetForegroundWindow()` every `0.12` seconds while running.
   * Resolves process name via `psutil.Process(pid).name().lower()`, window title via `GetWindowTextW`, and extended visual bounds via `dwmapi.DwmGetWindowAttribute(..., DWMWA_EXTENDED_FRAME_BOUNDS)` (falling back to `GetWindowRect`).
   * **Why Snip Hosts & Overlays Are Skipped:** When you press `Win + Shift + S`, Windows transfers focus to `ScreenClippingHost.exe` or `SnippingTool.exe`. By ignoring `SNIP_HOST_PROCESSES`, Discord overlays (`'overlay' in t_lower and pname == 'discord.exe'`), and tiny windows (`w <= 50 or h <= 50`), `self.last_active_window` preserves the *actual* window you were looking at.

4. **Matching Saved Images to Input (`find_matching_drag` & `get_recent_click`)**
   * **`find_matching_drag(target_w, target_h, tolerance=12, max_age=12.0)`:**
     1. Searches recent drags within `max_age` seconds matching `target_w` and `target_h` within `tolerance` pixels, choosing the closest dimension delta (`dw + dh`).
     2. Checks common DPI scaling ratios (`[1.25, 1.5, 0.8, 0.67]`) in case OS scaling differs between capture API and coordinates.
     3. Falls back to the most recent drag within `max_age`.
   * **`get_recent_click(max_age=12.0)`:** Returns the latest click coordinate within `max_age`.

