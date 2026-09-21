$h5 = 'DOWN'
$h8 = 'DOWN'
try { $r = Invoke-WebRequest -Uri 'http://localhost:5050/api/health' -TimeoutSec 3 -UseBasicParsing; $h5 = $r.StatusCode } catch {}
try { $r = Invoke-WebRequest -Uri 'http://localhost:8899/health' -TimeoutSec 3 -UseBasicParsing; $h8 = $r.StatusCode } catch {}
Write-Host ("5050=" + $h5 + " | 8899=" + $h8)

# Check tunnel_manager parent process to understand how it was launched
Write-Host "--- tunnel_manager parent chain ---"
$tm = Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match 'tunnel_manager' }
if ($tm) {
    Write-Host ("TM PID=" + $tm.ProcessId + " PPID=" + $tm.ParentProcessId)
    $parent = Get-WmiObject Win32_Process -Filter ("ProcessId=" + $tm.ParentProcessId)
    if ($parent) { Write-Host ("Parent: PID=" + $parent.ProcessId + " Name=" + $parent.Name + " CMD=" + $parent.CommandLine) }
    $gp = Get-WmiObject Win32_Process -Filter ("ProcessId=" + $parent.ParentProcessId)
    if ($gp) { Write-Host ("GrandParent: PID=" + $gp.ProcessId + " Name=" + $gp.Name) }
}

# Check job object membership for tunnel_manager
Write-Host "--- Check if processes are in Job Objects ---"
# Use QueryInformationJobObject via PowerShell
$code = @'
using System;
using System.Runtime.InteropServices;
public class JobCheck {
    [DllImport("kernel32.dll")]
    public static extern bool IsProcessInJob(IntPtr hProcess, IntPtr hJob, out bool result);
    [DllImport("kernel32.dll")]
    public static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll")]
    public static extern bool CloseHandle(IntPtr h);
    public static bool InJob(uint pid) {
        IntPtr h = OpenProcess(0x400, false, pid);
        if (h == IntPtr.Zero) return false;
        bool inJob = false;
        IsProcessInJob(h, IntPtr.Zero, out inJob);
        CloseHandle(h);
        return inJob;
    }
}
'@
try {
    Add-Type -TypeDefinition $code -Language CSharp -ErrorAction SilentlyContinue
    foreach ($p in Get-WmiObject Win32_Process | Where-Object { $_.Name -match 'python' }) {
        $inJob = [JobCheck]::InJob($p.ProcessId)
        $shortCmd = if ($p.CommandLine.Length -gt 60) { $p.CommandLine.Substring(0,60) } else { $p.CommandLine }
        Write-Host ("PID=" + $p.ProcessId + " InJob=" + $inJob + " " + $shortCmd)
    }
} catch {
    Write-Host "JobCheck failed: $_"
}
