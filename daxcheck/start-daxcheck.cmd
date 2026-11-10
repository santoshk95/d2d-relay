@echo off
rem Starts the D2D Relay DAX checker: Power BI's own engine checks every report's DAX before it is shared.
rem It opens a minimised window; leave it running while you use the app (close it to stop).
start "D2D Relay DAX checker" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0daxcheck.ps1" %*
