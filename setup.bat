@echo off
REM Blasting Intelligence - one-time setup (Windows)
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version || (echo Python 3.11+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv (%PY% -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt || (echo Dependency installation failed & pause & exit /b 1)
cd backend
REM Tests run on a temporary database; they never touch your data.
python -m pytest -q || (echo Automated tests failed & pause & exit /b 1)
REM Production database: creates or upgrades the schema (an existing database is backed up first). Never deletes data.
set BI_MODE=production
python -m app.manage db-upgrade || (echo Database upgrade failed & pause & exit /b 1)
python -m app.manage ensure-admin || (echo Administrator creation failed & pause & exit /b 1)
cd ..
echo.
echo Setup complete.
echo   start.bat       - the application (production)
echo   start_demo.bat  - the demonstration with a fictional site (port 8001)
pause
