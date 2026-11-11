# Lab5
<#
.SYNOPSIS
    Run the whole Lab 5 measurement matrix and render the report.

.DESCRIPTION
    One command for every number in docs/lab5-results.md. Clause by clause:

      2.2  Baseline environment    docker-compose.lab5.yml pins CPU/RAM; this script records
                                   what the engine actually applied, and keeps the k6 generator
                                   on the host so it never competes with the SUT for a limit.
      2.3  Warm-up + staged ramp   every k6 run carries its own warm-up scenario; the ladder
                                   10/25/50/100/200 VUs runs both as flat runs (for the table)
                                   and as one continuous ramp (for the curve).
      2.4  Metrics per stage       phase 'matrix'.
      2.5  Saturation + bottleneck phases 'pool' and 'ramp', plus pg_counters and docker stats
                                   around every single run.
      2.6  Scaling impact          phase 'scaling', 1 vs 3 instances, cache OFF and asserted.
           Caching impact          phase 'caching', cache off / cold / warm.
      4    Coordinated omission    phase 'open', the same load under an open model.

    Phases are independent and re-runnable: a 50-minute matrix that cannot resume from the
    middle is unusable. Pass -Only <phase> to run one.

    Determinism (clause 2.2) is enforced, not hoped for. Before every measured run this script
    stops the `agents` service, refreshes the fleet once, and - for the write scenario - levels
    the node_heartbeats table, because an append-only table that grows all afternoon means a
    late run is not measuring the same database as an early one. Each of those is a documented
    past mistake in this repo rather than a precaution.

.EXAMPLE
    ./scripts/lab5_run.ps1
    ./scripts/lab5_run.ps1 -Only calibrate
    ./scripts/lab5_run.ps1 -Only matrix -MeasureSeconds 30
    ./scripts/lab5_run.ps1 -Only render
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8080",

    [ValidateSet('all', 'up', 'calibrate', 'matrix', 'ramp', 'scaling', 'caching', 'pool', 'connrelease', 'restore', 'open', 'render')]
    [string]$Only = 'all',

    [int]$MeasureSeconds = 60,
    [int]$WarmupSeconds = 20,
    [int[]]$Stages = @(10, 25, 50, 100, 200),

    # The open-model control runs at the throughput the closed-model ladder found at
    # saturation. 0 means "derive it from the matrix results already on disk".
    [int]$OpenTargetRps = 0,

    [switch]$SkipBuild,

    # node_heartbeats carries ~143k rows of demo history on this machine. Levelling it is what
    # makes the write scenario's stages comparable; -KeepHistory opts out and says so in the
    # report instead.
    [switch]$KeepHistory
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
$pool2Args = $composeArgs + @("-f", (Join-Path $root "docker-compose.lab5-pool2.yml"))
$holdArgs = $composeArgs + @("-f", (Join-Path $root "docker-compose.lab5-holdconn.yml"))

$SUMMARY_DIR = "docs/loadtest/lab5"
$RAW_DIR = "load-tests/results"
$PG_CONTAINER = "cdn-control-plane-postgres-1"

New-Item -ItemType Directory -Force -Path $SUMMARY_DIR, $RAW_DIR | Out-Null

$script:Results = @()
$script:Step = 0

# ----------------------------------------------------------------- plumbing
# docker writes progress to stderr, which PowerShell 5.1 turns into a terminating
# NativeCommandError while $ErrorActionPreference is Stop. Judge docker by its exit code.
function Invoke-Docker([string[]]$DockerArgs) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker @DockerArgs 2>&1 | Out-Null
        return $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
}

function Get-DockerOutput([string[]]$DockerArgs) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { return (& docker @DockerArgs 2>&1) }
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

function Warn([string]$Text) { Write-Host ("     WARN  {0}" -f $Text) -ForegroundColor Yellow }

function Invoke-Psql([string]$Sql) {
    return Get-DockerOutput @("exec", $PG_CONTAINER, "psql", "-U", "cdn", "-d", "cdn_control_plane", "-At", "-c", $Sql)
}

