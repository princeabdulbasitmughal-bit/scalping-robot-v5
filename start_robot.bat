@echo off
:: Scalping Robot V5 - Auto-Start Launcher
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start_all.ps1"
