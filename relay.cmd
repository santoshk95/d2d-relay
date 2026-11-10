@echo off
rem RELAY by PASDACS: relay start, stop, restart, status, logs, backup, export, import FILE, login, open, build, load FILE
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0relay.ps1" %*
exit /b %ERRORLEVEL%
