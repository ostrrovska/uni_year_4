<#
.SYNOPSIS
    Lab 4 demo - layered architecture in Node.js and Go.

.DESCRIPTION
    One run covers every requirement of the lab, in nine stages:

      1. Build both services (npm install, go build).
      2. Service-layer tests, with no HTTP server involved at all.
      3. Start both services with the in-memory repository.
      4. Walk every endpoint and every status code: 200, 201, 204, 400, 404, 409.
      5. Show the request-logging middleware output, duration included.
      6. Swap the repository to the JSON file store and restart twice, proving
         the data survives while no Service, Controller or Router code changed.
      7. Point the file store at a corrupt file to reach the 500 branch of the
         centralized error handler.
      8. API-layer tests for both services.
      9. A table mapping each requirement to the stage that demonstrated it.

    Every request in stage 4 asserts the status code it expects, so a
    regression makes the demo fail loudly instead of printing a wrong number.

.EXAMPLE
    ./demo.ps1
    ./demo.ps1 -SkipTests     # only the live HTTP stages
#>
[CmdletBinding()]
param(
    [string]$Go = "go",
    [int]$NodePort = 3100,
    [int]$GoPort = 8180,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

# The node test reporter prints check marks and triangles in UTF-8. The Windows
# console usually runs a DOS code page, which would decode each of those bytes
# on its own and show mojibake, so child output is decoded as UTF-8 instead.
# Restored in the finally block, because this outlives the script otherwise.
$previousOutputEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = $PSScriptRoot
$nodeService = Join-Path $root "node-service"
$goService = Join-Path $root "go-service"
$goBinary = Join-Path $goService "bin\lab4-go.exe"
$logDir = Join-Path $root "logs"
$dataDir = Join-Path $root "data"

$nodeUrl = "http://localhost:$NodePort"
$goUrl = "http://localhost:$GoPort"

$script:backends = @()
$script:failures = 0

$httpClient = [System.Net.Http.HttpClient]::new()
$httpClient.Timeout = [timespan]::FromSeconds(15)

function Write-Head {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Write-Sub {
    param([string]$Text)
    Write-Host ""
    Write-Host "-- $Text" -ForegroundColor DarkCyan
}

# The node spec reporter marks results with U+2714, U+25B6 and U+2139. On a
# console in a DOS code page those arrive as mojibake, so they are replaced with
# ASCII and the test stages stay legible in any terminal. [char] is used because
# the `u{} escape needs PowerShell 6.
function Convert-ReporterGlyph {
    param([string]$Line)

    return $Line.
        Replace([string][char]0x2714, "[ok]").
        Replace([string][char]0x25B6, "[--]").
        Replace([string][char]0x2139, "[ i]")
}

function Write-Note {
    param([string]$Text)
    Write-Host "   $Text" -ForegroundColor DarkGray
}

# Kills whatever is already listening, so a service left behind by an
# interrupted run cannot make this one fail.
function Clear-Port {
    param([int]$Port)

    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

function Wait-Ready {
    param([string]$Name, [int]$Port, [int]$Attempts = 60)

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $health = Invoke-RestMethod "http://localhost:$Port/health" -TimeoutSec 2
            if ($health.status -eq "ok") {
                Write-Note "$Name listening on $Port, repository: $($health.repository)"
                return $health
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }

    throw "$Name did not become ready on port $Port - see $logDir"
}

function Start-Backend {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory,
        [int]$Port,
        [hashtable]$Environment = @{}
    )

    $logPath = Join-Path $logDir "$Name.log"
    $errorPath = Join-Path $logDir "$Name.err.log"
    Remove-Item $logPath, $errorPath -Force -ErrorAction SilentlyContinue

    # Start-Process has no environment parameter, so the variables are set in
    # this session and inherited by the child, then removed again.
    foreach ($key in $Environment.Keys) {
        Set-Item -Path "env:$key" -Value $Environment[$key]
    }
    try {
        # ArgumentList rejects an empty array, and the Go binary takes none.
        $options = @{
            FilePath               = $FilePath
            WorkingDirectory       = $WorkingDirectory
            RedirectStandardOutput = $logPath
            RedirectStandardError  = $errorPath
            PassThru               = $true
            NoNewWindow            = $true
        }
        if ($Arguments -and $Arguments.Count -gt 0) { $options["ArgumentList"] = $Arguments }

        $process = Start-Process @options
    }
    finally {
        foreach ($key in $Environment.Keys) {
            Remove-Item -Path "env:$key" -ErrorAction SilentlyContinue
        }
    }

    $script:backends += [pscustomobject]@{ Name = $Name; Process = $process; Log = $logPath }

    Wait-Ready -Name $Name -Port $Port | Out-Null
    return $process
}

function Start-BothBackends {
    param([string]$Repository = "memory", [string]$NodeDataFile, [string]$GoDataFile)

    $nodeEnvironment = @{ PORT = "$NodePort"; ITEM_REPO = $Repository }
    $goEnvironment = @{ PORT = "$GoPort"; ITEM_REPO = $Repository }

    if ($NodeDataFile) { $nodeEnvironment["ITEM_DATA_FILE"] = $NodeDataFile }
    if ($GoDataFile) { $goEnvironment["ITEM_DATA_FILE"] = $GoDataFile }

    Start-Backend -Name "node" -FilePath "node" -Arguments @("src/server.js") `
        -WorkingDirectory $nodeService -Port $NodePort -Environment $nodeEnvironment | Out-Null

    Start-Backend -Name "go" -FilePath $goBinary -Arguments @() `
        -WorkingDirectory $goService -Port $GoPort -Environment $goEnvironment | Out-Null
}

function Stop-Backends {
    foreach ($backend in $script:backends) {
        if ($backend.Process -and -not $backend.Process.HasExited) {
            Stop-Process -Id $backend.Process.Id -Force -ErrorAction SilentlyContinue
            $backend.Process.WaitForExit(5000) | Out-Null
        }
    }
    $script:backends = @()
}

# Sends one request and checks it against the expected status code, and against
# the expected error code where the response carries one.
function Invoke-Api {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$BaseUrl,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][int]$Expect,
        [string]$Body,
        [string]$ContentType = "application/json",
        [string]$ExpectError,
        [string]$Comment
    )

    $request = [System.Net.Http.HttpRequestMessage]::new(
        [System.Net.Http.HttpMethod]::new($Method), "$BaseUrl$Path")
    if ($PSBoundParameters.ContainsKey("Body")) {
        $request.Content = [System.Net.Http.StringContent]::new(
            $Body, [System.Text.Encoding]::UTF8, $ContentType)
    }

    $response = $httpClient.SendAsync($request).GetAwaiter().GetResult()
    $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    $status = [int]$response.StatusCode
    $response.Dispose()
    $request.Dispose()

    $errorCode = $null
    if ($payload -and $payload.TrimStart().StartsWith("{")) {
        try { $errorCode = ($payload | ConvertFrom-Json).error } catch { }
    }

    $passed = $status -eq $Expect
    if ($passed -and $ExpectError -and $errorCode -ne $ExpectError) { $passed = $false }

    $shown = ($payload -replace "\s+", " ").Trim()
    if ($shown.Length -gt 96) { $shown = $shown.Substring(0, 96) + "..." }
    $line = "{0,-6} {1,-24} {2}  {3}" -f $Method, $Path, $status, $shown

    if ($passed) {
        Write-Host "  ok   $line" -ForegroundColor Green
    }
    else {
        $script:failures++
        $wanted = "$Expect"
        if ($ExpectError) { $wanted = "$Expect / $ExpectError" }
        Write-Host "  FAIL $line" -ForegroundColor Red
        Write-Host "       expected $wanted" -ForegroundColor Red
    }

    if ($Comment) { Write-Note $Comment }

    return [pscustomobject]@{ Status = $status; Body = $payload; Error = $errorCode }
}

