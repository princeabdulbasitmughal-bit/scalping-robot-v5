Select-String -Path 'E:\scalping-robot-v5\python_engine\mt5_live_trader.py' -Pattern 'print\(' | Select-Object LineNumber,Line | Format-Table -AutoSize -Wrap
