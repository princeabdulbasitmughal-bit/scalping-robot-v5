# ==============================================================
# create_startup_shortcut.ps1
# Creates/updates Windows Startup file for Scalping Robot V5
# ==============================================================
$startupFolder = [Environment]::GetFolderPath('Startup')
$cmdFile = Join-Path $startupFolder 'start_all_robot.cmd'
$cmdContent = 'powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File E:\scalping-robot-v5\start_all.ps1'

# Remove legacy lnk if present to avoid dual launch
$legacyLnk = Join-Path $startupFolder 'ScalpingRobot.lnk'
if (Test-Path $legacyLnk) {
    Remove-Item $legacyLnk -Force -ErrorAction SilentlyContinue
}

Set-Content -Path $cmdFile -Value $cmdContent -Force
Write-Host "Startup script successfully created at: $cmdFile"
