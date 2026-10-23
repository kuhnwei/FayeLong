@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title FayeLong 精听

set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" goto :nopython

"%PY%" "%~dp0scripts\launcher.py" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" goto :failed
goto :eof

:nopython
echo.
echo   [错误] 找不到内置的 Python 运行时：
echo          %PY%
echo   交付包可能没有解压完整。请把压缩包重新解压一次，
echo   并确保整个文件夹（不要只挑几个文件）都被解压出来。
echo.
pause
exit /b 1

:failed
echo.
echo   启动失败（错误代码 %CODE%）。
echo   详细原因请看日志文件：data\logs\app.log
echo.
pause
exit /b %CODE%
