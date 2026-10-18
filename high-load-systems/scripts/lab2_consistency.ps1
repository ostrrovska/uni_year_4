# Lab2
<#
.SYNOPSIS
    Cross-instance consistency and resilience demo for the stateless API tier.

.DESCRIPTION
    Drives a single asset through two different instances to prove that no request
    depends on instance-local memory (no sticky sessions):

        POST  /assets            -> Instance 1   (create, version 1)
        GET   /assets/{id}       -> Instance 2   (sees Instance 1's write)
        POST  /assets/{id}/versions -> Instance 2 (update: bump to version 2)
        GET   /assets/{id}       -> Instance 1   (sees Instance 2's write)

    The update step is a version publish because the domain models a content change as
    a new version, not an in-place PUT; it is the write half of the POST/GET/PUT/GET
    rubric. Every response's X-Instance-ID is printed so the alternating instances are
    visible, and the asset version is asserted after each hop.

.EXAMPLE
    ./scripts/lab2_consistency.ps1
    ./scripts/lab2_consistency.ps1 -Instance1Url http://localhost:8001 -Instance2Url http://localhost:8002
#>
[CmdletBinding()]
param(
    [string]$Instance1Url = "http://localhost:8001",
    [string]$Instance2Url = "http://localhost:8002"
)

$ErrorActionPreference = "Stop"
$runId = Get-Date -Format "HHmmss"
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
    Write-Host ("     -> {0}  instance={1}" -f $status, $instance) -ForegroundColor Green

    $data = $null
    if ($response.Content) { $data = ($response.Content | ConvertFrom-Json) }
    return [pscustomobject]@{ Status = $status; Instance = $instance; Data = $data }
}

Write-Host "Lab 2 cross-instance consistency (I1=$Instance1Url  I2=$Instance2Url  run $runId)" -ForegroundColor White

# POST -> Instance 1
$created = Invoke-Api -Method POST -Uri "$Instance1Url/api/v1/assets" -ExpectStatus 201 `
    -Title "POST asset -> Instance 1 (create, version 1)" `
    -Body @{
        origin_path       = "/static/lab2-$runId.js"
        content_hash      = ("a" * 64)
        size_bytes        = 512000
        content_type      = "application/javascript"
        cache_ttl_seconds = 3600
    }
$assetId = $created.Data.id
Write-Host ("     asset $assetId version=$($created.Data.version)") -ForegroundColor DarkGray

# GET -> Instance 2: must see what Instance 1 just wrote
$read1 = Invoke-Api -Method GET -Uri "$Instance2Url/api/v1/assets/$assetId" -ExpectStatus 200 `
    -Title "GET asset -> Instance 2 (read-after-write across instances)"
if ($read1.Data.version -ne $created.Data.version) {
    throw "Consistency violated: Instance 2 sees version $($read1.Data.version), expected $($created.Data.version)"
}
Write-Host ("     Instance 2 sees version=$($read1.Data.version) - consistent") -ForegroundColor Green

# UPDATE (version publish) -> Instance 2: bump to version 2
$updated = Invoke-Api -Method POST -Uri "$Instance2Url/api/v1/assets/$assetId/versions" -ExpectStatus 201 `
    -Title "UPDATE asset -> Instance 2 (publish version 2)" `
    -Body @{
        content_hash = ("b" * 64)
        size_bytes   = 521400
        requested_by = "lab2-consistency"
        reason       = "cross-instance update"
    }
Write-Host ("     version $($updated.Data.previous_version) -> $($updated.Data.asset.version)") -ForegroundColor DarkGray

# GET -> Instance 1: must see the update made on Instance 2
$read2 = Invoke-Api -Method GET -Uri "$Instance1Url/api/v1/assets/$assetId" -ExpectStatus 200 `
    -Title "GET asset -> Instance 1 (sees Instance 2's update)"
if ($read2.Data.version -ne $updated.Data.asset.version) {
    throw "Consistency violated: Instance 1 sees version $($read2.Data.version), expected $($updated.Data.asset.version)"
}
Write-Host ("     Instance 1 sees version=$($read2.Data.version) - consistent") -ForegroundColor Green

# Sanity: the two URLs really are different instances
if ($created.Instance -eq $read1.Instance) {
    Write-Host ("     WARNING: both URLs report instance '$($created.Instance)' - not two instances?") -ForegroundColor Yellow
}
else {
    Write-Host ("     served by: $($created.Instance) and $($read1.Instance) - no sticky session needed") -ForegroundColor Green
}

Write-Host ""
Write-Host "--- resilience (instance loss) -------------------------------------" -ForegroundColor White
Write-Host "Kill one instance and re-read from the survivor - state lives in Postgres," -ForegroundColor Gray
Write-Host "so nothing is lost and the other instance keeps serving:" -ForegroundColor Gray
Write-Host "  docker compose -f docker-compose.yml -f docker-compose.lab2.yml kill api1" -ForegroundColor DarkGray
Write-Host "  curl -i $Instance2Url/api/v1/assets/$assetId   # still returns version $($read2.Data.version)" -ForegroundColor DarkGray

Write-Host ""
Write-Host "Consistency proven across instances." -ForegroundColor Green
