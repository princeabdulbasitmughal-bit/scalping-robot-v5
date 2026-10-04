$py = 'C:\Users\absh5\AppData\Local\Programs\Python\Python311\python.exe'
$pass_count = 0
$fail_count = 0
$fail_list = @()
Get-ChildItem E:\scalping-robot-v5 -Recurse -Filter *.py | ForEach-Object {
    $r = & $py -m py_compile $_.FullName 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PASS $($_.Name)"
        $pass_count++
    } else {
        Write-Host "FAIL $($_.Name): $r"
        $fail_count++
        $fail_list += $_.Name
    }
}
Write-Host "--- TOTAL: $pass_count PASS, $fail_count FAIL ---"
if ($fail_list.Count -gt 0) {
    Write-Host "FAILED FILES: $($fail_list -join ', ')"
}
