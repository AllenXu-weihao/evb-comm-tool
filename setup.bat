@echo off
setlocal
REM EVB 通信质量监测上位机 — Windows 环境一键配置（无需 PowerShell 执行策略）
REM 用法: 双击 setup.bat，或在 cmd / PowerShell 中运行 setup.bat

cd /d "%~dp0"

echo.
echo ========================================
echo   EVB 上位机 - 环境配置
echo ========================================
echo.

echo ==^> 检测 Python...
set "PY="
where py >nul 2>&1 && set "PY=py" && goto :found
where python >nul 2>&1 && set "PY=python" && goto :found
where python3 >nul 2>&1 && set "PY=python3" && goto :found

echo [错误] 未找到 Python。请安装 Python 3.10+ 并加入 PATH。
echo        下载: https://www.python.org/downloads/
if /i not "%~1"=="nopause" pause
exit /b 1

:found
echo     使用: %PY%
%PY% --version
if errorlevel 1 (
    echo [错误] Python 无法运行。
    if /i not "%~1"=="nopause" pause
    exit /b 1
)

echo.
echo ==^> 创建虚拟环境 .venv ...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        if /i not "%~1"=="nopause" pause
        exit /b 1
    )
) else (
    echo     .venv 已存在，跳过创建
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [错误] 未找到 %VENV_PY%
    if /i not "%~1"=="nopause" pause
    exit /b 1
)

echo.
echo ==^> 升级 pip ...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo [错误] pip 升级失败。
    if /i not "%~1"=="nopause" pause
    exit /b 1
)

echo.
echo ==^> 安装依赖 ...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败。
    if /i not "%~1"=="nopause" pause
    exit /b 1
)

echo.
echo ==^> 验证导入 ...
"%VENV_PY%" -c "import protocol.codec; import ui.main_window; import PyQt6.QtWidgets; print('验证通过')"
if errorlevel 1 (
    echo [错误] 导入验证失败。
    if /i not "%~1"=="nopause" pause
    exit /b 1
)

echo.
echo ========================================
echo   环境配置完成！
echo ========================================
echo.
echo 启动应用请运行:
echo   run.bat
echo.
echo 或直接执行:
echo   .venv\Scripts\python.exe main.py
echo.

if /i not "%~1"=="nopause" pause
exit /b 0
