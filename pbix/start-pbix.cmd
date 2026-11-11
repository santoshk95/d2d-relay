@echo off
rem Starts D2D Relay's Power BI file maker: Power BI Desktop on this PC turns every published dashboard into a .pbix.
rem It opens a minimised window; leave it running while you use the app (close it to stop). While it works, Power BI
rem Desktop windows open and close by themselves; leave them alone.
start "D2D Relay Power BI file maker" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pbix.ps1" %*