# ----------------------------------------------------------------- stack control
function Wait-Ready([int]$TimeoutSeconds = 120) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $seen = @{}
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "$BaseUrl/health/ready" -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) {
                $id = $r.Headers["X-Instance-ID"]
                if ($id) { $seen[$id] = $true }
                # Every instance must answer before a run starts: a cold instance joining the
                # pool mid-measurement shows up as a latency spike with no cause.
                if ($seen.Count -ge $script:ExpectedInstances) { return $seen.Keys -join ", " }
            }
        }
        catch { }
        Start-Sleep -Milliseconds 400
    }
    throw "only $($seen.Count) of $($script:ExpectedInstances) instance(s) answered /health/ready in ${TimeoutSeconds}s"
}

$script:ExpectedInstances = 3

$script:PoolFragment = "3-lab5"

# Recreating an API container gives it a new IP, and nginx resolved the upstream names once at
# startup - docker-compose.lab3.yml says so in its own header, and the `resolve` parameter that
# would re-resolve Docker's DNS is nginx Plus only. So a recreate leaves the balancer holding
# stale addresses: with max_fails=0 it keeps trying them, proxy_next_upstream retries onto the
# one instance whose address did not change, and every response comes from that instance.
#
# Found exactly that way - the first scaling run reported "only 1 of 3 instances answered". An
# lb-switch re-runs the config generation and reloads, which re-resolves the names.
function Sync-Balancer {
    $code = Invoke-Docker (Compose @("exec", "-T", "lb", "sh", "/usr/local/bin/lb-switch", "round-robin", $script:PoolFragment))
    if ($code -ne 0) { throw "balancer reload failed for pool '$($script:PoolFragment)'" }
    Start-Sleep -Milliseconds 800
}

function Set-Pool([string]$Fragment, [int]$Instances) {
    # Stopped, never removed: nginx resolves an upstream name once at startup and refuses to
    # start on an unresolvable one, so a `down` on an unused instance would break the balancer.
    $all = @("api1", "api2", "api3")
    $wanted = $all[0..($Instances - 1)]
    foreach ($svc in $all) {
        if ($wanted -contains $svc) { Invoke-Docker (Compose @("start", $svc)) | Out-Null }
        else { Invoke-Docker (Compose @("stop", $svc)) | Out-Null }
    }
    $script:PoolFragment = $Fragment
    $script:ExpectedInstances = $Instances
    Sync-Balancer
    $status = (Invoke-WebRequest -Uri "$BaseUrl/lb-status" -UseBasicParsing).Content
    Note "balancer: $status"
}

function Stop-Agents {
    Invoke-Docker (Compose @("stop", "agents")) | Out-Null
}

function Reset-Fleet([switch]$LevelHistory) {
    # One-shot refresh instead of the long-running `agents` service: the fleet is then fresh for
    # the whole measured window (HEARTBEAT_STALE_AFTER_SECONDS is 120) with no concurrent
    # writer competing for the same rows the scenarios measure.
    if ($LevelHistory -and -not $KeepHistory) {
        Invoke-Psql "TRUNCATE node_heartbeats;" | Out-Null
    }
    $code = Invoke-Docker (Compose @("run", "--rm", "refresh"))
    if ($code -ne 0) { throw "fleet refresh failed" }
}

function Get-HeartbeatRows {
    $rows = Invoke-Psql "SELECT count(*) FROM node_heartbeats;"
    return [int]($rows | Select-Object -Last 1)
}

function Set-Cache([bool]$Enabled) {
    # CACHE_ENABLED is baked into the container environment, so switching it means recreating
    # the three instances. Deliberate: toggling a cache at runtime would leave each instance's
    # circuit breaker and lru_cache in a different state, and clause 2.6's comparison needs
    # both runs to start from the same place.
    $value = if ($Enabled) { "true" } else { "false" }
    foreach ($svc in @("api1", "api2", "api3")) {
        Invoke-Docker (Compose @("stop", $svc)) | Out-Null
    }
    $extra = @()
    if (-not $Enabled) {
        $extra = @("-f", (Join-Path $root "docker-compose.lab5-nocache.yml"))
    }
    # $args is a PowerShell automatic variable inside a function; shadowing it works but reads
    # as a bug to anyone maintaining this.
    $composeCall = @("compose") + $composeArgs + $extra + @("up", "-d", "--no-deps", "api1", "api2", "api3")
    $code = Invoke-Docker $composeCall
    if ($code -ne 0) { throw "could not recreate the API pool with CACHE_ENABLED=$value" }
    Sync-Balancer
    Wait-Ready | Out-Null
}