# Every endpoint and every status code the lab requires, against one service.
function Invoke-EndpointWalk {
    param([string]$Name, [string]$BaseUrl)

    Write-Sub "$Name - $BaseUrl"

    Invoke-Api GET $BaseUrl "/health" -Expect 200 | Out-Null
    Invoke-Api GET $BaseUrl "/api/items" -Expect 200 -Comment "порожній список" | Out-Null

    Invoke-Api POST $BaseUrl "/api/items" -Expect 201 `
        -Body '{"name":"Keyboard","description":"Mechanical"}' -Comment "201 Created" | Out-Null
    Invoke-Api GET $BaseUrl "/api/items" -Expect 200 | Out-Null
    Invoke-Api GET $BaseUrl "/api/items/1" -Expect 200 | Out-Null

    Write-Note "далі - помилки, кожна через один централізований обробник"
    Invoke-Api POST $BaseUrl "/api/items" -Expect 409 -ExpectError "item_name_taken" `
        -Body '{"name":"KEYBOARD"}' -Comment "409: бізнес-правило унікальності імені, без урахування регістру" | Out-Null
    Invoke-Api POST $BaseUrl "/api/items" -Expect 400 -ExpectError "invalid_item" `
        -Body '{"description":"nameless"}' -Comment "400: обов'язкове поле відсутнє" | Out-Null
    Invoke-Api POST $BaseUrl "/api/items" -Expect 400 -ExpectError "invalid_item" `
        -Body '{"name":"   "}' -Comment "400: порожнє значення" | Out-Null
    Invoke-Api POST $BaseUrl "/api/items" -Expect 400 -ExpectError "invalid_item" `
        -Body '{"name":42}' -Comment "400: неправильний тип даних" | Out-Null
    Invoke-Api POST $BaseUrl "/api/items" -Expect 400 -ExpectError "invalid_json" `
        -Body '{ "name": ' -Comment "400: Invalid JSON" | Out-Null
    Invoke-Api POST $BaseUrl "/api/items" -Expect 400 -ExpectError "invalid_content_type" `
        -Body 'name=Keyboard' -ContentType "text/plain" -Comment "400: middleware 2, не JSON" | Out-Null

    Invoke-Api GET $BaseUrl "/api/items/abc" -Expect 400 -ExpectError "invalid_id" `
        -Comment "400: middleware 2 відкидає id до Controller, Service не викликається" | Out-Null
    Invoke-Api GET $BaseUrl "/api/items/0" -Expect 400 -ExpectError "invalid_id" | Out-Null
    Invoke-Api GET $BaseUrl "/api/items/9999" -Expect 404 -ExpectError "item_not_found" `
        -Comment "404: сутності немає" | Out-Null

    Invoke-Api PUT $BaseUrl "/api/items/1" -Expect 200 `
        -Body '{"name":"Keypad","description":"Compact"}' | Out-Null
    Invoke-Api PUT $BaseUrl "/api/items/9999" -Expect 404 -ExpectError "item_not_found" `
        -Body '{"name":"Ghost"}' | Out-Null

    Invoke-Api DELETE $BaseUrl "/api/items/1" -Expect 204 -Comment "204: тіло порожнє" | Out-Null
    Invoke-Api GET $BaseUrl "/api/items/1" -Expect 404 -ExpectError "item_not_found" `
        -Comment "після DELETE сутність справді зникла" | Out-Null

    Invoke-Api GET $BaseUrl "/api/nothing-here" -Expect 404 -ExpectError "route_not_found" `
        -Comment "невідомий маршрут - той самий формат помилки" | Out-Null
}

function Show-AccessLog {
    param([string]$Name, [string]$Path, [int]$Tail = 10)

    Write-Sub "$Name"

    if (-not (Test-Path $Path)) {
        Write-Host "  (лог відсутній: $Path)" -ForegroundColor Yellow
        return
    }

    $lines = Get-Content $Path |
        Where-Object { $_ -match '^(GET|POST|PUT|DELETE|PATCH) \S+ \d{3} \d+ms$' }

    if (-not $lines) {
        Write-Host "  (у лозі ще немає записів доступу)" -ForegroundColor Yellow
        return
    }

    $lines | Select-Object -Last $Tail | ForEach-Object { Write-Host "  $_" }
    Write-Note "усього рядків доступу: $($lines.Count) (показано останні $Tail)"
}

function Invoke-Tests {
    param([string]$Title, [string]$NodeArguments, [string]$GoPattern)

    Write-Sub "Node.js: node $NodeArguments"
    Push-Location $nodeService
    try {
        # Routed through Write-Host like the Go output below, so the stages stay
        # in order when the whole run is piped into a file.
        & node $NodeArguments.Split(" ") 2>&1 |
            ForEach-Object { Write-Host "  $(Convert-ReporterGlyph $_)" }
        if ($LASTEXITCODE -ne 0) {
            $script:failures++
            Write-Host "  Node тести провалились" -ForegroundColor Red
        }
    }
    finally {
        Pop-Location
    }

    Write-Sub "Go: go test ./tests -count=1 -run $GoPattern"
    Push-Location $goService
    try {
        # -count=1 disables the test cache, so the stage always really runs.
        & $Go test ./tests -count=1 -run $GoPattern -v 2>&1 |
            Where-Object { $_ -match '^(--- (PASS|FAIL|SKIP)|ok\s|FAIL\s|PASS\s|FAIL$)' } |
            ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) {
            $script:failures++
            Write-Host "  Go тести провалились" -ForegroundColor Red
        }
    }
    finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $logDir, $dataDir | Out-Null
Clear-Port $NodePort
Clear-Port $GoPort

try {
    Write-Head "1. Збірка"

    Push-Location $nodeService
    try {
        if (Test-Path "node_modules") {
            Write-Note "node_modules вже на місці, npm install пропущено"
        }
        else {
            & npm install --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
        }
    }
    finally {
        Pop-Location
    }

    Push-Location $goService
    try {
        & $Go build -o bin\lab4-go.exe ./cmd/server
        if ($LASTEXITCODE -ne 0) { throw "go build failed" }
        Write-Note "go build -o bin\lab4-go.exe ./cmd/server - готово"

        & $Go vet ./...
        if ($LASTEXITCODE -ne 0) { throw "go vet failed" }
        Write-Note "go vet ./... - чисто"
    }
    finally {
        Pop-Location
    }

    if (-not $SkipTests) {
        Write-Head "2. Тести рівня Service - без жодного HTTP-сервера"
        Write-Note "Service конструюється напряму з repository: ані порту, ані Express, ані net/http"
        Invoke-Tests -Title "Service" `
            -NodeArguments "--test --test-reporter=spec tests/item.service.test.js" `
            -GoPattern "^TestItemService"
    }

    Write-Head "3. Запуск обох сервісів (repository: memory)"
    Start-BothBackends -Repository "memory"

    Write-Head "4. Усі endpoint і всі коди відповіді"
    Invoke-EndpointWalk -Name "Node.js (Express)" -BaseUrl $nodeUrl
    Invoke-EndpointWalk -Name "Go (net/http)" -BaseUrl $goUrl

    Write-Head "5. Middleware 1: логування запитів (метод, шлях, код, тривалість)"
    Show-AccessLog -Name "Node.js" -Path (Join-Path $logDir "node.log")
    Show-AccessLog -Name "Go" -Path (Join-Path $logDir "go.log")

    Write-Head "6. Підміна Repository: InMemory -> File, той самий Service"
    Stop-Backends
    Remove-Item (Join-Path $dataDir "*.json") -Force -ErrorAction SilentlyContinue

    $nodeData = Join-Path $dataDir "node-items.json"
    $goData = Join-Path $dataDir "go-items.json"

    Write-Sub "Перший запуск із файловим сховищем"
    Start-BothBackends -Repository "file" -NodeDataFile $nodeData -GoDataFile $goData
    Invoke-Api POST $nodeUrl "/api/items" -Expect 201 -Body '{"name":"Persisted","description":"survives a restart"}' | Out-Null
    Invoke-Api POST $goUrl "/api/items" -Expect 201 -Body '{"name":"Persisted","description":"survives a restart"}' | Out-Null

    Write-Sub "Перезапуск: процеси вбито, дані лишились у файлі"
    Stop-Backends
    Start-BothBackends -Repository "file" -NodeDataFile $nodeData -GoDataFile $goData
    Invoke-Api GET $nodeUrl "/api/items" -Expect 200 -Comment "Node: сутність на місці після перезапуску" | Out-Null
    Invoke-Api GET $goUrl "/api/items" -Expect 200 -Comment "Go: сутність на місці після перезапуску" | Out-Null

    Write-Sub "DataStore на диску"
    Write-Host "  $nodeData"
    Get-Content $nodeData | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    Write-Host "  $goData"
    Get-Content $goData | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

    Write-Note "Змінився лише один рядок у src/server.js та cmd/server/main.go (вибір репозиторію)."
    Write-Note "Код Service, Controller і Router - той самий, перекомпіляції не було: бінарник той самий."

    Write-Head "7. 500 Internal Server Error через той самий обробник"
    Stop-Backends

    $corrupt = Join-Path $dataDir "corrupt.json"
    # ASCII, because UTF8 in Windows PowerShell adds a BOM and the parser
    # would then complain about that instead of about the real syntax error.
    Set-Content -Path $corrupt -Value "{ not json" -Encoding ASCII
    Write-Note "файловий DataStore наведено на зіпсований файл: $corrupt"
    Write-Note "це справжній збій інфраструктури - ані debug-маршруту, ані спецкоду в сервісах"

    Start-BothBackends -Repository "file" -NodeDataFile $corrupt -GoDataFile $corrupt
    Invoke-Api GET $nodeUrl "/api/items" -Expect 500 -ExpectError "internal_error" `
        -Comment "Node: Service не перетворив збій у 4xx, обробник віддав 500" | Out-Null
    Invoke-Api GET $goUrl "/api/items" -Expect 500 -ExpectError "internal_error" `
        -Comment "Go: те саме через response.WriteError" | Out-Null

    Write-Sub "Деталі збою лишились у логах сервера, клієнту їх не віддали"
    Get-Content (Join-Path $logDir "node.err.log") -ErrorAction SilentlyContinue |
        Select-Object -Last 2 | ForEach-Object { Write-Host "  node: $_" -ForegroundColor DarkGray }
    Get-Content (Join-Path $logDir "go.err.log") -ErrorAction SilentlyContinue |
        Select-Object -Last 2 | ForEach-Object { Write-Host "  go:   $_" -ForegroundColor DarkGray }

    Stop-Backends

    if (-not $SkipTests) {
        Write-Head "8. Тести рівня API"
        Invoke-Tests -Title "API" `
            -NodeArguments "--test --test-reporter=spec tests/item.api.test.js tests/item.repository.test.js" `
            -GoPattern "^(TestAPI|TestRepository)"
    }

    Write-Head "9. Що чим підтверджено"
    $summary = @(
        "| Вимога лабораторної                                   | Етап |",
        "|-------------------------------------------------------|------|",
        "| Router / Controller / Service / Repository / DataStore | 2-8  |",
        "| Усі обов'язкові endpoint                              | 4    |",
        "| 200 / 201 / 204                                       | 4    |",
        "| 400 Bad Request (поле, тип, порожнє, JSON, id)        | 4    |",
        "| 404 Not Found                                         | 4    |",
        "| 409 Conflict (дублювання за бізнес-логікою)           | 4    |",
        "| 500 Internal Server Error                             | 7    |",
        "| Централізована обробка помилок, один формат           | 4, 7 |",
        "| Middleware 1: логування method/path/status/duration   | 5    |",
        "| Middleware 2: валідація id і тіла до Service          | 4    |",
        "| Підміна InMemory -> File без зміни Service            | 6    |",
        "| Тести Service без HTTP-сервера                        | 2    |",
        "| Тести API                                             | 8    |"
    )
    $summary | ForEach-Object { Write-Host $_ }

    Write-Host ""
    if ($script:failures -eq 0) {
        Write-Host "ВСЕ ЗЕЛЕНЕ: усі перевірки цього прогону пройдені." -ForegroundColor Green
    }
    else {
        Write-Host "ПРОВАЛЕНО ПЕРЕВІРОК: $($script:failures)" -ForegroundColor Red
    }
    Write-Note "логи сервісів: $logDir"
}
finally {
    Stop-Backends
    Clear-Port $NodePort
    Clear-Port $GoPort
    $httpClient.Dispose()
    [Console]::OutputEncoding = $previousOutputEncoding
}

if ($script:failures -ne 0) { exit 1 }
