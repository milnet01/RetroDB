#!/bin/bash
# =============================================================================
# RETRODB - Startup Script
# =============================================================================
# This script starts the RetroDB web application
# Usage: ./start.sh
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# AMD GPU ROCm compatibility — gfx1032 has no ROCm kernels of its own and must
# be told to load gfx1030's.  Only set it for a card that actually needs it: on
# a different architecture this loads kernels for the wrong ISA and the ESRGAN
# upscaler hangs or crashes instead of failing cleanly.  An explicit value from
# the environment always wins (Pass 59.17).
if [[ -z "${HSA_OVERRIDE_GFX_VERSION:-}" ]] \
   && command -v rocminfo >/dev/null 2>&1 \
   && rocminfo 2>/dev/null | grep -q 'gfx1032'; then
    export HSA_OVERRIDE_GFX_VERSION=10.3.0
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                                                              ║"
echo "║  ██████╗ ███████╗████████╗██████╗  ██████╗ ██████╗ ██████╗   ║"
echo "║  ██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗██╔══██╗██╔══██╗  ║"
echo "║  ██████╔╝█████╗     ██║   ██████╔╝██║   ██║██║  ██║██████╔╝  ║"
echo "║  ██╔══██╗██╔══╝     ██║   ██╔══██╗██║   ██║██║  ██║██╔══██╗  ║"
echo "║  ██║  ██║███████╗   ██║   ██║  ██║╚██████╔╝██████╔╝██████╔╝  ║"
echo "║  ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═════╝   ║"
echo "║                                                              ║"
echo "║              Retro Gaming ROM Library Manager                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check Python
echo -e "${YELLOW}Checking Python installation...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON=python3
    echo -e "${GREEN}✓ Python 3 found${NC}"
elif command -v python &> /dev/null; then
    PYTHON=python
    echo -e "${GREEN}✓ Python found${NC}"
else
    echo -e "${RED}✗ Python not found! Please install Python 3.${NC}"
    exit 1
fi

# Resolve the port once (PORT -> RETRODB_PORT -> config default) so the banner
# and the browser-open URL below match what app.py actually binds.  app.py
# re-resolves it from the same environment, so nothing is passed through here.
# A malformed value dies now, with the message from server_port.py, rather
# than after a dependency check and a CSS build.
if ! SERVER_PORT=$($PYTHON server_port.py); then
    exit 1
fi

# Check Flask
echo -e "${YELLOW}Checking Flask installation...${NC}"
if $PYTHON -c "import flask" 2>/dev/null; then
    echo -e "${GREEN}✓ Flask is installed${NC}"
else
    echo -e "${YELLOW}Flask not found. Running the installer...${NC}"
    # install.py -> installer_core.select_pip_args, which prefers
    # `--require-hashes -r requirements.lock` and only falls back to an
    # unhashed requirements.txt when no lockfile is present.  It also applies
    # --break-system-packages as a PEP 668 retry rather than unconditionally,
    # so a Debian/Ubuntu system's site-packages is not clobbered up front.
    # Installing by hand here bypassed both controls (Pass 59.12).
    if ! $PYTHON install.py; then
        echo -e "${RED}✗ Dependency install failed — see the output above.${NC}"
        exit 1
    fi
fi

# Create directories if they don't exist
echo -e "${YELLOW}Checking directories...${NC}"
mkdir -p database
mkdir -p static/images/boxart
mkdir -p static/images/screenshots
mkdir -p static/images/systems
mkdir -p static/images/ratings
echo -e "${GREEN}✓ Directories ready${NC}"

# Build CSS
echo -e "${YELLOW}Building CSS bundle...${NC}"
if $PYTHON build_css.py > /dev/null 2>&1; then
    echo -e "${GREEN}✓ CSS bundle built (main.min.css)${NC}"
else
    echo -e "${RED}✗ CSS build failed - using existing bundle${NC}"
fi

# Get local IP (cross-platform via Python)
LOCAL_IP=$($PYTHON -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except Exception:
    print('127.0.0.1')
" 2>/dev/null || echo "127.0.0.1")

# Start the server
echo ""
echo -e "${GREEN}Starting RetroDB server...${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${GREEN}➜${NC}  Local:   ${CYAN}http://localhost:${SERVER_PORT}${NC}"
echo -e "  ${GREEN}➜${NC}  Network: ${CYAN}http://${LOCAL_IP}:${SERVER_PORT}${NC}"
echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
echo ""

# Open the browser a moment after the server binds (background; non-fatal).
( sleep 3; xdg-open "http://localhost:${SERVER_PORT}" >/dev/null 2>&1 || true ) &

$PYTHON app.py
