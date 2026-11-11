# Lab3
<#
.SYNOPSIS
    Switch the live balancing algorithm or pool size with no downtime.

.DESCRIPTION
    nginx: copies one algorithms/ fragment and one pools/ fragment into place inside the
    container, validates with `nginx -t`, then `nginx -s reload`. The reload starts new workers
    on the new config and lets the old workers drain their in-flight requests, so no connection
    is dropped. A config that fails validation is never loaded.

    HAProxy: rewrites the single `balance` line in loadbalancer/haproxy/haproxy.cfg on the host
    and sends SIGHUP, which the master-worker process turns into a seamless reload.

.EXAMPLE
    ./scripts/lb_switch.ps1 -Algorithm least-conn
    ./scripts/lb_switch.ps1 -Algorithm round-robin -PoolSize 2
    ./scripts/lb_switch.ps1 -Balancer haproxy -Algorithm round-robin
#>
[CmdletBinding()]
param(
    [ValidateSet('round-robin', 'least-conn', 'ip-hash', 'weighted')]
    [string]$Algorithm = 'round-robin',

    # Fragment names from loadbalancer/nginx/pools/, not just instance counts: the
    # *-aggressive variants carry the max_fails=1 passive-check setting.
    [ValidateSet('1', '2', '3', '4', '2-aggressive', '3-aggressive', '1-lab5', '2-lab5', '3-lab5')]
    [string]$PoolSize = '3',

    [ValidateSet('nginx', 'haproxy')]
    [string]$Balancer = 'nginx'
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$composeArgs = @(
    "-f", (Join-Path $root "docker-compose.yml"),
    "-f", (Join-Path $root "docker-compose.lab3.yml")
)

# `nginx -t` and docker's own progress go to stderr, which PowerShell 5.1 turns into a
# terminating NativeCommandError while $ErrorActionPreference is Stop. Judge docker by its
# exit code instead.
function Invoke-Docker([string[]]$DockerArgs) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker @DockerArgs 2>&1 | Out-Null
        return $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
}

if ($Balancer -eq 'nginx') {
    $code = Invoke-Docker (@("compose") + $composeArgs + @("exec", "-T", "lb", "sh", "/usr/local/bin/lb-switch", $Algorithm, $PoolSize))
    if ($code -ne 0) { throw "lb-switch failed for '$Algorithm' (pool $PoolSize)" }

    $status = (Invoke-WebRequest -Uri "http://127.0.0.1:8080/lb-status" -UseBasicParsing).Content
    Write-Host "nginx -> $status" -ForegroundColor Green
    return
}

# HAProxy keeps the method in its own config file; `source` is its IP-hash equivalent.
$haproxyBalance = @{
    'round-robin' = 'roundrobin'
    'least-conn'  = 'leastconn'
    'ip-hash'     = 'source'
}[$Algorithm]

if (-not $haproxyBalance) {
    throw "HAProxy has no direct equivalent for '$Algorithm'; use round-robin, least-conn or ip-hash."
}

$cfgPath = Join-Path $root "loadbalancer/haproxy/haproxy.cfg"
# Read and write UTF-8 explicitly: PowerShell 5.1's Get-Content defaults to the system ANSI
# codepage, which corrupts any non-ASCII byte on the round trip.
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$cfg = [System.IO.File]::ReadAllText($cfgPath, $utf8NoBom)
$updated = [regex]::Replace($cfg, '(?m)^(\s*)balance\s+\w+', "`${1}balance $haproxyBalance")
if ($updated -eq $cfg) {
    Write-Host "haproxy already on $haproxyBalance" -ForegroundColor DarkGray
}
else {
    # LF only: the config is bind-mounted into a Linux container.
    [System.IO.File]::WriteAllText($cfgPath, $updated.Replace("`r`n", "`n"), $utf8NoBom)
}

$code = Invoke-Docker (@("compose") + $composeArgs + @("kill", "-s", "HUP", "haproxy"))
if ($code -ne 0) { throw "haproxy reload signal failed" }
Start-Sleep -Milliseconds 500

$probe = Invoke-WebRequest -Uri "http://127.0.0.1:8090/health" -UseBasicParsing
if ($probe.StatusCode -ne 200) { throw "haproxy did not answer after the reload" }
Write-Host "haproxy -> balance $haproxyBalance (reloaded, :8090 answering)" -ForegroundColor Green