# ----------------------------------------------------------------- one measured run
function Invoke-K6Run {
    param(
        [Parameter(Mandatory)][string]$Script,
        [Parameter(Mandatory)][string]$Label,
        [int]$Stage = 50,
        [string]$Config = "default",
        [string[]]$ExtraEnv = @(),
        [switch]$Ramp,
        [switch]$ResetStatements,
        [int]$SamplerDuration = 0,
        # -1 means "use the run-wide default". 0 is a real value: no warm-up at all.
        [int]$WarmupOverride = -1
    )

    $before = "$RAW_DIR/$Label.pg-before.json"
    $after = "$RAW_DIR/$Label.pg-after.json"
    $statsCsv = "$RAW_DIR/$Label.stats.csv"
    $statsJson = "$SUMMARY_DIR/$Label.resources.json"
    $stopFile = "$RAW_DIR/$Label.stop"
    if (Test-Path $stopFile) { Remove-Item $stopFile -Force }

    $resetFlag = @()
    if ($ResetStatements) { $resetFlag = @("--reset-statements") }
    & python -m scripts.pg_counters snapshot --out $before @resetFlag | Out-Null

    if ($SamplerDuration -le 0) {
        $SamplerDuration = $WarmupSeconds + $MeasureSeconds + 120
        if ($Ramp) { $SamplerDuration = $WarmupSeconds + ($Stages.Count * ($MeasureSeconds + 10)) + 180 }
    }

    $sampler = Start-Process -FilePath "python" -PassThru -WindowStyle Hidden -ArgumentList @(
        "-m", "scripts.sample_docker_stats",
        "--out", $statsCsv, "--summary", $statsJson,
        "--label", $Label, "--interval", "1",
        "--duration", "$SamplerDuration", "--stop-file", $stopFile
    )

    $warmup = if ($WarmupOverride -ge 0) { $WarmupOverride } else { $WarmupSeconds }
    $k6Args = @(
        "run", $Script,
        "-e", "BASE_URL=$BaseUrl",
        "-e", "STAGE=$Stage",
        "-e", "LABEL=$Label",
        "-e", "CONFIG=$Config",
        "-e", "WARMUP_SECONDS=$warmup",
        "-e", "MEASURE_SECONDS=$MeasureSeconds",
        "-e", "SUMMARY_DIR=$SUMMARY_DIR",
        "--no-usage-report", "--quiet"
    ) + $ExtraEnv
    if ($Ramp) {
        # A ramp's handleSummary aggregate spans every rung at once and is therefore a
        # percentile over five different concurrencies - not a measurement of any of them. The
        # flat runs are what the clause 2.4 table is built from; the ramp exists for the
        # saturation *curve*, and a curve needs a time series. --out csv gives one per second.
        #
        # It lands in load-tests/results/, which .gitignore already excludes: the file is tens
        # of MB and scripts/render_lab5_results.py reduces it to the committed per-second
        # timeline in the summary.
        $k6Args += @("-e", "RAMP=1", "--out", "csv=$RAW_DIR/$Label.csv")
    }

    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & k6 @k6Args; $k6Code = $LASTEXITCODE }
    finally { $ErrorActionPreference = $previous }

    New-Item -ItemType File -Path $stopFile -Force | Out-Null
    $sampler.WaitForExit(40000) | Out-Null
    if (-not $sampler.HasExited) { $sampler.Kill() }
    if (Test-Path $stopFile) { Remove-Item $stopFile -Force }

    & python -m scripts.pg_counters snapshot --out $after | Out-Null

    # k6 exits 99 when a declared threshold failed. Every threshold in load-tests/lib/config.js
    # is deliberately loose - they exist so the sub-metrics are materialised at all - so a 99 is
    # information, not a failure: at 200 VUs degradation is the finding. Any other non-zero code
    # is a real error.
    if ($k6Code -ne 0 -and $k6Code -ne 99) {
        throw "k6 exited $k6Code for '$Label'"
    }

    $summaryPath = "$SUMMARY_DIR/$Label.json"
    if (-not (Test-Path $summaryPath)) { throw "k6 wrote no summary for '$Label'" }
    $summary = Get-Content $summaryPath -Raw | ConvertFrom-Json

    & python -m scripts.pg_counters delta --before $before --after $after `
        --requests $summary.requests --label $Label --out "$SUMMARY_DIR/$Label.pg.json" | Out-Null

    # A container that was OOM-killed makes the run void rather than interesting, and against a
    # 3.75 GB engine budget that is a live risk at 200 VUs - so it is checked, not assumed.
    if (Test-Path $statsJson) {
        $res = Get-Content $statsJson -Raw | ConvertFrom-Json
        foreach ($name in $res.containers.PSObject.Properties.Name) {
            $c = $res.containers.$name
            if ($c.oom_killed) { Warn "$name was OOM-killed during '$Label' - this run is void" }
        }
    }

    $l = $summary.latency_ms
    Note ("{0,-26} {1,6} req  {2,8} rps  p50 {3,7} ms  p95 {4,8} ms  p99 {5,8} ms  err {6} %" -f `
            $Label, $summary.requests, $summary.rps, $l.p50, $l.p95, $l.p99, $summary.error_rate_percent)
    return $summary
}

