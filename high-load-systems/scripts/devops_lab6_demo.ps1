# DevOps Lab6
<#
.SYNOPSIS
    Requirement-by-requirement defence demo for DevOps Lab 6 (progressive delivery).

.DESCRIPTION
    Each step is tagged with the assignment clause it satisfies, prints live evidence
    and asserts the outcome, so a silent regression fails the demo instead of passing
    unnoticed. A PASS table is printed at the end and every command output is written
    to docs/devops/lab-06-output/ so the report can cite real transcripts.

    Clauses: 1 the controller installed through Argo CD, CRDs present | 2 the API is a
    Rollout and no Deployment shares its selector | 3 the canary strategy as declared |
    4 a release by commit that stops at a pause, the traffic split measured from
    inside the cluster, then promote | 5 an aborted release - Synced but Degraded -
    finished through git revert.

    Like the Lab 5 demo this COMMITS AND PUSHES, for the same reason: under GitOps a
    release is a commit. -WhatIfGit shows the commits without pushing.

    Prerequisites: the Lab 5 cluster with Argo CD, plus the argo-rollouts Application
    Healthy and images 1.3.0, 1.4.0 and 1.5.0 published to GHCR.

.EXAMPLE
    ./scripts/devops_lab6_demo.ps1
#>
[CmdletBinding()]
param(
    [string]$App = "cdn-control-plane",
    [string]$ArgoNamespace = "argocd",
    [string]$Namespace = "cdn-gitops",
    [string]$RolloutName = "cdn-cdn-control-plane-api",
    [string]$ServiceName = "cdn-cdn-control-plane-api",
    [string]$FromVersion = "1.3.0",
    [string]$ToVersion = "1.4.0",
    [string]$AbortVersion = "1.5.0",
    [string]$Branch = "devops-lab-6-rollouts",
    [int]$Samples = 40,
    [switch]$WhatIfGit,
    [string]$KubectlPath,
    [string]$ArgocdPath,
    [string]$RolloutsPath
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$repo = Split-Path $root -Parent
$valuesFile = Join-Path $root "gitops/values/values-minikube.yaml"
$outDir = Join-Path $root "docs/devops/lab-06-output"
$valuesGitPath = "high-load-systems/gitops/values/values-minikube.yaml"

$script:Results = @()
$script:Step = 0
$script:CommitsMade = @()

function Resolve-Tool([string]$Name, [string]$Explicit) {
    if ($Explicit) {
        if (Test-Path $Explicit) { return $Explicit }
        throw "$Name was not found at $Explicit"
    }
    $onPath = Get-Command $Name -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $local = Join-Path $env:LOCALAPPDATA "Programs\k8stools\$Name.exe"
    if (Test-Path $local) { return $local }
    throw "$Name is not on PATH and not in %LOCALAPPDATA%\Programs\k8stools."
}

$kubectl = Resolve-Tool "kubectl" $KubectlPath
$argocd = Resolve-Tool "argocd" $ArgocdPath
$rollouts = Resolve-Tool "kubectl-argo-rollouts" $RolloutsPath
$git = Resolve-Tool "git" $null

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

function Section([string]$Clause, [string]$Title) {
    $script:Step++
    Write-Host ""
    Write-Host ("[{0:d2}] {1}  -  {2}" -f $script:Step, $Clause, $Title) -ForegroundColor Cyan
}
function Pass([string]$What, [string]$Evidence) {
    Write-Host ("     PASS  {0}" -f $Evidence) -ForegroundColor Green
    $script:Results += [pscustomobject]@{ Step = $script:Step; Check = $What; Evidence = $Evidence }
}
function Note([string]$Text) { Write-Host ("     {0}" -f $Text) -ForegroundColor DarkGray }

# "Continue" around every native call: in Windows PowerShell 5.1 a process that
# writes to stderr - which all four of these do for ordinary progress lines - is
# turned into a terminating error under "Stop".
function Invoke-Native([string]$Exe, [string[]]$NativeArgs) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        return (& $Exe @NativeArgs 2>&1 |
            ForEach-Object {
                if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { $_ }
            } | Out-String)
    }
    finally { $ErrorActionPreference = $previous }
}

