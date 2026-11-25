# Changelog

All notable changes to Nexus Macro. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning.

## 1.5.5 - 2026-11-24

### Fixed
- **Installation on other distributions**: PyInstaller's `LD_LIBRARY_PATH` was
  leaking into `gamescope` and `flatpak`, causing GLIBCXX/libstdc++ errors and
  a false “Sober is not installed as a Flatpak” message. Child processes now use
  `clean_env()`.
- **Video subsystem / display errors**: SDL falls back to Wayland when there is
  no X11 `DISPLAY`, a clear preflight error is shown for TTY/SSH sessions, and
  `flatpak` errors include their stderr.
- **Tab never detected**: `tabimage` now uses unmasked `TM_CCOEFF_NORMED` in
  the top-right band at 0.85–1.05 scale, instead of the masked matcher that
  ranked the header below dozens of bright patches.
- **Window too small on large screens**: the whole UI scales with the desktop
  size (base 1920×1080, clamp 0.80–2.00); override with `QT_SCALE_FACTOR`.

### Added
- One-time **Classic Forfeit** check: opens Settings, scrolls to the bottom,
  reads the toggle, turns it ON if needed and stores
  `classic_forfeit_checked`/`classic_forfeit_on` in config. It never runs again.
- `settingsbutton.png` and `classicforfeitsetting.png` templates.
- Launcher environment and graphical-session diagnostics.

### Changed
- `tabimage` matching is now independent of the HUD heuristic.
- README troubleshooting for the installation errors, AI install prompt and
  window scaling.

## 1.5.4 - 2026-11-24

### Added
- Reconnect-screen handling: `reconnectbutton.png` is detected but never
  clicked. Nexus Macro stops the engine, closes Sober/gamescope, relaunches it
  and retries later if the connection is still down.
- Portable project config: `<project>/config/config.json`, with automatic
  migration from `~/.config/NexusMacro`, a `NexusMacro.home` marker for the
  installed binary and `Path=` in the desktop entry.
- `--config-path` CLI flag.
- Multi-size application icons (64/256/512), absolute icon path in the desktop
  entry, `setDesktopFileName`, and KDE/GNOME icon-cache refresh on install.
- README screenshots, release packaging, MIT license and this changelog.
- GitHub Actions release workflow and release installer.

### Changed
- Subtitle is now “Build a Tower Defense Autopilot”.
- Removed the **Open Templates** button from About.
- `install.sh` installs the 64/256/512 icons and refreshes the desktop/icon
  caches.

### Fixed
- The window/taskbar icon now resolves through an absolute desktop icon path
  instead of a possibly stale theme cache.

## 1.5.3 - 2026-11-24

### Added
- Fuse and Best Place share a single Build menu: Build → Fuse → Place Best →
  Stop.
- Tab is only sent while `tabimage.png` is visible.

### Fixed
- Best Place no longer fails with “Build button not visible” after Fuse closed
  the menu.
- Tab no longer fires blindly or waits for Build/Spawner to be visible.

## 1.5.2 - 2026-11-24

### Added
- Manual Fuse/Best Place runs inside the main engine instead of a second
  engine, preventing concurrent Build clicks.
- Shop scrolling tolerates the close-button flicker after a purchase.
- Battle transition is verified for 2.5 s before a warning is logged.

### Fixed
- Scheduled spawner purchases now scroll instead of stopping after the first
  batch of buys.
- Manual and automatic actions can no longer fight over the Build menu.

## 1.5.1 - 2026-11-24

### Fixed
- Discard false positive: the colour fallback is centred, stricter, and a
  candidate that survives its click is ignored for 60 s.
- Build menu verification no longer aborts because a red Build badge was
  mistaken for the Discard button.

## 1.5.0 - 2026-11-24

### Changed
- Complete refactor: engine split into `automation/context`, `detection`,
  `navigation`, `shop`, `build` and `spawner`; Qt controller and UI pages
  extracted.
- Grayscale template matching, per-control search regions and more NCC
  candidates. Idle tick dropped from ~884 ms to ~75 ms.
- Portable and robust config with atomic writes, backups and tolerant loading.

### Fixed
- Pre-battle retry, stop cancelling Auto Reconnect, Play after Tab, shop
  session gating, live config updates and many smaller reliability issues.