function Assert-CacheBypassed($Summary, [string]$Label) {
    # docs/context/10 records the run this guard exists for: a four-instance scale-out test
    # accidentally executed on the Lab 4 stack, where one cached instance (287.9 rps, 99 % hit
    # ratio) beat four uncached ones (284.0) and the scale-out conclusion was backwards. A cache
    # in front of /routing/resolve makes 1 -> 3 look near-linear and hides the limit the
    # experiment exists to find.
    if ($Summary.cache.HIT -gt 0) {
        throw "scaling run '$Label' saw $($Summary.cache.HIT) cache HITs - the cache must be off"
    }
    Pass "scaling run is uncached" "$Label : HIT=0, BYPASS=$($Summary.cache.BYPASS), MISS=$($Summary.cache.MISS)"
}

# ----------------------------------------------------------------- phases
function Phase-Up {
    Section "2.2" "Baseline environment: bring up the pinned stack"
    $buildArgs = @("--profile", "demo", "up", "-d", "--remove-orphans")
    if (-not $SkipBuild) { $buildArgs += "--build" }
    $code = Invoke-Docker (Compose $buildArgs)
    if ($code -ne 0) { throw "stack did not come up" }

    $ok = & python -m scripts.pg_counters check
    Note $ok

    Stop-Agents
    Set-Pool -Fragment "3-lab5" -Instances 3
    Reset-Fleet
    $instances = Wait-Ready
    Pass "three instances serve through one entry point" "instances answering: $instances"

    $rows = Get-HeartbeatRows
    Note "node_heartbeats holds $rows row(s) before the matrix"
}

function Phase-Calibrate {
    Section "2.2" "Generator calibration: prove k6 is not the ceiling"
    # Lab 3's lesson, from docs/context/10: "calibrate the generator before trusting any
    # throughput number". The old Python probe topped out near 115 req/s per process and
    # reported that as the system's limit. Three targets, increasing in cost:
    #   /lb-health    static 200 from nginx, no application in the path -> k6 + balancer ceiling
    #   /health       app tier, no database, no cache                   -> API tier ceiling
    #   /health/ready the same plus one pooled SELECT 1                 -> + pool acquire
    Stop-Agents
    $lb = Invoke-K6Run -Script "load-tests/probe-pool.js" -Label "calib-lb-200vu" -Stage 200 `
        -Config "calibration" -ExtraEnv @("-e", "PROBE=lb")
    $app = Invoke-K6Run -Script "load-tests/probe-pool.js" -Label "calib-health-200vu" -Stage 200 `
        -Config "calibration" -ExtraEnv @("-e", "PROBE=health")

    $headroom = [math]::Round($lb.rps / [math]::Max($app.rps, 1), 2)
    if ($headroom -lt 2) {
        Warn "generator headroom is only ${headroom}x - every throughput number below is suspect"
    }
    else {
        Pass "generator is clear of the SUT" ("nginx static {0} rps vs app tier {1} rps = {2}x headroom" -f $lb.rps, $app.rps, $headroom)
    }
}

