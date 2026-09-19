@echo off
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "DEBUG_PROFILE=%USERPROFILE%\ChromeDebugProfile"

if not exist "%DEBUG_PROFILE%" mkdir "%DEBUG_PROFILE%"

REM Kill Chrome lama
taskkill /F /IM chrome.exe /T 2>nul
timeout /t 2 /nobreak >nul

REM Buka dengan DEBUG PORT
start "" "%CHROME%" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%DEBUG_PROFILE%" ^
  --no-first-run ^
  --no-default-browser-check ^
  https://studio.youtube.com

echo ✅ Chrome debug dibuka
echo.
echo 1. Login YouTube
echo 2. JANGAN tutup Chrome
echo 3. Klik Test Login di app
pause