@echo off
setlocal enabledelayedexpansion
title AshaBot Setup Wizard

echo.
echo  ==========================================
echo   AshaBot Setup Wizard — Starting...
echo  ==========================================
echo.

:: Check Docker
echo [1/4] Checking Docker Desktop...
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Docker Desktop is not running.
    echo  Please start Docker Desktop and double-click this file again.
    echo.
    echo  Download Docker Desktop: https://www.docker.com/products/docker-desktop
    echo.
    pause
    exit /b 1
)
echo        Docker is running.

:: Create workspace
echo [2/4] Creating workspace at %USERPROFILE%\ashabot ...
mkdir "%USERPROFILE%\ashabot" 2>nul
cd /d "%USERPROFILE%\ashabot"

:: Download compose file
echo [3/4] Downloading wizard...
curl -fsSL -o docker-compose.wizard.yml https://raw.githubusercontent.com/A4i-tech/byoeb/a4i/main/docker-compose.wizard.yml
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Download failed. Check your internet connection and try again.
    echo.
    pause
    exit /b 1
)
echo        Downloaded.

:: Launch
echo [4/4] Starting AshaBot wizard...
echo.
echo  Setup wizard will open in your browser at http://localhost:5001
echo  (may take 30-60 seconds on first run while images download)
echo.
echo  Keep this window open while using the wizard.
echo  Close it when you are done.
echo.

:: Open browser after short delay
start "" cmd /c "timeout /t 15 /nobreak >nul && start http://localhost:5001"

docker compose -f docker-compose.wizard.yml up

pause
