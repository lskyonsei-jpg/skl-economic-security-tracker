@echo off
setlocal
title SKL Economic Security Tracker
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_update.ps1"
echo.
pause
endlocal
