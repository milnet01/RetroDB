# platform_utils.py - Cross-platform utilities for RetroDB
# ================================================================================
# Centralized platform detection and OS-specific helpers.
# Used across the application to ensure Linux/Windows/macOS compatibility.
# ================================================================================

import os
import sys
import socket

# =============================================================================
# OS DETECTION
# =============================================================================

IS_WINDOWS = sys.platform == 'win32'
IS_MACOS = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

PLATFORM_NAME = 'Windows' if IS_WINDOWS else ('macOS' if IS_MACOS else 'Linux')


# =============================================================================
# NETWORK UTILITIES
# =============================================================================

def get_local_ip():
    """Get the local network IP address (works on all platforms)"""
    try:
        # Connect to a public DNS to determine local IP (no data is sent)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


# =============================================================================
# TOOL DETECTION
# =============================================================================

def get_tool_install_instructions():
    """Get platform-specific tool installation instructions"""
    if IS_LINUX:
        return {
            'unzip': 'sudo apt install unzip',
            '7z': 'sudo apt install p7zip-full',
            'unrar': 'sudo apt install unrar',
            'chdman': 'sudo apt install mame-tools',
            'all': 'sudo apt install p7zip-full unrar mame-tools',
        }
    elif IS_MACOS:
        return {
            'unzip': 'Built-in on macOS',
            '7z': 'brew install p7zip',
            'unrar': 'brew install unrar',
            'chdman': 'brew install rom-tools  (or build from MAME source)',
            'all': 'brew install p7zip unrar rom-tools',
        }
    else:  # Windows
        return {
            'unzip': 'Built-in on Windows (PowerShell) or install 7-Zip',
            '7z': 'Download 7-Zip from https://www.7-zip.org/',
            'unrar': 'Download WinRAR from https://www.win-rar.com/',
            'chdman': 'Download MAME from https://www.mamedev.org/ (includes chdman)',
            'all': 'Install 7-Zip, WinRAR, and MAME (for chdman)',
        }
