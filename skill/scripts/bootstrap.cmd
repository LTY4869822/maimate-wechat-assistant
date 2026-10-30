@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "WGA_PYTHON=%~1\runtimes\python312\python.exe"
if not exist "%WGA_PYTHON%" set "WGA_PYTHON=%~1\MaiBot\.venv\Scripts\python.exe"
if not exist "%WGA_PYTHON%" (
    echo No bundled Python found. Provide the extracted offline bundle or an existing installation as the first argument.
    exit /b 18
)
"%WGA_PYTHON%" -I -X utf8 -B "%~dp0agent_entry.py" %*
exit /b %errorlevel%
