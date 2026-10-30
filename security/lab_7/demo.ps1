<#
  Lab 7, variant 1 - work protocol of the discretionary access control subsystem.
  Three subjects, twelve protected objects, allowed and denied operations,
  delegation and revocation of rights by the owner.

  Usage:  .\demo.ps1                 (token = auto-detected flash drive)
          .\demo.ps1 -TokenDir C:\tmp\fake_token
#>
param(
    [string]$TokenDir = "",
    [int]$Port = 5707
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$lab6 = Join-Path (Split-Path $here -Parent) "lab_6"
# python: a bundled embeddable build when present (portable run, nothing installed),
# otherwise the launcher of the local installation
$bundled = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "python\python.exe"
if (Test-Path $bundled) { $py = $bundled; $pyArgs = @() }
else { $py = (Get-Command py).Source; $pyArgs = @("-3") }
$log  = Join-Path $here "logs\lab7_protocol.log"
$db   = Join-Path $lab6 "server_db.json"

if (Test-Path $log) { Remove-Item $log -Force }
if (Test-Path $db)  { Remove-Item $db  -Force }

if ($TokenDir -ne "") { $tokenArgs = @("--token-dir", $TokenDir) }
else {
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
        Write-Host "Security token: ${letter}:\SECTOKEN" -ForegroundColor Cyan
    }
}

function Enroll($user, $password, $pin, $slot) {
    & $py ($pyArgs + @((Join-Path $lab6 "enroll.py"), "--user", $user, "--password", $password,
             "--pin", $pin, "--slot", $slot, "--db", $db, "--log", $log) + $tokenArgs)
}

function Session($title, $pin, $slot, [string[]]$Commands) {
    Write-Host "`n--- $title ---" -ForegroundColor Yellow
    $a = $pyArgs + @("client.py", "--pin", $pin, "--slot", $slot, "--port", $Port, "--log", $log)
    foreach ($c in $Commands) { $a += @("--cmd", $c) }
    & $py ($a + $tokenArgs)
}

Push-Location $here
try {
    Write-Host "`n=== 1. Three subjects enrolled on the security token ===" -ForegroundColor Green
    Enroll "ostrovska"  "Kateryna#2026" "1111" "u_ostrovska"
    Enroll "shevchenko" "Taras#1814"    "2222" "u_shevchenko"
    Enroll "kovalenko"  "Olha#7731"     "3333" "u_kovalenko"

    Write-Host "`n=== 2. Twelve protected objects ===" -ForegroundColor Green
    & $py @pyArgs "seed_objects.py" "--log" $log

    Write-Host "`n=== 3. Access control server ===" -ForegroundColor Green
    $srv = Start-Process -FilePath $py `
        -ArgumentList ($pyArgs + @("server.py", "--port", $Port, "--db", $db, "--log", $log)) `
        -WorkingDirectory $here -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 900

    Session "S1  ostrovska: owner works with her own objects" "1111" "u_ostrovska" @(
        "list",
        "matrix",
        "caps",
        "read finance_q1",
        "write finance_q1 revenue 1 200 000 UAH",
        "read finance_q1",
        "rights finance_q1"
    )

    Session "S2  shevchenko: attempts against somebody else's objects" "2222" "u_shevchenko" @(
        "read finance_q1",
        "write finance_q1 injected by shevchenko",
        "delete diary",
        "grant finance_q1 shevchenko read",
        "read lab_report"
    )

    Session "S3  ostrovska grants rights (discretionary control)" "1111" "u_ostrovska" @(
        "grant finance_q1 shevchenko read",
        "grant finance_q2 shevchenko write",
        "grant finance_q1 kovalenko grant",
        "rights finance_q1"
    )

    Session "S4  shevchenko uses the rights he was given" "2222" "u_shevchenko" @(
        "read finance_q1",
        "write finance_q2 added by shevchenko",
        "delete finance_q1",
        "caps"
    )

    Session "S5  kovalenko re-delegates (weakness of discretionary control)" "3333" "u_kovalenko" @(
        "read finance_q1",
        "grant finance_q1 kovalenko read",
        "read finance_q1",
        "grant finance_q1 kovalenko own"
    )

    Session "S6  ostrovska revokes the rights" "1111" "u_ostrovska" @(
        "revoke finance_q1 shevchenko read",
        "revoke finance_q1 kovalenko read",
        "revoke finance_q1 kovalenko grant",
        "rights finance_q1"
    )

    Session "S7  shevchenko after the revocation" "2222" "u_shevchenko" @(
        "read finance_q1",
        "read finance_q2"
    )

    Session "S8  kovalenko: own objects, creation, ownership transfer" "3333" "u_kovalenko" @(
        "create meeting_notes Notes of the meeting on 11.10.2026",
        "read meeting_notes",
        "write public_notes anyone may be allowed to read this",
        "grant public_notes shevchenko read",
        "grant protocol ostrovska own",
        "read protocol",
        "delete grades",
        "list"
    )

    Session "S9  ostrovska: final state of the access matrix" "1111" "u_ostrovska" @(
        "read protocol",
        "matrix",
        "list"
    )
}
finally {
    if ($srv -and -not $srv.HasExited) { Stop-Process -Id $srv.Id -Force }
    Pop-Location
}

Write-Host "`nProtocol written to: $log" -ForegroundColor Cyan
exit 0
