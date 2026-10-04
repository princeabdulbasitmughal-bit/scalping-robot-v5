# ==============================================================================
# start_all.ps1 - Scalping Robot V5 Complete Auto-Start Orchestrator
# Auto-starts all components in sequence with proper spacing and hidden windows.
# ==============================================================================

# Ensure working directory is the repository root
Set-Location 'E:\scalping-robot-v5'

# Ensure Python 3.11 environment is on PATH
$pythonDir = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311'
$scriptsDir = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\Scripts'
if ($env:PATH -notlike "*$pythonDir*") {
    $env:PATH = "$pythonDir;$scriptsDir;$env:PATH"
}

# a. OmniCommand server: Start-Process pythonw -ArgumentList 'E:\scalping-robot-v5\omnicommand_server.py' -WindowStyle Hidden
Start-Process pythonw -ArgumentList 'E:\scalping-robot-v5\omnicommand_server.py' -WindowStyle Hidden

# b. Wait 2 seconds: Start-Sleep 2
Start-Sleep 2

# c. Trader via watchdog: Start-Process python -ArgumentList '-m python_engine.mt5_live_trader --symbol XAUUSD --lot 0.02 --iterations 999999 --interval 0.5' -WorkingDirectory 'E:\scalping-robot-v5' -WindowStyle Hidden
Start-Process python -ArgumentList '-m python_engine.mt5_live_trader --symbol XAUUSD --lot 0.02 --iterations 999999 --interval 0.5' -WorkingDirectory 'E:\scalping-robot-v5' -WindowStyle Hidden

# d. Wait 3 seconds: Start-Sleep 3
Start-Sleep 3

# e. Tunnel watchdog: Start-Process pythonw -ArgumentList 'E:\scalping-robot-v5\tunnel_watchdog.py' -WindowStyle Hidden
Start-Process pythonw -ArgumentList 'E:\scalping-robot-v5\tunnel_watchdog.py' -WindowStyle Hidden

# f. Auto backup: Start-Process pythonw -ArgumentList 'E:\scalping-robot-v5\auto_backup.py' -WindowStyle Hidden
Start-Process pythonw -ArgumentList 'E:\scalping-robot-v5\auto_backup.py' -WindowStyle Hidden

# g. Log: Write-Host 'All systems started at $(Get-Date)'
$logMessage = "All systems started at $(Get-Date)"
Write-Host $logMessage
Add-Content -Path 'E:\scalping-robot-v5\startup.log' -Value $logMessage -ErrorAction SilentlyContinue
