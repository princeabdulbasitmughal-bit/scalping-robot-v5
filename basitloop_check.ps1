# ============================================================
# BasitLoop Autonomous Health Monitor + Auto-Restart
# FIXED: Port 5051 for SuperSender Pro (was 5050 - WRONG)
# FIXED: Correct uvicorn restart command
# FIXED: Stale status detection with age check
# ============================================================

$h5 = 'DOWN'
$h8 = 'DOWN'

# SuperSender Pro is on PORT 5051 (per .env PORT=5051)
try { $r = Invoke-WebRequest -Uri 'http://localhost:5051/api/health' -TimeoutSec 4 -UseBasicParsing; $h5 = $r.StatusCode } catch {}
try { $r = Invoke-WebRequest -Uri 'http://localhost:8899/health' -TimeoutSec 4 -UseBasicParsing; $h8 = $r.StatusCode } catch {}

# -----------------------------------------------
# If 8899 DOWN - restart with CORRECT uvicorn command
# -----------------------------------------------
if ($h8 -ne 200 -and $h8 -ne '200') {
    Write-Host "8899 DOWN - restarting uvicorn..."
    # Kill any stale uvicorn/omnicommand processes first
    Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match 'omnicommand_server|uvicorn.*8899' } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    $py = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe'
    $uargs = '-m uvicorn omnicommand_server:app --host 0.0.0.0 --port 8899'
    Start-Process -FilePath $py -ArgumentList $uargs -WorkingDirectory 'E:\scalping-robot-v5' -WindowStyle Hidden
    Start-Sleep -Seconds 8
    $h8 = 'FAIL'
    try { $r = Invoke-WebRequest -Uri 'http://localhost:8899/health' -TimeoutSec 4 -UseBasicParsing; $h8 = $r.StatusCode } catch {}
    Write-Host ("8899 after restart: " + $h8)
}

# -----------------------------------------------
# If SuperSender 5051 DOWN - restart it
# -----------------------------------------------
if ($h5 -ne 200 -and $h5 -ne '200') {
    Write-Host "SuperSender (5051) DOWN - restarting..."
    Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match 'server\.js' -and $_.ExecutablePath -match 'node' } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
    Start-Process -FilePath 'node' -ArgumentList 'server.js' -WorkingDirectory 'E:\supersenderpro' -WindowStyle Hidden
    Start-Sleep -Seconds 10
    try { $r = Invoke-WebRequest -Uri 'http://localhost:5051/api/health' -TimeoutSec 5 -UseBasicParsing; $h5 = $r.StatusCode } catch { $h5 = 'STILL_DOWN' }
    Write-Host ("5051 after restart: " + $h5)
}

# -----------------------------------------------
# If trader not running - restart it
# -----------------------------------------------
$trader = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match 'mt5_live_trader' }
if (-not $trader) {
    Write-Host "Trader NOT running - restarting..."
    $py = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe'
    $targs = '-m python_engine.mt5_live_trader --symbol XAUUSD --lot 0.01 --iterations 999999 --interval 1.0'
    Start-Process -FilePath $py -ArgumentList $targs -WorkingDirectory 'E:\scalping-robot-v5' -WindowStyle Hidden
    Write-Host "Trader restart issued"
}

# -----------------------------------------------
# Status Report
# -----------------------------------------------
$raw = Get-Content 'E:\scalping-robot-v5\live_status.json' -Raw -ErrorAction SilentlyContinue
if ($raw) {
    $s = $raw | ConvertFrom-Json
    $net = [math]::Round($s.balance - 10000, 2)
    $netSign = if ($net -ge 0) { "+" } else { "" }
    $age = 0
    try { $age = [math]::Round(((Get-Date).ToUniversalTime() - [datetime]$s.updated_at).TotalMinutes, 1) } catch {}
    $traderAlive = if ($age -lt 5) { "ALIVE" } else { "STALE(${age}min)" }

    Write-Host "============================================"
    Write-Host ("  BASITLOOP REPORT | " + (Get-Date -Format 'HH:mm:ss PKT'))
    Write-Host "============================================"
    Write-Host ("SuperSender(5051)=" + $h5 + " | OmniCmd(8899)=" + $h8)
    Write-Host ("BAL=$" + $s.balance + " | NET=" + $netSign + $net + " | WIN=" + $s.win_rate_pct + "% | GOLD=$" + $s.current_price)
    Write-Host ("TRADES=" + $s.total_trades + " | SPREAD=" + $s.spread_pips + "pip | TRADER=" + $traderAlive)

    # Alerts
    if ($h5 -ne 200 -and $h5 -ne '200') { Write-Host "*** CRITICAL: SuperSender 5051 DOWN ***" }
    if ($net -lt -100) { Write-Host "*** CRITICAL: NET < -$100 ***" }
    if ($s.win_rate_pct -lt 40 -and $s.total_trades -gt 5) { Write-Host "*** WARNING: WIN RATE < 40% ***" }
    if ($age -gt 10) { Write-Host "*** WARNING: TRADER STATUS STALE (${age}min) ***" }
    if ($net -ge 0) { Write-Host ">>> PROFITABLE: NET +$$net <<<" }
    Write-Host "============================================"
} else {
    Write-Host "live_status.json not found - trader may not be running"
}
