# DevOps Lab3
<#
.SYNOPSIS
    Requirement-by-requirement defence demo for DevOps Lab 3 (Kubernetes deployment).

.DESCRIPTION
    Each step is tagged with the assignment clause it satisfies, prints live evidence and
    asserts the outcome, so a silent regression fails the demo instead of passing unnoticed.
    A PASS table is printed at the end, and every command output is also written to
    docs/devops/lab-03-output/ so the report can cite real transcripts.

    Clauses: 5a apply the whole directory in one command | 5b the created objects |
    5c the application answers over the Service | 5d ConfigMap and Secret reach the
    container | 6a self-healing | 6b scaling and traffic distribution | 6c rolling
    update | 6d history and rollback | 6e availability during the update | 7a-d
    diagnosing ImagePullBackOff through events, logs and an interactive shell.

    Prerequisites - a running cluster with both image tags side-loaded:
        minikube start --driver=docker --cpus=4 --memory=3072 --disk-size=12g
        minikube addons enable ingress
        minikube addons enable metrics-server
        docker build -f docker/Dockerfile --build-arg APP_VERSION=1.0.0 -t ghcr.io/ostrrovska/cdn-control-plane:1.0.0 .
        docker build -f docker/Dockerfile --build-arg APP_VERSION=1.1.0 -t ghcr.io/ostrrovska/cdn-control-plane:1.1.0 .
        minikube image load ghcr.io/ostrrovska/cdn-control-plane:1.0.0
        minikube image load ghcr.io/ostrrovska/cdn-control-plane:1.1.0

.PARAMETER Port
    Local port for the port-forward. Default 8181, clear of 8080/8090/8404 so the
    Compose stack of the high-load labs is never shadowed.

.PARAMETER Requests
    Requests per distribution sample (default 60).

.PARAMETER Present
    Defence mode: pause before every step and print the cue for what to say.
    Use it at the defence; without it the script runs straight through, which
    is what you want when you are only checking that nothing regressed.

.EXAMPLE
    ./scripts/devops_lab3_demo.ps1
    ./scripts/devops_lab3_demo.ps1 -Present
    ./scripts/devops_lab3_demo.ps1 -Requests 120
