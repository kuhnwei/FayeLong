@echo off
chcp 65001 >nul
rem ============================================================================
rem FayeLong · 任务执行进程（worker）
rem
rem P3-2 起，转码 / 识别 / 翻译 / 切片由独立 worker 执行，web 进程只提供 API。
rem 开发时一般用 dev.bat（它会连这个窗口一起开）；只想单独看 worker 时双击本文件。
rem
rem 注意：
rem   1. worker **没有热重载**（`--reload` 对它是无意义的）—— 改了后端代码请手动
rem      关掉本窗口再重开，否则跑的还是旧代码。
rem   2. 日志在 data\logs\worker.log（与 web 的 app.log 刻意分开：
rem      两个进程共用一个文件会让 Windows 上的轮转直接 PermissionError）。
rem   3. 这个窗口不要关：关了任务就没人执行，上传的素材会一直显示「排队中」。
rem      （web 侧 FAYELONG_WEB_INPROC_WORKER=auto 会在 5s 后兜底接管，但会慢一些。）
rem ============================================================================
cd /d "%~dp0.."
echo [FayeLong] 启动任务执行进程 (worker) ...
echo   日志: data\logs\worker.log
set "PYTHONPATH=%CD%\backend;%PYTHONPATH%"
backend\.venv\Scripts\python.exe -m app.worker
echo.
echo [FayeLong] worker 已退出（错误码 %ERRORLEVEL%）。按任意键关闭窗口。
pause >nul
