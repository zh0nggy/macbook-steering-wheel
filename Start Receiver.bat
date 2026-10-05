@echo off
rem Double-click on Windows to open the Tilt Wheel receiver without a console.
cd /d "%~dp0"
start "" pythonw receiver_app.pyw
