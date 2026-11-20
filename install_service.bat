@echo off
REM Installs Blasting Intelligence as a background server (Windows scheduled task at start-up, restarted if it stops),
REM opens the firewall port(s) and protects the certificate folder. Run as Administrator.
REM   install_service.bat                        runs as the local SYSTEM account
REM   install_service.bat -Account MINE\svc-blasting   runs as a service account (password prompted)
cd /d "%~dp0"
net session >nul 2>&1 || (echo Right-click install_service.bat and choose "Run as administrator". & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\service.ps1" -Action install %*
pause
