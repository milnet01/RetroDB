#!/bin/bash
# =============================================================================
# RETRODB - macOS Startup Script
# =============================================================================
# Double-click this file in Finder to start RetroDB
# Or run from Terminal: ./start.command
# =============================================================================

# Change to the script's directory
cd "$(dirname "$0")"

echo ""
echo "========================================================"
echo "  RetroDB - Retro Gaming ROM Library Manager"
echo "========================================================"
echo ""

# Check Python
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "ERROR: Python not found! Install from python.org or: brew install python3"
    echo "Press any key to exit..."
    read -n 1
    exit 1
fi
echo "  OK: Python found ($($PYTHON --version))"

# Check dependencies
if ! $PYTHON -c "import flask" 2>/dev/null; then
    echo "  Installing dependencies..."
    $PYTHON -m pip install -r requirements.txt
fi

# Create directories
mkdir -p database logs data
mkdir -p static/images/{boxart,screenshots,systems,ratings}

# Build CSS
$PYTHON build_css.py > /dev/null 2>&1

echo ""
echo "========================================================"
echo "  Starting RetroDB server..."
echo "  Local:   http://localhost:5000"
echo "  Press Ctrl+C to stop the server"
echo "========================================================"
echo ""

$PYTHON app.py
