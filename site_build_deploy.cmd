@echo off
setlocal
title SKL site build + deploy
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
echo [1/2] publish_site.py
".venv\Scripts\python.exe" publish_site.py > logs\site_build_last.log 2>&1
type logs\site_build_last.log
if errorlevel 1 ( echo BUILD FAILED & goto end )
echo [2/2] deploy_site.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy_site.ps1" > logs\site_deploy_last.log 2>&1
type logs\site_deploy_last.log
:end
echo DONE %ERRORLEVEL% >> logs\site_deploy_last.log
echo.
echo === DONE ===
pause
endlocal
