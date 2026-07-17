chcp 65001 >nul
@echo off
setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "MAIN=%~dp0main.py"
set "NEED_SETUP=0"

if not exist "%VENV_PY%" (
    set "NEED_SETUP=1"
) else (
    "%VENV_PY%" --version >nul 2>&1
    if errorlevel 1 set "NEED_SETUP=1"
)

if "%NEED_SETUP%"=="1" (
    echo.
    echo [信息] 未找到可用虚拟环境 .venv，正在运行首次配置 setup.bat ...
    echo.
    call "%~dp0setup.bat" nopause
    if errorlevel 1 (
        echo.
        echo [错误] 环境配置失败，请检查上方错误信息。
        pause
        exit /b 1
    )
)

if not exist "%VENV_PY%" (
    echo [错误] 虚拟环境仍未创建。请手动运行: setup.bat
    pause
    exit /b 1
)

if not exist "%MAIN%" (
    echo [错误] 未找到 main.py: %MAIN%
    pause
    exit /b 1
)

echo [信息] 正在启动 EVB 通信质量监测上位机 ...
echo.

"%VENV_PY%" "%MAIN%"
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo.
    echo [错误] 程序异常退出，代码: %EXITCODE%
    pause
)

exit /b %EXITCODE%
