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

# ── Auto-restart / Heal Trader if stale, missing, or trader_status != 'ACTIVE_SCALPING' ──
$healedTrader = $false
$statusFile   = "$base\live_status.json"
$needHeal     = $false

$traderStatus = $null
if ($health -and $health.trader_status) {
    $traderStatus = $health.trader_status
} elseif (Test-Path $statusFile) {
    try {
        $statusObj = Get-Content $statusFile -Raw | ConvertFrom-Json
        $traderStatus = $statusObj.status
    } catch {}
}

if (-not (Test-Path $statusFile)) {
    $needHeal = $true
} else {
    try {
        $age = ((Get-Date) - (Get-Item $statusFile).LastWriteTime).TotalSeconds
        if ($age -gt 90) { $needHeal = $true }   # 90s stale threshold
    } catch { $needHeal = $true }
}

# Auto-restart logic: if trader_status is NOT 'ACTIVE_SCALPING', restart trader
if ($traderStatus -ne 'ACTIVE_SCALPING') {
    $needHeal = $true
}

if ($needHeal) {
    # Kill any stuck python trader processes
    Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowTitle -eq "" -and $_.CPU -lt 0.1
    } | Stop-Process -Force -ErrorAction SilentlyContinue

    Start-Sleep 1

    # Restart trader
    $py = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe'
    Start-Process -FilePath $py -ArgumentList '-m','python_engine.mt5_live_trader','--symbol','XAUUSD','--lot','0.02','--iterations','999999','--interval','0.5' -WorkingDirectory 'E:\scalping-robot-v5' -WindowStyle Hidden
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

# If trader_status is still not ACTIVE_SCALPING after re-fetch, restart trader
if ($health -and ($health.trader_status -ne 'ACTIVE_SCALPING') -and (-not $healedTrader)) {
    $py = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe'
    Start-Process -FilePath $py -ArgumentList '-m','python_engine.mt5_live_trader','--symbol','XAUUSD','--lot','0.02','--iterations','999999','--interval','0.5' -WorkingDirectory 'E:\scalping-robot-v5' -WindowStyle Hidden
    $healedTrader = $true
    Start-Sleep 5
    try {
        $health = Invoke-RestMethod 'http://localhost:8899/health' -TimeoutSec 8
    } catch {}
}

# ── Read last 5 lines of trader log ───────────────────────
$traderLog = Get-Content "$base\trader_err.log" -Tail 5 -ErrorAction SilentlyContinue
$port8899  = netstat -ano | findstr ':8899'

# ── Extract metrics for grade, balance trend, warning, and history ──
$currentBalance  = $null
$currentEquity   = $null
$currentDailyPnl = $null
$currentPrice    = $null
$winRate         = $null
$totalTrades     = $null

if ($health) {
    if ($null -ne $health.balance) { $currentBalance = [double]$health.balance }
    if ($null -ne $health.equity) { $currentEquity = [double]$health.equity }
    if ($null -ne $health.daily_pnl) { $currentDailyPnl = [double]$health.daily_pnl }
    if ($null -ne $health.current_price -and $health.current_price -ne 0) { $currentPrice = [double]$health.current_price }
    if ($null -ne $health.win_rate_pct) { $winRate = [double]$health.win_rate_pct }
    if ($null -ne $health.total_trades) { $totalTrades = [int]$health.total_trades }
}

if (Test-Path $statusFile) {
    try {
        $liveData = Get-Content $statusFile -Raw | ConvertFrom-Json
        if ($null -eq $currentBalance -and $null -ne $liveData.balance) { $currentBalance = [double]$liveData.balance }
        if ($null -eq $currentEquity -and $null -ne $liveData.equity) { $currentEquity = [double]$liveData.equity }
        if ($null -eq $currentDailyPnl -and $null -ne $liveData.daily_pnl) { $currentDailyPnl = [double]$liveData.daily_pnl }
        if ($null -eq $currentPrice -and $null -ne $liveData.current_price -and $liveData.current_price -ne 0) { $currentPrice = [double]$liveData.current_price }
        if ($null -eq $winRate -and $null -ne $liveData.win_rate_pct) { $winRate = [double]$liveData.win_rate_pct }
        if ($null -eq $totalTrades -and $null -ne $liveData.total_trades) { $totalTrades = [int]$liveData.total_trades }
    } catch {}
}

# ── Balance trend vs previous cycle (prev_balance.txt) ────
$prevBalanceFile = "$base\prev_balance.txt"
$prevBalance = $null
$balanceTrend = "N/A (Baseline initialized)"

if (Test-Path $prevBalanceFile) {
    try {
        $prevRaw = (Get-Content $prevBalanceFile -Raw -ErrorAction SilentlyContinue)
        if ($prevRaw) {
            $prevRaw = $prevRaw.Trim()
            if ($prevRaw -match '^-?[\d\.]+$') {
                $prevBalance = [double]$prevRaw
            }
        }
    } catch {}
}

