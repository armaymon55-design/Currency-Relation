@echo off
rem Starts the live updater and the dashboard in two windows, then opens the page.
rem Needs the XM MT5 terminal installed (the updater launches it if it is not running).
cd /d "%~dp0"
set PY=C:\Users\ahmed\AppData\Local\Programs\Python\Python313\python.exe
start "Currency relations - live updater" "%PY%" scripts\live.py
start "Currency relations - dashboard"    "%PY%" app\server.py
rem full path: a shell like Git Bash on PATH can otherwise shadow Windows' timeout.exe
"%SystemRoot%\System32\timeout.exe" /t 8 /nobreak >nul
start "" http://127.0.0.1:5050
