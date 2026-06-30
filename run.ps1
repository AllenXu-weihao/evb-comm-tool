# 启动 EVB 通信质量监测上位机
#
# 若 PowerShell 提示“禁止运行脚本”(ExecutionPolicy)，请改用:
#   .\run.bat
# 或:
#   .\.venv\Scripts\python.exe main.py
# 或临时绕过:
#   powershell -ExecutionPolicy Bypass -File .\run.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "未找到虚拟环境，正在运行 setup.bat ..."
    & cmd /c "`"$PSScriptRoot\setup.bat`" nopause"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not (Test-Path $venvPython)) {
    Write-Host ""
    Write-Host "错误: 虚拟环境未创建。请运行 .\setup.bat" -ForegroundColor Red
    Write-Host "若 .\run.ps1 被禁止，可直接双击 run.bat 或在 cmd 中运行 run.bat"
    exit 1
}

& $venvPython (Join-Path $PSScriptRoot "main.py")
