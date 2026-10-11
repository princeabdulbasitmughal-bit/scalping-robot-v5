# ==============================================================================
# start_all.ps1 - Scalping Robot V5 Complete Auto-Start Orchestrator
# Auto-starts all components in sequence with proper spacing and hidden windows.
# ==============================================================================

# Ensure working directory is the repository root dynamically
$baseDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
Set-Location $baseDir

# Ensure Python 3.11 environment is on PATH
$pythonDir = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311'
$scriptsDir = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\Scripts'
if ($env:PATH -notlike "*$pythonDir*") {
    $env:PATH = "$pythonDir;$scriptsDir;$env:PATH"
}

# a. OmniCommand server
$serverScript = Join-Path $baseDir 'omnicommand_server.py'
Start-Process pythonw -ArgumentList $serverScript -WindowStyle Hidden

# b. Wait 2 seconds
Start-Sleep 2

# c. Trader via watchdog
Start-Process python -ArgumentList '-m python_engine.mt5_live_trader --symbol XAUUSD --lot 0.02 --iterations 999999 --interval 0.5' -WorkingDirectory $baseDir -WindowStyle Hidden

# d. Wait 3 seconds
Start-Sleep 3

# e. Tunnel watchdog
$tunnelScript = Join-Path $baseDir 'tunnel_watchdog.py'
Start-Process pythonw -ArgumentList $tunnelScript -WindowStyle Hidden

# f. Auto backup
$backupScript = Join-Path $baseDir 'auto_backup.py'
Start-Process pythonw -ArgumentList $backupScript -WindowStyle Hidden

# g. Log
$logMessage = "All systems started at $(Get-Date)"
Write-Host $logMessage
$startupLog = Join-Path $baseDir 'startup.log'
Add-Content -Path $startupLog -Value $logMessage -ErrorAction SilentlyContinue
