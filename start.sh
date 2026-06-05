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

# AMD GPU (gfx1032) ROCm compatibility — map to supported gfx1030 architecture
export HSA_OVERRIDE_GFX_VERSION=10.3.0

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

# Check Flask
echo -e "${YELLOW}Checking Flask installation...${NC}"
if $PYTHON -c "import flask" 2>/dev/null; then
    echo -e "${GREEN}✓ Flask is installed${NC}"
else
    echo -e "${YELLOW}Flask not found. Installing dependencies...${NC}"
    $PYTHON -m pip install -r requirements.txt --break-system-packages
fi

# Check requests
if $PYTHON -c "import requests" 2>/dev/null; then
    echo -e "${GREEN}✓ Requests library is installed${NC}"
else
    echo -e "${YELLOW}Installing requests...${NC}"
    $PYTHON -m pip install requests --break-system-packages
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
echo -e "  ${GREEN}➜${NC}  Local:   ${CYAN}http://localhost:5000${NC}"
echo -e "  ${GREEN}➜${NC}  Network: ${CYAN}http://${LOCAL_IP}:5000${NC}"
echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
echo ""

$PYTHON app.py