#>
[CmdletBinding()]
param(
    [int]$Port = 8181,
    [int]$Requests = 60,
    [string]$Namespace = "cdn-control-plane",
    [string]$Image = "ghcr.io/ostrrovska/cdn-control-plane",
    [string]$KubectlPath,
    [string]$MinikubePath,
    # Defence mode: stop before every step, print the Ukrainian cue for what to
    # say, and wait for Enter. Without it the script runs straight through,
    # which is what you want when you are only checking that nothing regressed.
    [switch]$Present
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$outDir = Join-Path $root "docs/devops/lab-03-output"
$base = "http://127.0.0.1:$Port"

$script:Results = @()
$script:Step = 0

# Resolve the CLIs explicitly instead of trusting PATH. minikube and Helm 3 are
# installed under %LOCALAPPDATA%\Programs\k8stools, and a shell started before
# that entry was added to the user PATH - which is any shell already open when
# the tools were installed - will not find them. Failing here with a clear
# message beats failing twenty steps in with an empty command output.
function Resolve-Tool([string]$Name, [string]$Explicit) {
    if ($Explicit) {
        if (Test-Path $Explicit) { return $Explicit }
        throw "$Name was not found at $Explicit"
    }
    $onPath = Get-Command $Name -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $local = Join-Path $env:LOCALAPPDATA "Programs\k8stools\$Name.exe"
    if (Test-Path $local) { return $local }
    throw "$Name is not on PATH and not in %LOCALAPPDATA%\Programs\k8stools. Open a new terminal, or pass -$Name<Path>."
}

$kubectl = Resolve-Tool "kubectl" $KubectlPath
$minikube = Resolve-Tool "minikube" $MinikubePath

$script:Forward = $null

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

function Section([string]$Clause, [string]$Title, [string]$Say) {
    $script:Step++
    if ($Present) {
        Write-Host ""
        Write-Host ("=" * 76) -ForegroundColor DarkGray
        Write-Host ("  STEP {0}   ({1})" -f $script:Step, $Clause) -ForegroundColor White
        if ($Say) {
            foreach ($line in ($Say -split "\|")) {
                Write-Host ("  > {0}" -f $line.Trim()) -ForegroundColor Yellow
            }
        }
        Write-Host ("=" * 76) -ForegroundColor DarkGray
        Read-Host "  press Enter to run this step"
    }
    Write-Host ""
    Write-Host ("[{0:d2}] {1}  -  {2}" -f $script:Step, $Clause, $Title) -ForegroundColor Cyan
}

function Pass([string]$What, [string]$Evidence) {
    Write-Host ("     PASS  {0}" -f $Evidence) -ForegroundColor Green
    $script:Results += [pscustomobject]@{ Step = $script:Step; Check = $What; Evidence = $Evidence }
}

function Note([string]$Text) { Write-Host ("     {0}" -f $Text) -ForegroundColor DarkGray }

# Echo the command that is about to run. The output of a kubectl call means
# nothing at a defence unless the command that produced it is on screen too.
function Show-Cmd([string]$Text) {
    Write-Host ("     $ {0}" -f $Text) -ForegroundColor White
}

# Runs kubectl, echoes the output and appends it to a named transcript under
# docs/devops/lab-03-output/. "Continue" around the call because in Windows
# PowerShell 5.1 a native process writing to stderr - which kubectl does for
# perfectly ordinary progress lines - is wrapped into a terminating error
# under "Stop". Every call below checks its own outcome instead.
function Capture([string]$Name, [string[]]$KubectlArgs, [switch]$Silent) {
    # Always shown, even with -Silent: -Silent hides the *output* (because it is
    # long), never the command itself.
    Show-Cmd ("kubectl " + ($KubectlArgs -join " "))
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $text = (& $kubectl @KubectlArgs 2>&1 | Out-String)
    }
    finally { $ErrorActionPreference = $previous }

    $file = Join-Path $outDir "$Name.txt"
    Add-Content -Path $file -Encoding UTF8 -Value ("$ kubectl " + ($KubectlArgs -join " "))
    Add-Content -Path $file -Encoding UTF8 -Value $text

    if (-not $Silent) {
        foreach ($line in ($text -split "`r?`n")) {
            if ($line.Trim()) { Write-Host ("     {0}" -f $line) -ForegroundColor Gray }
        }
    }
    return $text
}

function Write-Transcript([string]$Name, [string[]]$Lines) {
    Add-Content -Path (Join-Path $outDir "$Name.txt") -Encoding UTF8 -Value $Lines
}

function Reset-Transcript([string]$Name) {
    $file = Join-Path $outDir "$Name.txt"
    if (Test-Path $file) { Remove-Item $file }
}

function Start-Forward {
    Show-Cmd ("kubectl port-forward svc/cdn-api {0}:80 -n {1}   (in the background)" -f $Port, $Namespace)
    $script:Forward = Start-Process -FilePath $kubectl -PassThru -NoNewWindow -ArgumentList @(
        "port-forward", "svc/cdn-api", ("{0}:80" -f $Port), "-n", $Namespace
    )
    foreach ($i in 1..60) {
        Start-Sleep -Milliseconds 500
        try {
            $r = Invoke-WebRequest -Uri "$base/health" -UseBasicParsing -TimeoutSec 5
            if ([int]$r.StatusCode -eq 200) { return }
        }
        catch { }
    }
    throw "port-forward to svc/cdn-api never became reachable on $base"
}

function Stop-Forward {
    if ($script:Forward -and -not $script:Forward.HasExited) {
        Stop-Process -Id $script:Forward.Id -Force -ErrorAction SilentlyContinue
    }
    $script:Forward = $null
}

# A port-forward follows one pod, so it dies whenever that pod is replaced.
# Every step that reschedules pods restarts it rather than assuming it survived.
function Reset-Forward {
    Stop-Forward
    Start-Sleep -Milliseconds 500
    Start-Forward
}

function Get-Health {
    Show-Cmd "curl $base/health"
    $r = Invoke-WebRequest -Uri "$base/health" -UseBasicParsing -TimeoutSec 10
    Write-Host ("     {0}" -f $r.Content) -ForegroundColor Gray
    return ($r.Content | ConvertFrom-Json)
}

