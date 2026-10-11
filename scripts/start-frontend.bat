@echo off
chcp 65001 >nul
cd /d "%~dp0..\frontend"
if not exist node_modules (
  echo [FayeLong] 首次运行，安装前端依赖 ...
  call npm install
)
echo [FayeLong] 启动前端 (Vite @ http://localhost:5173) ...
call npm run dev
