#!/usr/bin/env bash
# Build Nexus Macro as a standalone Linux executable.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
    echo "==> Creating virtual environment..."
    python3 -m venv .venv
fi
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements-build.txt

USE_VENDOR="${BUILD_WITH_VENDOR:-1}"
if [[ "$USE_VENDOR" == "1" && ! -x vendor/gamescope/usr/bin/gamescope ]]; then
    if [[ -x ../.vendor/gamescope/usr/bin/gamescope ]]; then
        echo "==> Copying local gamescope from ../.vendor..."
        mkdir -p vendor
        cp -a ../.vendor/gamescope vendor/gamescope
    else
        echo "WARNING: vendor/gamescope is missing. The binary will use system gamescope."
    fi
fi

ADD_DATA=(
    --add-data "templates:templates"
    --add-data "assets:assets"
)
if [[ "$USE_VENDOR" == "1" && -x vendor/gamescope/usr/bin/gamescope ]]; then
    ADD_DATA+=(--add-data "vendor/gamescope:vendor/gamescope")
else
    echo "==> Building WITHOUT bundled gamescope; system gamescope is required."
fi

echo "==> Building with PyInstaller..."
./.venv/bin/python -m PyInstaller \
    --noconfirm \
    --clean \
    --onefile \
    --windowed \
    --name NexusMacro \
    --icon assets/icon.png \
    "${ADD_DATA[@]}" \
    --hidden-import Xlib.ext.xtest \
    app.py

echo
echo "Executable: $PWD/dist/NexusMacro"
echo "Try it with:"
echo "  ./dist/NexusMacro --version"
echo "  ./dist/NexusMacro --selftest"
echo "Install it in the app menu with:"
echo "  ./install.sh"
