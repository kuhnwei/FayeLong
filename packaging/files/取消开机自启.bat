@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title FayeLong 取消开机自启

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "DST=%STARTUP%\FayeLong-Autostart.vbs"

if not exist "%DST%" goto :notfound

del /q "%DST%" >nul 2>&1
if exist "%DST%" goto :failed

echo.
echo   已取消开机自启。
echo.
echo   说明：这只影响「开机自动运行」，不影响已经启动的服务。
echo   要停止当前正在运行的服务，请双击「停止 FayeLong.bat」。
echo.
pause
exit /b 0

:notfound
echo.
echo   当前没有安装开机自启（未在「启动」文件夹找到 FayeLong-Autostart.vbs）。
echo.
pause
exit /b 0

:failed
echo.
echo   [错误] 删除失败，可能被安全软件锁定。请手动删除：
echo     %DST%
echo.
pause
exit /b 1
