@echo off
setlocal
title YouTube Live Chat Sender - CLI Runner

echo ========================================================
echo   YouTube Live Chat Sender - Terminal Runner
echo ========================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python install nahi mila! Kripya Python 3.10+ install karein aur PATH me add karein.
    pause
    exit /b 1
)

:: Check dependencies
python -c "import playwright, rich" >nul 2>&1
if errorlevel 1 (
    echo [*] Dependencies missing! Installing requirements...
    pip install -r requirements.txt
    python -m playwright install chromium
    echo.
)

echo [*] Starting YouTube Live Chat Sender...
echo.
python main.py

echo.
echo ========================================================
echo Bot stop ho chuka hai.
pause
