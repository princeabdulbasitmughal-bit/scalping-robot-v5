@echo off
:: Scalping Robot V5 — Auto-Start Launcher
:: Place shortcut to this file in Windows Startup folder:
:: %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
cd /d E:\scalping-robot-v5
start "" /B "C:\Users\absh5\AppData\Local\Programs\Python\Python311\pythonw.exe" "E:\scalping-robot-v5\watchdog_runner.py"