if ($null -ne $currentBalance) {
    if ($null -ne $prevBalance) {
        $balDiff = [math]::Round(($currentBalance - $prevBalance), 2)
        if ($balDiff -gt 0) {
            $balanceTrend = "+`$$balDiff (UP from `$$prevBalance to `$$currentBalance)"
        } elseif ($balDiff -lt 0) {
            $absDiff = [math]::Abs($balDiff)
            $balanceTrend = "-`$$absDiff (DOWN from `$$prevBalance to `$$currentBalance)"
        } else {
            $balanceTrend = "`$0.00 (FLAT at `$$currentBalance)"
        }
    } else {
        $balanceTrend = "`$0.00 (Baseline set at `$$currentBalance)"
    }
    Set-Content $prevBalanceFile $currentBalance
}

# ── Trade activity & 60-min stagnation check ───────────────
$lastTradeDt = $null

if (Test-Path "$base\trader_err.log") {
    $tradeLines = Get-Content "$base\trader_err.log" -Tail 1000 -ErrorAction SilentlyContinue | Select-String -Pattern "\[TRADE CLOSED\]|\[NEW POSITION"
    if ($tradeLines) {
        $lastLine = $tradeLines | Select-Object -Last 1
        if ($lastLine.Line -match '^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})') {
            try {
                $lastTradeDt = [datetime]::ParseExact($matches[1], 'yyyy-MM-dd HH:mm:ss', $null)
            } catch {}
        }
    }
}

if (Test-Path $statusFile) {
    try {
        $sObj = Get-Content $statusFile -Raw | ConvertFrom-Json
        if ($sObj.open_positions) {
            foreach ($pos in $sObj.open_positions) {
                if ($pos.open_time) {
                    $posDt = [datetime]::Parse($pos.open_time).ToLocalTime()
                    if ($null -eq $lastTradeDt -or $posDt -gt $lastTradeDt) {
                        $lastTradeDt = $posDt
                    }
                }
            }
        }
    } catch {}
}

$warnNoTrades = $false
$hasCurrentPrice = ($null -ne $currentPrice -and $currentPrice -gt 0)

if ($lastTradeDt) {
    $minSinceTrade = ((Get-Date) - $lastTradeDt).TotalMinutes
    if ($minSinceTrade -ge 60 -and $hasCurrentPrice) {
        $warnNoTrades = $true
    }
} elseif ($hasCurrentPrice) {
    # No trades recorded at all
    $warnNoTrades = $true
}

# ── Performance Grade calculation ─────────────────────────
$perfWinRate = if ($null -ne $winRate) { [double]$winRate } else { 0.0 }
$perfGrade = 'C'
if ($perfWinRate -gt 90) {
    $perfGrade = 'A+'
} elseif ($perfWinRate -gt 85) {
    $perfGrade = 'A'
} elseif ($perfWinRate -gt 75) {
    $perfGrade = 'B'
} else {
    $perfGrade = 'C'
}

# ── Save balance history to balance_history.json ───────────
$balanceHistoryFile = "$base\balance_history.json"
$history = @()
if (Test-Path $balanceHistoryFile) {
    try {
        $rawHist = Get-Content $balanceHistoryFile -Raw -ErrorAction SilentlyContinue
        if ($rawHist -and $rawHist.Trim() -ne '') {
            $parsedHist = $rawHist | ConvertFrom-Json
            if ($parsedHist) {
                $history = @($parsedHist)
            }
        }
    } catch {
        $history = @()
    }
}

$historyEntry = [PSCustomObject]@{
    cycle        = $cycleNum
    timestamp    = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')
    balance      = if ($null -ne $currentBalance) { [double]$currentBalance } else { 0.0 }
    equity       = if ($null -ne $currentEquity) { [double]$currentEquity } else { 0.0 }
    daily_pnl    = if ($null -ne $currentDailyPnl) { [double]$currentDailyPnl } else { 0.0 }
    win_rate_pct = $perfWinRate
    grade        = $perfGrade
    trend        = $balanceTrend
}
$history += $historyEntry

$jsonStr = if ($history.Count -eq 1) {
    "[`n" + ($history[0] | ConvertTo-Json -Depth 5) + "`n]"
} else {
    $history | ConvertTo-Json -Depth 5
}
Set-Content $balanceHistoryFile $jsonStr

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

if ($warnNoTrades) {
    Write-Host "WARNING: No trades for 60+ min" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "--- PERFORMANCE GRADE ---"
Write-Host "PERFORMANCE GRADE : $perfGrade"
Write-Host "Grade: $perfGrade (Win Rate: $perfWinRate%)"
Write-Host "BALANCE TREND     : $balanceTrend"
Write-Host ""
