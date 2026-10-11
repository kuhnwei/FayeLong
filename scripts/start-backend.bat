@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo [FayeLong] 启动后端 (FastAPI @ http://127.0.0.1:8000) ...
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