function Phase-Matrix {
    Section "2.4" "Metrics per scenario per rung: the ladder as flat runs"
    $scenarios = @(
        @{ Name = "a"; Script = "load-tests/scenario-a-read.js"; Level = $true },
        @{ Name = "b"; Script = "load-tests/scenario-b-write.js"; Level = $true },
        @{ Name = "c"; Script = "load-tests/scenario-c-workflow.js"; Level = $true }
    )
    foreach ($s in $scenarios) {
        foreach ($stage in $Stages) {
            Stop-Agents
            Reset-Fleet -LevelHistory:$s.Level
            $rowsBefore = Get-HeartbeatRows
            $label = "$($s.Name)-warm-${stage}vu"
            $summary = Invoke-K6Run -Script $s.Script -Label $label -Stage $stage `
                -Config "3inst-warm-pool10" -ResetStatements
            $rowsAfter = Get-HeartbeatRows
            Note "node_heartbeats $rowsBefore -> $rowsAfter during $label"
            if ($summary.requests -le 0) { throw "$label recorded no requests" }
        }
    }
    Pass "ladder measured for three scenarios" ("{0} rungs x 3 scenarios, warm cache, 3 instances" -f $Stages.Count)
}

function Phase-Ramp {
    Section "2.3" "Continuous staged ramp: the saturation curve"
    foreach ($s in @(
            @{ Name = "a"; Script = "load-tests/scenario-a-read.js" },
            @{ Name = "b"; Script = "load-tests/scenario-b-write.js" },
            @{ Name = "c"; Script = "load-tests/scenario-c-workflow.js" }
        )) {
        Stop-Agents
        Reset-Fleet -LevelHistory
        Invoke-K6Run -Script $s.Script -Label "$($s.Name)-ramp" -Config "3inst-warm-ramp" -Ramp | Out-Null
    }
    Pass "continuous ramp recorded" "10 -> 25 -> 50 -> 100 -> 200 VUs per scenario"
}

function Phase-Scaling {
    Section "2.6" "Scaling impact: 1 vs 3 instances, cache OFF"
    Set-Cache $false
    try {
        foreach ($count in @(1, 3)) {
            Set-Pool -Fragment "$count-lab5" -Instances $count
            foreach ($stage in @(50, 100, 200)) {
                Stop-Agents
                Reset-Fleet
                $label = "scale-${count}inst-${stage}vu"
                $summary = Invoke-K6Run -Script "load-tests/scenario-a-read.js" -Label $label `
                    -Stage $stage -Config "${count}inst-nocache-pool10" -ResetStatements
                Assert-CacheBypassed $summary $label
            }
        }
    }
    finally {
        Set-Pool -Fragment "3-lab5" -Instances 3
        Set-Cache $true
    }
    Pass "scale-out measured under identical conditions" "1 and 3 instances x 50/100/200 VUs, cache off"
}

