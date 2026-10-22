@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title FayeLong - stop service

rem ===========================================================================
rem ASCII only. Do NOT add Chinese text, goto/labels or ( ) blocks here.
rem
rem Why: cmd.exe parses a batch file byte by byte under chcp 65001, and the
rem result depends on the active code page of the host console. With multi-byte
rem text inside this file, some invocations split a line mid-character and the
rem tail is executed as a command ("'pid' is not recognized ..."). Verified on
rem this machine: goto/label style broke on some paths, straight-line style
rem broke on others -> the only deterministic form is 7-bit ASCII.
rem Chinese user guidance for stopping the service lives in the README txt
rem shipped next to this file (Q10 in section 5).
rem
rem FOUND values: 0 = nothing was running
rem               1 = launcher found (its /T tree kill also takes the worker)
rem               2 = only a leftover worker was running (launcher was force-killed)
rem ===========================================================================

set "PIDFILE=%~dp0data\logs\fayelong.pid"
set "WORKERPIDFILE=%~dp0data\logs\worker.pid"
set "FOUND=0"

if exist "%PIDFILE%" echo.
if exist "%PIDFILE%" echo   Stopping FayeLong ...
if exist "%PIDFILE%" set "FOUND=1"
rem taskkill /T walks the parent-child tree, so the worker child dies with the
rem launcher (python -m app.worker / worker_entry.py is its direct child).
if exist "%PIDFILE%" for /f "usebackq delims=" %%p in ("%PIDFILE%") do taskkill /PID %%p /T /F >nul 2>&1
if exist "%PIDFILE%" del /q "%PIDFILE%" >nul 2>&1

rem Second pass: kill a leftover worker by worker.pid. Needed when the launcher
rem was force-killed from Task Manager, so /T could not walk the tree. The
rem worker also self-exits within ~5s (--parent-pid watch); this just makes the
rem stop deterministic and leaves no orphan process competing for jobs.
rem If the launcher was already gone, mark FOUND=2 so we report "stopped a
rem leftover worker" instead of the misleading "FayeLong is not running."
if exist "%WORKERPIDFILE%" if "%FOUND%"=="0" set "FOUND=2"
if exist "%WORKERPIDFILE%" for /f "usebackq delims=" %%p in ("%WORKERPIDFILE%") do taskkill /PID %%p /T /F >nul 2>&1
if exist "%WORKERPIDFILE%" del /q "%WORKERPIDFILE%" >nul 2>&1

echo.
if "%FOUND%"=="1" echo   Stopped (web + task worker).
if "%FOUND%"=="2" echo   Stopped leftover task worker.
if "%FOUND%"=="0" echo   FayeLong is not running.
if "%FOUND%"=="0" echo   If a FayeLong console window is still open, just close it.
echo.
pause
exit /b 0
