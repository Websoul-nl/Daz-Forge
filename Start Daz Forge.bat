@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Daz Forge could not find .venv\Scripts\python.exe
    echo Run the setup steps in docs\user-manual.md first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m forge.ui.app %*
