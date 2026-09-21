# Step 1: Register watchdog as Scheduled Task using XML
Write-Host "Registering ScalpingWatchdog task..."
$result = schtasks /Create /TN "ScalpingWatchdog" /XML "E:\scalping-robot-v5\watchdog_task.xml" /F 2>&1
Write-Host "schtasks result: $result"

# Step 2: Run it now
Write-Host "Starting task..."
$r2 = schtasks /Run /TN "ScalpingWatchdog" 2>&1
Write-Host "Run result: $r2"

Start-Sleep -Seconds 5

# Step 3: Query status
$r3 = schtasks /Query /TN "ScalpingWatchdog" /FO LIST 2>&1
Write-Host "Task status:"
Write-Host $r3
