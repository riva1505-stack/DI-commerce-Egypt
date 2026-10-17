@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo AI Commerce Egypt - Restaurant Edition v1.0
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    set "PY=python"
)
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" start.py
if errorlevel 1 goto :failed
pause
exit /b 0
:failed
echo.
echo An error occurred. Check that Python 3.11+ and internet are available.
pause
exit /b 1
