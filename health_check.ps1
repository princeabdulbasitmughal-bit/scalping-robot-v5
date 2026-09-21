$h5 = 'DOWN'
$h8 = 'DOWN'
try { $r = Invoke-WebRequest -Uri 'http://localhost:5050/api/health' -TimeoutSec 3 -UseBasicParsing; $h5 = $r.StatusCode } catch {}
try { $r = Invoke-WebRequest -Uri 'http://localhost:8899/health' -TimeoutSec 3 -UseBasicParsing; $h8 = $r.StatusCode } catch {}
Write-Host "5050=$h5 | 8899=$h8"

Write-Host "--- Watchdog log tail ---"
Get-Content 'E:\scalping-robot-v5\watchdog_out.log' -Tail 10 -ErrorAction SilentlyContinue

Write-Host "--- Python PIDs ---"
$procs = Get-WmiObject Win32_Process -Filter "Name='python.exe'"
foreach ($p in $procs) {
    Write-Host ("PID=" + $p.ProcessId + " CMD=" + $p.CommandLine)
}

Write-Host "--- MT5 status ---"
try {
    $raw = Get-Content 'E:\scalping-robot-v5\live_status.json' -Raw -ErrorAction SilentlyContinue
    if ($raw) {
        $s = $raw | ConvertFrom-Json
        $net = [math]::Round($s.balance - 10000, 2)
        $age = [math]::Round(((Get-Date) - [datetime]$s.updated_at).TotalMinutes, 1)
        Write-Host ("BAL=" + $s.balance + " NET=+" + $net + " WIN=" + $s.win_rate_pct + "% GOLD=" + $s.current_price + " AGE=" + $age + "min")
    }
} catch {}
