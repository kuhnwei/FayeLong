@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo [FayeLong] 一键启动：后端 + 任务执行进程 + 前端（3 个窗口）
echo.
echo   Backend  : http://127.0.0.1:8000/docs   （API + 静态托管）
echo   Worker   : 无端口，日志 data\logs\worker.log（转码/识别/翻译/切片）
echo   Frontend : http://localhost:5173         （Vite 开发服务器）
echo.
echo 说明：start-backend.bat 一个字都没改 —— 它只起 web，靠
echo       FAYELONG_WEB_INPROC_WORKER=auto 在 5s 后兜底；所以只跑后端也能用，
echo       只是任务会在 web 进程内执行（慢一些）。本脚本额外把 worker 单独开一窗，
echo       这样任务在独立进程里跑，web 保持轻量。
echo.
start "FayeLong-Backend" cmd /k "%~dp0start-backend.bat"
timeout /t 2 >nul
start "FayeLong-Worker" cmd /k "%~dp0start-worker.bat"
timeout /t 1 >nul
start "FayeLong-Frontend" cmd /k "%~dp0start-frontend.bat"
