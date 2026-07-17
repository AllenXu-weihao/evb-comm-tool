chcp 65001 >nul
@echo off
setlocal EnableDelayedExpansion
REM EVB 通信质量监测上位机 — Windows 环境一键配置（无需 PowerShell 执行策略）
REM 用法: 双击 setup.bat，或在 cmd / PowerShell 中运行 setup.bat

cd /d "%~dp0"

echo.
echo ========================================
echo   EVB 上位机 - 环境配置
echo ========================================
echo.

echo ==^> 检测 Python 3.10+ ...
set "PY="
set "PY_ARGS="

where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY=py"
        set "PY_ARGS=-3"
    )
)
if not defined PY (
    where py >nul 2>&1
    if not errorlevel 1 set "PY=py"
)
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    where python3 >nul 2>&1
    if not errorlevel 1 set "PY=python3"
)
if not defined PY goto :no_python

if defined PY_ARGS (
    echo     使用: !PY! !PY_ARGS!
    !PY! !PY_ARGS! --version
) else (
    echo     使用: !PY!
    !PY! --version
)
if errorlevel 1 goto :python_broken

if defined PY_ARGS (
    !PY! !PY_ARGS! -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)"
) else (
    !PY! -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)"
)
if errorlevel 1 goto :python_old

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "NEED_VENV=1"

if exist "%VENV_PY%" (
    "%VENV_PY%" --version >nul 2>&1
    if not errorlevel 1 (
        set "NEED_VENV=0"
        echo.
        echo ==^> 虚拟环境 .venv 已存在且可用，跳过创建
    ) else (
        echo.
        echo ==^> 检测到损坏的 .venv（可能来自其他电脑），正在重建 ...
        rmdir /s /q ".venv" 2>nul
    )
)

if "!NEED_VENV!"=="1" (
    echo.
    echo ==^> 创建虚拟环境 .venv ...
    if defined PY_ARGS (
        !PY! !PY_ARGS! -m venv .venv
    ) else (
        !PY! -m venv .venv
    )
    if errorlevel 1 goto :venv_failed
)

if not exist "%VENV_PY%" goto :venv_missing

set "PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PIP_OPTS=-i %PIP_MIRROR% --trusted-host pypi.tuna.tsinghua.edu.cn"

echo.
echo ==^> 升级 pip ...
"%VENV_PY%" -m pip install --upgrade pip %PIP_OPTS%
if errorlevel 1 (
    echo [警告] 清华镜像升级 pip 失败，尝试官方源 ...
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 goto :pip_failed
)

echo.
echo ==^> 安装依赖 ...
"%VENV_PY%" -m pip install -r requirements.txt %PIP_OPTS%
if errorlevel 1 (
    echo [警告] 清华镜像安装失败，尝试官方 PyPI ...
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :deps_failed
)

echo.
echo ==^> 验证导入 ...
"%VENV_PY%" -c "import protocol.codec; import ui.main_window; import PyQt6.QtWidgets; print('验证通过')"
if errorlevel 1 goto :import_failed

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

:no_python
echo [错误] 未找到 Python 3.10+。请安装 Python 并加入 PATH。
echo        下载: https://www.python.org/downloads/
echo        安装时建议勾选 "Add python.exe to PATH"
if /i not "%~1"=="nopause" pause
exit /b 1

:python_broken
echo [错误] Python 无法运行。
if /i not "%~1"=="nopause" pause
exit /b 1

:python_old
echo [错误] 需要 Python 3.10 或更高版本。
if /i not "%~1"=="nopause" pause
exit /b 1

:venv_failed
echo [错误] 创建虚拟环境失败。
if /i not "%~1"=="nopause" pause
exit /b 1

:venv_missing
echo [错误] 未找到 %VENV_PY%
if /i not "%~1"=="nopause" pause
exit /b 1

:pip_failed
echo [错误] pip 升级失败。
if /i not "%~1"=="nopause" pause
exit /b 1

:deps_failed
echo [错误] 依赖安装失败。
if /i not "%~1"=="nopause" pause
exit /b 1

:import_failed
echo [错误] 导入验证失败。
if /i not "%~1"=="nopause" pause
exit /b 1