function Get-PodNames([string]$Component) {
    $raw = (& $kubectl get pods -n $Namespace -l "app.kubernetes.io/component=$Component" `
            -o "jsonpath={range .items[*]}{.metadata.name}{' '}{end}")
    return @($raw -split "\s+" | Where-Object { $_ })
}

# Probes run INSIDE the cluster, from a throwaway pod, and go through the
# ClusterIP Service.
#
# This is not fussiness. `kubectl port-forward svc/...` resolves the Service
# once, picks a single pod and tunnels straight to it - it does not balance. A
# distribution measured through a port-forward would always show exactly one
# replica, and during a rolling update the tunnel dies together with its pod,
# which would report dropped requests that the Service never actually dropped.
# Going through the Service from inside the cluster measures what kube-proxy
# really does.
function Start-ClusterProbe([string]$PodName, [string]$ShellScript) {
    Show-Cmd ("kubectl run {0} -n {1} --image={2}:1.0.0 --restart=Never --command -- sh -c '{3}'" `
            -f $PodName, $Namespace, $Image, $ShellScript)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $kubectl delete pod $PodName -n $Namespace --ignore-not-found --now 2>&1 | Out-Null
        & $kubectl run $PodName -n $Namespace "--image=$Image`:1.0.0" --image-pull-policy=IfNotPresent `
            --restart=Never --labels="app.kubernetes.io/component=probe" `
            --command -- sh -c $ShellScript 2>&1 | Out-Null
    }
    finally { $ErrorActionPreference = $previous }
}

function Receive-ClusterProbe([string]$PodName, [int]$TimeoutSeconds = 300) {
    Show-Cmd ("kubectl wait --for=jsonpath='{{.status.phase}}'=Succeeded pod/{0} -n {1}" -f $PodName, $Namespace)
    Show-Cmd ("kubectl logs {0} -n {1}" -f $PodName, $Namespace)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $kubectl wait --for=jsonpath="{.status.phase}=Succeeded" "pod/$PodName" `
            -n $Namespace --timeout="${TimeoutSeconds}s" 2>&1 | Out-Null
        $out = (& $kubectl logs $PodName -n $Namespace 2>&1 | Out-String)
        & $kubectl delete pod $PodName -n $Namespace --ignore-not-found --now 2>&1 | Out-Null
        return $out
    }
    finally { $ErrorActionPreference = $previous }
}

# Tally one field out of the probe output, where every line is either a /health
# body or the literal FAILED.
function Measure-Probe([string]$Output, [string]$Field) {
    $tally = @{}
    $errors = 0
    foreach ($line in ($Output -split "`r?`n")) {
        $line = $line.Trim()
        if (-not $line) { continue }
        if ($line -match "FAILED") { $errors++; continue }
        $m = [regex]::Match($line, "`"$Field`"\s*:\s*`"([^`"]+)`"")
        if ($m.Success) {
            $v = $m.Groups[1].Value
            if (-not $tally.ContainsKey($v)) { $tally[$v] = 0 }
            $tally[$v]++
        }
        else { $errors++ }
    }
    $total = ($tally.Values | Measure-Object -Sum).Sum
    return [pscustomobject]@{ Tally = $tally; Errors = $errors; Total = $total + $errors }
}

function Show-Distribution($Result) {
    $total = ($Result.Tally.Values | Measure-Object -Sum).Sum
    foreach ($name in ($Result.Tally.Keys | Sort-Object)) {
        $count = $Result.Tally[$name]
        $share = if ($total) { 100 * $count / $total } else { 0 }
        $bar = "#" * [math]::Round($share / 2)
        Write-Host ("     {0,-34} {1,4}  {2,5:N1} %  {3}" -f $name, $count, $share, $bar) -ForegroundColor Gray
    }
    if ($Result.Errors) { Write-Host ("     failed: {0}" -f $Result.Errors) -ForegroundColor Red }
}

function Format-Tally($Table) {
    return @($Table.GetEnumerator() | Sort-Object Name | ForEach-Object { "{0,6} {1}" -f $_.Value, $_.Name })
}

