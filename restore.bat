@echo off
REM Blasting Intelligence - restore a backup. STOP THE SERVER FIRST (close the start_demo.bat window).
REM Usage: restore.bat bi-backup-YYYYMMDD-HHMMSS-reason.zip   (file name in data\backups, or a full path)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set BI_MODE=production
cd backend
if "%~1"=="" (python -m app.manage backups & echo. & echo Usage: restore.bat FILE & pause & exit /b 1)
python -m app.manage verify "%~1" || (pause & exit /b 1)
echo.
echo WARNING: the current data will be replaced by this backup (it is backed up first).
choice /c YN /m "Is the server stopped and do you want to continue"
if errorlevel 2 exit /b 0
python -m app.manage restore "%~1" --yes
pause
