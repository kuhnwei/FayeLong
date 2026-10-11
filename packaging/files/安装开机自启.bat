@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title FayeLong 安装开机自启

set "SRC=%~dp0FayeLong-Autostart.vbs"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "DST=%STARTUP%\FayeLong-Autostart.vbs"

if not exist "%SRC%" goto :nosrc
if not exist "%STARTUP%" goto :nostartup

copy /y "%SRC%" "%DST%" >nul 2>&1
if errorlevel 1 goto :failed

echo.
echo   ============================================================
echo    已安装开机自启
echo   ============================================================
echo.
echo   下次开机后，FayeLong 会在后台自动运行（不弹窗口、不弹浏览器）。
echo.
echo   · 打开网站：浏览器访问  http://127.0.0.1:8000
echo   · 立刻启动（不用等重启）：双击「静默启动 FayeLong.vbs」
echo   · 取消自启：双击「取消开机自启.bat」
echo.
echo   提示：如果这是第一次用，建议先双击「静默启动 FayeLong.vbs」
echo         确认一切正常，再依赖开机自启。
echo.
pause
exit /b 0

:nosrc
echo.
echo   [错误] 找不到 FayeLong-Autostart.vbs（应与本文件在同一目录）。
echo   请确认整个文件夹都已完整解压。
echo.
pause
exit /b 1

:nostartup
echo.
echo   [错误] 找不到 Windows「启动」文件夹：
echo          %STARTUP%
echo   可以手动把 FayeLong-Autostart.vbs 复制到该文件夹。
echo.
pause
exit /b 1

:failed
echo.
echo   [错误] 复制到「启动」文件夹失败（可能被安全软件拦截，或权限不足）。
echo   可以手动把 FayeLong-Autostart.vbs 复制到：
echo     %STARTUP%
echo.
pause
exit /b 1
