#!/bin/bash
# =============================================================================
# RETRODB — Setup Script (Entry Point)
# =============================================================================
# This is the first thing a new user runs after downloading RetroDB.
# It ensures Python 3, pip, and tkinter are installed at the system level,
# then launches the graphical installer (install_gui.py).
#
# Falls back to the CLI installer (install.py) if tkinter can't be set up.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
# =============================================================================

set -e

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# ── Script directory ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Banner ───────────────────────────────────────────────────────────────────
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
echo "║                     FIRST-TIME SETUP                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Detect distro ────────────────────────────────────────────────────────────
DISTRO="unknown"

if [ -f /etc/os-release ]; then
    . /etc/os-release
    ID_COMBINED="$ID $ID_LIKE"
    case "$ID_COMBINED" in
        *nobara*|*fedora*|*rhel*|*centos*)
            DISTRO="fedora"
            ;;
        *debian*|*ubuntu*|*mint*|*pop*)
            DISTRO="debian"
            ;;
        *arch*|*manjaro*|*endeavour*)
            DISTRO="arch"
            ;;
        *opensuse*|*suse*)
            DISTRO="suse"
            ;;
    esac
    echo -e "  Detected: ${BOLD}${PRETTY_NAME:-$ID}${NC}"
else
    echo -e "  ${YELLOW}Could not detect distribution${NC}"
fi
echo ""

# ── Helper: install a system package ─────────────────────────────────────────
install_pkg() {
    local pkg_fedora="$1"
    local pkg_debian="$2"
    local pkg_arch="$3"
    local pkg_suse="${4:-$1}"

    echo -e "  ${YELLOW}Installing with sudo (you may be prompted for your password)...${NC}"

    case "$DISTRO" in
        fedora)  sudo dnf install -y "$pkg_fedora" ;;
        debian)  sudo apt-get install -y "$pkg_debian" ;;
        arch)    sudo pacman -S --noconfirm "$pkg_arch" ;;
        suse)    sudo zypper install -y "$pkg_suse" ;;
        *)
            echo -e "  ${RED}Cannot auto-install on this distro.${NC}"
            echo -e "  Please install the equivalent of '${BOLD}$pkg_fedora${NC}' manually."
            return 1
            ;;
    esac
}

# ── Step 1: Python 3 ────────────────────────────────────────────────────────
echo -e "${BOLD}[1/3]${NC} Checking Python 3..."

if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1)
    echo -e "  ${GREEN}✓${NC} $PY_VER"
else
    echo -e "  ${YELLOW}Python 3 not found${NC}"
    install_pkg "python3" "python3" "python" || {
        echo -e "  ${RED}✗ Python 3 is required. Please install it and run this script again.${NC}"
        exit 1
    }
    if ! command -v python3 &>/dev/null; then
        echo -e "  ${RED}✗ Python 3 installation failed${NC}"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} $(python3 --version)"
fi

# ── Step 2: pip ──────────────────────────────────────────────────────────────
echo -e "${BOLD}[2/3]${NC} Checking pip..."

if python3 -m pip --version &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} pip available"
else
    echo -e "  ${YELLOW}pip not found${NC}"
    install_pkg "python3-pip" "python3-pip" "python-pip" || {
        # Try ensurepip as fallback
        python3 -m ensurepip --default-pip 2>/dev/null || {
            echo -e "  ${RED}✗ pip is required. Please install python3-pip and run this script again.${NC}"
            exit 1
        }
    }
    if python3 -m pip --version &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} pip installed"
    else
        echo -e "  ${RED}✗ pip installation failed${NC}"
        exit 1
    fi
fi

# ── Step 3: tkinter ─────────────────────────────────────────────────────────
echo -e "${BOLD}[3/3]${NC} Checking tkinter (for graphical installer)..."

if python3 -c "import tkinter" &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} tkinter available"
    USE_GUI=true
else
    echo -e "  ${YELLOW}tkinter not found${NC}"
    install_pkg "python3-tkinter" "python3-tk" "tk" "python3-tk" && {
        if python3 -c "import tkinter" &>/dev/null; then
            echo -e "  ${GREEN}✓${NC} tkinter installed"
            USE_GUI=true
        else
            echo -e "  ${YELLOW}tkinter still not working — using CLI installer instead${NC}"
            USE_GUI=false
        fi
    } || {
        echo -e "  ${YELLOW}Could not install tkinter — using CLI installer instead${NC}"
        USE_GUI=false
    }
fi

# ── Launch installer ────────────────────────────────────────────────────────
echo ""

if [ "$USE_GUI" = true ] && [ -f "$SCRIPT_DIR/install_gui.py" ]; then
    echo -e "${GREEN}Launching graphical installer...${NC}"
    echo ""
    python3 "$SCRIPT_DIR/install_gui.py"
    EXIT_CODE=$?
else
    echo -e "${GREEN}Running CLI installer...${NC}"
    echo ""
    python3 "$SCRIPT_DIR/install.py"
    EXIT_CODE=$?
fi

exit $EXIT_CODE
