@echo off
cd /d "%~dp0"
set "UV_CACHE_DIR=%~dp0.uv-cache"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
) else (
    uv run main.py
    pause
)
