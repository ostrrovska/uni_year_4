# Lab5
<#
.SYNOPSIS
    Set up the Lab 5 defence in one command, and verify it before the examiner sees it.

.DESCRIPTION
    Clause 4 asks for four things at the defence, and this script prepares all of them:

      "Demonstration of a test run"      the live ladder behind the Run live button, and the
                                         real command for the full matrix.
      "Analysis of the results"          the ladder, tail and saturation charts on
                                         /lab5-report.html.
      "Comparative modes"                the scaled/unscaled and cached/uncached sections of
                                         the same page.
      "Theoretical defence"              the Theory card: saturation point, coordinated
                                         omission, GC/JIT and percentiles.

    What it does: brings up the pinned stack if it is not already running, switches the balancer
    to the load-test pool, refreshes the seeded fleet, asserts the report data is on disk, starts
    the live runner on :8099 and checks that nginx can actually reach it through /lab5/ - because
    "the button does nothing" is not a thing to discover in front of an examiner.

    The runner stays in the foreground: closing this window stops it, and the page then degrades
    to printing the command instead of showing a dead button.

.EXAMPLE
    ./scripts/lab5_demo.ps1
    ./scripts/lab5_demo.ps1 -NoRunner      # just verify and open the page
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [int]$RunnerPort = 8099,
    [switch]$NoRunner,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$composeArgs = @(
    "-f", (Join-Path $root "docker-compose.yml"),
    "-f", (Join-Path $root "docker-compose.lab3.yml"),
    "-f", (Join-Path $root "docker-compose.lab4.yml"),
    "-f", (Join-Path $root "docker-compose.lab5.yml")
)

$script:Step = 0
$script:Results = @()

function Invoke-Docker([string[]]$DockerArgs) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker @DockerArgs 2>&1 | Out-Null
        return $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
}

function Compose([string[]]$Rest) { return @("compose") + $composeArgs + $Rest }

function Section([string]$Clause, [string]$Title) {
    $script:Step++
    Write-Host ""
    Write-Host ("[{0:d2}] {1}  -  {2}" -f $script:Step, $Clause, $Title) -ForegroundColor Cyan
}

function Pass([string]$What, [string]$Evidence) {
    Write-Host ("     PASS  {0}" -f $Evidence) -ForegroundColor Green
    $script:Results += [pscustomobject]@{ Check = $What; Evidence = $Evidence }
}

function Note([string]$Text) { Write-Host ("     {0}" -f $Text) -ForegroundColor DarkGray }

Write-Host "Lab 5 defence setup" -ForegroundColor White
Write-Host "report $BaseUrl/lab5-report.html | live runner :$RunnerPort | k6 on the host" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 2.2 the stack
Section "2.2" "The pinned stack"
$running = $false
try {
    $probe = Invoke-WebRequest -Uri "$BaseUrl/lb-health" -UseBasicParsing -TimeoutSec 3
    $running = $probe.StatusCode -eq 200
}
catch { $running = $false }

if (-not $running) {
    Note "balancer not answering - bringing the stack up (first run builds, which takes a minute)"
    $code = Invoke-Docker (Compose @("--profile", "demo", "up", "-d", "--build", "--remove-orphans"))
    if ($code -ne 0) { throw "the stack did not come up" }
}

# The load-test pool fragment, not Lab 3's. pools/3.conf ejects a peer after three failures in
# five seconds and proxy.conf counts an application 503 as a failure, so a demo that pushes the
# system into 503s would answer 502 from an empty pool instead - see the Theory card.
$code = Invoke-Docker (Compose @("exec", "-T", "lb", "sh", "/usr/local/bin/lb-switch", "round-robin", "3-lab5"))
if ($code -ne 0) { throw "could not switch the balancer to the load-test pool" }
Start-Sleep -Milliseconds 800
$status = (Invoke-WebRequest -Uri "$BaseUrl/lb-status" -UseBasicParsing).Content
Note "balancer: $status"

$seen = @{}
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "$BaseUrl/health/ready" -UseBasicParsing -TimeoutSec 4
        if ($r.StatusCode -eq 200 -and $r.Headers["X-Instance-ID"]) { $seen[$r.Headers["X-Instance-ID"]] = $true }
    }
    catch { }
    if ($seen.Count -ge 3) { break }
    Start-Sleep -Milliseconds 400
}
if ($seen.Count -lt 3) { throw "only $($seen.Count) instance(s) answered /health/ready" }
Pass "three instances behind one entry point" ($seen.Keys -join ", ")

