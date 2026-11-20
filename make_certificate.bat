@echo off
REM HTTPS certificate for this server, signed by the site's internal certificate authority (created the first time).
REM   make_certificate.bat                         names and IPv4 addresses of this computer
REM   make_certificate.bat --dns blasting.mine.local --ip 10.20.1.15
REM Certificate issued by IT instead (.pfx):   .venv\Scripts\python -m app.manage import-pfx C:\path\server.pfx  (from backend\)
cd /d "%~dp0"
if not exist .venv (echo Run setup.bat first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
cd backend
python -m app.manage make-cert %*
pause
