chcp 65001 >nul
@echo off
setlocal
cd /d "%~dp0"

REM 弱机 / 远程桌面 / 换机卡顿：启用 UI 节流（不改变协议与 BER 语义）
set "EVB_UI_LITE=1"

echo [信息] 弱机模式 EVB_UI_LITE=1（图表延迟加载、更少 UI 刷新）
call "%~dp0run.bat"
exit /b %ERRORLEVEL%