function Phase-Caching {
    Section "2.6" "Caching impact: disabled vs cold vs warm"
    # Three states, not two. "Cache disabled" and "cold cache" are different systems: a
    # disabled cache never pays the Redis round trip, a cold one pays it and misses. Reporting
    # only disabled-vs-warm would attribute the round-trip cost to the wrong side.
    Set-Cache $false
    try {
        Stop-Agents; Reset-Fleet
        Invoke-K6Run -Script "load-tests/scenario-a-read.js" -Label "cache-off-100vu" `
            -Stage 100 -Config "3inst-nocache" -ResetStatements | Out-Null
    }
    finally { Set-Cache $true }

    # Cold: an empty Redis, measured from the first request. The warm-up scenario inside the run
    # is what fills it, so the cold window is genuinely short - which is itself the finding.
    Stop-Agents; Reset-Fleet
    Invoke-Docker (Compose @("exec", "-T", "redis", "redis-cli", "FLUSHALL")) | Out-Null
    Invoke-K6Run -Script "load-tests/scenario-a-read.js" -Label "cache-cold-100vu" `
        -Stage 100 -Config "3inst-cold" -ResetStatements -WarmupOverride 0 | Out-Null

    Stop-Agents; Reset-Fleet
    Invoke-K6Run -Script "load-tests/scenario-a-read.js" -Label "cache-warm-100vu" `
        -Stage 100 -Config "3inst-warm" -ResetStatements | Out-Null
    Pass "cache states measured" "disabled / cold / warm at 100 VUs on the same pool"
}

function Phase-Pool {
    Section "2.5" "Primary bottleneck: the connection-pool control pair"
    # /health and /health/ready differ by exactly one pooled SELECT 1, so p95(ready) - p95(live)
    # is pool-acquire latency with request parsing, routing, serialisation, the balancer and the
    # network all subtracted out. Running the same ladder against a pool of 2 moves the knee
    # into the measured range and turns the mechanism from an assertion into a demonstration.
    foreach ($stage in $Stages) {
        Stop-Agents; Reset-Fleet
        Invoke-K6Run -Script "load-tests/probe-pool.js" -Label "pool10-${stage}vu" -Stage $stage `
            -Config "pool10+10" | Out-Null
    }

    Note "recreating the API pool with DB_POOL_SIZE=2, DB_MAX_OVERFLOW=0"
    foreach ($svc in @("api1", "api2", "api3")) { Invoke-Docker (Compose @("stop", $svc)) | Out-Null }
    $code = Invoke-Docker (@("compose") + $pool2Args + @("up", "-d", "--no-deps", "api1", "api2", "api3"))
    if ($code -ne 0) { throw "could not recreate the pool-2 stack" }
    try {
        Sync-Balancer
        Wait-Ready | Out-Null
        foreach ($stage in $Stages) {
            Stop-Agents; Reset-Fleet
            Invoke-K6Run -Script "load-tests/probe-pool.js" -Label "pool2-${stage}vu" -Stage $stage `
                -Config "pool2+0" | Out-Null
        }
        foreach ($stage in @(50, 100, 200)) {
            Stop-Agents; Reset-Fleet
            Invoke-K6Run -Script "load-tests/scenario-a-read.js" -Label "a-pool2-${stage}vu" `
                -Stage $stage -Config "pool2+0" -ResetStatements | Out-Null
        }
    }
    finally {
        foreach ($svc in @("api1", "api2", "api3")) { Invoke-Docker (Compose @("stop", $svc)) | Out-Null }
        Invoke-Docker (Compose @("up", "-d", "--no-deps", "api1", "api2", "api3")) | Out-Null
        Sync-Balancer
        Wait-Ready | Out-Null
        Note "restored the shipped pool (10 + 10 per instance)"
    }
    Pass "pool control pair measured on two pool sizes" "ladder on 10+10 and on 2+0"
}


