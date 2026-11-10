@echo off
rem Starts the Relay DAX checker: Power BI's own engine checks every report's DAX before it is shared.
rem It opens a minimised window; leave it running while you use the app (close it to stop).
start "Relay DAX checker" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0daxcheck.ps1" %*
