Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

Dim pythonExe, watchdogScript, logFile
pythonExe = "C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe"
watchdogScript = "E:\scalping-robot-v5\watchdog_runner.py"
logFile = "E:\scalping-robot-v5\vbs_launcher.log"

Dim fLog
Set fLog = objFSO.OpenTextFile(logFile, 8, True)

fLog.WriteLine("[" & Now() & "] VBS launcher starting...")
fLog.Close

Dim restartCount
restartCount = 0

Do While True
    ' Check if watchdog is running
    Dim isRunning
    isRunning = False
    
    Dim oExec, sLine
    Set oExec = objShell.Exec("tasklist /FI ""IMAGENAME eq python.exe"" /FO CSV")
    Dim allOutput
    allOutput = ""
    Do While Not oExec.StdOut.AtEndOfStream
        sLine = oExec.StdOut.ReadLine()
        allOutput = allOutput & sLine
    Loop
    
    If InStr(allOutput, "watchdog_runner") > 0 Then
        isRunning = True
    End If
    
    If Not isRunning Then
        restartCount = restartCount + 1
        Set fLog = objFSO.OpenTextFile(logFile, 8, True)
        fLog.WriteLine("[" & Now() & "] Watchdog NOT running. Restart #" & restartCount & ". Launching...")
        fLog.Close
        
        ' Launch watchdog in its own window, detached
        objShell.Run """" & pythonExe & """ """ & watchdogScript & """", 1, False
    End If
    
    ' Sleep 10 seconds
    WScript.Sleep 10000
Loop
