@echo off
REM Shows whether the background server is running and answering.
REM   service_status.bat           status
REM   service_status.bat restart   restart it (as Administrator, e.g. after editing server.env or renewing the certificate)
cd /d "%~dp0"
set A=%~1
if "%A%"=="" set A=status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\service.ps1" -Action %A%
pause
