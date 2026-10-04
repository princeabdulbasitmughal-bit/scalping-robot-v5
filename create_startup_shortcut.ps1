$startupFolder = [Environment]::GetFolderPath('Startup')
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut("$startupFolder\ScalpingRobot.lnk")
$shortcut.TargetPath = 'E:\scalping-robot-v5\start_robot.bat'
$shortcut.WorkingDirectory = 'E:\scalping-robot-v5'
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Host "Startup shortcut created at: $startupFolder\ScalpingRobot.lnk"
