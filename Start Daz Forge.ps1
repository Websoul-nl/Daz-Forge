$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Daz Forge could not find .venv\Scripts\python.exe"
    Write-Host "Run the setup steps in docs/user-manual.md first."
    Read-Host "Press Enter to close"
    exit 1
}

& $python -c "from importlib.util import find_spec; raise SystemExit(any(find_spec(name) is None for name in ('PySide6', 'numpy')))"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Daz Forge dependencies are missing from this virtual environment."
    Write-Host 'Run: .\.venv\Scripts\python.exe -m pip install -e .'
    exit 1
}

& $python -m forge.ui.app @args
