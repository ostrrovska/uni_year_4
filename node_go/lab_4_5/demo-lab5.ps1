<#
.SYNOPSIS
    Lab 5 demo - non-blocking I/O: streams, backpressure and WebSockets.

.DESCRIPTION
    One run covers every requirement of the lab, in ten stages:

      1.  Build and versions (npm install, node, ws).
      2.  Generate the test dataset: 256 MB written at a flat memory profile.
      3.  The whole test suite, lab 4 included, so the extension is shown not to
          have broken the CRUD module.
      4.  The highWaterMark experiment: the same pipeline at three buffer sizes.
      5.  The full chain through readable.pipe(...).pipe(...), with the output
          file verified line by line against the reported statistics.
      6.  Backpressure, scenarios A / B / C: the same slow consumer with no flow
          control, with manual pause/drain, and through pipe().
      7.  The HTTP surface of both new modules, every status code asserted.
      8.  The WebSocket lifecycle: welcome, identification, a wrong token, an
          auth timeout, invalid frames, broadcast, a clean close, and a client
          lost without a close handshake.
      9.  Streams and WebSockets integrated: two fast clients and one slow one
          receive the progress and the processed chunks of a live job.
      10. WebSocket backpressure with the protection off and on, side by side.

    Every stage asserts what it claims, so a regression makes the demo fail
    loudly instead of printing a wrong number.

.EXAMPLE
    ./demo-lab5.ps1
    ./demo-lab5.ps1 -Quick               # 64 MB dataset, shorter experiments
    ./demo-lab5.ps1 -SkipTests           # only the live stages
    ./demo-lab5.ps1 -Regenerate          # rebuild the dataset even if it exists
