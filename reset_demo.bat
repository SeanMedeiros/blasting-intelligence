@echo off
REM Restore the DEMONSTRATION dataset (data\demo\demo.db). The production database is never touched.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set BI_MODE=demo
echo.
echo All data and accounts of the DEMONSTRATION database will be replaced by the fictional dataset.
choice /c YN /m "Continue"
if errorlevel 2 exit /b 0
cd backend
python -m app.seed.generator
echo Demonstration data restored.
pause
