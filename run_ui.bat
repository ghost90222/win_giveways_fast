@echo off
setlocal
title YouTube Live Chat Sender - UI Launcher

echo ========================================================
echo   YouTube Live Chat Sender - Starting Desktop UI
echo ========================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python install nahi mila! Kripya Python 3.10+ install karein.
    pause
    exit /b 1
)

:: Check dependencies
python -c "import playwright, rich, customtkinter" >nul 2>&1
if errorlevel 1 (
    echo [*] Dependencies missing! Installing requirements...
    pip install -r requirements.txt
    python -m playwright install chromium
    echo.
)

echo [*] Launching Desktop UI...
start "" pythonw gui.py

exit
