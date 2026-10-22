@echo off
chcp 65001 >nul
cd /d "%~dp0..\frontend-vue"
if not exist node_modules (
  echo [FayeLong] 首次运行，安装前端依赖 ...
  call npm install --ignore-scripts
)
echo [FayeLong] 启动前端 (Vue + Vite @ http://localhost:5174) ...
call npm run dev
