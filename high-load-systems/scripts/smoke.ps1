<#
.SYNOPSIS
    End-to-end walkthrough of the CDN Control Plane API.

.DESCRIPTION
    Exercises every business flow in order: register a region and a node, report
    telemetry, register content, pin it to a region, report a cached replica, resolve
    a route, publish a new version, observe the purge it triggers, acknowledge that
    purge and read network statistics.

    Each run uses a unique suffix, so it can be repeated against a live stack without
    colliding with its own previous data.

.EXAMPLE
    ./scripts/smoke.ps1
    ./scripts/smoke.ps1 -BaseUrl http://localhost:8080   # through the Lab 3 balancer
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"
$runId = Get-Date -Format "HHmmss"
$api = "$BaseUrl/api/v1"
$step = 0

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Uri,
        [object]$Body,
        [int]$ExpectStatus,
        [string]$Title
    )

    $script:step++
    Write-Host ""
    Write-Host ("[{0:d2}] {1}" -f $script:step, $Title) -ForegroundColor Cyan
    Write-Host ("     {0} {1}" -f $Method, $Uri) -ForegroundColor DarkGray

    $params = @{
        Method          = $Method
        Uri             = $Uri
        UseBasicParsing = $true
        ContentType     = "application/json"
    }
    if ($null -ne $Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 6 -Compress)
    }

    try {
        $response = Invoke-WebRequest @params
    }
    catch {
        $failed = $_.Exception.Response
        if ($null -ne $failed) {
            $reader = New-Object System.IO.StreamReader($failed.GetResponseStream())
            Write-Host ("     FAILED {0}: {1}" -f [int]$failed.StatusCode, $reader.ReadToEnd()) -ForegroundColor Red
        }
        else {
            Write-Host ("     FAILED: {0}" -f $_.Exception.Message) -ForegroundColor Red
        }
        throw
    }

    $status = [int]$response.StatusCode
    if ($status -ne $ExpectStatus) {
        throw "Expected HTTP $ExpectStatus but got $status for $Method $Uri"
    }

    $instance = $response.Headers["X-Instance-ID"]
    $elapsed = $response.Headers["X-Response-Time-ms"]
    $cache = $response.Headers["X-Cache"]
    $meta = "     -> $status  instance=$instance  ${elapsed}ms"
    if ($cache) { $meta += "  cache=$cache" }
    Write-Host $meta -ForegroundColor Green

    if ($response.Content) {
        return ($response.Content | ConvertFrom-Json)
    }
    return $null
}

Write-Host "CDN Control Plane smoke test against $BaseUrl (run $runId)" -ForegroundColor White

Invoke-Api -Method GET -Uri "$BaseUrl/health" -ExpectStatus 200 `
    -Title "Liveness probe" | Out-Null

Invoke-Api -Method GET -Uri "$BaseUrl/health/ready" -ExpectStatus 200 `
    -Title "Readiness probe (checks the database)" | Out-Null

$regionCode = "demo-$runId"
Invoke-Api -Method POST -Uri "$api/regions" -ExpectStatus 201 `
    -Title "Register a region" `
    -Body @{ code = $regionCode; name = "Demo Region $runId"; continent = "Europe" } | Out-Null

$node = Invoke-Api -Method POST -Uri "$api/nodes" -ExpectStatus 201 `
    -Title "Register an edge node" `
    -Body @{
        hostname      = "edge-demo-$runId.cdn.net"
        public_ipv4   = "198.51.100.7"
        region_code   = $regionCode
        capacity_mbps = 20000
        agent_version = "1.4.2"
    }

$heartbeat = Invoke-Api -Method POST -Uri "$api/nodes/$($node.id)/heartbeat" -ExpectStatus 202 `
    -Title "Report telemetry (node becomes healthy)" `
    -Body @{
        cpu_percent        = 21
        memory_percent     = 44
        bandwidth_out_mbps = 3000
        active_connections = 1800
        cache_hit_ratio    = 0.93
    }
Write-Host ("     node status is now '{0}' at {1}% load" -f $heartbeat.status, $heartbeat.current_load_percent)

$asset = Invoke-Api -Method POST -Uri "$api/assets" -ExpectStatus 201 `
    -Title "Register an asset" `
    -Body @{
        origin_path       = "/static/demo-$runId.js"
        content_hash      = ("a" * 64)
        size_bytes        = 512000
        content_type      = "application/javascript"
        cache_ttl_seconds = 3600
    }

Invoke-Api -Method PUT -Uri "$api/assets/$($asset.id)/distribution" -ExpectStatus 200 `
    -Title "Pin the asset to the demo region" `
    -Body @{ rules = @(@{ region_code = $regionCode; priority = 10; enabled = $true }) } | Out-Null

Invoke-Api -Method PUT -Uri "$api/nodes/$($node.id)/replicas/$($asset.id)" -ExpectStatus 200 `
    -Title "Node reports it has cached the asset" `
    -Body @{ state = "cached"; cached_version = 1; bytes_cached = 512000 } | Out-Null

$route = Invoke-Api -Method GET `
    -Uri "$api/routing/resolve?path=/static/demo-$runId.js&client_region=$regionCode" `
    -ExpectStatus 200 -Title "Resolve a route (read hot path)"
foreach ($candidate in $route.candidates) {
    Write-Host ("     {0}  score={1}  {2}" -f $candidate.hostname, $candidate.score, $candidate.reason)
}

$published = Invoke-Api -Method POST -Uri "$api/assets/$($asset.id)/versions" -ExpectStatus 201 `
    -Title "Publish a new version (auto-invalidates replicas)" `
    -Body @{
        content_hash = ("b" * 64)
        size_bytes   = 521400
        requested_by = "ci-pipeline"
        reason       = "smoke test release"
    }
Write-Host ("     version {0} -> {1}, {2} replica(s) invalidated, purge {3}" -f `
        $published.previous_version, $published.asset.version, `
        $published.replicas_invalidated, $published.purge_event_id)

$purge = Invoke-Api -Method GET -Uri "$api/purges/$($published.purge_event_id)" -ExpectStatus 200 `
    -Title "Inspect the purge campaign"
Write-Host ("     status={0} acknowledged={1}/{2}" -f $purge.status, $purge.acknowledged_count, $purge.target_node_count)

$acked = Invoke-Api -Method POST `
    -Uri "$api/purges/$($published.purge_event_id)/acknowledgements" -ExpectStatus 200 `
    -Title "Edge node acknowledges the purge" `
    -Body @{ node_id = $node.id; result = "purged" }
Write-Host ("     status={0} acknowledged={1}/{2}" -f $acked.status, $acked.acknowledged_count, $acked.target_node_count)

Invoke-Api -Method GET -Uri "$api/stats/network" -ExpectStatus 200 `
    -Title "Aggregate network statistics (Lab 4 caching target)" | Out-Null

Write-Host ""
Write-Host "--- negative paths -------------------------------------------------" -ForegroundColor White

try {
    Invoke-Api -Method GET -Uri "$api/routing/resolve?path=/does/not/exist" -ExpectStatus 200 `
        -Title "Unknown asset should fail with problem+json" | Out-Null
    throw "Expected the unknown-asset lookup to fail"
}
catch [System.Net.WebException] {
    $code = [int]$_.Exception.Response.StatusCode
    Write-Host ("     -> {0} as expected (application/problem+json)" -f $code) -ForegroundColor Green
}

Write-Host ""
Write-Host "All checks passed." -ForegroundColor Green
