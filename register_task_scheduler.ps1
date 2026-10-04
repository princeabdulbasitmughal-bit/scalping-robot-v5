# ==============================================================
# register_task_scheduler.ps1
# Registers Scalping Robot watchdog as a Windows Task Scheduler
# task that starts at boot and restarts on failure.
# Run once as Administrator.
# ==============================================================

$py   = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\pythonw.exe'
$base = 'E:\scalping-robot-v5'

# ── Unregister old task if it exists ──────────────────────
Unregister-ScheduledTask -TaskName 'ScalpingWatchdog' -Confirm:$false -ErrorAction SilentlyContinue

# ── Create new task action ────────────────────────────────
$action = New-ScheduledTaskAction `
    -Execute $py `
    -Argument "$base\watchdog_runner.py" `
    -WorkingDirectory $base

# ── Trigger at system startup ─────────────────────────────
$trigger = New-ScheduledTaskTrigger -AtStartup

# ── Principal: run as current user, highest privilege ─────
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

# ── Settings: restart on failure, no time limit ───────────
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

# ── Register ──────────────────────────────────────────────
Register-ScheduledTask `
    -TaskName  'ScalpingWatchdog' `
    -Action    $action `
    -Trigger   $trigger `
    -Principal $principal `
    -Settings  $settings `
    -Description 'Scalping Robot V5 — persistent watchdog (auto-restart on failure)' `
    -Force

# ── Start it now immediately ──────────────────────────────
Start-ScheduledTask -TaskName 'ScalpingWatchdog'
Start-Sleep 3

$state = (Get-ScheduledTask -TaskName 'ScalpingWatchdog').State
Write-Host "Task state: $state"
Write-Host "ScalpingWatchdog registered and started. It will auto-start on every reboot."
