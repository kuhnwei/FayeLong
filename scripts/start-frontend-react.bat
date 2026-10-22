@echo off
chcp 65001 >nul
cd /d "%~dp0..\frontend"
if not exist node_modules (
  echo [FayeLong] 首次运行，安装前端依赖 ...
  call npm install --ignore-scripts
)
echo [FayeLong] 启动前端 (旧 React 版，已冻结 @ http://localhost:5173) ...
call npm run dev
