#!/usr/bin/env bash
# Install a Nexus Macro release tarball into ~/.local (no sudo).
set -euo pipefail
cd "$(dirname "$0")"

BIN="$PWD/NexusMacro"
if [[ ! -x "$BIN" ]]; then
    echo "ERROR: NexusMacro binary is missing from the release." >&2
    exit 1
fi

install -Dm755 "$BIN" "$HOME/.local/bin/NexusMacro"
# Release installs are not tied to a project folder: use the XDG config.
rm -f "$HOME/.local/bin/NexusMacro.home"

install -Dm644 nexusmacro-64.png \
    "$HOME/.local/share/icons/hicolor/64x64/apps/nexusmacro.png"
install -Dm644 nexusmacro.png \
    "$HOME/.local/share/icons/hicolor/256x256/apps/nexusmacro.png"
install -Dm644 nexusmacro-512.png \
    "$HOME/.local/share/icons/hicolor/512x512/apps/nexusmacro.png"

install -Dm644 NexusMacro.desktop \
    "$HOME/.local/share/applications/NexusMacro.desktop"
ICON_PATH="$HOME/.local/share/icons/hicolor/512x512/apps/nexusmacro.png"
sed -i "s|^Exec=.*$|Exec=$HOME/.local/bin/NexusMacro|" \
    "$HOME/.local/share/applications/NexusMacro.desktop"
sed -i "s|^Icon=.*$|Icon=$ICON_PATH|" \
    "$HOME/.local/share/applications/NexusMacro.desktop"
sed -i '/^Path=/d' "$HOME/.local/share/applications/NexusMacro.desktop"

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi
rm -f "$HOME/.cache/icon-cache.kcache" 2>/dev/null || true

echo "Nexus Macro installed."
echo "  Binary: $HOME/.local/bin/NexusMacro"
echo "  Menu:   search for «Nexus Macro»"
echo "  Config: $HOME/.config/NexusMacro/config.json (created on first save)"
