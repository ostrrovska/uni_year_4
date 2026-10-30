<#
  Lab 8 - the registration subsystem in action.

  Produces every category the task requires (successful and failed authentication,
  successful and failed access to objects), then shows that the journal itself is
  protected: it is unreadable without the key, and altering or deleting a record
  is detected.

  Usage:  .\demo.ps1                 (token = auto-detected flash drive)
          .\demo.ps1 -TokenDir C:\temp\tok
#>
param(
    [string]$TokenDir = "",
    [int]$Port = 5707
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$sec  = Split-Path $here -Parent
$lab6 = Join-Path $sec "lab_6"
$lab7 = Join-Path $sec "lab_7"

# python: a bundled embeddable build when present (portable run), else the launcher
$bundled = Join-Path (Split-Path $sec -Parent) "python\python.exe"
if (Test-Path $bundled) { $py = $bundled; $pyArgs = @() }
else { $py = (Get-Command py).Source; $pyArgs = @("-3") }

$log     = Join-Path $here "logs\lab8_protocol.log"
$journal = Join-Path $here "logs\audit.jsonl"
$db      = Join-Path $lab6 "server_db.json"
$auditor = "kovalenko"

New-Item -ItemType Directory -Force -Path (Join-Path $here "logs") | Out-Null
foreach ($f in @($log, $journal, $db)) { if (Test-Path $f) { Remove-Item $f -Force } }

if ($TokenDir -ne "") {
    $tokenArgs = @("--token-dir", $TokenDir)
    $tokenRoot = Join-Path $TokenDir "SECTOKEN"
} else {
    $letter = (Get-Volume | Where-Object { $_.DriveType -eq 'Removable' -and $_.DriveLetter } |
               Select-Object -First 1).DriveLetter
    if (-not $letter) {
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
Write-Host "Security token: $tokenRoot" -ForegroundColor Cyan
Write-Host "Audit journal : $journal" -ForegroundColor Cyan
Write-Host "Auditor       : $auditor" -ForegroundColor Cyan

function Enroll($user, $password, $pin, $slot, [switch]$NoDb) {
    $a = $pyArgs + @((Join-Path $lab6 "enroll.py"), "--user", $user, "--password", $password,
                     "--pin", $pin, "--slot", $slot, "--db", $db, "--log", $log) + $tokenArgs
    if ($NoDb) { $a += "--no-db" }
    & $py $a
}

function Session($title, $pin, $slot, [string[]]$Commands) {
    Write-Host "`n--- $title ---" -ForegroundColor Yellow
    $a = $pyArgs + @("client.py", "--pin", $pin, "--slot", $slot, "--port", $Port, "--log", $log)
    foreach ($c in $Commands) { $a += @("--cmd", $c) }
    Push-Location $lab7
    & $py ($a + $tokenArgs)
    Pop-Location
}

function Tool($script, [string[]]$Extra) {
    & $py ($pyArgs + @((Join-Path $here $script), "--journal", $journal) + $Extra)
}

try {
    Write-Host "`n=== 1. Реєстрація суб'єктів і об'єктів ===" -ForegroundColor Green
    Enroll "ostrovska"  "Kateryna#2026" "1111" "u_ostrovska"
    Enroll "shevchenko" "Taras#1814"    "2222" "u_shevchenko"
    Enroll "kovalenko"  "Olha#7731"     "3333" "u_kovalenko"
    Enroll "mallory"    "Mallory#666"   "5555" "u_mallory" -NoDb
    Enroll "ostrovska"  "WrongPassword" "4444" "u_forged"  -NoDb
    & $py ($pyArgs + @((Join-Path $lab7 "seed_objects.py"), "--log", $log))

    Write-Host "`n=== 2. Сервер з увімкненою підсистемою реєстрації ===" -ForegroundColor Green
    $srv = Start-Process -FilePath $py `
        -ArgumentList ($pyArgs + @("server.py", "--port", $Port, "--db", $db,
                                   "--log", $log, "--audit", $journal, "--auditor", $auditor)) `
        -WorkingDirectory $lab7 -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 900

    Write-Host "`n=== 3. Події, які вимагає завдання ===" -ForegroundColor Green

    Session "A  ostrovska: вдала аутентифікація, доступ дозволений і відхилений" "1111" "u_ostrovska" @(
        "read finance_q1",
        "write finance_q1 quarterly revenue 1 200 000 UAH",
        "read lab_report",
        "delete lab_report",
        "read poems"
    )

    Session "B  невдала аутентифікація: незареєстрований ідентифікатор" "5555" "u_mallory" @("list")
    Session "C  невдала аутентифікація: підроблений токен" "4444" "u_forged" @("list")

    Session "D  ostrovska делегує права" "1111" "u_ostrovska" @(
        "grant finance_q1 shevchenko read",
        "grant finance_q1 kovalenko grant"
    )

    Session "E  shevchenko користується виданим правом" "2222" "u_shevchenko" @(
        "read finance_q1",
        "delete finance_q1"
    )

    Session "F  kovalenko зловживає делегованим правом grant" "3333" "u_kovalenko" @(
        "read finance_q1",
        "grant finance_q1 kovalenko read",
        "read finance_q1",
        "grant finance_q1 kovalenko delete",
        "delete finance_q1"
    )

    Session "G  shevchenko намагається прочитати журнал аудиту" "2222" "u_shevchenko" @("audit 5")
    Session "H  kovalenko як аудитор читає журнал по мережі" "3333" "u_kovalenko" @("audit 8")
}
finally {
    if ($srv -and -not $srv.HasExited) { Stop-Process -Id $srv.Id -Force }
}
Start-Sleep -Milliseconds 500

Write-Host "`n=== 4. Журнал захищено від читання ===" -ForegroundColor Green
Write-Host "Перші 160 байт файлу журналу:" -ForegroundColor DarkGray
$raw = [IO.File]::ReadAllText($journal)
Write-Host $raw.Substring(0, [Math]::Min(160, $raw.Length))
Write-Host "`nСпроба прочитати з чужим ключем:" -ForegroundColor DarkGray
Tool "audit_view.py" @("--key", "not-the-auditor-key", "--tail", "3")

Write-Host "`n=== 5. Цілісність журналу ===" -ForegroundColor Green
Tool "audit_verify.py"

Write-Host "`n--- підміна одного байта в середині журналу ---" -ForegroundColor Yellow
$lines = [IO.File]::ReadAllLines($journal)
$backup = $lines.Clone()
$victim = [Math]::Floor($lines.Count / 2)
$chars = $lines[$victim].ToCharArray()
$chars[20] = $(if ($chars[20] -eq 'A') { 'B' } else { 'A' })
$lines[$victim] = -join $chars
[IO.File]::WriteAllLines($journal, $lines)
Tool "audit_verify.py"

Write-Host "`n--- видалення цілого запису ---" -ForegroundColor Yellow
[IO.File]::WriteAllLines($journal, ($backup[0..($victim - 1)] + $backup[($victim + 1)..($backup.Count - 1)]))
Tool "audit_verify.py"

Write-Host "`n--- журнал відновлено ---" -ForegroundColor Yellow
[IO.File]::WriteAllLines($journal, $backup)
Tool "audit_verify.py"

Write-Host "`n=== 6. Ознаки порушень ===" -ForegroundColor Green
Tool "audit_analyze.py"

Write-Host "`n=== 7. Таблиця «дія користувача - запис у журналі» ===" -ForegroundColor Green
Tool "report_table.py"

Write-Host "`nПротокол: $log" -ForegroundColor Cyan
Write-Host "Таблиця : $(Join-Path $here 'logs\audit_table.md')" -ForegroundColor Cyan
exit 0