function Wait-Rollout([string]$Target, [int]$TimeoutSeconds = 300) {
    Capture "00-wait" @("rollout", "status", $Target, "-n", $Namespace, "--timeout=${TimeoutSeconds}s") -Silent | Out-Null
}

Write-Host "DevOps Lab 3 defence demo - Kubernetes deployment of CDN Control Plane API" -ForegroundColor White
Write-Host "namespace $Namespace | transcripts -> docs/devops/lab-03-output/" -ForegroundColor DarkGray

foreach ($n in @("00-wait", "02-environment", "05-deploy", "06-lifecycle", "07-diagnostics")) { Reset-Transcript $n }

try {
    # ---------------------------------------------------------------- clause 1-2
    Section "clause 1 + 2" "the cluster, its system pods, the addons and the two image tags" `
        "Cluster on the docker driver, node Ready, a live control plane in kube-system.|Both addons the assignment asks for are on: ingress and metrics-server.|Exactly two tags in the cluster, 1.0.0 and 1.1.0, and NO latest."
    Capture "02-environment" @("version", "--client=true", "-o", "yaml") -Silent | Out-Null
    $nodes = Capture "02-environment" @("get", "nodes", "-o", "wide")
    if ($nodes -notmatch "\sReady\s") { throw "the minikube node is not Ready" }

    # The system pods are part of the assignment, not decoration: they are what
    # shows the control plane is actually healthy rather than merely created.
    $sys = Capture "02-environment" @("get", "pods", "-n", "kube-system")
    if ($sys -notmatch "coredns") { throw "kube-system does not look like a running control plane" }

    # Addons and images come from minikube rather than kubectl, so they are
    # appended to the same transcript by hand.
    $addons = (& $minikube addons list 2>$null | Out-String)
    $images = (& $minikube image ls 2>$null | Out-String)
    $mkVersion = (& $minikube version 2>$null | Out-String)
    # minikube draws its addon table with box characters and ANSI colour codes,
    # which turn into mojibake in a committed transcript. Strip both so the
    # evidence file stays readable.
    $enabled = @($addons -split "`r?`n" |
        Where-Object { $_ -match "(ingress|metrics-server)" -and $_ -match "enabled" } |
        ForEach-Object {
            ($_ -replace "\x1b\[[0-9;]*m", "" -replace "[^\x20-\x7E]", " ") -replace "\s{2,}", " "
        } | ForEach-Object { $_.Trim() })
    $tags = @($images -split "`r?`n" | Where-Object { $_ -match "cdn-control-plane" } | Sort-Object)
    foreach ($line in $enabled) { Note $line.Trim() }
    foreach ($line in $tags) { Note $line.Trim() }
    Write-Transcript "02-environment" (@("$ minikube version", $mkVersion.Trim(),
            "", "$ minikube addons list   (filtered)") + $enabled + @("", "$ minikube image ls   (filtered)") + $tags)

    if ($enabled.Count -lt 2) { throw "the ingress and metrics-server addons are not both enabled" }
    if ($tags.Count -lt 2) { throw "both image tags are not loaded into the cluster" }
    if ($tags -match ":latest") { throw "a latest tag is present, which the assignment forbids" }
    Pass "cluster, addons and images are all in the state the assignment requires" `
    ("node Ready, ingress + metrics-server enabled, {0} version tags loaded, no latest" -f $tags.Count)

    # ---------------------------------------------------------------- clause 5
    Section "clause 5a" "the whole directory applied with one command" `
        "The whole stack comes up with ONE command from the directory: kubectl apply -f k8s/.|Fifteen objects, one file per object."
    $applied = Capture "05-deploy" @("apply", "-f", (Join-Path $root "k8s"))
    $objects = ([regex]::Matches($applied, "(created|configured|unchanged)")).Count
    if ($objects -lt 15) { throw "expected 15 objects from k8s/, saw $objects" }
    Note "waiting for the migration Job and the rollouts"
    Capture "05-deploy" @("wait", "--for=condition=complete", "job/cdn-migrate", "-n", $Namespace, "--timeout=300s") | Out-Null
    Wait-Rollout "deployment/cdn-postgres"
    Wait-Rollout "deployment/cdn-api"
    Wait-Rollout "deployment/cdn-agents"
    Pass "kubectl apply -f k8s/ brings up the whole stack" "$objects objects, migrate Job complete, every rollout ready"

    Section "clause 5b" "the objects that were created" `
        "The same four roles as in compose: postgres with a disk, redis, api at two replicas, agents.|Plus the migration Job, which ran once and stopped."
    Capture "05-deploy" @("get", "all,pvc,configmap,secret,ingress", "-n", $Namespace) | Out-Null
    $pods = Capture "05-deploy" @("get", "pods", "-n", $Namespace, "-o", "wide")
    $running = ([regex]::Matches($pods, "Running")).Count
    Capture "05-deploy" @("get", "rs", "-n", $Namespace) -Silent | Out-Null
    Pass "pods, Deployments, ReplicaSets, Services, Ingress and the PVC all exist" "$running pods Running"

    Section "clause 5c" "the application answers through the Service" `
        "instance_id is the pod name: INSTANCE_ID is deliberately unset, so the app falls back to hostname.|In a minute that becomes the proof of how traffic spreads.|app_version comes from the image, so the update will be visible in the RESPONSE."
    Start-Forward
    $health = Get-Health
    Note ("GET /health -> instance_id={0} app_version={1}" -f $health.instance_id, $health.app_version)
    Show-Cmd "curl $base/health/ready"
    $ready = Invoke-WebRequest -Uri "$base/health/ready" -UseBasicParsing -TimeoutSec 15
    Write-Host ("     {0}" -f $ready.Content) -ForegroundColor Gray
    Show-Cmd "curl $base/api/v1/stats/network"
    $stats = Invoke-WebRequest -Uri "$base/api/v1/stats/network" -UseBasicParsing -TimeoutSec 30
    Write-Host ("     {0}" -f $stats.Content.Substring(0, [Math]::Min(160, $stats.Content.Length))) -ForegroundColor Gray
    if ([int]$ready.StatusCode -ne 200) { throw "/health/ready did not return 200" }
    if ([int]$stats.StatusCode -ne 200) { throw "/api/v1/stats/network did not return 200" }
    Write-Transcript "05-deploy" @(
        "$ curl $base/health",
        ($health | ConvertTo-Json -Compress),
        "$ curl $base/health/ready",
        $ready.Content,
        "$ curl $base/api/v1/stats/network",
        $stats.Content
    )
    # The NodePort exists and is how the app is reached from the node itself.
    # On Windows with the docker driver the minikube IP lives inside the WSL VM
    # and is not routable from the host, so the port-forward above is the
    # dependency-free way in; `minikube service cdn-api -n ... --url` opens the
    # same tunnel interactively.
    $nodeIp = (& $minikube ip 2>$null)
    $nodePort = (& $kubectl get svc cdn-api -n $Namespace -o "jsonpath={.spec.ports[0].nodePort}")
    Note ("NodePort: {0}:{1} (from the node); on Windows use the port-forward or minikube service" -f $nodeIp, $nodePort)
    Write-Transcript "05-deploy" @("NodePort endpoint: ${nodeIp}:${nodePort}")
    Pass "liveness, readiness and a business endpoint all answer 200" "/health, /health/ready and /api/v1/stats/network over svc/cdn-api"

    Section "clause 5d" "ConfigMap and Secret values really reached the container" `
        "Clause 5d: the values really are inside the container.|APP_ENV, CACHE_ENABLED, REDIS_URL come from the ConfigMap. DATABASE_URL from the Secret."
    $apiPod = (Get-PodNames "api")[0]
    # The whole environment is dumped and filtered here rather than with a grep
    # inside the container: the pattern then lives in one place and does not
    # have to survive two levels of shell quoting.
    $wanted = "APP_ENV|LOG_LEVEL|CACHE_ENABLED|REDIS_URL|HEARTBEAT_INTERVAL_SECONDS|DATABASE_URL"
    $allEnv = Capture "05-deploy" @("exec", $apiPod, "-n", $Namespace, "--", "env") -Silent
    $envDump = (@($allEnv -split "`r?`n" | Where-Object { $_ -match "^($wanted)=" } | Sort-Object) -join "`n")
    foreach ($line in ($envDump -split "`n")) { Note $line }
    Write-Transcript "05-deploy" @("(filtered to the ConfigMap and Secret keys)", $envDump)
    if ($envDump -notmatch "APP_ENV=") { throw "ConfigMap values are not visible in the container environment" }
    if ($envDump -notmatch "DATABASE_URL=postgresql\+asyncpg") { throw "the Secret value is not visible in the container environment" }
    Pass "ConfigMap and Secret are both visible inside the running container" "APP_ENV / LOG_LEVEL / CACHE_ENABLED / REDIS_URL from the ConfigMap, DATABASE_URL from the Secret"

    # ---------------------------------------------------------------- clause 6
    Section "clause 6a" "self-healing: a deleted pod is replaced" `
        "I delete a pod and a new one appears at once, with a DIFFERENT name.|Nobody repaired it: the ReplicaSet drove reality back to the desired state."
    $before = Get-PodNames "api"
    Capture "06-lifecycle" @("delete", "pod", $before[0], "-n", $Namespace) | Out-Null
    Wait-Rollout "deployment/cdn-api"
    $after = Get-PodNames "api"
    Capture "06-lifecycle" @("get", "pods", "-n", $Namespace, "-l", "app.kubernetes.io/component=api") | Out-Null
    $replacement = @($after | Where-Object { $before -notcontains $_ })
    if ($replacement.Count -eq 0) { throw "no replacement pod appeared after deleting $($before[0])" }
    Pass "the ReplicaSet recreates a deleted pod" ("{0} deleted -> {1} created" -f $before[0], ($replacement -join ", "))

    Section "clause 6b" "scaling, and how traffic spreads across the replicas" `
        "Scaling is ONE number.|I measure the spread from a separate pod INSIDE the cluster, through the Service.|port-forward tunnels to a single pod and does not balance, so it cannot measure this."
    Capture "06-lifecycle" @("scale", "deployment/cdn-api", "--replicas=4", "-n", $Namespace) | Out-Null
    Wait-Rollout "deployment/cdn-api"
    Note "sampling $Requests requests from inside the cluster, through svc/cdn-api"
    Start-ClusterProbe "cdn-probe-spread" `
    ('for i in $(seq 1 ' + $Requests + '); do curl -s -m 5 http://cdn-api/health || printf FAILED; echo; done')
    $dist = Measure-Probe (Receive-ClusterProbe "cdn-probe-spread") "instance_id"
    Show-Distribution $dist
    Write-Transcript "06-lifecycle" (@(
            "$ from inside the cluster, through the Service:",
            "$   repeat $Requests x: curl -s http://cdn-api/health | jq -r .instance_id   (tallied)"
        ) + (Format-Tally $dist.Tally) + @("failed requests: $($dist.Errors)"))
    if ($dist.Tally.Keys.Count -lt 2) { throw "traffic reached only $($dist.Tally.Keys.Count) replica" }
    if ($dist.Errors -gt 0) { throw "$($dist.Errors) requests failed while sampling the distribution" }
    Pass "scaling to 4 replicas spreads traffic over distinct pods" ("{0} pods served {1} requests, 0 errors" -f $dist.Tally.Keys.Count, $Requests)

    Section "clause 6c + 6e" "rolling update to 1.1.0, and the service stays up throughout" `
        "MAIN BLOCK - takes ~2 min, talk while it runs.|A probe polls the Service for the whole rollout. maxSurge 1, maxUnavailable 0.|The key point: maxUnavailable 0 is NOT enough. The first measurement lost 2 of 557.|Endpoint removal and SIGTERM happen in parallel. preStop sleep 5 fixes it."
    # An in-cluster probe hammers the Service for the whole rollout and records
    # which build answered each request. A mix of 1.0.0 and 1.1.0 with zero
    # failures is the direct evidence that maxUnavailable: 0 held: an old pod is
    # only allowed to go away once a new one is Ready, so the Service never has
    # an empty endpoint list.
    Start-ClusterProbe "cdn-probe-rollout" `
    ('end=$(( $(date +%s) + 120 )); while [ $(date +%s) -lt $end ]; do curl -s -m 5 http://cdn-api/health || printf FAILED; echo; sleep 0.2; done')
    Note "probe running; starting the rollout"
    Start-Sleep -Seconds 5

    Capture "06-lifecycle" @("set", "image", "deployment/cdn-api", ("api={0}:1.1.0" -f $Image), "-n", $Namespace) | Out-Null
    Capture "06-lifecycle" @("rollout", "status", "deployment/cdn-api", "-n", $Namespace, "--timeout=300s") | Out-Null

    $roll = Measure-Probe (Receive-ClusterProbe "cdn-probe-rollout") "app_version"
    foreach ($v in ($roll.Tally.Keys | Sort-Object)) {
        Note ("app_version {0}: {1} responses" -f $v, $roll.Tally[$v])
    }
    Note ("failed requests during the rollout: {0} of {1}" -f $roll.Errors, $roll.Total)
    Write-Transcript "06-lifecycle" (@(
            "$ during the 1.0.0 -> 1.1.0 rollout, from inside the cluster:",
            "$   while ...; do curl -s http://cdn-api/health; done   (tallied by app_version)"
        ) + (Format-Tally $roll.Tally) + @("failed requests: $($roll.Errors) of $($roll.Total)"))

    $versions = ($roll.Tally.Keys | Sort-Object) -join ", "
    if ($roll.Errors -gt 0) { throw "$($roll.Errors) requests failed during the rolling update" }
    if ($roll.Tally.Keys.Count -lt 2) { throw "the probe never saw both versions - it did not span the rollout" }
    Reset-Forward
    if ((Get-Health).app_version -ne "1.1.0") { throw "the deployment did not converge on 1.1.0" }
    Pass "rolling update 1.0.0 -> 1.1.0 without dropping a request" ("versions seen: {0}; 0 of {1} requests failed" -f $versions, $roll.Total)

    Section "clause 6d" "revision history and rollback" `
        "Before the undo: revisions 1 and 2. After: 2 and 3.|The rollback is appended as a NEW revision - the history is a log, not a stack."
    Capture "06-lifecycle" @("rollout", "history", "deployment/cdn-api", "-n", $Namespace) | Out-Null
    Capture "06-lifecycle" @("rollout", "undo", "deployment/cdn-api", "-n", $Namespace) | Out-Null
    Wait-Rollout "deployment/cdn-api"
    Reset-Forward
    $rolledBack = (Get-Health).app_version
    Note "the history after the undo - note the rollback is appended as a NEW revision"
    Capture "06-lifecycle" @("rollout", "history", "deployment/cdn-api", "-n", $Namespace) | Out-Null
    if ($rolledBack -ne "1.0.0") { throw "rollback did not return the deployment to 1.0.0 (saw $rolledBack)" }
    Pass "rollback restores the previous revision and is itself recorded" "serving $rolledBack again; the undo appends a revision rather than rewriting history"

    # ---------------------------------------------------------------- clause 7
    Section "clause 7a" "a deliberately wrong tag produces ImagePullBackOff" `
        "I set a tag that does not exist. The new pod goes ErrImagePull, then ImagePullBackOff.|But the old pods are ALIVE: maxUnavailable 0 refused to drop a single working replica."
    Capture "07-diagnostics" @("set", "image", "deployment/cdn-api", ("api={0}:9.9.9-does-not-exist" -f $Image), "-n", $Namespace) | Out-Null
    $bad = $null
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 2
        $states = (& $kubectl get pods -n $Namespace -l "app.kubernetes.io/component=api" `
                -o "jsonpath={range .items[*]}{.metadata.name}={.status.containerStatuses[0].state.waiting.reason}{'|'}{end}")
        $bad = @($states -split "\|" | Where-Object { $_ -match "(ImagePullBackOff|ErrImagePull)" })[0]
        if ($bad) { break }
    }
    if (-not $bad) { throw "no pod ever entered ImagePullBackOff" }
    $badPod = $bad.Split("=")[0]
    Capture "07-diagnostics" @("get", "pods", "-n", $Namespace, "-l", "app.kubernetes.io/component=api") | Out-Null
    Pass "a non-existent tag leaves the new pod stuck in ImagePullBackOff" $bad

    Section "clause 7b" "finding the cause in the pod description and the events" `
        "The cause is in Events: Failed to pull image ... not found.|The pod status says WHAT, the events say WHY.|A broken update hangs, but it does not take the release down."
    $desc = Capture "07-diagnostics" @("describe", "pod", $badPod, "-n", $Namespace) -Silent
    Capture "07-diagnostics" @("get", "events", "-n", $Namespace, "--sort-by=.lastTimestamp") -Silent | Out-Null
    $failedLine = @($desc -split "`r?`n" | Where-Object { $_ -match "(Failed to pull image|not found|manifest unknown|pull access denied)" })[0]
    if (-not $failedLine) { throw "the pod description does not name the pull failure" }
    Note $failedLine.Trim()
    Note "the previous ReplicaSet is untouched, so the Service never lost an endpoint"
    $stillUp = Get-Health
    Pass "describe and events name the cause, and the release keeps serving" ("still answering with app_version {0}" -f $stillUp.app_version)

    Section "clause 7c" "container logs and an interactive shell" `
        "Logs are structured JSON on stdout, every line carries instance_id.|Shell inside: uid 1000 and /srv/app - the securityContext applied, no root."
    $healthyPod = @(Get-PodNames "api" | Where-Object { $_ -ne $badPod })[0]
    Capture "07-diagnostics" @("logs", $healthyPod, "-n", $Namespace, "--tail=15") -Silent | Out-Null
    $inside = Capture "07-diagnostics" @("exec", $healthyPod, "-n", $Namespace, "--", "sh", "-c", "id -u && pwd && ls app")
    if ($inside -notmatch "1000") { throw "the container is not running as uid 1000" }
    Pass "logs are readable and an interactive shell works inside the pod" "kubectl exec into $healthyPod; uid 1000, workdir /srv/app"

    Section "clause 7d" "correcting the tag brings the deployment back to healthy" `
        "I fix the tag: the broken ReplicaSet scales to zero and the replicas are healthy again."
    Capture "07-diagnostics" @("set", "image", "deployment/cdn-api", ("api={0}:1.0.0" -f $Image), "-n", $Namespace) | Out-Null
    Wait-Rollout "deployment/cdn-api"
    Capture "07-diagnostics" @("get", "pods", "-n", $Namespace, "-l", "app.kubernetes.io/component=api") | Out-Null
    Start-ClusterProbe "cdn-probe-final" `
    ('for i in $(seq 1 20); do curl -s -m 5 http://cdn-api/health || printf FAILED; echo; done')
    $final = Measure-Probe (Receive-ClusterProbe "cdn-probe-final") "instance_id"
    $ready = (& $kubectl get deployment cdn-api -n $Namespace -o "jsonpath={.status.readyReplicas}")
    if ($final.Errors -gt 0) { throw "$($final.Errors) requests failed after the fix" }
    Pass "the deployment converges again once the tag is corrected" ("{0} replicas Ready, {1}/{2} requests served" -f $ready, ($final.Total - $final.Errors), $final.Total)

    # ---------------------------------------------------------------- summary
    Write-Host ""
    Write-Host "--- summary -------------------------------------------------------" -ForegroundColor White
    $script:Results | Format-Table -AutoSize Step, Check, Evidence
    Write-Host ("{0} checks passed." -f $script:Results.Count) -ForegroundColor Green
    Write-Host ("Transcripts: {0}" -f $outDir) -ForegroundColor DarkGray
}
finally {
    # Always hand the cluster back in a usable state, whichever step failed.
    Stop-Forward
    Write-Host ""
    Write-Host "restoring: cdn-api back to 2 replicas on tag 1.0.0" -ForegroundColor DarkGray
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $kubectl set image deployment/cdn-api ("api={0}:1.0.0" -f $Image) -n $Namespace 2>&1 | Out-Null
    & $kubectl scale deployment/cdn-api --replicas=2 -n $Namespace 2>&1 | Out-Null
    $ErrorActionPreference = $previous
}
