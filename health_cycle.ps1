# ============================================================
# SCALPING ROBOT V5 — HEALTH CYCLE & SELF-HEAL WATCHDOG
# Fixes: dynamic cycle counter, log append, correct stale logic
# ============================================================

$py      = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe'
$pythonw = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\pythonw.exe'
$base    = 'E:\scalping-robot-v5'

# ── Cycle counter (persisted across runs) ──────────────────
$counterFile = "$base\cycle_count.txt"
$cycleNum = 1
if (Test-Path $counterFile) {
    try { $cycleNum = [int](Get-Content $counterFile -Raw) + 1 } catch {}
}
Set-Content $counterFile $cycleNum

# ── Check API health ───────────────────────────────────────
$apiOk  = $false
$health = $null
try {
    $health = Invoke-RestMethod 'http://localhost:8899/health' -TimeoutSec 6
    $apiOk  = $true
} catch {}

# ── Read tunnel URL ────────────────────────────────────────
$tunnelUrl = Get-Content "$base\tunnel_url.txt" -ErrorAction SilentlyContinue

# ── Heal API (uvicorn) if down ────────────────────────────
$healedApi = $false
if (-not $apiOk) {
    # Kill any zombie uvicorn on port 8899
    $zombie = Get-NetTCPConnection -LocalPort 8899 -ErrorAction SilentlyContinue
    if ($zombie) {
        $zombie | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        Start-Sleep 2
    }
    Start-Process -FilePath $py `
        -ArgumentList '-m','uvicorn','omnicommand_server:app','--host','0.0.0.0','--port','8899','--log-level','warning' `
        -WorkingDirectory $base `
        -RedirectStandardOutput "$base\uvicorn_out.log" `
        -RedirectStandardError  "$base\uvicorn_err.log" `
        -WindowStyle Hidden
    $healedApi = $true
    Start-Sleep 7
    try {
        $health = Invoke-RestMethod 'http://localhost:8899/health' -TimeoutSec 6
        $apiOk  = $true
    } catch {}
}

# ── Heal Trader if stale or missing ───────────────────────
$healedTrader = $false
$statusFile   = "$base\live_status.json"
$needHeal     = $false

if (-not (Test-Path $statusFile)) {
    $needHeal = $true
} else {
    try {
        $age = ((Get-Date) - (Get-Item $statusFile).LastWriteTime).TotalSeconds
        if ($age -gt 90) { $needHeal = $true }   # 90s stale threshold (was 120 — more responsive)
    } catch { $needHeal = $true }
}

if ($needHeal) {
    # Kill any stuck python trader processes
    Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowTitle -eq "" -and $_.CPU -lt 0.1
    } | Stop-Process -Force -ErrorAction SilentlyContinue

    Start-Sleep 1

    # Launch trader — use APPEND mode for logs (>> not >)
    $traderArgs = '-m','python_engine.mt5_live_trader','--symbol','XAUUSD','--lot','0.02','--iterations','999999','--interval','0.5'
    Start-Process -FilePath $py `
        -ArgumentList $traderArgs `
        -WorkingDirectory $base `
        -RedirectStandardError "$base\trader_err.log" `
        -WindowStyle Hidden
    $healedTrader = $true
    Start-Sleep 5
}

# ── Heal Tunnel watchdog if stale ─────────────────────────
$healedTunnel = $false
try {
    $tunnelAge = ((Get-Date) - (Get-Item "$base\tunnel_watchdog.log").LastWriteTime).TotalSeconds
    if ($tunnelAge -gt 300) { throw "stale" }
} catch {
    Start-Process -FilePath $pythonw -ArgumentList "$base\tunnel_watchdog.py" -WorkingDirectory $base
    $healedTunnel = $true
    Start-Sleep 3
    $tunnelUrl = Get-Content "$base\tunnel_url.txt" -ErrorAction SilentlyContinue
}

# ── Re-fetch health after heals ───────────────────────────
if ($healedApi -or $healedTrader) {
    Start-Sleep 3
    try {
        $health = Invoke-RestMethod 'http://localhost:8899/health' -TimeoutSec 8
        $apiOk  = $true
    } catch {}
}

# ── Read last 5 lines of trader log ───────────────────────
$traderLog = Get-Content "$base\trader_err.log" -Tail 5 -ErrorAction SilentlyContinue
$port8899  = netstat -ano | findstr ':8899'

# ── Print cycle report ─────────────────────────────────────
$cycleTime = Get-Date -Format 'HH:mm:ss'
Write-Host ""
Write-Host "===[ CYCLE $cycleNum | $cycleTime PKT ]===" -ForegroundColor Cyan
Write-Host "API=$apiOk | HEAL_API=$healedApi | HEAL_TRADER=$healedTrader | HEAL_TUNNEL=$healedTunnel"
Write-Host "TUNNEL=$tunnelUrl"
if ($health) {
    Write-Host ""
    $health | Select-Object ok,trader_status,balance,equity,daily_pnl,open_positions,current_price,last_signal,total_trades,win_rate_pct | Format-List
}
if ($traderLog) {
    Write-Host "--- TRADER ERR LOG (last 5) ---"
    $traderLog
}
Write-Host "PORT 8899: $port8899"
Write-Host ""
