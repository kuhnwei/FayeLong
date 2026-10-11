@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title FayeLong 就地更新（不会动你的学习数据）

set "SELF=%~dp0"
set "UPD=%SELF%scripts\update.py"
set "TARGET=%~1"
set "PY="

if not exist "%UPD%" goto :noupd

rem (1) 完整包自带运行时 → 直接用
set "PY=%SELF%runtime\python\python.exe"
if exist "%PY%" goto :run

rem (2) 更新包通常不带运行时 → 借用旧安装目录里的运行时
if "%TARGET%"=="" goto :ask
call :resolvepy
if not exist "%PY%" goto :badrunner
goto :run

:ask
echo.
echo   ============================================================
echo    FayeLong 更新 —— 先指定旧版本的安装目录
echo   ============================================================
echo.
echo   做法一（推荐）：把旧目录（例如 D:\FayeLong）用鼠标拖到本文件上
echo   做法二：在下面输入安装目录的完整路径，然后回车
echo.
set "TARGET="
set /p "TARGET=安装目录："
if "%TARGET%"=="" goto :abort
set "TARGET=%TARGET:"=%"
call :resolvepy
if not exist "%PY%" goto :badrunner
goto :run

:resolvepy
set "PY=%TARGET%\runtime\python\python.exe"
exit /b 0

:run
echo.
echo   正在更新：新版本 → %TARGET%
echo   （会自动停止正在运行的服务，并先备份 data\app.db）
echo.
if "%TARGET%"=="" (
  "%PY%" "%UPD%"
) else (
  "%PY%" "%UPD%" --target "%TARGET%"
)
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" goto :failed
echo.
echo   更新完成。双击「启动 FayeLong.bat」或用「静默启动 FayeLong.vbs」即可使用新版本。
echo.
pause
exit /b 0

:abort
echo.
echo   已取消。
echo.
pause
exit /b 0

:noupd
echo.
echo   [错误] 找不到更新脚本：%UPD%
echo   请确认整个文件夹都已完整解压。
echo.
pause
exit /b 1

:badrunner
echo.
echo   [错误] 在下面这个目录里找不到内置的 Python 运行时：
echo          %TARGET%\runtime\python\python.exe
echo.
echo   请确认它确实是 FayeLong 的安装目录（里面有 app、runtime、data 等文件夹），
echo   或者改用完整包（自带运行时）来执行更新。
echo.
pause
exit /b 1

:failed
echo.
echo   [错误] 更新失败（错误代码 %CODE%）。
echo   你的学习数据（data 目录）**没有**被改动；
echo   如果需要人工排查，请把上面的输出发给开发者。
echo.
pause
exit /b %CODE%
