# Windows port — feasibility and plan

Status: **research / design**, not implemented.

The current 1.5.x code is Linux-only because it talks to gamescope's private
Xwayland through Xlib/XTest. On Windows there is no gamescope and no Sober;
the macro would drive the normal Roblox client.

## The honest summary

A **foreground-only** Windows mode is feasible with moderate work. A
background, non-intrusive mode like the Linux one is **not realistic** with the
normal Roblox client and would carry a high anti-cheat risk.

The user's proposed model is the right one:

> On Play, bring the Roblox window to the front and keep it focused; the macro
> captures that window and sends normal mouse/keyboard input. If focus is lost,
> pause and recover.

That is how a Windows build should behave.

## What changes

### 1. A real backend interface

The engine already separates the backend in `nexusmacro/backend.py`, but the
rest of the code assumes a few X11 concepts. Before Windows, extract:

```text
WindowBackend
  connect() / close()
  capture() -> BGR frame
  size / client rect
  focus()
  move(x, y) / click(x, y) / click_series(...)
  scroll(...) / drag(...)
  key(name)
```

Then implement:

- `X11Backend` (current) for Linux/gamescope.
- `Win32Backend` for Windows/Roblox.

The engine, vision, shop, build and spawner components should not import Xlib.

### 2. Capture on Windows

Options, in order of preference:

1. **Windows Graphics Capture (WGC) + Direct3D 11** — modern, fast, can capture
   a specific window (HWND). Rust crate: `windows-capture`; Python options:
   `windows-capture` bindings or a small native helper.
2. **DXGI Desktop Duplication** (`dxcam` in Python, `dxgi` in Rust) — very fast
   for a visible window; captures the desktop region of the window.
3. **`PrintWindow` / BitBlt** — fallback, slower, can fail with hardware
   acceleration.

The game must stay **visible** (not minimized) for reliable capture. Windows
may throttle occluded/minimized windows.

Set the process **DPI-aware** and capture the **client area** of the Roblox
window. Click coordinates must be converted from client coordinates to screen
coordinates; account for the title bar and borders.

### 3. Input and focus on Windows

- `SendInput` (Win32) for mouse/keyboard. This moves the **real cursor** and
  requires the Roblox window to be foreground.
- Background clicks with `PostMessage(WM_LBUTTONDOWN)` are unreliable and may
  be ignored by Roblox/anti-cheat; do not depend on them.
- Bring the window to the front with:
  - `ShowWindow(hwnd, SW_RESTORE)`
  - `SetForegroundWindow(hwnd)`
  - `AttachThreadInput` workaround if Windows refuses
  - optionally `SetWindowPos(HWND_TOPMOST)` then remove topmost
- Verify `GetForegroundWindow() == hwnd` before every action group. If focus is
  lost, pause and retry; never click blindly into another window.
- The user must not move the physical mouse or alt-tab during a run.

### 4. Launcher and window discovery

- Launch Roblox with the `roblox://experience?placeId=...` URI (or the Roblox
  player executable).
- Find the window by process/title/class (`RobloxPlayerBeta`), not by a fixed
  X11 class.
- Wait for the client area to reach 1280x720 (or resize it) before starting.
- "Play" becomes: focus the Roblox window, click Play, wait for the match HUD.

### 5. Configuration and UI

- Qt/PySide6 works on Windows. The existing UI can be reused.
- Config path: `%APPDATA%\NexusMacro\config.json` via `QStandardPaths`; optional
  portable mode next to the executable.
- The launcher/gamescope settings must be hidden or replaced by Windows
  settings (Roblox path, window title, focus mode).
- Packaging: PyInstaller on Windows, `--windowed`; Qt/OpenCV increase the size
  (roughly 100–180 MB). This is the main argument for a Rust v2.

### 6. Template calibration

The game UI is likely the same at 1280×720, but the Windows client may render
fonts/DPI differently. Expect to recalibrate some crops. The multi-scale search
helps, but it is not a guarantee.

## Difficulty and risks

| Area | Difficulty | Notes |
|---|---|---|
| Backend abstraction | Medium | Mechanical but touches everything. |
| WGC/DXGI capture | Medium | Mature libraries; window/client coordinates. |
| SendInput + focus | Medium | Works, but real cursor and focus stealing. |
| Background mode | High / uncertain | Anti-cheat and Windows focus rules. |
| Roblox anti-cheat | **High risk** | Byfron/Hyperion on Windows; automation may be flagged. |
| UI/config port | Low–medium | Qt is cross-platform. |
| Packaging | Medium | PyInstaller works; size is large. |
| Testing | Medium | Needs a real Windows PC/VM; anti-cheat in a VM is a problem. |

A basic foreground-only MVP is roughly **1–2 weeks** of focused work. Parity
with the current Linux reliability, tests and packaging is closer to **3–4
weeks**, plus real Windows testing.

## Recommended path

1. Finish and ship the Linux 1.5.x release.
2. Refactor the backend into a platform interface (benefits Linux too).
3. Implement a Windows **foreground-only** MVP:
   - launch/focus Roblox
   - capture the client area
   - SendInput clicks/keys
   - run a subset: Play, Tab, Battle, Spawners
4. Test on a real Windows machine; measure ban risk and reliability.
5. Only then decide whether Rust is worth it. Rust does not remove the focus or
   anti-cheat problems; it only changes the implementation language and binary
   size.

## What would make Windows impossible

- If Roblox's anti-cheat blocks synthetic `SendInput` input.
- If the client refuses to render/capture while unfocused (background mode).
- If the user cannot keep the window focused during a run.

In those cases, the honest answer is: Windows support would be limited to a
manual, focused, single-window mode, and the project should say so clearly.
