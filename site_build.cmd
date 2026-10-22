@echo off
setlocal
title SKL site build (local preview)
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
rem 2026-10-22: 배포는 GitHub Actions 가 GitHub Pages 로 한다(.github/workflows/deploy-pages.yml).
rem 이 파일은 로컬에서 site/ 를 만들어 확인할 때만 쓴다.
echo [1/1] publish_site.py
".venv\Scripts\python.exe" publish_site.py --open > logs\site_build_last.log 2>&1
type logs\site_build_last.log
if errorlevel 1 ( echo BUILD FAILED )
echo.
echo === DONE ===
pause
endlocal
