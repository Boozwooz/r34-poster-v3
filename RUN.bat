@echo off
title BoozStudio - R34 Poster
color 0A

echo.
echo  ============================================================
echo   BoozStudio - R34 Poster  v3.2.0
echo  ============================================================
echo.

:: --- 1. Check Python ---
echo  [1/4] Checking Python installation...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] Python is not installed or not in PATH!
    echo.
    echo  Please download and install Python 3.10 or newer:
    echo  https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: During install, check the box that says
    echo  "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
python --version
echo  Python found. OK
echo.

:: --- 2. Install packages ---
echo  [2/4] Installing required packages (first time may take a few minutes)...
echo  Please wait and do not close this window.
echo.
pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] Failed to install packages.
    echo  Make sure you are connected to the internet and try again.
    echo.
    pause
    exit /b 1
)
echo  Packages installed. OK
echo.

:: --- 3. Install browser ---
echo  [3/4] Setting up upload browser (first time only, may take a moment)...
python -m playwright install chromium 2>nul
echo  Browser ready. OK
echo.

:: --- 4. Launch ---
echo  [4/4] Launching BoozStudio R34 Poster...
echo.
echo  ============================================================
echo.
python app.py

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] The application closed with an error (code %errorlevel%).
    echo  Check the output above for details.
    echo.
    pause
)
