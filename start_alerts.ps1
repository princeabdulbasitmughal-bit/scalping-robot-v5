$pythonw = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\pythonw.exe'
$baseDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
Start-Process -FilePath $pythonw -ArgumentList (Join-Path $baseDir 'alert_system.py') -WindowStyle Hidden

