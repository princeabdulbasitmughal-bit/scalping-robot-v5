Set objShell = CreateObject("WScript.Shell")

Dim pythonExe, watchdogScript, workDir
pythonExe    = "C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe"
watchdogScript = "E:\scalping-robot-v5\watchdog_runner.py"
workDir      = "E:\scalping-robot-v5"

' objShell.Run creates process NOT inheriting job objects
' WindowStyle 0 = hidden, bWaitOnReturn = False = fire and forget
objShell.CurrentDirectory = workDir
objShell.Run """" & pythonExe & """ """ & watchdogScript & """", 0, False

WScript.Echo "Watchdog launched via WScript.Shell"
