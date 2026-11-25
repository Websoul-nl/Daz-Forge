@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Daz Forge could not find .venv\Scripts\python.exe
    echo Run the setup steps in docs\user-manual.md first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "from importlib.util import find_spec; raise SystemExit(any(find_spec(name) is None for name in ('PySide6', 'numpy')))"
if errorlevel 1 (
    echo Daz Forge dependencies are missing from this virtual environment.
    echo Run: .\.venv\Scripts\python.exe -m pip install -e .
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m forge.ui.app %*
