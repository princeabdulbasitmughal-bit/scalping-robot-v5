@echo off
title SCALPING ROBOT V5 PRO - METATRADER 5 LIVE TRADER
color 0A
cd /d "E:\scalping-robot-v5"

echo ==============================================================================
echo   SCALPING ROBOT V5 PRO - METATRADER 5 LIVE TRADING ENGINE
echo ==============================================================================
echo [INFO] Target Symbol: XAUUSD (Gold)
echo [INFO] Default Lot Size: 0.01
echo [INFO] Risk Guard: Max 1.5%% Stop-Loss ^| MaxOrders=1 ^| Trailing TP
echo [INFO] Iterations: 99999999 (continuous)
echo.

:restart
echo [%TIME%] Starting trader...
python -m python_engine.mt5_live_trader --symbol XAUUSD --lot 0.01 --iterations 99999999 --interval 1.0
echo [%TIME%] Trader exited. Restarting in 5 seconds...
timeout /t 5 /nobreak
goto restart
