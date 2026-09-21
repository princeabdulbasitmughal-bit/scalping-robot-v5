Start-Sleep -Seconds 25

Write-Host "=== WATCHDOG STATUS ==="
Get-Content 'E:\scalping-robot-v5\watchdog_out.log' -Tail 12 -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== PYTHON PROCESSES ==="
$procs = Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' }
foreach ($p in $procs) {
    $short = if ($p.CommandLine.Length -gt 80) { $p.CommandLine.Substring(0,80) } else { $p.CommandLine }
    Write-Host ("PID=" + $p.ProcessId + " " + $short)
}

Write-Host ""
Write-Host "=== 8899 CHECK ==="
$h8 = 'DOWN'
try { $r = Invoke-WebRequest -Uri 'http://localhost:8899/health' -TimeoutSec 3 -UseBasicParsing; $h8 = $r.StatusCode } catch {}
Write-Host ("8899=" + $h8)
