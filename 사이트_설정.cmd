@echo off
setlocal
title SKL Site Setup
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0site_setup.ps1"
echo.
pause
endlocal
