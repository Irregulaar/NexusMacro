#!/usr/bin/env bash
# Install Nexus Macro in ~/.local (no sudo).
set -euo pipefail
cd "$(dirname "$0")"

PROJECT_DIR="$PWD"
BIN="$PWD/dist/NexusMacro"
if [[ ! -x "$BIN" ]]; then
    echo "ERROR: dist/NexusMacro is missing. Run ./build_linux.sh first."
    exit 1
fi

install -Dm755 "$BIN" "$HOME/.local/bin/NexusMacro"
# Portable config: the installed binary reads this marker and uses
# <project>/config/config.json instead of ~/.config/NexusMacro.
printf '%s\n' "$PROJECT_DIR" > "$HOME/.local/bin/NexusMacro.home"
install -Dm644 assets/icon_64.png \
    "$HOME/.local/share/icons/hicolor/64x64/apps/nexusmacro.png"
install -Dm644 assets/icon.png \
    "$HOME/.local/share/icons/hicolor/256x256/apps/nexusmacro.png"
install -Dm644 assets/icon_512.png \
    "$HOME/.local/share/icons/hicolor/512x512/apps/nexusmacro.png"
install -Dm644 NexusMacro.desktop \
    "$HOME/.local/share/applications/NexusMacro.desktop"

# Use an absolute path so it works even if ~/.local/bin is not in PATH.
sed -i "s|^Exec=.*$|Exec=$HOME/.local/bin/NexusMacro|" \
    "$HOME/.local/share/applications/NexusMacro.desktop"
# Run from the project folder so the portable config is used even when the
# app is opened from the menu.
sed -i '/^Path=/d' "$HOME/.local/share/applications/NexusMacro.desktop"
printf 'Path=%s\n' "$PROJECT_DIR" \
    >> "$HOME/.local/share/applications/NexusMacro.desktop"

# Absolute icon path bypasses a stale icon-theme cache (KDE/GNOME).
ICON_PATH="$HOME/.local/share/icons/hicolor/512x512/apps/nexusmacro.png"
sed -i "s|^Icon=.*$|Icon=$ICON_PATH|" \
    "$HOME/.local/share/applications/NexusMacro.desktop"

rm -f "$HOME/.local/share/applications/TowerPilot.desktop"
rm -f "$HOME/.local/bin/TowerPilot"
rm -f "$HOME/.local/share/icons/hicolor/256x256/apps/towerpilot.png"

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi
# KDE keeps its own icon cache; force it to rebuild the new app icon.
rm -f "$HOME/.cache/icon-cache.kcache" 2>/dev/null || true

echo "Nexus Macro installed."
echo "  Binary: $HOME/.local/bin/NexusMacro"
echo "  Menu:    search for «Nexus Macro»"
echo
echo "If «NexusMacro» is not in PATH, add ~/.local/bin or use the full path."
