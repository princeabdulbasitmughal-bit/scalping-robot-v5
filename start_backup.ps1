$pythonw = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\pythonw.exe'
Start-Process -FilePath $pythonw -ArgumentList 'E:\scalping-robot-v5\auto_backup.py' -WindowStyle Hidden
Write-Output "Auto-backup process launched in background."
