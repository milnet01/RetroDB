#!/bin/bash
# =============================================================================
# RetroDB - Standalone launcher (Linux)
# =============================================================================
# Ships inside the Standalone zip, NOT in a source install.  The bundle has a
# baked-in Python runtime and no .py files on disk, so this script must not
# reach for `python3`, `server_port.py` or `app.py` — it only execs the
# PyInstaller binary sitting next to it.  The binary resolves its own port and
# opens the browser (see app.py's frozen branch).
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [[ ! -x ./retrodb ]]; then
    echo "ERROR: the 'retrodb' binary is missing from $SCRIPT_DIR."
    echo "       Re-extract the Standalone zip, keeping the folder intact."
    read -r -n 1 -s -p "Press any key to exit..."
    exit 1
fi

exec ./retrodb
