@echo off
title BoozStudio - R34 Poster
color 0A
chcp 65001 > nul

echo.
echo  ============================================================
echo   BoozStudio ^— R34 Poster  v3.0
echo  ============================================================
echo.

:: ─────────────────────────────────────────────
:: 1. Check Python
:: ─────────────────────────────────────────────
echo  [1/4] Checking Python installation...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] Python was not found on your system!
    echo.
    echo  Please install Python 3.10 or newer from:
    echo  https://www.python.org/downloads/
    echo.
    echo  Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo         Found: %%v
echo.

:: ─────────────────────────────────────────────
:: 2. Install Python packages
:: ─────────────────────────────────────────────
echo  [2/4] Installing required packages (this may take a minute)...
echo         Please wait — do not close this window.
echo.
pip install customtkinter>=5.2.0 Pillow>=10.0.0 requests>=2.31.0 onnxruntime>=1.17.0 huggingface_hub>=0.20.0 numpy>=1.24.0 playwright --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] Package installation failed.
    echo  Make sure you are connected to the internet and try again.
    echo.
    pause
    exit /b 1
)
echo         Packages installed successfully.
echo.

:: ─────────────────────────────────────────────
:: 3. Install Playwright browser
:: ─────────────────────────────────────────────
echo  [3/4] Setting up browser for uploads (first time only)...
playwright install chromium --quiet > nul 2>&1
if %errorlevel% neq 0 (
    echo         Note: Could not auto-install browser. Trying fallback...
    python -m playwright install chromium --quiet > nul 2>&1
)
echo         Browser ready.
echo.

:: ─────────────────────────────────────────────
:: 4. Launch the app
:: ─────────────────────────────────────────────
echo  [4/4] Launching BoozStudio R34 Poster...
echo.
echo  ============================================================
echo.
python app.py

:: If the app crashes, show the error
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] The application crashed with code %errorlevel%.
    echo  Please check the output above for details.
    echo.
    pause
)
