#!/usr/bin/env bash
# Build and package a release tarball.
#   SKIP_BUILD=1     reuse dist/NexusMacro
#   BUILD_WITH_VENDOR=1  bundle vendor/gamescope (default: 0 for releases)
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(grep -m1 '^APP_VERSION = ' nexusmacro/paths.py | sed -E 's/.*"([^"]+)".*/\1/')"
if [[ -z "$VERSION" ]]; then
    echo "ERROR: could not read APP_VERSION." >&2
    exit 1
fi

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
    BUILD_WITH_VENDOR="${BUILD_WITH_VENDOR:-0}" ./build_linux.sh
fi
if [[ ! -x dist/NexusMacro ]]; then
    echo "ERROR: dist/NexusMacro is missing." >&2
    exit 1
fi

NAME="NexusMacro-${VERSION}-linux-x86_64"
STAGE="release/${NAME}"
rm -rf "$STAGE"
mkdir -p "$STAGE"

cp dist/NexusMacro "$STAGE/NexusMacro"
cp packaging/install-release.sh "$STAGE/install.sh"
chmod +x "$STAGE/install.sh"
cp NexusMacro.desktop "$STAGE/NexusMacro.desktop"
cp assets/icon_64.png "$STAGE/nexusmacro-64.png"
cp assets/icon.png "$STAGE/nexusmacro.png"
cp assets/icon_512.png "$STAGE/nexusmacro-512.png"
cp README.md LICENSE CHANGELOG.md "$STAGE/"

ARCHIVE_NAME="${NAME}.tar.gz"
ARCHIVE="release/${ARCHIVE_NAME}"
tar -czf "$ARCHIVE" -C release "$NAME"
# The checksum file must contain only the basename, so it verifies after
# download: sha256sum -c NexusMacro-...tar.gz.sha256
( cd release && sha256sum "$ARCHIVE_NAME" > "${ARCHIVE_NAME}.sha256" )

echo
echo "Release artifact:"
echo "  $ARCHIVE"
echo "  ${ARCHIVE}.sha256"
