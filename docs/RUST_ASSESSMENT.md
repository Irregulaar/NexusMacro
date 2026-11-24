# Rust assessment

Status: **research**, not a commitment. The current project stays Python for
1.5.x.

## Short answer

Yes, Rust can target **Linux and Windows** from one codebase and produce much
smaller binaries with lower RAM. But a full rewrite would be a new project, not
a refactor, and it would not by itself fix the game-specific detection or the
Windows focus/anti-cheat problems.

## What Rust would improve

| Metric | Python + PyInstaller | Rust |
|---|---|---|
| Binary | ~100–180 MB | ~10–30 MB (UI dependent) |
| Startup | 1–2 s | <100 ms |
| RAM | High (Qt + Python + OpenCV) | Lower |
| Distribution | Onefile extraction | Single native binary |
| Type safety | Runtime | Compile time |
| CI build | PyInstaller | Cargo + cross targets |

These are real wins, especially for “download and run”. They are not gameplay
wins.

## What it would not improve

- Template matching: `opencv-python` already calls native C++; a Rust OpenCV
  wrapper calls the same code. The 884→75 ms improvement came from grayscale,
  search regions and candidate limits, not from Python.
- Click timing: sleeps, game animations and cooldowns dominate.
- Windows focus: `SendInput` still moves the real cursor and Roblox still needs
  focus.
- Anti-cheat: a Rust binary is still automation; the risk does not disappear.
- Templates/UI layout: still need calibration and maintenance.

## The expensive parts

1. **UI**: Qt/PySide6 is not maturely bindable from Rust. Options:
   - `egui` / `iced` / `slint`: pure Rust, small, but a new look and a full page
     rewrite.
   - Tauri: web UI; needs WebView2 on Windows and WebKitGTK on Linux; not a
     single self-contained binary.
2. **Vision**: the `opencv` crate requires OpenCV; bundling it on Windows is
   painful. Pure Rust (`imageproc` + custom NCC/SIMD) is possible but needs
   performance work to match OpenCV.
3. **Backends**: `x11rb` + XTest on Linux; `windows` crate + WGC/DXGI +
   SendInput on Windows. Two implementations, one interface.
4. **Parity**: re-port the 60 tests and every game-flow fix (shop flicker,
   discard, Build menu, reconnect, Tab image, focus recovery).
5. **Testing**: a real Linux and a real Windows machine.

Estimated effort for parity: several weeks to a few months depending on UI
choice and how much of OpenCV is kept.

## Cross-platform shape

```text
crates/core       engine, state machine, vision interface, config
crates/linux      x11rb capture, XTest, gamescope/Sober launcher
crates/windows    WGC/DXGI capture, SendInput, Roblox launcher/focus
crates/ui         egui or iced (or a Tauri frontend)
```

Shared:

- config (`serde`), paths, logging (`tracing`), error types (`thiserror`)
- template matcher (OpenCV crate or custom)
- shop/build/spawner state machines (port from Python)
- tests (golden frames, synthetic UI, no real game required)

Platform-specific:

- capture and input
- window discovery/focus
- launcher (gamescope/Sober vs Roblox)
- packaging

## Recommended sequence

1. Ship Python 1.5.x (Linux) and the GitHub release.
2. If Windows is a priority, do the **Python Windows foreground backend** first
   (`docs/WINDOWS_PORT.md`). It is much cheaper and validates the concept.
3. If binary size/RAM become the main complaint, build a **Rust spike**:
   - one window capture path per OS
   - one template match + click
   - measure tick, size, startup
4. Only then decide on a full Rust v2. Keep the Python version as the reference
   and test oracle during the port.

## Verdict

Rust is a good long-term fit for a small cross-platform binary. It is a bad
first move if the goal is “make the macro work better” or “add Windows soon”.
Python can carry the Windows foreground MVP; Rust is the optimization after
the product is proven.
