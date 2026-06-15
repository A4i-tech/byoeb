#!/bin/bash
# AshaBot Setup Wizard launcher for macOS
# Double-click this file in Finder to start.

set -euo pipefail

echo ""
echo " =========================================="
echo "  AshaBot Setup Wizard — Starting..."
echo " =========================================="
echo ""

# Check Docker
echo "[1/4] Checking Docker Desktop..."
if ! docker info &>/dev/null; then
    osascript -e 'display alert "Docker Desktop is not running." message "Please start Docker Desktop and double-click this file again.\n\nDownload: https://www.docker.com/products/docker-desktop" as critical buttons {"OK"} default button "OK"'
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

# Open browser after delay
(sleep 15 && open http://localhost:5001) &

docker compose -f docker-compose.wizard.yml up
