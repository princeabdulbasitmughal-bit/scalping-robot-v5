Start-Sleep -Seconds 20
Get-Content 'E:\scalping-robot-v5\supervisor.log' -Tail 10 -ErrorAction SilentlyContinue
Write-Host '--- Watchdog log ---'
Get-Content 'E:\scalping-robot-v5\watchdog_out.log' -Tail 10 -ErrorAction SilentlyContinue
Write-Host '--- 8899 check ---'
$h8 = 'DOWN'
try { $r = Invoke-WebRequest -Uri 'http://localhost:8899/health' -TimeoutSec 3 -UseBasicParsing; $h8 = $r.StatusCode } catch {}
Write-Host "8899=$h8"
Write-Host '--- All Python PIDs ---'
$procs = Get-WmiObject Win32_Process -Filter "Name='python.exe'"
foreach ($p in $procs) {
    Write-Host ($p.ProcessId.ToString() + ' ' + $p.CommandLine)
}
