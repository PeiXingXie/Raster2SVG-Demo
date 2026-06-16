@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist "%SCRIPT_DIR%start-service.ps1" (
    echo [ERROR] Missing start-service.ps1
    pause
    exit /b 1
)

echo Starting service from "%SCRIPT_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-service.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Service stopped with exit code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
