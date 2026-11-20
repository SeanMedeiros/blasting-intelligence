@echo off
REM Stops and removes the background server and its firewall rules. Data, backups and certificates are kept.
cd /d "%~dp0"
net session >nul 2>&1 || (echo Right-click uninstall_service.bat and choose "Run as administrator". & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\service.ps1" -Action uninstall
pause
