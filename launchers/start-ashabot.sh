#!/bin/bash
# AshaBot Setup Wizard launcher for Linux
# Right-click → "Run as Program" (Ubuntu/GNOME), or: bash start-ashabot.sh

set -euo pipefail

echo ""
echo " =========================================="
echo "  AshaBot Setup Wizard — Starting..."
echo " =========================================="
echo ""

# Check Docker
echo "[1/4] Checking Docker..."
if ! docker info &>/dev/null; then
    echo ""
    echo " ERROR: Docker is not running."
    echo " Please start Docker Desktop (or Docker Engine) and try again."
    echo ""
    echo " Download Docker Desktop: https://www.docker.com/products/docker-desktop"
    echo ""
    read -rp " Press Enter to exit..."
    exit 1
fi
echo "       Docker is running."

# Create workspace
WORKSPACE="$HOME/ashabot"
echo "[2/4] Creating workspace at $WORKSPACE ..."
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

# Download compose file
echo "[3/4] Downloading wizard..."
curl -fsSL -o docker-compose.wizard.yml \
    https://github.com/A4i-tech/byoeb/releases/download/v1.0.0-local-setup/docker-compose.wizard.yml
echo "       Downloaded."

# Launch
echo "[4/4] Starting AshaBot wizard..."
echo ""
echo " Setup wizard will open in your browser at http://localhost:5001"
echo " (may take 30-60 seconds on first run while images download)"
echo ""
echo " Keep this window open while using the wizard."
echo " Close it when you are done."
echo ""

# Open browser after delay (xdg-open works on most Linux desktops)
(sleep 15 && xdg-open http://localhost:5001 &>/dev/null) &

docker compose -f docker-compose.wizard.yml up
