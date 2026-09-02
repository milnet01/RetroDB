#!/bin/bash
# =============================================================================
# RetroDB - pin the Standalone bundle to the desktop menu (Linux)
# =============================================================================
# packaging/RetroDB.desktop ships with __EXEC__/__ICON__ placeholders because
# the extraction path is only known on the user's machine.  This substitutes
# them against wherever the bundle was actually unpacked and installs the
# result.  The source-install equivalent is scripts/install_launcher.py, which
# needs Python and so cannot run inside the bundle.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/packaging/RetroDB.desktop"
BINARY="$SCRIPT_DIR/retrodb"
ICON="$SCRIPT_DIR/packaging/icons/retrodb-256.png"
DEST_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DEST="$DEST_DIR/RetroDB.desktop"

for required in "$TEMPLATE" "$BINARY" "$ICON"; do
    if [[ ! -e "$required" ]]; then
        echo "ERROR: $required is missing — run this from inside the extracted bundle." >&2
        exit 1
    fi
done

mkdir -p "$DEST_DIR"
sed -e "s|__EXEC__|$BINARY|" -e "s|__ICON__|$ICON|" "$TEMPLATE" > "$DEST"
chmod 644 "$DEST"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DEST_DIR" >/dev/null 2>&1 || true
fi

echo "Installed $DEST"
echo "  Exec=$BINARY"
echo "  Icon=$ICON"
