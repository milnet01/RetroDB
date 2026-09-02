#!/bin/bash
# =============================================================================
# RetroDB - Standalone launcher (macOS)
# =============================================================================
# Double-click in Finder.  See packaging/standalone/start.sh for why this must
# not invoke Python: the bundle ships no .py files.
# =============================================================================

cd "$(dirname "$0")" || exit 1

if [[ ! -x ./retrodb ]]; then
    echo "ERROR: the 'retrodb' binary is missing from $(pwd)."
    echo "       Re-extract the Standalone zip, keeping the folder intact."
    read -r -n 1 -s -p "Press any key to exit..."
    exit 1
fi

exec ./retrodb
