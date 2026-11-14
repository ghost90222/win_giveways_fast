@echo off
setlocal
title YouTube Chat Sender - Chrome Launcher

echo ========================================================
echo   YouTube Live Chat Sender - Chrome Launcher (Debug Mode)
echo ========================================================
echo.

:: 1. Profile directory (retains existing C:\yt_bot_profile if present, otherwise uses %LOCALAPPDATA%)
set "PROFILE_DIR=C:\yt_bot_profile"
if not exist "%PROFILE_DIR%" (
    set "PROFILE_DIR=%LOCALAPPDATA%\yt_bot_profile"
    if not exist "%PROFILE_DIR%" (
        mkdir "%PROFILE_DIR%" 2>nul
    )
)

:: 2. Find Chrome or Chromium browser
set "CHROME_BIN="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
) else if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
) else if exist "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" (
    set "CHROME_BIN=C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
) else if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    set "CHROME_BIN=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)

if "%CHROME_BIN%"=="" (
    echo [ERROR] Google Chrome / Brave / Edge nahi mila!
    echo Kripya Google Chrome install karein.
    pause
    exit /b 1
)

echo [*] Browser Found: "%CHROME_BIN%"
echo [*] Profile Folder: "%PROFILE_DIR%"
echo [*] Launching on Port 9222 with Background Throttling Disabled...
echo.
echo [!] INSTRUCTIONS:
echo     1. Is Chrome window mein apna YouTube account 'Sign In' karein.
echo     2. Wo live stream open karein jisme auto-chat bhejni hai.
echo     3. Tab background ya minimize mein bhi smoothly run karega!
echo.

start "" "%CHROME_BIN%" --remote-debugging-port=9222 --user-data-dir="%PROFILE_DIR%" --disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-features=CalculateNativeWinOcclusion --no-first-run --no-default-browser-check https://www.youtube.com

echo [*] Chrome launch ho chuka hai!
echo [*] Ab aap 'run.bat' (Terminal) ya 'run_ui.bat' (Desktop UI) chala sakte hain.
echo.
timeout /t 5 >nul
