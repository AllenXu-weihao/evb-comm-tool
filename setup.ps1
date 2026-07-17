# EVB 上位机 — Windows 环境配置（可选，run.bat 会自动调用 setup.bat）
# 用法: .\setup.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            & py -3 --version | Out-Null
            if ($LASTEXITCODE -eq 0) { return @{ Cmd = "py"; Args = @("-3") } }
        } catch { }
        return @{ Cmd = "py"; Args = @() }
    }
    foreach ($cmd in @("python", "python3")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            return @{ Cmd = $cmd; Args = @() }
        }
    }
    return $null
}

Write-Host "==> 检测 Python 3.10+ ..."
$pyInfo = Find-Python
if (-not $pyInfo) {
    Write-Error "未找到 Python。请安装 Python 3.10+ 并加入 PATH。"
}

$pyCmd = $pyInfo.Cmd
$pyArgs = $pyInfo.Args
if ($pyArgs.Count -gt 0) {
    Write-Host ("    使用: {0} {1}" -f $pyCmd, ($pyArgs -join ' '))
    & $pyCmd @pyArgs --version
} else {
    Write-Host ("    使用: {0}" -f $pyCmd)
    & $pyCmd --version
}

$versionCheck = if ($pyArgs.Count -gt 0) {
    & $pyCmd @pyArgs -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)"
} else {
    & $pyCmd -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)"
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "需要 Python 3.10 或更高版本。"
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$needVenv = $true
if (Test-Path $venvPython) {
    try {
        & $venvPython --version | Out-Null
        if ($LASTEXITCODE -eq 0) { $needVenv = $false }
    } catch { }
}

if ($needVenv) {
    if (Test-Path ".venv") {
        Write-Host "==> 检测到损坏的 .venv，正在重建 ..."
        Remove-Item -LiteralPath ".venv" -Recurse -Force
    } else {
        Write-Host "==> 创建虚拟环境 .venv ..."
    }
    if ($pyArgs.Count -gt 0) {
        & $pyCmd @pyArgs -m venv .venv
    } else {
        & $pyCmd -m venv .venv
    }
} else {
    Write-Host "==> 虚拟环境 .venv 已存在且可用，跳过创建"
}

if (-not (Test-Path $venvPython)) {
    Write-Error "创建虚拟环境失败: $venvPython"
}

Write-Host "==> 升级 pip ..."
& $venvPython -m pip install --upgrade pip

Write-Host "==> 安装依赖 ..."
& $venvPython -m pip install -r requirements.txt

Write-Host "==> 验证导入 ..."
& $venvPython -c "import protocol.codec; import ui.main_window; import PyQt6.QtWidgets; print('验证通过')"

Write-Host ""
Write-Host "环境配置完成。启动:"
Write-Host "  .\run.bat"
Write-Host ""