function Phase-ConnRelease {
    Section "2.5" "Does releasing the connection early actually pay?"
    # Both arms on the same host within the same minutes. The first attempt at this compared a
    # fresh run against figures recorded hours earlier and could not support its own claim:
    # /health, which touches no database at all, was 19 % slower in the later run, so the host
    # had moved underneath the comparison.
    #
    # Order matters only in that the two arms must be adjacent. The release arm runs first
    # because it is the shipped behaviour and leaves the stack in the state everything else
    # expects.
    foreach ($stage in @(25, 100, 200)) {
        Stop-Agents; Reset-Fleet
        Invoke-K6Run -Script "load-tests/probe-pool.js" -Label "release-on-${stage}vu" `
            -Stage $stage -Config "release-early" | Out-Null
    }

    Note "recreating the API pool with DB_RELEASE_EARLY=false"
    foreach ($svc in @("api1", "api2", "api3")) { Invoke-Docker (Compose @("stop", $svc)) | Out-Null }
    $code = Invoke-Docker (@("compose") + $holdArgs + @("up", "-d", "--no-deps", "api1", "api2", "api3"))
    if ($code -ne 0) { throw "could not recreate the pool with DB_RELEASE_EARLY=false" }
    try {
        Sync-Balancer
        Wait-Ready | Out-Null
        foreach ($stage in @(25, 100, 200)) {
            Stop-Agents; Reset-Fleet
            Invoke-K6Run -Script "load-tests/probe-pool.js" -Label "release-off-${stage}vu" `
                -Stage $stage -Config "hold-connection" | Out-Null
        }
        foreach ($stage in @(100, 200)) {
            Stop-Agents; Reset-Fleet
            Invoke-K6Run -Script "load-tests/scenario-a-read.js" -Label "a-holdconn-${stage}vu" `
                -Stage $stage -Config "hold-connection" -ResetStatements | Out-Null
        }
    }
    finally {
        foreach ($svc in @("api1", "api2", "api3")) { Invoke-Docker (Compose @("stop", $svc)) | Out-Null }
        Invoke-Docker (Compose @("up", "-d", "--no-deps", "api1", "api2", "api3")) | Out-Null
        Sync-Balancer
        Wait-Ready | Out-Null
        Note "restored DB_RELEASE_EARLY=true"
    }
    Pass "connection-release arms measured back to back" "release on/off at 25/100/200 VUs"
}


function Phase-Restore {
    Section "2.4" "Re-measure a named subset of the ladder"
    # Exists because a later matrix run was stopped part way through and had already overwritten
    # nine of the forty-three result files. The rest of the set is still valid, so rather than
    # re-measuring everything, this re-takes exactly the runs that were lost - on the same
    # configuration as the survivors, which is what keeps the ladder a ladder.
    # Re-resolve the upstreams first. A rebuild of api1..api3 outside this script gives them new
    # IPs, nginx resolved the names once at startup, and every request then dies on
    # proxy_connect_timeout. That is what happened on the first attempt at this phase: p95 was
    # pinned at ~2100 ms - the 2 s connect timeout - across every run, with 30 % errors, and the
    # numbers were meaningless. Cheap to do unconditionally, expensive to forget.
    Sync-Balancer
    Wait-Ready | Out-Null

    $todo = @(
        @{ Label = "calib-lb-200vu"; Script = "load-tests/probe-pool.js"; Stage = 200; Config = "calibration"; Env = @("-e", "PROBE=lb") },
        @{ Label = "calib-health-200vu"; Script = "load-tests/probe-pool.js"; Stage = 200; Config = "calibration"; Env = @("-e", "PROBE=health") },
        @{ Label = "a-warm-10vu"; Script = "load-tests/scenario-a-read.js"; Stage = 10; Config = "3inst-warm-pool10"; Env = @() },
        @{ Label = "a-warm-25vu"; Script = "load-tests/scenario-a-read.js"; Stage = 25; Config = "3inst-warm-pool10"; Env = @() },
        @{ Label = "a-warm-50vu"; Script = "load-tests/scenario-a-read.js"; Stage = 50; Config = "3inst-warm-pool10"; Env = @() },
        @{ Label = "a-warm-100vu"; Script = "load-tests/scenario-a-read.js"; Stage = 100; Config = "3inst-warm-pool10"; Env = @() },
        @{ Label = "a-warm-200vu"; Script = "load-tests/scenario-a-read.js"; Stage = 200; Config = "3inst-warm-pool10"; Env = @() },
        @{ Label = "b-warm-10vu"; Script = "load-tests/scenario-b-write.js"; Stage = 10; Config = "3inst-warm-pool10"; Env = @() },
        @{ Label = "b-warm-25vu"; Script = "load-tests/scenario-b-write.js"; Stage = 25; Config = "3inst-warm-pool10"; Env = @() }
    )
    foreach ($run in $todo) {
        Stop-Agents
        Reset-Fleet -LevelHistory
        Invoke-K6Run -Script $run.Script -Label $run.Label -Stage $run.Stage `
            -Config $run.Config -ExtraEnv $run.Env -ResetStatements | Out-Null
    }
    Pass "lost runs re-measured" ("{0} runs restored on the surviving configuration" -f $todo.Count)
}

