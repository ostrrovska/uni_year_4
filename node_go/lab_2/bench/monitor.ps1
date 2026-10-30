# Samples CPU time and working set of a running service while a load test runs.
# k6 only measures the client side, so the CPU and RAM columns of the lab table
# come from here.
#
# Usage:
#   .\monitor.ps1 -ProcessId 13668 -DurationSec 35

param(
    [Parameter(Mandatory = $true)]
    [int]$ProcessId,

    [int]$DurationSec = 35,

    [int]$IntervalMs = 250
)

# Note: the parameter is -ProcessId, not -Pid, because $PID is a reserved
# PowerShell automatic variable holding the current shell's own process id.

$proc = Get-Process -Id $ProcessId -ErrorAction Stop
$cores = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors

$cpuSecondsStart = $proc.CPU
$peakRamMb = 0
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

Write-Host "Sampling $($proc.ProcessName) (pid $ProcessId) for $DurationSec s..."

while ($stopwatch.Elapsed.TotalSeconds -lt $DurationSec) {
    if ($proc.HasExited) {
        Write-Warning "Process exited early."
        break
    }

    $proc.Refresh()
    $ramMb = [math]::Round($proc.WorkingSet64 / 1MB, 1)
    if ($ramMb -gt $peakRamMb) { $peakRamMb = $ramMb }

    Start-Sleep -Milliseconds $IntervalMs
}

$proc.Refresh()
$cpuSecondsUsed = $proc.CPU - $cpuSecondsStart
$wallSeconds = $stopwatch.Elapsed.TotalSeconds
$percentOfOneCore = ($cpuSecondsUsed / $wallSeconds) * 100

[PSCustomObject]@{
    ProcessName      = $proc.ProcessName
    ProcessId        = $ProcessId
    LogicalCores     = $cores
    WallClockSec     = [math]::Round($wallSeconds, 1)
    CpuSeconds       = [math]::Round($cpuSecondsUsed, 2)
    CpuPercentOfCore = [math]::Round($percentOfOneCore, 1)
    CpuPercentOfHost = [math]::Round($percentOfOneCore / $cores, 1)
    PeakRamMB        = $peakRamMb
}
