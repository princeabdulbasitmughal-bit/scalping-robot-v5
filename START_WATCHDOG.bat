@echo off
:loop
echo [%TIME%] Starting Watchdog v5...
cd /d E:\scalping-robot-v5
python watchdog_runner.py >> watchdog_launcher.log 2>&1
echo [%TIME%] Watchdog exited - restarting in 3s...
timeout /t 3 /nobreak >nul
goto loop