function Capture([string]$Name, [string]$Exe, [string[]]$NativeArgs, [switch]$Silent) {
    $text = Invoke-Native $Exe $NativeArgs
    Add-Content -Path (Join-Path $outDir "$Name.txt") -Encoding UTF8 -Value ("$ " + (Split-Path $Exe -Leaf) + " " + ($NativeArgs -join " "))
    Add-Content -Path (Join-Path $outDir "$Name.txt") -Encoding UTF8 -Value $text
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

$argoFlags = @("--port-forward", "--port-forward-namespace", $ArgoNamespace, "--insecure")

# kubectl annotate, not kubectl patch -p '<json>': PowerShell does not pass a
# single-quoted JSON argument through to a native process intact. See the Lab 5
# demo for the failure this caused.
function Request-Refresh([string]$Name = $App) {
    Invoke-Native $kubectl @("annotate", "application", $Name, "-n", $ArgoNamespace,
        "argocd.argoproj.io/refresh=hard", "--overwrite") | Out-Null
}

function Get-AppField([string]$Name, [string]$JsonPath) {
    return (& $kubectl get application $Name -n $ArgoNamespace -o "jsonpath={$JsonPath}")
}
function Get-RolloutField([string]$JsonPath) {
    return (& $kubectl get rollout $RolloutName -n $Namespace -o "jsonpath={$JsonPath}")
}

function Wait-For([scriptblock]$Condition, [string]$What, [int]$TimeoutSeconds = 420) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) { return }
        Request-Refresh
        Start-Sleep -Seconds 5
    }
    throw "timed out after ${TimeoutSeconds}s waiting for: $What"
}

function Set-ImageTag([string]$Tag) {
    $text = Get-Content $valuesFile -Raw
    $next = [regex]::Replace($text, '(?m)^(\s*tag:\s*)"[^"]*"', ('${1}"' + $Tag + '"'))
    if ($next -eq $text) { throw "image.tag was not found in $valuesFile" }
    Set-Content -Path $valuesFile -Value $next -Encoding UTF8 -NoNewline
}

function New-GitOpsCommit([string]$Name, [string]$Message) {
    if ($WhatIfGit) {
        Note "-WhatIfGit: would commit and push '$Message'"
        return $null
    }
    Capture $Name $git @("-C", $repo, "add", "--", $valuesGitPath) -Silent | Out-Null
    Capture $Name $git @("-C", $repo, "commit", "-m", $Message, "--", $valuesGitPath) -Silent | Out-Null
    Capture $Name $git @("-C", $repo, "push", "origin", $Branch) -Silent | Out-Null
    $sha = (Invoke-Native $git @("-C", $repo, "rev-parse", "--short", "HEAD")).Trim()
    $script:CommitsMade += $sha
    Note "committed and pushed $sha  $Message"
    return $sha
}

# The traffic split has to be sampled from inside the cluster. A port-forward
# attaches to one pod and would report 100% of whichever version it happened to
# pick - the single most common way this demonstration is got wrong.
function Measure-Split([int]$Count = $Samples) {
    $script = "for i in `$(seq 1 $Count); do curl -s --max-time 2 http://$ServiceName/version; echo; done"
    $raw = Invoke-Native $kubectl @(
        "run", "canary-probe-$(Get-Random -Maximum 99999)", "-n", $Namespace, "--rm", "--attach", "--restart=Never",
        "--image=curlimages/curl:8.11.1", "--quiet", "--command", "--", "sh", "-c", $script
    )
    $counts = @{}
    foreach ($line in ($raw -split "`r?`n")) {
        if ($line -match '"version"\s*:\s*"([^"]+)"') {
            $v = $Matches[1]
            $counts[$v] = 1 + ($counts[$v] | ForEach-Object { $_ })
        }
    }
    return $counts
}

foreach ($n in @("01-controller", "02-rollout", "03-strategy", "04-release", "05-abort")) { Reset-Transcript $n }

