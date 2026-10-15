@echo off
title MARAT - Autonomous Multi-Agent Intelligence & Reverse Engineering Platform
echo ======================================================================
echo    MARAT v2.0 - Autonomous Multi-Agent Intelligence Platform
echo ======================================================================
echo.

cd /d "%~dp0"

if exist "dist\Marat\Marat.exe" (
    echo Launching compiled Marat executable...
    start "" "dist\Marat\Marat.exe"
    exit /b 0
)

echo Starting MARAT via Python launcher...
start http://localhost:8000
python main.py
