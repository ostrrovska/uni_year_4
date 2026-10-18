<#
.SYNOPSIS
    Runs every benchmark 

.DESCRIPTION
    Eight k6 runs in total: three for the event-loop blocking experiment and
    five for the load table. Each load run is sampled by monitor.ps1 at the
    same time, so the CPU and RAM columns come out filled in instead of being
    copied by hand afterwards.

    Both services must already be listening; their pids are looked up by port.

.EXAMPLE
    .\run-all.ps1
    .\run-all.ps1 -Quick     # 10s per load run, for rehearsing the demo
#>
param(
    [switch]$Quick,
    [string]$NodeUrl = 'http://localhost:3000',
    [string]$GoUrl = 'http://localhost:8080'
)

$ErrorActionPreference = 'Stop'

$bench = $PSScriptRoot
$outDir = Join-Path $bench 'results'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$loadDuration = if ($Quick) { '10s' } else { '30s' }
$loadSeconds = [int]($loadDuration -replace '\D', '')

function Get-ServicePid {
    param([int]$Port, [string]$Name)

    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $conn) {
        throw "$Name is not listening on port $Port - start it first."
    }
    return [int]$conn.OwningProcess
}

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host "=== $Text" -ForegroundColor Cyan
}

# k6 writes console.log() to stderr; --log-output=stdout keeps the live
# "health: N ms" lines in the same stream as the summary table.
$k6Common = @('run', '--quiet', '--log-format=raw', '--log-output=stdout')

