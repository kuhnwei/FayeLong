@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title FayeLong 停止服务

set "PIDFILE=%~dp0data\logs\fayelong.pid"
if not exist "%PIDFILE%" goto :norunning

set /p PID=<"%PIDFILE%"
if "%PID%"=="" goto :norunning

echo.
echo   正在停止 FayeLong（进程号 %PID%）...
taskkill /PID %PID% /T /F >nul 2>&1
if errorlevel 1 (
  echo   该进程可能已经退出。
) else (
  echo   已停止。
)
del /q "%PIDFILE%" >nul 2>&1
echo.
pause
exit /b 0

:norunning
echo.
echo   没有找到正在运行的 FayeLong。
echo   如果你确实开着服务，请直接关闭那个标题为「FayeLong 英语学习网站」的窗口。
echo.
pause
exit /b 0
