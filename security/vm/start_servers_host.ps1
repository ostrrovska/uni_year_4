<#
  Two-machine run: this script is the SERVER side, launched on the host.

  It determines the host address on the local network, writes it onto the
  security token (server_ip.txt) so that the client in the virtual machine
  picks it up by itself, and opens two visible console windows: lab 6 on port
  5607 and lab 7 on port 5707, both bound to 0.0.0.0.

  Leave the windows open, run RUN_ON_VM.bat inside the VM, and watch the
  incoming peer addresses appear - that is the proof of a distributed run.

  Usage:  .\start_servers_host.ps1
          .\start_servers_host.ps1 -Enroll            (re-enroll users first)
          .\start_servers_host.ps1 -ServerIP 1.2.3.4  (override autodetection)
#>
param(
    [switch]$Enroll,
    [string]$ServerIP = ""
)

$ErrorActionPreference = "Stop"
$sec  = Split-Path $PSScriptRoot -Parent
$lab6 = Join-Path $sec "lab_6"
$lab7 = Join-Path $sec "lab_7"
$py   = (Get-Command py).Source
$log  = Join-Path $sec "vm\logs\vm_test.log"
$db   = Join-Path $lab6 "server_db.json"

New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if (Test-Path $log) { Remove-Item $log -Force }

# a previous run may still hold the ports
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 5607, 5707 } |
    ForEach-Object {
        Write-Host "stopping previous server (pid $($_.OwningProcess))" -ForegroundColor DarkGray
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }

# the address the VM has to connect to: the interface that owns the default route
if ($ServerIP -eq "") {
    $ServerIP = (Get-NetIPConfiguration |
                 Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
                 Select-Object -First 1).IPv4Address.IPAddress
}
if (-not $ServerIP) { throw "Could not determine the host address - pass -ServerIP manually." }

# where the tokens go: the flash drive when one is plugged in, otherwise a folder
# next to the portable package, which the virtual machine downloads together with it
$share = Join-Path $env:USERPROFILE "BPD_SHARE"
$flash = (Get-Volume | Where-Object { $_.DriveType -eq "Removable" -and $_.DriveLetter } |
          Select-Object -First 1).DriveLetter
if ($flash) {
    $tokenArgs = @()
    $tokenHome = "${flash}:"
} else {
    New-Item -ItemType Directory -Force -Path $share | Out-Null
    $tokenArgs = @("--token-dir", $share)
    $tokenHome = $share
    Write-Host "No removable drive - tokens go to $share" -ForegroundColor Yellow
}

if ($Enroll) {
    Write-Host "Enrolling users on the security token..." -ForegroundColor Green
    & $py (@("-3", (Join-Path $lab6 "enroll.py"), "--user", "ostrovska",  "--password", "Kateryna#2026", "--pin", "1111", "--slot", "u_ostrovska",  "--db", $db, "--log", $log) + $tokenArgs)
    & $py (@("-3", (Join-Path $lab6 "enroll.py"), "--user", "shevchenko", "--password", "Taras#1814",    "--pin", "2222", "--slot", "u_shevchenko", "--db", $db, "--log", $log) + $tokenArgs)
    & $py (@("-3", (Join-Path $lab6 "enroll.py"), "--user", "kovalenko",  "--password", "Olha#7731",     "--pin", "3333", "--slot", "u_kovalenko",  "--db", $db, "--log", $log) + $tokenArgs)
    & $py (@("-3", (Join-Path $lab6 "enroll.py"), "--user", "mallory",    "--password", "Mallory#666",   "--pin", "5555", "--slot", "u_mallory", "--no-db", "--log", $log) + $tokenArgs)
    & $py -3 (Join-Path $lab7 "seed_objects.py") --log $log
}

# hand the address to the client the same way the tokens travel
[IO.File]::WriteAllText((Join-Path $tokenHome "server_ip.txt"), $ServerIP, [Text.Encoding]::ASCII)
Write-Host "Server address $ServerIP written to $tokenHome" -ForegroundColor Green

if (-not $flash) {
    # one small archive the VM downloads next to the package: tokens + address
    $bundle = Join-Path $share "token.zip"
    if (Test-Path $bundle) { Remove-Item $bundle -Force }
    Compress-Archive -Path (Join-Path $share "SECTOKEN"), (Join-Path $share "server_ip.txt") `
                     -DestinationPath $bundle -Force
    Write-Host "Tokens packed into $bundle - download it in the VM and unpack it" -ForegroundColor Green
    Write-Host "next to CLIENT_TO_HOST.bat" -ForegroundColor Green
}

Write-Host "`nStarting servers on 0.0.0.0 (reachable at $ServerIP)" -ForegroundColor Green
Start-Process $py -ArgumentList @("-3", "server.py", "--host", "0.0.0.0", "--port", "5607",
                                  "--db", $db, "--log", $log) -WorkingDirectory $lab6
Start-Process $py -ArgumentList @("-3", "server.py", "--host", "0.0.0.0", "--port", "5707",
                                  "--db", $db, "--log", $log) -WorkingDirectory $lab7

Write-Host @"

Both servers are up in their own windows.

  lab 6 (authentication) : ${ServerIP}:5607
  lab 7 (access control) : ${ServerIP}:5707
  joint log              : $log

Now, inside the virtual machine:
  1. open the security token in Explorer
  2. double-click RUN_ON_VM.bat   (no arguments needed)
  3. screenshot the VM window and the two server windows

Close the server windows when you are done.
"@ -ForegroundColor Cyan
