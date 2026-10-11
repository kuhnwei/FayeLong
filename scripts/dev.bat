@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo [FayeLong] 一键启动：后端 + 前端
start "FayeLong-Backend" cmd /k "%~dp0start-backend.bat"
timeout /t 3 >nul
start "FayeLong-Frontend" cmd /k "%~dp0start-frontend.bat"
echo.
echo 后端: http://127.0.0.1:8000/docs
echo 前端: http://localhost:5173
