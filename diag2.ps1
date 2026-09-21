$f = Get-Item 'E:\scalping-robot-v5\live_status.json' -ErrorAction SilentlyContinue
if ($f) {
    $age = [math]::Round(((Get-Date) - $f.LastWriteTime).TotalSeconds, 1)
    Write-Host ("live_status.json LastWrite=" + $f.LastWriteTime + " Age=" + $age + "s")
}

$t = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match 'mt5_live_trader' }
if ($t) {
    Write-Host ("Trader PID=" + $t.ProcessId + " ALIVE=True")
} else {
    Write-Host "Trader NOT running"
}

$uv = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn' -or $_.CommandLine -match 'omnicommand_server' }
if ($uv) {
    foreach ($p in $uv) { Write-Host ("Uvicorn PID=" + $p.ProcessId + " CMD=" + $p.CommandLine.Substring(0, [math]::Min(80, $p.CommandLine.Length))) }
} else {
    Write-Host "Uvicorn NOT running"
}

$tm = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match 'tunnel_manager' } | Select-Object -First 1
if ($tm) {
    Write-Host ("TM PID=" + $tm.ProcessId + " PPID=" + $tm.ParentProcessId)
    $ppid = $tm.ParentProcessId
    $pp = Get-WmiObject Win32_Process | Where-Object { $_.ProcessId -eq $ppid } | Select-Object -First 1
    if ($pp) {
        Write-Host ("Parent Name=" + $pp.Name + " PID=" + $pp.ProcessId)
    } else {
        Write-Host "Parent (PPID=$ppid) NOT FOUND - process orphaned/parent already dead"
    }
}
