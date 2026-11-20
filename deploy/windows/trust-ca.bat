@echo off
REM Run on a WORKSTATION (as Administrator) to trust the site's internal certificate authority.
REM   trust-ca.bat \\server\share\ca.crt
REM For many workstations prefer a Group Policy (see docs\DEPLOYMENT.md).
if "%~1"=="" (echo Usage: trust-ca.bat path\to\ca.crt & exit /b 1)
net session >nul 2>&1 || (echo Run as administrator. & exit /b 1)
certutil -addstore -f Root "%~1"
