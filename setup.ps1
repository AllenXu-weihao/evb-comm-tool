# EVB host app - Windows setup script
# Usage: .\setup.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Detecting Python..."
$py = $null
foreach ($cmd in @("py", "python", "python3")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $py = $cmd
        break
    }
}
if (-not $py) {
    Write-Error "Python not found. Install Python 3.10+ from https://www.python.org/downloads/"
}

& $py --version

Write-Host "==> Creating virtual environment .venv ..."
if (-not (Test-Path ".venv")) {
    & $py -m venv .venv
} else {
    Write-Host "    .venv already exists, skipping"
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Failed to create venv at $venvPython"
}

Write-Host "==> Upgrading pip ..."
& $venvPython -m pip install --upgrade pip

Write-Host "==> Installing dependencies ..."
& $venvPython -m pip install -r requirements.txt

Write-Host "==> Verifying imports ..."
& $venvPython -c "import protocol.codec; import ui.main_window; import PyQt6.QtWidgets; print('OK')"

Write-Host ""
Write-Host "Setup complete. Start the app with:"
Write-Host "  .\.venv\Scripts\python.exe main.py"
Write-Host ""
Write-Host "Or run:"
Write-Host "  .\run.ps1"
