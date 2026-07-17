@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
REM 打包可分发 zip（排除 .venv、git、缓存等）
REM 用法: 双击 pack.bat，或在项目根目录运行 pack.bat

cd /d "%~dp0"

for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-Date -Format 'yyyyMMdd_HHmmss')"`) do set "STAMP=%%I"
set "ZIP_NAME=evb-comm-tool_%STAMP%.zip"
set "OUT=%~dp0..\%ZIP_NAME%"

echo.
echo ========================================
echo   EVB 上位机 - 打包分发
echo ========================================
echo.
echo 输出: %OUT%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\pack.ps1" -Root "%~dp0" -Out "%OUT%"
if errorlevel 1 (
    echo.
    echo [错误] 打包失败。
    pause
    exit /b 1
)

echo.
echo [完成] 已生成: %OUT%
echo 请将 zip 发给同事，解压后双击 run.bat 即可（首次会自动 setup）。
echo.
pause
exit /b 0
