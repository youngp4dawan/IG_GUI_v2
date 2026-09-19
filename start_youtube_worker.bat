@echo off
title YouTube Upload Worker
cd /d "%~dp0"

echo ============================================================
echo  YouTube Worker
echo ============================================================
echo  Dir: %CD%
echo ============================================================
echo.

python youtube_service.py
set EXITCODE=%errorlevel%

echo.
echo ============================================================
echo  Worker STOPPED (exit code: %EXITCODE%)
echo ============================================================
echo.
echo Tekan tombol apapun untuk menutup...
pause >nul