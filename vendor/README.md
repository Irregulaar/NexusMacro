# Local gamescope

This folder contains an extracted copy of **gamescope 3.17.0** from the
CachyOS package (`x86_64_v3`), used so Nexus Macro works without a system-wide
gamescope install.

- Project: https://github.com/ValveSoftware/gamescope
- License: BSD-2-Clause / BSD-3-Clause (see the original project).
- The copy includes local libraries that were missing on the host:
  `libavif`, `libseat`, `libXRes` and `libyuv`.

If you install gamescope with `sudo pacman -S gamescope`, Nexus Macro will use
the system version and you can delete this folder.
