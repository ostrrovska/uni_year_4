<#
  Hands the portable demo package to the virtual machine over HTTP.

  No USB drive and no Guest Additions needed: the VM has a bridged adapter, so it
  reaches this machine over the local network and downloads the package with Edge.

  Usage:  .\serve_to_vm.ps1          (serves C:\Users\<you>\BPD_SHARE on port 8000)
          .\serve_to_vm.ps1 -Port 8080 -ShareDir D:\somewhere
#>
param(
    [int]$Port = 8000,
    [string]$ShareDir = (Join-Path $env:USERPROFILE "BPD_SHARE")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path (Join-Path $ShareDir "BPD_LAB.zip"))) {
    throw "BPD_LAB.zip not found in $ShareDir"
}

$ip = (Get-NetIPConfiguration |
       Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
       Select-Object -First 1).IPv4Address.IPAddress
if (-not $ip) { throw "Could not determine this machine's address on the network." }

$py = (Get-Command py).Source

Write-Host @"

Serving $ShareDir on port $Port.
Only this one folder is exposed - it holds nothing but the package.

Inside the virtual machine:
  1. open Edge
  2. go to   http://${ip}:${Port}/BPD_LAB.zip
  3. save the file, right-click it -> Extract All
  4. open the extracted folder and run DEMO_LAB6.bat, then DEMO_LAB7.bat

Press Ctrl+C in this window when you are done.

"@ -ForegroundColor Cyan

& $py -3 -m http.server $Port --directory $ShareDir --bind 0.0.0.0
