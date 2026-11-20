@echo off
REM Blasting Intelligence - PRODUCTION server in a console window (stop with Ctrl+C).
REM Network, HTTPS and database settings: server.env (see server.env.example and docs\DEPLOYMENT.md).
REM For a server that runs without anyone signed in, use install_service.bat instead.
cd /d "%~dp0"
if not exist .venv (echo Run setup.bat first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
if not exist frontend\dist\index.html (echo Frontend build missing: frontend\dist & pause & exit /b 1)
set BI_MODE=production
cd backend
python -m app.serve --check || (pause & exit /b 1)
for /f "delims=" %%u in ('python -m app.serve --url') do set BI_URL=%%u
start "" /b cmd /c "timeout /t 3 >nul & start %BI_URL%"
python -m app.serve