function Phase-Open {
    Section "4" "Coordinated omission: the same load under an open model"
    $target = $OpenTargetRps
    if ($target -le 0) {
        # The saturation throughput the closed-model ladder actually reached, read off disk
        # rather than guessed, so the two models are compared at the same offered load.
        $best = 0
        Get-ChildItem "$SUMMARY_DIR/a-warm-*vu.json" -ErrorAction SilentlyContinue | ForEach-Object {
            $s = Get-Content $_.FullName -Raw | ConvertFrom-Json
            if ($s.rps -gt $best) { $best = $s.rps }
        }
        $target = [int][math]::Round($best)
    }
    if ($target -le 0) { throw "no closed-model result to derive a target RPS from - run -Only matrix first" }
    Note "open-model target: $target req/s (the closed-model ladder's peak)"
    Stop-Agents; Reset-Fleet
    Invoke-K6Run -Script "load-tests/arrival-rate.js" -Label "open-${target}rps" -Stage 0 `
        -Config "3inst-warm-open" -ExtraEnv @("-e", "TARGET_RPS=$target") -ResetStatements | Out-Null
    Pass "open-model control recorded" "constant-arrival-rate at $target req/s"
}

function Phase-Render {
    Section "3" "Render the report from the JSON on disk"
    # Order matters: the renderer embeds the charts, so it needs to know which exist, and the
    # chart script reads ui/data/lab5.json, which the renderer writes. Run the renderer once to
    # refresh the data, then the charts, then the renderer again so the image links land.
    & python -m scripts.render_lab5_results
    if ($LASTEXITCODE -ne 0) { throw "renderer failed" }
    & python -m scripts.render_lab5_charts
    if ($LASTEXITCODE -ne 0) { throw "chart renderer failed" }
    & python -m scripts.render_lab5_results
    if ($LASTEXITCODE -ne 0) { throw "renderer failed on the second pass" }
    Pass "report generated" "docs/lab5-results.md, docs/lab5-results-ua.md, charts and ui/data/lab5.json"
}

# ----------------------------------------------------------------- main
Write-Host "Lab 5 - load testing and performance baseline" -ForegroundColor White
Write-Host "entry point $BaseUrl (nginx) | k6 on the host, SUT in Docker with pinned limits" -ForegroundColor DarkGray
Write-Host ("phase '{0}' | warm-up {1}s | measure {2}s | ladder {3}" -f $Only, $WarmupSeconds, $MeasureSeconds, ($Stages -join "/")) -ForegroundColor DarkGray

$started = Get-Date
try {
    if ($Only -in @('all', 'up')) { Phase-Up }
    if ($Only -in @('all', 'calibrate')) { Phase-Calibrate }
    if ($Only -in @('all', 'matrix')) { Phase-Matrix }
    if ($Only -in @('all', 'ramp')) { Phase-Ramp }
    if ($Only -in @('all', 'scaling')) { Phase-Scaling }
    if ($Only -in @('all', 'caching')) { Phase-Caching }
    if ($Only -in @('all', 'pool')) { Phase-Pool }
    if ($Only -in @('all', 'connrelease')) { Phase-ConnRelease }
    if ($Only -eq 'restore') { Phase-Restore }
    if ($Only -in @('all', 'open')) { Phase-Open }
    if ($Only -in @('all', 'render')) { Phase-Render }
}
finally {
    # The agent simulator is stopped for every measured run; leaving it stopped would make the
    # dashboard report a fleet that has silently aged out of the routing pool, which looks like
    # a broken system rather than a finished experiment.
    Invoke-Docker (Compose @("start", "agents")) | Out-Null
    Note "agent simulator restarted"
}

Write-Host ""
if ($script:Results.Count -gt 0) {
    $script:Results | Format-Table -AutoSize -Wrap
}
$elapsed = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
Write-Host ("$($script:Results.Count) check(s) passed in $elapsed min.") -ForegroundColor Green
Write-Host "Report:    docs/lab5-results.md" -ForegroundColor DarkGray
Write-Host "Dashboard: $BaseUrl/lab5-report.html" -ForegroundColor DarkGray
