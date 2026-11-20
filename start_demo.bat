@echo off
REM Blasting Intelligence - DEMONSTRATION (fictional site, fixed date, separate database data\demo\demo.db) on port 8001
REM Always on this computer only (127.0.0.1), whatever server.env says.
cd /d "%~dp0"
if not exist .venv (echo Run setup.bat first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
if not exist frontend\dist\index.html (echo Frontend build missing: frontend\dist & pause & exit /b 1)
set BI_MODE=demo
set BI_ENV_FILE=none
set BI_HOST=127.0.0.1
set BI_PORT=8001
set BI_BACKUP_DAILY_AT=
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8001"
cd backend
python -m app.serve