# ---------------------------------------------------------------- 2.2 the data
Section "2.2" "Deterministic fleet"
$code = Invoke-Docker (Compose @("run", "--rm", "refresh"))
if ($code -ne 0) { throw "fleet refresh failed" }
Pass "seeded fleet refreshed" "every node is fresh for the next 120 s of heartbeat staleness"

# ---------------------------------------------------------------- 3 the report
Section "3" "Report data on disk"
$dataPath = Join-Path $root "ui/data/lab5.json"
if (-not (Test-Path $dataPath)) {
    Note "ui/data/lab5.json is missing - rendering from whatever summaries exist"
    & python -m scripts.render_lab5_results
}
if (-not (Test-Path $dataPath)) {
    throw "no report data. Run ./scripts/lab5_run.ps1 first - the live button is a demo, not the measurement."
}
$data = Get-Content $dataPath -Raw | ConvertFrom-Json
$scenarios = ($data.ladder.PSObject.Properties.Name) -join ", "
Pass "report data present" ("scenarios $scenarios, generated " + $data.generated_at)

if ($data.baseline -and $data.baseline.primary_bottleneck) {
    Note ("baseline says: " + $data.baseline.stable_throughput + " stable, bottleneck " + $data.baseline.primary_bottleneck)
}

# ---------------------------------------------------------------- 4 the live runner
if ($NoRunner) {
    Note "skipping the live runner (-NoRunner)"
}
else {
    Section "4" "Live runner and the path the browser takes to it"
    $k6 = Get-Command k6 -ErrorAction SilentlyContinue
    if (-not $k6) { throw "k6 is not on PATH - the live button needs it, and so does lab5_run.ps1" }
    Note ("k6: " + (& k6 version | Select-Object -First 1))

    $runner = Start-Process -FilePath "python" -PassThru -WindowStyle Hidden -ArgumentList @(
        "-m", "scripts.lab5_live", "--port", "$RunnerPort", "--base-url", $BaseUrl
    )

    try {
        # Verified through nginx, not against the runner directly. Reaching the runner on
        # localhost proves nothing about what the page can do: the request the browser makes
        # goes through the balancer's /lab5/ block and out to host.docker.internal, and that is
        # the hop that actually breaks.
        $reachable = $false
        for ($i = 0; $i -lt 20; $i++) {
            try {
                $probe = Invoke-WebRequest -Uri "$BaseUrl/lab5/status" -UseBasicParsing -TimeoutSec 4
                if ($probe.StatusCode -eq 200) { $reachable = $true; break }
            }
            catch { }
            Start-Sleep -Milliseconds 500
        }
        if (-not $reachable) {
            throw "nginx cannot reach the runner through /lab5/ - check that host.docker.internal resolves inside the lb container"
        }
        $profileName = ($probe.Content | ConvertFrom-Json).profile
        Pass "the Run live button will work" "GET $BaseUrl/lab5/status answered 200 - profile: $profileName"

        if (-not $NoBrowser) { Start-Process "$BaseUrl/lab5-report.html" | Out-Null }

        Write-Host ""
        $script:Results | Format-Table -AutoSize -Wrap
        Write-Host "$($script:Results.Count) check(s) passed." -ForegroundColor Green
        Write-Host ""
        Write-Host "Open   $BaseUrl/lab5-report.html  and press Run live." -ForegroundColor White
        Write-Host "Full matrix (about 70 min):  ./scripts/lab5_run.ps1" -ForegroundColor DarkGray
        Write-Host "Report:                      docs/lab5-results.md" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "Runner is in the foreground. Ctrl+C here stops it." -ForegroundColor Yellow
        $runner.WaitForExit()
    }
    finally {
        if (-not $runner.HasExited) {
            $runner.Kill()
            Note "live runner stopped"
        }
    }
    return
}

if (-not $NoBrowser) { Start-Process "$BaseUrl/lab5-report.html" | Out-Null }
Write-Host ""
$script:Results | Format-Table -AutoSize -Wrap
Write-Host "$($script:Results.Count) check(s) passed." -ForegroundColor Green
Write-Host "Open $BaseUrl/lab5-report.html" -ForegroundColor White