function Invoke-Blocking {
    param([string]$Name, [string]$BaseUrl, [string]$CpuPath)

    Write-Step "Блокування: $Name"
    & k6 @k6Common -e BASE_URL=$BaseUrl -e CPU_PATH=$CpuPath -e JSON_OUT="results/$Name.json" blocking.js
    if ($LASTEXITCODE -ne 0) { throw "k6 failed for $Name" }

    Get-Content (Join-Path $outDir "$Name.json") -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Invoke-Load {
    param([string]$Name, [string]$BaseUrl, [string]$Endpoint, [int]$Vus, [int]$ServicePid)

    Write-Step "Навантаження: $Name ($Endpoint, $Vus VU, $loadDuration)"

    # The sampler outlives the run by a few seconds so it never stops early.
    $monitor = Start-Job -FilePath (Join-Path $bench 'monitor.ps1') `
        -ArgumentList $ServicePid, ($loadSeconds + 3)

    & k6 @k6Common -e BASE_URL=$BaseUrl -e ENDPOINT=$Endpoint -e VUS=$Vus `
        -e DURATION=$loadDuration -e JSON_OUT="results/$Name.json" load.js
    $k6Failed = $LASTEXITCODE -ne 0

    $sampled = Receive-Job $monitor -Wait
    Remove-Job $monitor
    if ($k6Failed) { throw "k6 failed for $Name" }

    $usage = $sampled |
        Where-Object { $_.PSObject.Properties.Name -contains 'CpuPercentOfCore' } |
        Select-Object -Last 1

    [pscustomobject]@{
        Summary = Get-Content (Join-Path $outDir "$Name.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        Usage   = $usage
    }
}

# Values above a second are rounded to whole milliseconds; the invariant culture
# keeps the decimal separator a dot so the markdown is copy-paste safe.
function Fmt {
    param($Value, [int]$Digits = 1)

    if ($null -eq $Value) { return '-' }
    $number = [double]$Value
    if ($number -ge 1000) { return [string][math]::Round($number, 0) }
    return ([math]::Round($number, $Digits)).ToString([cultureinfo]::InvariantCulture)
}

function Get-Duration { param($Summary) $Summary.metrics.http_req_duration.values }
function Get-Health { param($Summary) $Summary.metrics.health_latency_ms.values }
function Get-CpuMs { param($Summary) $Summary.metrics.cpu_duration_ms.values.max }
function Get-Rps { param($Summary) $Summary.metrics.http_reqs.values.rate }

$nodePid = Get-ServicePid -Port ([uri]$NodeUrl).Port -Name 'Node service'
$goPid = Get-ServicePid -Port ([uri]$GoUrl).Port -Name 'Go service'

Push-Location $bench
try {
    Write-Host "Node pid=$nodePid   Go pid=$goPid   тривалість прогону: $loadDuration" -ForegroundColor DarkGray

    $blockNode = Invoke-Blocking -Name 'blocking-node-cpu' -BaseUrl $NodeUrl -CpuPath '/cpu'
    $blockGo = Invoke-Blocking -Name 'blocking-go-cpu' -BaseUrl $GoUrl -CpuPath '/cpu'
    $blockGoRoutines = Invoke-Blocking -Name 'blocking-go-goroutines' -BaseUrl $GoUrl -CpuPath '/cpu-goroutines'

    $ioNode = Invoke-Load -Name 'load-node-io' -BaseUrl $NodeUrl -Endpoint '/io' -Vus 50 -ServicePid $nodePid
    $ioGo = Invoke-Load -Name 'load-go-io' -BaseUrl $GoUrl -Endpoint '/io' -Vus 50 -ServicePid $goPid
    $cpuNode = Invoke-Load -Name 'load-node-cpu' -BaseUrl $NodeUrl -Endpoint '/cpu' -Vus 10 -ServicePid $nodePid
    $cpuGo = Invoke-Load -Name 'load-go-cpu' -BaseUrl $GoUrl -Endpoint '/cpu' -Vus 10 -ServicePid $goPid
    $cpuGoRoutines = Invoke-Load -Name 'load-go-goroutines' -BaseUrl $GoUrl -Endpoint '/cpu-goroutines' -Vus 10 -ServicePid $goPid
}
finally {
    Pop-Location
}

function New-BlockingRow {
    param([string]$Runtime, [string]$CpuPath, $Summary)

    $health = Get-Health $Summary
    '| {0} | `{1}` | {2} | {3} | {4} | {5} |' -f $Runtime, $CpuPath,
        (Fmt (Get-CpuMs $Summary)), (Fmt $health.avg), (Fmt $health.'p(95)'), (Fmt $health.max)
}

function New-LoadRow {
    param([string]$Workload, [string]$Runtime, $Run)

    $duration = Get-Duration $Run.Summary
    '| {0} | {1} | {2} | {3} | {4} | {5} | {6} % | {7} МБ |' -f $Workload, $Runtime,
        (Fmt (Get-Rps $Run.Summary)), (Fmt $duration.avg), (Fmt $duration.'p(95)'),
        (Fmt $duration.'p(99)'), (Fmt $Run.Usage.CpuPercentOfCore), (Fmt $Run.Usage.PeakRamMB)
}

$report = @()
$report += '## 1. Дослід: блокування event loop'
$report += ''
$report += '| Сервіс | Ендпойнт CPU | `/cpu`, мс | `/health` avg, мс | `/health` p95, мс | `/health` max, мс |'
$report += '|---|---|---|---|---|---|'
$report += New-BlockingRow -Runtime 'Node.js' -CpuPath '/cpu' -Summary $blockNode
$report += New-BlockingRow -Runtime 'Go' -CpuPath '/cpu' -Summary $blockGo
$report += New-BlockingRow -Runtime 'Go' -CpuPath '/cpu-goroutines' -Summary $blockGoRoutines
$report += ''
$report += '## 2. Порівняльна таблиця навантаження'
$report += ''
$report += '| Workload | Runtime | RPS | Avg | p95 | p99 | CPU | RAM |'
$report += '|---|---|---|---|---|---|---|---|'
$report += New-LoadRow -Workload 'I/O' -Runtime 'Node.js' -Run $ioNode
$report += New-LoadRow -Workload 'I/O' -Runtime 'Go' -Run $ioGo
$report += New-LoadRow -Workload 'CPU (послідовно)' -Runtime 'Node.js' -Run $cpuNode
$report += New-LoadRow -Workload 'CPU (послідовно)' -Runtime 'Go' -Run $cpuGo
$report += New-LoadRow -Workload 'CPU (goroutines)' -Runtime 'Go' -Run $cpuGoRoutines
$report += ''
$report += '## 3. Порівняння двох версій `/cpu` у Go'
$report += ''
$report += '| Версія | Одиночний запит, мс | RPS під навантаженням | CPU |'
$report += '|---|---|---|---|'
$report += '| Послідовна (`/cpu`) | {0} | {1} | {2} % |' -f (Fmt (Get-CpuMs $blockGo)),
    (Fmt (Get-Rps $cpuGo.Summary)), (Fmt $cpuGo.Usage.CpuPercentOfCore)
$report += '| Goroutines (`/cpu-goroutines`) | {0} | {1} | {2} % |' -f (Fmt (Get-CpuMs $blockGoRoutines)),
    (Fmt (Get-Rps $cpuGoRoutines.Summary)), (Fmt $cpuGoRoutines.Usage.CpuPercentOfCore)

$reportPath = Join-Path $outDir 'summary.md'
$report | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ''
Write-Host '========== ФІНАЛЬНІ ТАБЛИЦІ ДЛЯ RESULTS.md ==========' -ForegroundColor Green
Write-Host ''
$report | ForEach-Object { Write-Host $_ }
Write-Host ''
Write-Host "Збережено: $reportPath" -ForegroundColor DarkGray
Write-Host "Сирі метрики кожного прогону: $outDir\*.json" -ForegroundColor DarkGray
