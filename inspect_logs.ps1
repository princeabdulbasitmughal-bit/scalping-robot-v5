$base = 'E:\scalping-robot-v5'

Write-Host '--- trader_err.log (last 20) ---'
Get-Content "$base\trader_err.log" -Tail 20 -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '--- trader_out.log (last 20) ---'
Get-Content "$base\trader_out.log" -Tail 20 -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '--- live_status.json ---'
Get-Content "$base\live_status.json" -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '--- live_status.json age (seconds) ---'
try {
    $age = ((Get-Date) - (Get-Item "$base\live_status.json").LastWriteTime).TotalSeconds
    Write-Host "Age: $age seconds"
} catch {
    Write-Host "Could not read age"
}
