@echo off
REM Blasting Intelligence - create a backup now (the server may keep running).
REM Can be scheduled with Windows Task Scheduler, e.g.:
REM   schtasks /create /tn "Blasting Intelligence backup" /sc daily /st 02:30 /tr "C:\BlastingIntelligence\backup.bat"
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set BI_MODE=production
cd backend
python -m app.manage backup --reason scheduled
exit /b %errorlevel%
