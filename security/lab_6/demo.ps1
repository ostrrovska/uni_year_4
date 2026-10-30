<#
  Lab 6, variant 2 - full work protocol on the loopback interface.
  Enrolls three users on the security token, then runs one successful and
  four unsuccessful authentications. Everything lands in logs\lab6_protocol.log.

  Usage:  .\demo.ps1                 (token = auto-detected flash drive)
          .\demo.ps1 -TokenDir C:\tmp\fake_token   (no flash drive needed)
#>
param(
    [string]$TokenDir = "",
    [int]$Port = 5607
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
# python: a bundled embeddable build when present (portable run, nothing installed),
# otherwise the launcher of the local installation
$bundled = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "python\python.exe"
if (Test-Path $bundled) { $py = $bundled; $pyArgs = @() }
else { $py = (Get-Command py).Source; $pyArgs = @("-3") }
$log  = Join-Path $here "logs\lab6_protocol.log"
$db   = Join-Path $here "server_db.json"

if (Test-Path $log) { Remove-Item $log -Force }
if (Test-Path $db)  { Remove-Item $db  -Force }

if ($TokenDir -ne "") {
    $tokenArgs = @("--token-dir", $TokenDir)
    $tokenRoot = Join-Path $TokenDir "SECTOKEN"
} else {
    $letter = (Get-Volume | Where-Object { $_.DriveType -eq 'Removable' -and $_.DriveLetter } |
               Select-Object -First 1).DriveLetter
    if (-not $letter) {
        # no flash drive at hand: fall back to a folder that stands in for the token.
        # The file format and its protection are identical, only the medium differs.
        $TokenDir = Join-Path $env:LOCALAPPDATA "BPD_TOKEN"
        New-Item -ItemType Directory -Force -Path $TokenDir | Out-Null
        $tokenArgs = @("--token-dir", $TokenDir)
        $tokenRoot = Join-Path $TokenDir "SECTOKEN"
        Write-Host "No removable drive found - using a stand-in token folder:" -ForegroundColor Yellow
        Write-Host "  $tokenRoot" -ForegroundColor Yellow
    } else {
        $tokenArgs = @()
        $tokenRoot = "${letter}:\SECTOKEN"
    }
}
Write-Host "Security token directory: $tokenRoot" -ForegroundColor Cyan

function Enroll($user, $password, $pin, $slot, [switch]$NoDb) {
    $a = $pyArgs + @("enroll.py", "--user", $user, "--password", $password, "--pin", $pin,
           "--slot", $slot, "--log", $log) + $tokenArgs
    if ($NoDb) { $a += "--no-db" }
    & $py @a
}

function TryAuth($title, $pin, $slot) {
    Write-Host "`n--- $title ---" -ForegroundColor Yellow
    & $py @pyArgs "client.py" "--pin" $pin "--slot" $slot "--port" $Port "--log" $log @tokenArgs
    Write-Host "exit code: $LASTEXITCODE"
}

Push-Location $here
try {
    Write-Host "`n=== 1. Enrollment of three users ===" -ForegroundColor Green
    Enroll "ostrovska"  "Kateryna#2026" "1111" "u_ostrovska"
    Enroll "shevchenko" "Taras#1814"    "2222" "u_shevchenko"
    Enroll "kovalenko"  "Olha#7731"     "3333" "u_kovalenko"

    Write-Host "`n=== 2. Forged tokens for the negative tests ===" -ForegroundColor Green
    # same identifier, different password -> hash image will not match the database
    Enroll "ostrovska" "WrongPassword" "4444" "u_forged" -NoDb
    # identifier that was never registered on the server
    Enroll "mallory"   "Mallory#666"   "5555" "u_mallory" -NoDb

    # bit-flip inside an otherwise valid token file
    Copy-Item (Join-Path $tokenRoot "u_kovalenko\token.dat") `
              (New-Item -ItemType Directory -Force -Path (Join-Path $tokenRoot "u_damaged")).FullName
    $dmg = Join-Path $tokenRoot "u_damaged\token.dat"
    $bytes = [IO.File]::ReadAllBytes($dmg)
    $bytes[25] = $bytes[25] -bxor 0xFF
    [IO.File]::WriteAllBytes($dmg, $bytes)
    Write-Host "Damaged copy prepared: $dmg (byte 25 inverted)"

    Write-Host "`n=== 3. Starting the authentication server ===" -ForegroundColor Green
    $srv = Start-Process -FilePath $py `
        -ArgumentList ($pyArgs + @("server.py", "--port", $Port, "--log", $log)) `
        -WorkingDirectory $here -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 900

    TryAuth "TEST 1 (positive): ostrovska, correct PIN"            "1111" "u_ostrovska"
    TryAuth "TEST 2 (positive): shevchenko, correct PIN"           "2222" "u_shevchenko"
    TryAuth "TEST 3 (negative): kovalenko, WRONG PIN"              "9999" "u_kovalenko"
    TryAuth "TEST 4 (negative): forged token, wrong password"      "4444" "u_forged"
    TryAuth "TEST 5 (negative): identifier unknown to the server"  "5555" "u_mallory"
    TryAuth "TEST 6 (negative): token file damaged (bit flip)"     "3333" "u_damaged"
}
finally {
    if ($srv -and -not $srv.HasExited) { Stop-Process -Id $srv.Id -Force }
    Pop-Location
}

Write-Host "`n=== 4. Proof that the token file is protected ===" -ForegroundColor Green
$sample = Join-Path $tokenRoot "u_ostrovska\token.dat"
Write-Host "File: $sample  ($((Get-Item $sample).Length) bytes)"
$raw = [IO.File]::ReadAllBytes($sample)
($raw[0..47] | ForEach-Object { "{0:X2}" -f $_ }) -join " "
Write-Host "`nProtocol written to: $log" -ForegroundColor Cyan

exit 0