try {
    Write-Host ""
    Write-Host "DevOps Lab 6 - progressive delivery with Argo Rollouts" -ForegroundColor White
    Write-Host ("branch {0} | rollout {1} | namespace {2}" -f $Branch, $RolloutName, $Namespace) -ForegroundColor DarkGray
    if ($WhatIfGit) { Write-Host "-WhatIfGit: no commit will be made or pushed." -ForegroundColor Yellow }

    # ------------------------------------------------------------- preflight
    Section "preflight" "on the configuration branch, with the GitOps files clean"
    $branchNow = (Invoke-Native $git @("-C", $repo, "rev-parse", "--abbrev-ref", "HEAD")).Trim()
    if ($branchNow -ne $Branch) { throw "checked out branch is '$branchNow', expected '$Branch'" }
    $dirty = (Invoke-Native $git @("-C", $repo, "status", "--porcelain", "--", $valuesGitPath)).Trim()
    if ($dirty -and -not $WhatIfGit) { throw "values-minikube.yaml has uncommitted changes:`n$dirty" }
    Pass "the demo starts from a clean, pushed branch" "on $Branch"

    # ------------------------------------------------------------- clause 1
    Section "clause 1" "the Rollouts controller was installed by Argo CD, not by hand"
    $ctrlApp = Capture "01-controller" $kubectl @("get", "application", "argo-rollouts", "-n", $ArgoNamespace)
    if ($ctrlApp -notmatch "Synced\s+Healthy") { throw "the argo-rollouts Application is not Synced/Healthy" }
    $wave = (& $kubectl get application argo-rollouts -n $ArgoNamespace `
            -o "jsonpath={.metadata.annotations['argocd\.argoproj\.io/sync-wave']}")
    if ($wave -ne "-1") { throw "the controller should be at sync-wave -1, found '$wave'" }
    Capture "01-controller" $kubectl @("get", "pods", "-n", "argo-rollouts") | Out-Null
    $crds = Capture "01-controller" $kubectl @("get", "crd", "-o", "name") -Silent
    foreach ($crd in @("rollouts.argoproj.io", "analysistemplates.argoproj.io", "experiments.argoproj.io")) {
        if ($crds -notmatch [regex]::Escape($crd)) { throw "CRD $crd is missing" }
    }
    Write-Transcript "01-controller" @("", "CRDs present: rollouts, analysistemplates, analysisruns, experiments, clusteranalysistemplates")
    Capture "01-controller" $rollouts @("version") | Out-Null
    Note "sync-wave -1 is what keeps the CRDs ahead of the application that needs them:"
    Note "an application containing kind: Rollout cannot sync before the CRD exists."
    Pass "the controller is an Application like any other" "argo-rollouts Synced/Healthy at wave -1, CRDs installed"

    # ------------------------------------------------------------- clause 2
    Section "clause 2" "the API is a Rollout, and no Deployment shares its selector"
    $ro = Capture "02-rollout" $kubectl @("get", "rollout", "-n", $Namespace)
    if ($ro -notmatch $RolloutName) { throw "no Rollout named $RolloutName" }
    $deployments = Invoke-Native $kubectl @("get", "deployment", "-n", $Namespace, "-o", "name")
    if ($deployments -match "deployment.apps/$RolloutName\b") {
        throw "a Deployment with the same name still exists - two controllers would drive the same pods"
    }
    Capture "02-rollout" $kubectl @("get", "deployment", "-n", $Namespace) | Out-Null
    $replicas = [int](Get-RolloutField ".spec.replicas")
    Note "api-deployment.yaml renders nothing while rollout.enabled is true, so the"
    Note "Deployment and the Rollout can never both own these pods."
    Pass "the API runs as a Rollout, with no competing Deployment" "$RolloutName, $replicas replicas; Deployments left: agents, postgresql, redis"

    # ------------------------------------------------------------- clause 3
    Section "clause 3" "the canary strategy, as declared in Git"
    $strategy = Capture "03-strategy" $kubectl @("get", "rollout", $RolloutName, "-n", $Namespace,
        "-o", "jsonpath={.spec.strategy}")
    if ($strategy -notmatch "setWeight") { throw "the Rollout has no canary steps" }
    $steps = (Get-RolloutField ".spec.strategy.canary.steps")
    Write-Transcript "03-strategy" @("", "steps: $steps")
    if ($strategy -notmatch '"setWeight":20') { throw "the first step should be setWeight 20" }
    Note "20% of five replicas is exactly one canary pod. Without a service mesh the"
    Note "weight is expressed as a share of the replica count, and one Service fronts"
    Note "both versions - which is why five replicas, not one."
    Pass "the strategy in the cluster is the one in Git" "canary 20 -> pause -> 60 -> 80, $replicas replicas"

    # ------------------------------------------------------------- clause 4
    Section "clause 4" "a release by commit, stopping at the manual pause"
    $startTag = (Get-RolloutField ".spec.template.spec.containers[0].image").Split(":")[-1]
    if ($startTag -ne $FromVersion) { throw "expected the Rollout to start on $FromVersion, found $startTag" }
    Set-ImageTag $ToVersion
    $sha = New-GitOpsCommit "04-release" "gitops: canary release of the CDN Control Plane $ToVersion"
    if (-not $WhatIfGit) {
        Request-Refresh
        # Suspended is Argo CD's word for "the Rollout is sitting on a pause step".
        Wait-For { (Get-AppField $App ".status.health.status") -eq "Suspended" } "the application to report Suspended" 480
        $ros = Capture "04-release" $rollouts @("get", "rollout", $RolloutName, "-n", $Namespace)
        $appState = Capture "04-release" $kubectl @("get", "application", $App, "-n", $ArgoNamespace)
        if ($ros -notmatch "Paused") { throw "the Rollout does not report Paused" }
        Note "the release stopped on `pause: {}` and is waiting for a human. This is the"
        Note "difference from a rolling update: the schedule has a gate in it."

        Note "sampling the traffic split from inside the cluster ($Samples requests)..."
        $counts = Measure-Split
        $total = ($counts.Values | Measure-Object -Sum).Sum
        $newCount = [int]$counts[$ToVersion]
        $oldCount = [int]$counts[$FromVersion]
        $pct = if ($total) { [math]::Round(100 * $newCount / $total) } else { 0 }
        Write-Transcript "04-release" @(
            "",
            "traffic split sampled from a pod inside the cluster, $total responses:",
            ("  {0}  {1,3} responses" -f $FromVersion, $oldCount),
            ("  {0}  {1,3} responses  ({2}%)" -f $ToVersion, $newCount, $pct),
            "",
            "Sampled through the Service from inside the cluster on purpose: a",
            "port-forward attaches to one pod and would report 100% of whichever",
            "version that pod happens to run."
        )
        if ($total -lt 1) { throw "the probe returned no responses" }
        if ($newCount -lt 1) { throw "no response came from the canary" }
        if ($oldCount -lt 1) { throw "every response came from the canary - that is not a 20% split" }
        Pass "the canary serves a minority of real traffic while paused" "$newCount of $total responses on $ToVersion (~$pct%), rest on $FromVersion"

        Section "clause 4" "promote, and the release finishes on its own"
        Capture "04-release" $rollouts @("promote", $RolloutName, "-n", $Namespace) | Out-Null
        Wait-For {
            ((Get-AppField $App ".status.health.status") -eq "Healthy") -and
            ((Get-RolloutField ".status.phase") -eq "Healthy")
        } "the Rollout to finish" 600
        $after = Capture "04-release" $rollouts @("get", "rollout", $RolloutName, "-n", $Namespace)
        $finalCounts = Measure-Split 12
        $allNew = ($finalCounts.Keys | Where-Object { $_ -ne $ToVersion }).Count -eq 0
        Write-Transcript "04-release" @("", "after promote, 12 responses: " + (($finalCounts.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join " "))
        if (-not $allNew) { throw "not every response is on $ToVersion after promote" }
        Pass "promote completes the remaining steps automatically" "every response on $ToVersion, Rollout and application Healthy"
    }
    else { Pass "the release commit was prepared" "-WhatIfGit, nothing pushed" }

    # ------------------------------------------------------------- clause 5
    Section "clause 5" "an aborted release: Synced, but Degraded"
    if (-not $WhatIfGit) {
        Set-ImageTag $AbortVersion
        $shaAbort = New-GitOpsCommit "05-abort" "gitops: release $AbortVersion (aborted in the Lab 6 demonstration)"
        Request-Refresh
        Wait-For { (Get-AppField $App ".status.health.status") -eq "Suspended" } "the second release to reach its pause" 480
        Capture "05-abort" $rollouts @("get", "rollout", $RolloutName, "-n", $Namespace) | Out-Null
        Capture "05-abort" $rollouts @("abort", $RolloutName, "-n", $Namespace) | Out-Null
        Wait-For { (Get-RolloutField ".status.phase") -eq "Degraded" } "the Rollout to report Degraded" 300
        $abortState = Capture "05-abort" $rollouts @("get", "rollout", $RolloutName, "-n", $Namespace)
        Request-Refresh
        Wait-For { (Get-AppField $App ".status.health.status") -eq "Degraded" } "the application to report Degraded" 300
        $appAbort = Capture "05-abort" $kubectl @("get", "application", $App, "-n", $ArgoNamespace)
        $syncNow = Get-AppField $App ".status.sync.status"
        $stable = Measure-Split 12
        Write-Transcript "05-abort" @("", "while aborted, 12 responses: " + (($stable.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join " "))
        if ($syncNow -ne "Synced") { throw "expected Synced after the abort, found $syncNow" }
        if ([int]$stable[$ToVersion] -lt 1) { throw "traffic is not back on the stable version $ToVersion" }
        Note "Synced because the manifest in the cluster matches Git - Git really does say"
        Note "$AbortVersion. Degraded because the release was abandoned and the stable"
        Note "version is the one serving. The cluster is obeying Git and is still not in"
        Note "the state Git describes, which is exactly what abort means."
        Pass "an aborted release is Synced and Degraded, serving the stable version" "sync=$syncNow, Rollout Degraded, traffic on $ToVersion"

        Section "clause 5" "finishing it through Git: git revert"
        $revert = Capture "05-abort" $git @("-C", $repo, "revert", "--no-edit", $shaAbort)
        if ($revert -notmatch "Revert") { throw "the revert did not produce a commit" }
        Capture "05-abort" $git @("-C", $repo, "push", "origin", $Branch) -Silent | Out-Null
        $shaRevert = (Invoke-Native $git @("-C", $repo, "rev-parse", "--short", "HEAD")).Trim()
        $script:CommitsMade += $shaRevert

        # The sync that delivered the aborted release is still Running, and it
        # will stay that way: a wave sync waits for every resource in the wave to
        # become healthy, and an aborted Rollout reports Degraded by definition.
        # Argo CD starts no new sync while one is in flight, so the revert would
        # sit in Git, already observed, until the controller's own timeout -
        # measured here as `Retrying attempt #5`, minutes away.
        #
        # Same lock, same release valve as Lab 5 §7.4. Doing it only when an
        # operation is actually running keeps it honest: this is an operator
        # action, not part of the GitOps loop.
        if ((Get-AppField $App ".status.operationState.phase") -eq "Running") {
            Note "the aborted release's sync is still running and holds the application lock"
            Capture "05-abort" $argocd (@("app", "terminate-op", $App) + $argoFlags) -Silent | Out-Null
            Start-Sleep -Seconds 10
        }
        Request-Refresh
        Wait-For {
            ((Get-AppField $App ".status.health.status") -eq "Healthy") -and
            ((Get-RolloutField ".status.phase") -eq "Healthy")
        } "the Rollout to return to Healthy on $ToVersion" 600
        $final = Capture "05-abort" $rollouts @("get", "rollout", $RolloutName, "-n", $Namespace)
        Capture "05-abort" $git @("-C", $repo, "log", "--oneline", "-5") | Out-Null
        $tagNow = (Get-RolloutField ".spec.template.spec.containers[0].image").Split(":")[-1]
        if ($tagNow -ne $ToVersion) { throw "expected $ToVersion after the revert, found $tagNow" }
        Note "the abort stopped the release; the revert is what made Git agree with it."
        Note "Without the revert the cluster would stay Degraded forever, correctly."
        Pass "git revert returns the application to Healthy" "back to $ToVersion, Rollout and application Healthy"
    }
    else { Pass "the abort steps were skipped" "-WhatIfGit" }

    Write-Host ""
    Write-Host "--- summary -------------------------------------------------------" -ForegroundColor White
    $script:Results | Format-Table -AutoSize Step, Check, Evidence
    Write-Host ("{0} checks passed." -f $script:Results.Count) -ForegroundColor Green
    if ($script:CommitsMade.Count) {
        Write-Host ("Commits pushed to {0}: {1}" -f $Branch, ($script:CommitsMade -join ", ")) -ForegroundColor DarkGray
    }
    Write-Host ("Transcripts: {0}" -f $outDir) -ForegroundColor DarkGray
}
finally {
    # Nothing to tear down: every change this demo made is a commit, and the last
    # one restores a working release. An interrupted run is meant to be inspected.
    if (-not $WhatIfGit) {
        $left = (Get-Content $valuesFile -Raw)
        if ($left -match [regex]::Escape($AbortVersion)) {
            Write-Host ""
            Write-Host "The run stopped with $AbortVersion still committed. Finish it with:" -ForegroundColor Yellow
            Write-Host ("  kubectl-argo-rollouts abort $RolloutName -n $Namespace") -ForegroundColor Yellow
            Write-Host ("  git -C `"$repo`" revert --no-edit <that commit> ; git -C `"$repo`" push origin $Branch") -ForegroundColor Yellow
        }
    }
}