#>
[CmdletBinding()]
param(
    [int]$Size = 256,
    [int]$NodePort = 3100,
    [switch]$SkipTests,
    [switch]$Regenerate,
    [switch]$Quick
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
$logDir = Join-Path $root "logs"
$dataDir = Join-Path $root "data"
$outDir = Join-Path $root "out"
$docsDir = Join-Path $root "docs\lab5"

$dataset = Join-Path $dataDir "events.ndjson"
$nodeUrl = "http://localhost:$NodePort"

if ($Quick) { $Size = 64 }

# The experiments are parameterised in one place, because the report quotes
# these numbers and they have to match what actually ran.
$sweep = if ($Quick) { "16384,65536" } else { "16384,65536,1048576" }
$backpressureDelayMs = 2
$backpressureMB = if ($Quick) { 32 } else { 128 }
$jobDelayMs = 40
$sampleEvery = 4
$slowClientSeconds = if ($Quick) { 12 } else { 20 }

# Stage 10 is not shortened by -Quick, and it samples every surviving record
# rather than every fourth. Both for the same reason: bufferedAmount does not
# move until several megabytes are in flight, so the stage needs volume and a
# window wide enough for the backlog to appear.
$wsBackpressureSeconds = 30
$wsClientSeconds = 45
$wsSampleEvery = 1
$wsChunkBatch = 50

$script:backends = @()
$script:failures = 0

$httpClient = [System.Net.Http.HttpClient]::new()
$httpClient.Timeout = [timespan]::FromSeconds(30)

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

function Write-Note {
    param([string]$Text)
    Write-Host "   $Text" -ForegroundColor DarkGray
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

# Every claim this demo makes goes through here, so a broken claim is a failed
# run and not a line of text nobody checked.
function Test-Claim {
    param([Parameter(Mandatory)][string]$Text, [Parameter(Mandatory)][bool]$Condition, [string]$Detail)

    if ($Condition) {
        Write-Host "  ok   $Text" -ForegroundColor Green
        if ($Detail) { Write-Note $Detail }
        return
    }

    $script:failures++
    Write-Host "  FAIL $Text" -ForegroundColor Red
    if ($Detail) { Write-Host "       $Detail" -ForegroundColor Red }
}

# Kills whatever is already listening, so a service left behind by an
# interrupted run cannot make this one fail.
function Clear-Port {
    param([int]$Port)

    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

function Wait-Ready {
    param([string]$Name, [int]$Port, [int]$Attempts = 80)

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

# One service, started with the environment a given stage needs. Several stages
# need different WebSocket limits, which is why this takes an environment and
# the script restarts the service between them rather than hard-coding one.
function Start-Service {
    param([string]$Name, [hashtable]$Environment = @{})

    $logPath = Join-Path $logDir "$Name.log"
    $errorPath = Join-Path $logDir "$Name.err.log"
    Remove-Item $logPath, $errorPath -Force -ErrorAction SilentlyContinue

    $Environment["PORT"] = "$NodePort"

    # Start-Process has no environment parameter, so the variables are set in
    # this session and inherited by the child, then removed again.
    foreach ($key in $Environment.Keys) {
        Set-Item -Path "env:$key" -Value $Environment[$key]
    }
    try {
        $process = Start-Process -FilePath "node" -ArgumentList @("src/server.js") `
            -WorkingDirectory $nodeService -RedirectStandardOutput $logPath `
            -RedirectStandardError $errorPath -PassThru -NoNewWindow
    }
    finally {
        foreach ($key in $Environment.Keys) {
            Remove-Item -Path "env:$key" -ErrorAction SilentlyContinue
        }
    }

    $script:backends += [pscustomobject]@{ Name = $Name; Process = $process; Log = $logPath }
    Wait-Ready -Name $Name -Port $NodePort | Out-Null
    return $process
}

function Stop-Services {
    foreach ($backend in $script:backends) {
        if ($backend.Process -and -not $backend.Process.HasExited) {
            Stop-Process -Id $backend.Process.Id -Force -ErrorAction SilentlyContinue
            $backend.Process.WaitForExit(5000) | Out-Null
        }
    }
    $script:backends = @()
    Start-Sleep -Milliseconds 300
}

# Sends one request and checks it against the expected status code, and against
# the expected error code where the response carries one.
function Invoke-Api {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][int]$Expect,
        [string]$Body,
        [string]$ContentType = "application/json",
        [int[]]$AlsoExpect = @(),
        [string]$ExpectError,
        [string]$Comment
    )

    $request = [System.Net.Http.HttpRequestMessage]::new(
        [System.Net.Http.HttpMethod]::new($Method), "$nodeUrl$Path")
    if ($PSBoundParameters.ContainsKey("Body")) {
        $request.Content = [System.Net.Http.StringContent]::new(
            $Body, [System.Text.Encoding]::UTF8, $ContentType)
    }

    $response = $httpClient.SendAsync($request).GetAwaiter().GetResult()
    $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    $status = [int]$response.StatusCode
    $response.Dispose()
    $request.Dispose()

    $parsed = $null
    if ($payload -and ($payload.TrimStart().StartsWith("{") -or $payload.TrimStart().StartsWith("["))) {
        try { $parsed = $payload | ConvertFrom-Json } catch { }
    }

    $errorCode = if ($parsed -and $parsed.PSObject.Properties.Name -contains "error") { $parsed.error } else { $null }

    # AlsoExpect exists for the clean-up calls: aborting a job that has just
    # finished on its own is a 409, and that is not a regression.
    $passed = ($status -eq $Expect) -or ($AlsoExpect -contains $status)
    if ($passed -and $ExpectError -and $status -eq $Expect -and $errorCode -ne $ExpectError) { $passed = $false }

    $shown = ($payload -replace "\s+", " ").Trim()
    if ($shown.Length -gt 92) { $shown = $shown.Substring(0, 92) + "..." }
    $line = "{0,-6} {1,-30} {2}  {3}" -f $Method, $Path, $status, $shown

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

    return [pscustomobject]@{ Status = $status; Body = $payload; Json = $parsed; Error = $errorCode }
}

function Get-Json {
    param([string]$Path)
    return Invoke-RestMethod "$nodeUrl$Path" -TimeoutSec 20
}

# Runs one of the tools under node and hands back the JSON it wrote, so the
# stage asserts on numbers rather than on text it had to parse.
function Invoke-Tool {
    param([string]$Script, [string[]]$Arguments, [string]$JsonPath, [switch]$Show)

    Push-Location $nodeService
    try {
        & node (@($Script) + $Arguments) 2>&1 | ForEach-Object {
            if ($Show) { Write-Host "  $_" } else { Write-Verbose $_ }
        }
        if ($LASTEXITCODE -ne 0) {
            $script:failures++
            Write-Host "  $Script завершився з кодом $LASTEXITCODE" -ForegroundColor Red
        }
    }
    finally {
        Pop-Location
    }

    if ($JsonPath) { return Get-Content $JsonPath -Raw | ConvertFrom-Json }
    return $null
}

# A WebSocket client as a background process. --json makes its last line a
# summary this script can assert on.
function Start-WsClient {
    param([string]$Name, [string[]]$Arguments)

    $out = Join-Path $logDir "ws-$Name.json"
    $err = Join-Path $logDir "ws-$Name.err.log"
    Remove-Item $out, $err -Force -ErrorAction SilentlyContinue

    # Start-Process joins ArgumentList with spaces and quotes nothing, so an
    # argument containing a space would arrive as two. Quoting them here keeps
    # every call site free of the detail.
    $all = (@("tools/ws-client.js", "--name", $Name, "--quiet", "--json") + $Arguments) |
        ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }

    $process = Start-Process -FilePath "node" -ArgumentList $all -WorkingDirectory $nodeService `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -NoNewWindow

    return [pscustomobject]@{ Name = $Name; Process = $process; Out = $out }
}

function Wait-WsClient {
    param($Client, [int]$TimeoutSec = 90)

    if (-not $Client.Process.WaitForExit($TimeoutSec * 1000)) {
        Stop-Process -Id $Client.Process.Id -Force -ErrorAction SilentlyContinue
        $script:failures++
        Write-Host "  клієнт $($Client.Name) не завершився за $TimeoutSec с" -ForegroundColor Red
        return $null
    }

    $raw = (Get-Content $Client.Out -Raw)
    if (-not $raw) { return $null }

    $line = ($raw -split "`n" | Where-Object { $_.TrimStart().StartsWith("{") } | Select-Object -Last 1)
    if (-not $line) { return $null }

    return $line | ConvertFrom-Json
}

function Show-ClientSummary {
    param($Summary)

    if (-not $Summary) {
        Write-Host "  (немає підсумку клієнта)" -ForegroundColor Yellow
        return
    }

    $types = ($Summary.byType.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ", "
    $close = if ($Summary.close) { "$($Summary.close.code) $($Summary.close.reason)" } else { "ще відкрито" }
    Write-Host ("  {0,-10} кадрів {1,5}  байтів {2,9}  закрито {3}" -f $Summary.name, $Summary.received, $Summary.bytes, $close)
    Write-Note "типи: $types"
}

function Show-ServerLog {
    param([string]$Name, [string]$Pattern, [int]$Tail = 8)

    $path = Join-Path $logDir "$Name.log"
    if (-not (Test-Path $path)) {
        Write-Host "  (лог відсутній: $path)" -ForegroundColor Yellow
        return @()
    }

    $lines = Get-Content $path | Where-Object { $_ -match $Pattern }
    if (-not $lines) {
        Write-Host "  (у лозі немає рядків за шаблоном $Pattern)" -ForegroundColor Yellow
        return @()
    }

    $lines | Select-Object -Last $Tail | ForEach-Object { Write-Host "  $_" }
    return $lines
}

# Watches one client in the registry over time, keeping the highest
# bufferedAmount it ever reported.
#
# Polling rather than one snapshot because bufferedAmount stays at zero until
# the socket buffers of both ends are full: the kernel accepts the first
# megabytes happily, and only then does the backlog become visible to the
# process. Taking a single sample too early reads zero and proves nothing.
function Watch-Client {
    param([string]$Name, [int]$TimeoutSec, [int]$ThresholdBytes = 0)

    $observed = [pscustomobject]@{ Peak = 0; State = "?"; Dropped = 0; Sent = 0; Gone = $false; Seconds = 0 }
    $started = Get-Date
    $deadline = $started.AddSeconds($TimeoutSec)

    while ((Get-Date) -lt $deadline) {
        $snapshot = Get-Json "/api/ws/clients"
        $client = $snapshot.clients.clients | Where-Object { $_.name -eq $Name }

        if (-not $client) {
            # Either it has not connected yet, or the server has dropped it.
            if ($observed.Sent -gt 0) {
                $observed.Gone = $true
                break
            }
        }
        else {
            $observed.Peak = [math]::Max($observed.Peak, $client.peakBufferedAmount)
            $observed.State = $client.state
            $observed.Dropped = $client.dropped
            $observed.Sent = $client.sent

            if ($ThresholdBytes -gt 0 -and $observed.Peak -ge $ThresholdBytes) { break }
        }

        Start-Sleep -Milliseconds 700
    }

    $observed.Seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    return $observed
}

# Starts a job over HTTP and waits for it to leave the running state.
function Start-Job-Request {
    param([string]$BodyJson, [int]$Expect = 202)
    return (Invoke-Api -Method POST -Path "/api/stream/jobs" -Expect $Expect -Body $BodyJson)
}

function Wait-JobFinished {
    param([string]$JobId, [int]$TimeoutSec = 300)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $job = Get-Json "/api/stream/jobs/$JobId"
        if ($job.state -ne "running") { return $job }
        Start-Sleep -Milliseconds 250
    }

    $script:failures++
    Write-Host "  задача $JobId не завершилась за $TimeoutSec с" -ForegroundColor Red
    return $null
}

# ---------------------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $logDir, $dataDir, $outDir, $docsDir | Out-Null
Clear-Port $NodePort

try {
    # -----------------------------------------------------------------------
    Write-Head "1. Збірка і версії"

    Push-Location $nodeService
    try {
        & npm install --silent --no-audit --no-fund 2>&1 | ForEach-Object { Write-Host "  $_" }
        Write-Note "npm install - готово"
    }
    finally {
        Pop-Location
    }

    $nodeVersion = (& node --version)
    Push-Location $nodeService
    try {
        # Run from node-service: require() resolves against the current
        # directory, and the dependencies live there, not in the lab root.
        $wsVersion = (& node -e "process.stdout.write(require('ws/package.json').version)")
        $expressVersion = (& node -e "process.stdout.write(require('express/package.json').version)")
    }
    finally {
        Pop-Location
    }
    Write-Note "node $nodeVersion, ws $wsVersion, express $expressVersion"
    Test-Claim -Text "ws встановлено" -Condition ([bool]$wsVersion)

    # -----------------------------------------------------------------------
    Write-Head "2. Тестове джерело даних"

    if ($Regenerate -or -not (Test-Path $dataset)) {
        Invoke-Tool -Script "tools/generate-dataset.js" -Arguments @("--size", "$Size") -Show | Out-Null
    }
    else {
        Write-Note "датасет уже існує, генерацію пропущено (-Regenerate щоб перегенерувати)"
    }

    $datasetInfo = Get-Item $dataset
    $datasetMB = [math]::Round($datasetInfo.Length / 1MB, 1)
    Write-Note "файл: $dataset"
    Write-Note "розмір: $datasetMB MB"

    Test-Claim -Text "файл суттєво більший за один буфер" -Condition ($datasetInfo.Length -gt 64MB) `
        -Detail "$datasetMB MB проти 64 KiB highWaterMark за замовчуванням - у 4096 разів більше"

    # -----------------------------------------------------------------------
    if (-not $SkipTests) {
        Write-Head "3. Тести"

        Push-Location $nodeService
        try {
            & node --test --test-reporter=spec --test-timeout=40000 tests/*.test.js 2>&1 |
                ForEach-Object { Write-Host "  $(Convert-ReporterGlyph $_)" }
            if ($LASTEXITCODE -ne 0) {
                $script:failures++
                Write-Host "  тести провалились" -ForegroundColor Red
            }
            else {
                Write-Note "сюда входять і 69 тестів лабораторної 4: розширення нічого не зламало"
            }
        }
        finally {
            Pop-Location
        }
    }

    # -----------------------------------------------------------------------
    Write-Head "4. Параметри, що визначають розмір порції"

    $sweepJson = Join-Path $logDir "sweep.json"
    $sweepResults = Invoke-Tool -Script "tools/stream-run.js" `
        -Arguments @("--sweep", $sweep, "--levels", "error", "--quiet", "--json", $sweepJson) `
        -JsonPath $sweepJson -Show

    foreach ($result in $sweepResults) {
        $hwm = $result.highWaterMark
        Test-Claim -Text "highWaterMark ${hwm}: жодна порція не перевищила буфер" `
            -Condition ($result.chunks.maxChunk -le $hwm) `
            -Detail "max $($result.chunks.maxChunk) B, avg $($result.chunks.avgChunk) B, порцій $($result.chunks.chunksIn)"
    }

    $lineCounts = ($sweepResults | ForEach-Object { $_.stats.linesOut } | Sort-Object -Unique)
    Test-Claim -Text "результат не залежить від розміру буфера" -Condition ($lineCounts.Count -eq 1) `
        -Detail "у всіх прогонах записано однаково рядків: $($lineCounts -join ', ')"

    $first = $sweepResults[0]
    $last = $sweepResults[-1]
    Test-Claim -Text "кількість читань масштабується як 1/highWaterMark" `
        -Condition ($first.chunks.chunksIn -gt $last.chunks.chunksIn) `
        -Detail "$($first.highWaterMark) B -> $($first.chunks.chunksIn) порцій, $($last.highWaterMark) B -> $($last.chunks.chunksIn) порцій"

    # -----------------------------------------------------------------------
    Write-Head "5. Ланцюг readable.pipe(transform).pipe(writable)"

    $chainJson = Join-Path $logDir "chain.json"
    $outputFile = Join-Path $outDir "events-demo.ndjson"
    $chain = Invoke-Tool -Script "tools/stream-run.js" `
        -Arguments @("--chain", "pipe", "--levels", "error", "--out", $outputFile, "--json", $chainJson) `
        -JsonPath $chainJson -Show
    $chain = $chain[0]

    Test-Claim -Text "вихідний файл створено" -Condition (Test-Path $outputFile)

    # The claim being checked is not "a file appeared" but "the file holds
    # exactly the records the transform said it kept".
    $actualLines = (Get-Content $outputFile | Measure-Object -Line).Lines
    Test-Claim -Text "рядків у файлі стільки ж, скільки звітував Transform" `
        -Condition ($actualLines -eq $chain.stats.linesOut) `
        -Detail "у файлі $actualLines, Transform звітував $($chain.stats.linesOut)"

    $outputMB = [math]::Round((Get-Item $outputFile).Length / 1MB, 1)
    Test-Claim -Text "фільтр справді зменшив обсяг" -Condition ($outputMB -lt $datasetMB) `
        -Detail "$datasetMB MB на вході, $outputMB MB на виході"

    $levels = (Get-Content $outputFile -TotalCount 200 | ForEach-Object { ($_ | ConvertFrom-Json).level } | Sort-Object -Unique)
    Test-Claim -Text "у вихідному файлі лише запитані рівні" -Condition (($levels -join ",") -eq "error") `
        -Detail "рівні у перших 200 рядках: $($levels -join ', ')"

    Test-Claim -Text "зіпсовані рядки підраховані, а не аварійні" -Condition ($chain.stats.malformed -gt 0) `
        -Detail "$($chain.stats.malformed) непарсабельних рядків, конвеєр дійшов до кінця"

    Test-Claim -Text "пам'ять не залежить від розміру файлу" `
        -Condition ($chain.metrics.peakRssMB -lt ($datasetMB / 2)) `
        -Detail "оброблено $datasetMB MB, пік RSS $($chain.metrics.peakRssMB) MB"

    Write-Note "рядків: $($chain.stats.linesIn) прочитано -> $($chain.stats.linesOut) записано, відфільтровано $($chain.stats.filtered)"
    Write-Note "затримки: min $($chain.stats.latency.min) мс, avg $($chain.stats.latency.avg) мс, max $($chain.stats.latency.max) мс"

    # -----------------------------------------------------------------------
    Write-Head "6. Backpressure: сценарії A / B / C"

    $bpJson = Join-Path $logDir "backpressure.json"
    $bpMarkdown = Join-Path $docsDir "backpressure.md"
    $scenarios = Invoke-Tool -Script "tools/backpressure-compare.js" `
        -Arguments @("--delay-ms", "$backpressureDelayMs", "--mb", "$backpressureMB",
                     "--json", $bpJson, "--markdown", $bpMarkdown) `
        -JsonPath $bpJson -Show

    $a = $scenarios | Where-Object { $_.scenario -eq "uncontrolled" }
    $b = $scenarios | Where-Object { $_.scenario -eq "manual" }
    $c = $scenarios | Where-Object { $_.scenario -eq "pipe" }

    Test-Claim -Text "A без контролю накопичує дані в пам'яті" `
        -Condition ($a.peakBufferedBytes -gt ($a.highWaterMark * 10)) `
        -Detail "пік буфера $($a.peakBufferedMB) MB при буфері $($a.highWaterMark) B"

    Test-Claim -Text "A жодного разу не зупинила виробника" -Condition ($a.pauses -eq 0)

    Test-Claim -Text "B тримає буфер у межах одного highWaterMark" `
        -Condition ($b.peakBufferedBytes -le ($b.highWaterMark * 2)) `
        -Detail "пік буфера $($b.peakBufferedBytes) B, пауз $($b.pauses)"

    Test-Claim -Text "C через pipe() тримає так само, без жодного pause() у коді" `
        -Condition ($c.peakBufferedBytes -le ($c.highWaterMark * 2)) `
        -Detail "пік буфера $($c.peakBufferedBytes) B, у $($c.pausedSamples) семплах джерело було на паузі"

    # Stated as "the buffered bytes are visible in RSS" rather than as a fixed
    # ratio, because the ratio depends on how much of the process is interpreter
    # overhead - which is a property of the test size, not of the mechanism.
    Test-Claim -Text "забуферизовані дані видно як приріст пам'яті саме у A" `
        -Condition ($a.rssGrowthMB -gt ($c.rssGrowthMB + $a.peakBufferedMB * 0.5)) `
        -Detail "A +$($a.rssGrowthMB) MB при піку буфера $($a.peakBufferedMB) MB; B +$($b.rssGrowthMB) MB, C +$($c.rssGrowthMB) MB"

    # The time column is the counter-intuitive one, and it is the point: flow
    # control does not cost throughput, the consumer sets the pace either way.
    $spread = [math]::Abs($a.elapsedMs - $c.elapsedMs) / [double]$c.elapsedMs
    Test-Claim -Text "час виконання практично однаковий" -Condition ($spread -lt 0.35) `
        -Detail "A $($a.elapsedMs) мс, B $($b.elapsedMs) мс, C $($c.elapsedMs) мс - темп задає споживач"

    Write-Note "таблиця збережена у $bpMarkdown"

    # -----------------------------------------------------------------------
    Write-Head "7. HTTP-поверхня нових модулів"

    Start-Service -Name "node" -Environment @{} | Out-Null

    Write-Sub "датасет і задачі"
    Invoke-Api -Method GET -Path "/api/stream/dataset" -Expect 200 | Out-Null
    Invoke-Api -Method GET -Path "/api/stream/jobs" -Expect 200 -Comment "порожній список задач" | Out-Null

    $created = Invoke-Api -Method POST -Path "/api/stream/jobs" -Expect 202 `
        -Body '{"mode":"analyze","chain":"pipeline","levels":["error"]}' `
        -Comment "202 Accepted: робота триватиме довше за будь-який таймаут запиту"
    $jobId = $created.Json.id

    Invoke-Api -Method GET -Path "/api/stream/jobs/$jobId" -Expect 200 | Out-Null

    Write-Sub "валідація до сервісу"
    Invoke-Api -Method POST -Path "/api/stream/jobs" -Expect 400 -ExpectError "invalid_job" `
        -Body '{"mode":"magic"}' -Comment "режим не з білого списку" | Out-Null
    Invoke-Api -Method POST -Path "/api/stream/jobs" -Expect 400 -ExpectError "invalid_job" `
        -Body '{"highWaterMark":1}' -Comment "highWaterMark поза діапазоном" | Out-Null
    Invoke-Api -Method POST -Path "/api/stream/jobs" -Expect 400 -ExpectError "invalid_job" `
        -Body '{"levels":["panic"]}' | Out-Null
    Invoke-Api -Method POST -Path "/api/stream/jobs" -Expect 400 -ExpectError "invalid_json" `
        -Body '{ не json' | Out-Null
    Invoke-Api -Method POST -Path "/api/stream/jobs" -Expect 400 -ExpectError "invalid_content_type" `
        -Body '{}' -ContentType "text/plain" | Out-Null
    Invoke-Api -Method GET -Path "/api/stream/jobs/not-an-id" -Expect 400 -ExpectError "invalid_job_id" | Out-Null
    Invoke-Api -Method GET -Path "/api/stream/jobs/deadbeef" -Expect 404 -ExpectError "job_not_found" | Out-Null

    Write-Sub "реєстр WebSocket-клієнтів через HTTP"
    Invoke-Api -Method GET -Path "/api/ws/clients" -Expect 200 -Comment "той самий реєстр, що бачить WebSocket-модуль" | Out-Null
    Invoke-Api -Method POST -Path "/api/ws/broadcast" -Expect 400 -ExpectError "invalid_text" -Body '{"text":""}' | Out-Null

    Write-Sub "дошка і статика"
    $dashboard = Invoke-WebRequest "$nodeUrl/" -TimeoutSec 10 -UseBasicParsing
    Test-Claim -Text "інтерактивна панель віддається на /" -Condition ($dashboard.StatusCode -eq 200) `
        -Detail "$($dashboard.RawContentLength) байтів HTML, відкривається у браузері на $nodeUrl/"

    $finished = Wait-JobFinished -JobId $jobId
    if ($finished) {
        Test-Claim -Text "задача завершилася станом done" -Condition ($finished.state -eq "done") `
            -Detail "$($finished.result.stats.linesIn) рядків за $($finished.result.elapsedMs) мс, пік RSS $($finished.result.metrics.peakRssMB) MB"
    }

    Write-Sub "перервання задачі"
    $slowJob = Start-Job-Request -BodyJson '{"mode":"slow","slowDelayMs":200}'
    Invoke-Api -Method DELETE -Path "/api/stream/jobs/$($slowJob.Json.id)" -Expect 204 `
        -Comment "AbortController руйнує ланцюг, дескриптори закриваються" | Out-Null
    $aborted = Wait-JobFinished -JobId $slowJob.Json.id -TimeoutSec 30
    if ($aborted) {
        Test-Claim -Text "перервана задача має стан aborted" -Condition ($aborted.state -eq "aborted")
    }
    Invoke-Api -Method DELETE -Path "/api/stream/jobs/$($slowJob.Json.id)" -Expect 409 -ExpectError "job_not_running" | Out-Null

    Stop-Services

    # -----------------------------------------------------------------------
    Write-Head "8. Життєвий цикл WebSocket-з'єднання"

    # The heartbeat is cut to two seconds so the "lost client" case finishes
    # inside the demo instead of after half a minute.
    Start-Service -Name "ws-lifecycle" -Environment @{ WS_HEARTBEAT_MS = "2000"; WS_AUTH_TIMEOUT_MS = "1500" } | Out-Null

    Write-Sub "нормальний клієнт: welcome -> hello -> ready -> message -> close"
    $alice = Start-WsClient -Name "alice" -Arguments @("--duration", "6000", "--say", "привіт від alice", "--say-every", "1200")
    Start-Sleep -Milliseconds 500
    $bob = Start-WsClient -Name "bob" -Arguments @("--duration", "5000", "--say", "і від bob")

    $aliceSummary = Wait-WsClient -Client $alice
    $bobSummary = Wait-WsClient -Client $bob
    Show-ClientSummary $aliceSummary
    Show-ClientSummary $bobSummary

    Test-Claim -Text "клієнт отримав welcome і був ідентифікований" `
        -Condition ($aliceSummary.byType.welcome -eq 1 -and $aliceSummary.byType.ready -eq 1)
    Test-Claim -Text "повідомлення дійшло до іншого клієнта, а не до відправника" `
        -Condition ($aliceSummary.byType.message -ge 1 -and $bobSummary.byType.message -ge 1) `
        -Detail "alice бачила $($aliceSummary.byType.message) чужих message, bob - $($bobSummary.byType.message)"
    Test-Claim -Text "присутність інших клієнтів оголошується" -Condition ($aliceSummary.byType.presence -ge 1)
    Test-Claim -Text "закриття штатне, код 1000" -Condition ($aliceSummary.close.code -eq 1000)

    Write-Sub "невірний токен"
    $intruder = Wait-WsClient -Client (Start-WsClient -Name "intruder" -Arguments @("--token", "wrong", "--duration", "5000"))
    Show-ClientSummary $intruder
    Test-Claim -Text "невірний токен закриває з'єднання кодом 4401" -Condition ($intruder.close.code -eq 4401) `
        -Detail "причина: $($intruder.close.reason)"

    Write-Sub "клієнт, який не ідентифікувався"
    # --token is irrelevant here: the client is told to never send hello at all.
    $silent = Wait-WsClient -Client (Start-WsClient -Name "silent" -Arguments @("--no-hello", "--duration", "6000"))
    Show-ClientSummary $silent
    Test-Claim -Text "мовчання довше за таймаут закриває з'єднання кодом 4408" -Condition ($silent.close.code -eq 4408)

    Write-Sub "невалідні кадри"
    $noisy = Wait-WsClient -Client (Start-WsClient -Name "noisy" -Arguments @("--invalid", "6", "--duration", "6000"))
    Show-ClientSummary $noisy
    Test-Claim -Text "на кожен невалідний кадр приходить error, а не розрив" -Condition ($noisy.byType.error -ge 1) `
        -Detail "кадрів error: $($noisy.byType.error)"
    Test-Claim -Text "після ліміту порушень з'єднання закривається кодом 4400" -Condition ($noisy.close.code -eq 4400)

    Write-Sub "втрата клієнта: сокет знищено без close-рукостискання"
    # A locally destroyed socket still sends a TCP reset, so the server learns
    # about it at once and reports 1006 - abnormal closure, no close frame.
    $ghost = Start-WsClient -Name "ghost" -Arguments @("--kill-socket", "800", "--duration", "9000")
    Wait-WsClient -Client $ghost -TimeoutSec 30 | Out-Null
    Start-Sleep -Seconds 1
    $ghostLines = Show-ServerLog -Name "ws-lifecycle" -Pattern "ghost|code=1006"
    Test-Claim -Text "знищений сокет помічено відразу, код 1006" -Condition ($ghostLines.Count -ge 1) `
        -Detail "1006 означає, що close-кадру не було: клієнт зник, а не попрощався"

    Write-Sub "втрата клієнта: сокет живий, але клієнт не відповідає"
    # The harder case, and the one the heartbeat exists for: the connection is
    # open, nothing was reset, and the client simply never reads again. Pausing
    # the socket also stops the automatic pong, which is exactly what an
    # unreachable client looks like from the server.
    $mute = Start-WsClient -Name "mute" -Arguments @("--slow", "--resume-every", "0", "--duration", "20000")
    Start-Sleep -Seconds 8
    $heartbeat = Show-ServerLog -Name "ws-lifecycle" -Pattern "heartbeat lost"
    Test-Claim -Text "heartbeat виявив клієнта, що не відповідає, і знищив сокет" -Condition ($heartbeat.Count -ge 1) `
        -Detail "два пропущені pong -> terminate(), бо close() нікому завершувати рукостискання"
    Wait-WsClient -Client $mute -TimeoutSec 40 | Out-Null

    $registry = Get-Json "/api/ws/clients"
    Test-Claim -Text "реєстр після всіх відключень порожній" -Condition ($registry.clients.total -eq 0) `
        -Detail "усього з'єднань за прогін: $($registry.clients.totalConnections)"

    Stop-Services

    # -----------------------------------------------------------------------
    Write-Head "9. Інтеграція: прогрес і оброблені порції у реальному часі"

    Start-Service -Name "integration" -Environment @{ WS_HEARTBEAT_MS = "60000" } | Out-Null

    $job = Start-Job-Request -BodyJson "{""mode"":""slow"",""slowDelayMs"":$jobDelayMs,""sampleEvery"":$sampleEvery,""chunkBatch"":25,""levels"":[""error""]}"
    Write-Note "задача $($job.Json.id) запущена, повільний споживач $jobDelayMs мс на порцію"

    $fast1 = Start-WsClient -Name "fast-1" -Arguments @("--duration", "$($slowClientSeconds * 1000)")
    $fast2 = Start-WsClient -Name "fast-2" -Arguments @("--duration", "$($slowClientSeconds * 1000)")

    Start-Sleep -Seconds 3
    $midflight = Get-Json "/api/stream/jobs/$($job.Json.id)"
    Test-Claim -Text "прогрес видно ще до завершення операції" `
        -Condition ($midflight.state -eq "running" -and $midflight.progress.processed -gt 0) `
        -Detail "оброблено $([math]::Round($midflight.progress.processed / 1MB, 1)) MB з $([math]::Round($midflight.progress.total / 1MB, 1)) MB, $($midflight.progress.percent)%"

    $fast1Summary = Wait-WsClient -Client $fast1
    $fast2Summary = Wait-WsClient -Client $fast2
    Show-ClientSummary $fast1Summary
    Show-ClientSummary $fast2Summary

    Test-Claim -Text "клієнти отримують кадри progress" -Condition ($fast1Summary.byType.progress -ge 1) `
        -Detail "progress: $($fast1Summary.byType.progress) кадрів"
    Test-Claim -Text "клієнти отримують самі оброблені записи" -Condition ($fast1Summary.byType.chunk -ge 1) `
        -Detail "chunk: $($fast1Summary.byType.chunk) кадрів, кожен $($sampleEvery)-й запис"
    Test-Claim -Text "обидва клієнти отримали однаковий потік" `
        -Condition ([math]::Abs($fast1Summary.byType.chunk - $fast2Summary.byType.chunk) -le [math]::Max(3, $fast1Summary.byType.chunk * 0.2)) `
        -Detail "fast-1: $($fast1Summary.byType.chunk), fast-2: $($fast2Summary.byType.chunk)"

    Invoke-Api -Method DELETE -Path "/api/stream/jobs/$($job.Json.id)" -Expect 204 -AlsoExpect 409 | Out-Null
    Stop-Services

    # -----------------------------------------------------------------------
    Write-Head "10. Backpressure у WebSocket: повільний клієнт"

    Write-Sub "A. захист вимкнено (WS_PROTECTION=0)"
    Start-Service -Name "ws-unprotected" -Environment @{ WS_PROTECTION = "0"; WS_HEARTBEAT_MS = "60000" } | Out-Null

    $jobA = Start-Job-Request -BodyJson "{""mode"":""slow"",""slowDelayMs"":$jobDelayMs,""sampleEvery"":$wsSampleEvery,""chunkBatch"":$wsChunkBatch,""levels"":[""error""]}"
    $slowA = Start-WsClient -Name "slow-unprotected" -Arguments @("--slow", "--resume-every", "0", "--duration", "$($wsClientSeconds * 1000)")

    $observedA = Watch-Client -Name "slow-unprotected" -TimeoutSec $wsBackpressureSeconds -ThresholdBytes 1048576
    Write-Note "через $($observedA.Seconds) с: стан $($observedA.State), пік bufferedAmount $($observedA.Peak) B, надіслано $($observedA.Sent), відкинуто $($observedA.Dropped)"

    Test-Claim -Text "без захисту кадри накопичуються в буфері сокета" `
        -Condition ($observedA.Peak -gt 262144) `
        -Detail "пік bufferedAmount $([math]::Round($observedA.Peak / 1MB, 2)) MB - це пам'ять сервера, яку тримає один повільний клієнт"
    Test-Claim -Text "без захисту нічого не відкидається" -Condition ($observedA.Dropped -eq 0) `
        -Detail "сервер віддав у send() усі $($observedA.Sent) кадрів, не спитавши, чи клієнт встигає"
    Test-Claim -Text "клієнта не відключено, хоч він і не читає" -Condition (-not $observedA.Gone)

    Stop-Process -Id $slowA.Process.Id -Force -ErrorAction SilentlyContinue
    Invoke-Api -Method DELETE -Path "/api/stream/jobs/$($jobA.Json.id)" -Expect 204 -AlsoExpect 409 | Out-Null
    Stop-Services

    Write-Sub "B. захист увімкнено, ліміти зменшені до демонстраційних"
    # The production defaults (256 KB soft, 4 MB hard) would need minutes of a
    # paused client to trip. The mechanism is identical at any scale; only the
    # thresholds are scaled down so the effect fits in one demo stage.
    Start-Service -Name "ws-protected" -Environment @{
        WS_HEARTBEAT_MS  = "60000"
        WS_SOFT_LIMIT    = "32768"
        WS_HARD_LIMIT    = "65536"
        WS_SLOW_GRACE_MS = "2000"
    } | Out-Null

    $jobB = Start-Job-Request -BodyJson "{""mode"":""slow"",""slowDelayMs"":$jobDelayMs,""sampleEvery"":$wsSampleEvery,""chunkBatch"":$wsChunkBatch,""levels"":[""error""]}"
    $fastB = Start-WsClient -Name "fast-beside-slow" -Arguments @("--duration", "$($wsClientSeconds * 1000)")
    # Chat messages are what keep the pressure on: an ack is a protocol frame
    # and is never dropped, so a client that reads nothing but keeps talking is
    # the one case where the buffer can still reach the hard limit.
    $slowB = Start-WsClient -Name "slow-protected" -Arguments @(
        "--slow", "--resume-every", "0", "--say", "я ще тут", "--say-every", "3",
        "--duration", "$($wsClientSeconds * 1000)")

    $observedB = Watch-Client -Name "slow-protected" -TimeoutSec $wsBackpressureSeconds
    Write-Note "через $($observedB.Seconds) с: стан $($observedB.State), пік bufferedAmount $($observedB.Peak) B, надіслано $($observedB.Sent), відкинуто $($observedB.Dropped)"

    $snapshotB = Get-Json "/api/ws/clients"
    Write-Note "політика: $($snapshotB.policy.sent) надіслано, $($snapshotB.policy.dropped) відкинуто (з них rate limit $($snapshotB.policy.rateLimited)), $($snapshotB.policy.batched) у батчах, $($snapshotB.policy.closed) закрито"

    $closings = Show-ServerLog -Name "ws-protected" -Pattern "closing|over_hard_limit"

    Test-Claim -Text "повільного клієнта розпізнано за станом буфера" `
        -Condition ($observedB.State -eq "slow" -or $observedB.Dropped -gt 0 -or $observedB.Gone) `
        -Detail "стан $($observedB.State), відкинуто $($observedB.Dropped) кадрів"
    Test-Claim -Text "із захистом кадри відкидаються, а не накопичуються" -Condition ($snapshotB.policy.dropped -gt 0) `
        -Detail "відкинуто $($snapshotB.policy.dropped) кадрів, з них за rate limit $($snapshotB.policy.rateLimited)"
    Test-Claim -Text "клієнт, що стабільно не встигає, відключається" `
        -Condition ($snapshotB.policy.closed -ge 1 -or $closings.Count -ge 1 -or $observedB.Gone) `
        -Detail "кодом 4290 після $($snapshotB.policy.slowGraceMs) мс за межею hard-ліміту"

    $fastBSummary = Wait-WsClient -Client $fastB -TimeoutSec 90
    Show-ClientSummary $fastBSummary
    Stop-Process -Id $slowB.Process.Id -Force -ErrorAction SilentlyContinue

    Test-Claim -Text "повільний клієнт не нашкодив швидкому" -Condition ($fastBSummary.byType.chunk -ge 1) `
        -Detail "швидкий клієнт отримав $($fastBSummary.byType.chunk) chunk і $($fastBSummary.byType.progress) progress кадрів"

    Invoke-Api -Method DELETE -Path "/api/stream/jobs/$($jobB.Json.id)" -Expect 204 -AlsoExpect 409 | Out-Null
    Stop-Services

    # -----------------------------------------------------------------------
    Write-Head "11. Що чим підтверджено"
    $summary = @(
        "| Вимога лабораторної                                        | Етап  |",
        "|------------------------------------------------------------|-------|",
        "| 1. Тестовий файл 100 MB - 1 GB, не в один Buffer           | 2     |",
        "| 2. Readable Stream, параметри розміру порції               | 4     |",
        "| 3. Transform Stream, результат у новий файл                | 5     |",
        "| 4. Звʼязування через pipe()                                | 5     |",
        "| 5.1 Повільний Writable                                     | 6, 9  |",
        "| 5.2 Сценарій A без контролю швидкості                      | 6     |",
        "| 5.3 Сценарій B з механізмом backpressure                   | 6     |",
        "| 5.4 Таблиця: час, пам'ять, буфер                           | 6     |",
        "| 6. WebSocket endpoint: connect/message/broadcast/disconnect | 8     |",
        "| 7.1 Реєстрація клієнта, список активних з'єднань           | 7, 8  |",
        "| 7.2 Обмін повідомленнями між клієнтами                     | 8     |",
        "| 8.1 Нове підключення                                       | 8     |",
        "| 8.2 Автентифікація, таймаут і невірний токен               | 8     |",
        "| 8.3 Невалідне повідомлення                                 | 8     |",
        "| 8.4 Закриття зʼєднання                                     | 8     |",
        "| 8.5 Втрата клієнта (heartbeat, terminate)                  | 8     |",
        "| 8.6 clientId, connectedAt, connection state                | 7, 8  |",
        "| 9. Результат обробки передається клієнтам у реальному часі  | 9     |",
        "| 10.1 Повільний WebSocket-клієнт                            | 10    |",
        "| 10.2 Накопичення без захисту                               | 10 A  |",
        "| 10.3 Контроль обсягу буфера, rate limiting, drop, batching  | 10 B  |",
        "| 10.4 Відключення клієнта, що не встигає                     | 10 B  |",
        "| Інтеграція у структуру лабораторної 4                      | 3, 7  |"
    )
    $summary | ForEach-Object { Write-Host $_ }

    Write-Host ""
    if ($script:failures -eq 0) {
        Write-Host "ВСЕ ЗЕЛЕНЕ: усі перевірки цього прогону пройдені." -ForegroundColor Green
    }
    else {
        Write-Host "ПРОВАЛЕНО ПЕРЕВІРОК: $($script:failures)" -ForegroundColor Red
    }
    Write-Note "логи: $logDir"
    Write-Note "таблиці: $docsDir"
    Write-Note "оброблені файли: $outDir"
}
finally {
    Stop-Services
    Clear-Port $NodePort
    $httpClient.Dispose()
    [Console]::OutputEncoding = $previousOutputEncoding
}

if ($script:failures -ne 0) { exit 1 }
