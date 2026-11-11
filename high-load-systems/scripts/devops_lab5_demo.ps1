# DevOps Lab5
<#
.SYNOPSIS
    Requirement-by-requirement defence demo for DevOps Lab 5 (GitOps with Argo CD).

.DESCRIPTION
    Each step is tagged with the assignment clause it satisfies, prints live evidence
    and asserts the outcome, so a silent regression fails the demo instead of passing
    unnoticed. A PASS table is printed at the end and every command output is written
    to docs/devops/lab-05-output/ so the report can cite real transcripts.

    Clauses: 3 Argo CD installed, admin password changed | 4 App of Apps, the
    application Synced/Healthy | 5 a release made by commit | 6a drift without
    selfHeal, then selfHeal returning it | 6b a nonexistent tag: Synced but
    Degraded | 6c git revert, git log and argocd app history.

    This demo COMMITS AND PUSHES to the configuration branch. That is not an
    accident of the script - it is the point of the lab. Under GitOps the only
    way to change the cluster is to change Git, so a demo that proved anything
    without touching Git would be proving the wrong thing. Every commit it makes
    is reverted or superseded by the end of the run, and -WhatIfGit shows them
    without pushing.

    Prerequisites, all created once by scripts/devops_lab5_setup.ps1:
      - minikube running, Argo CD installed in namespace argocd, admin password changed
      - the cdn-db Secret present in namespace cdn-gitops
      - the root Application applied
      - images ghcr.io/ostrrovska/cdn-control-plane:1.2.0 and :1.3.0 published

.PARAMETER FromVersion
    The image tag the cluster is expected to be on when the demo starts (default 1.2.1).

.PARAMETER ToVersion
    The image tag the demo rolls out through Git (default 1.3.0).

.PARAMETER BadVersion
    A tag that does not exist in the registry, used for the Degraded demonstration.

.EXAMPLE
    ./scripts/devops_lab5_demo.ps1
#>
[CmdletBinding()]
param(
    [string]$App = "cdn-control-plane",
    [string]$RootApp = "root",
    [string]$ArgoNamespace = "argocd",
    [string]$Namespace = "cdn-gitops",
    [string]$FromVersion = "1.2.1",
    [string]$ToVersion = "1.3.0",
    [string]$BadVersion = "0.0.0-does-not-exist",
    [string]$Branch = "devops-lab-5-gitops",
    [int]$Port = 8183,
    [switch]$WhatIfGit,
    [string]$KubectlPath,
    [string]$ArgocdPath
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$repo = Split-Path $root -Parent          # the monorepo root; git runs from here
$valuesFile = Join-Path $root "gitops/values/values-minikube.yaml"
$appFile = Join-Path $root "gitops/argocd-apps/cdn-control-plane.yaml"
$outDir = Join-Path $root "docs/devops/lab-05-output"
$base = "http://127.0.0.1:$Port"

# Paths as git wants them: repo-relative, forward slashes.
$valuesGitPath = "high-load-systems/gitops/values/values-minikube.yaml"
$appGitPath = "high-load-systems/gitops/argocd-apps/cdn-control-plane.yaml"

$script:Results = @()
$script:Step = 0
$script:Forward = $null
$script:CommitsMade = @()

# Same resolution as Lab 3 and 4: the k8s tooling lives under
# %LOCALAPPDATA%\Programs\k8stools and a shell opened before that entry was
# added to PATH will not find it. Failing here with a clear message beats
# failing fifteen steps in on an empty command output.
function Resolve-Tool([string]$Name, [string]$Explicit) {
    if ($Explicit) {
        if (Test-Path $Explicit) { return $Explicit }
        throw "$Name was not found at $Explicit"
    }
    $onPath = Get-Command $Name -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $local = Join-Path $env:LOCALAPPDATA "Programs\k8stools\$Name.exe"
    if (Test-Path $local) { return $local }
    throw "$Name is not on PATH and not in %LOCALAPPDATA%\Programs\k8stools. Open a new terminal, or pass -$Name`Path."
}

$kubectl = Resolve-Tool "kubectl" $KubectlPath
$argocd = Resolve-Tool "argocd" $ArgocdPath
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
# writes to stderr - which kubectl, argocd and git all do for ordinary progress
# lines - is turned into a terminating error under "Stop". Outcomes are asserted
# below instead, on the output and on $LASTEXITCODE.
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

function Git([string[]]$GitArgs) { return (Invoke-Native $git (@("-C", $repo) + $GitArgs)) }

# ---------------------------------------------------------------- git helpers

# One commit, one push, recorded so the summary can list exactly what this run
# wrote to the branch.
function New-GitOpsCommit([string]$Name, [string]$Path, [string]$Message) {
    if ($WhatIfGit) {
        Note "-WhatIfGit: would commit and push '$Message'"
        Capture $Name $git @("-C", $repo, "diff", "--", $Path) -Silent | Out-Null
        return $null
    }
    Capture $Name $git @("-C", $repo, "add", "--", $Path) -Silent | Out-Null
    $commit = Capture $Name $git @("-C", $repo, "commit", "-m", $Message, "--", $Path)
    if ($LASTEXITCODE -ne 0 -and $commit -notmatch "\d+ file") { throw "the commit failed: $commit" }
    Capture $Name $git @("-C", $repo, "push", "origin", $Branch) -Silent | Out-Null
    $sha = (Invoke-Native $git @("-C", $repo, "rev-parse", "--short", "HEAD")).Trim()
    $script:CommitsMade += $sha
    Note "committed and pushed $sha  $Message"
    return $sha
}

function Set-ImageTag([string]$Tag) {
    $text = Get-Content $valuesFile -Raw
    $next = [regex]::Replace($text, '(?m)^(\s*tag:\s*)"[^"]*"', ('${1}"' + $Tag + '"'))
    if ($next -eq $text) { throw "image.tag was not found in $valuesFile" }
    Set-Content -Path $valuesFile -Value $next -Encoding UTF8 -NoNewline
}

function Get-ImageTag {
    $m = [regex]::Match((Get-Content $valuesFile -Raw), '(?m)^\s*tag:\s*"([^"]*)"')
    if (-not $m.Success) { throw "image.tag was not found in $valuesFile" }
    return $m.Groups[1].Value
}

function Set-SelfHeal([bool]$Enabled) {
    $text = Get-Content $appFile -Raw
    $value = if ($Enabled) { "true" } else { "false" }
    $next = [regex]::Replace($text, '(?m)^(\s*selfHeal:\s*)(true|false)\s*$', ('${1}' + $value))
    if ($next -eq $text) { throw "selfHeal was not found in $appFile" }
    Set-Content -Path $appFile -Value $next -Encoding UTF8 -NoNewline
}

# ---------------------------------------------------------------- argo helpers

function Argo([string[]]$ArgoArgs) { return (Invoke-Native $argocd ($ArgoArgs + @("--port-forward", "--port-forward-namespace", $ArgoNamespace, "--insecure"))) }

function Get-AppField([string]$Name, [string]$JsonPath) {
    return (& $kubectl get application $Name -n $ArgoNamespace -o "jsonpath={$JsonPath}")
}

function Get-SyncStatus([string]$Name = $App) { return (Get-AppField $Name ".status.sync.status") }
function Get-HealthStatus([string]$Name = $App) { return (Get-AppField $Name ".status.health.status") }

# Argo CD polls the repository every three minutes by default. Waiting that out
# at every step would make the demo unwatchable, so each Git change is followed
# by an explicit refresh - the same thing the "Refresh" button in the UI does.
function Request-Refresh([string]$Name = $App) {
    & $kubectl patch application $Name -n $ArgoNamespace --type merge `
        -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}' | Out-Null
}

function Wait-AppState([string]$Sync, [string]$Health, [int]$TimeoutSeconds = 300, [string]$Name = $App) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastSync = ""; $lastHealth = ""
    while ((Get-Date) -lt $deadline) {
        $lastSync = Get-SyncStatus $Name
        $lastHealth = Get-HealthStatus $Name
        $syncOk = (-not $Sync) -or ($lastSync -eq $Sync)
        $healthOk = (-not $Health) -or ($lastHealth -eq $Health)
        if ($syncOk -and $healthOk) { return @{ Sync = $lastSync; Health = $lastHealth } }
        Start-Sleep -Seconds 5
    }
    throw "$Name did not reach sync=$Sync health=$Health within ${TimeoutSeconds}s (last: sync=$lastSync health=$lastHealth)"
}

# Wait for Argo CD to have observed a specific commit, so a later assertion
# cannot accidentally pass against the state from before the push.
function Wait-Revision([string]$Sha, [int]$TimeoutSeconds = 300) {
    if (-not $Sha) { return }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $revs = (Get-AppField $App ".status.sync.revisions") + (Get-AppField $App ".status.sync.revision")
        if ($revs -match $Sha) { return }
        Request-Refresh
        Start-Sleep -Seconds 5
    }
    throw "Argo CD never observed commit $Sha within ${TimeoutSeconds}s"
}

# ---------------------------------------------------------------- app helpers

function Get-ApiDeployment {
    $name = (& $kubectl get deployment -n $Namespace `
            -l "app.kubernetes.io/part-of=cdn-control-plane,app.kubernetes.io/component=api" `
            -o "jsonpath={.items[0].metadata.name}")
    if (-not $name) { throw "no api Deployment found in $Namespace" }
    return $name
}

function Get-DeployedTag {
    $image = (& $kubectl get deployment (Get-ApiDeployment) -n $Namespace `
            -o "jsonpath={.spec.template.spec.containers[0].image}")
    return $image.Split(":")[-1]
}

function Get-ApiReplicas {
    return [int](& $kubectl get deployment (Get-ApiDeployment) -n $Namespace -o "jsonpath={.spec.replicas}")
}

function Start-Forward {
    $svc = (& $kubectl get service -n $Namespace `
            -l "app.kubernetes.io/part-of=cdn-control-plane,app.kubernetes.io/component=api" `
            -o "jsonpath={.items[0].metadata.name}")
    $script:Forward = Start-Process -FilePath $kubectl -PassThru -NoNewWindow -ArgumentList @(
        "port-forward", "svc/$svc", ("{0}:80" -f $Port), "-n", $Namespace
    )
    foreach ($i in 1..60) {
        Start-Sleep -Milliseconds 500
        try {
            if ([int](Invoke-WebRequest -Uri "$base/health" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) { return }
        }
        catch { }
    }
    throw "port-forward to the api service never became reachable on $base"
}

function Stop-Forward {
    if ($script:Forward -and -not $script:Forward.HasExited) {
        Stop-Process -Id $script:Forward.Id -Force -ErrorAction SilentlyContinue
    }
    $script:Forward = $null
}

# The version the running pods actually report, which is the only answer that
# cannot be faked by editing a manifest: /version reads values baked into the
# image at build time.
function Get-ServedVersion {
    Stop-Forward; Start-Sleep -Milliseconds 500; Start-Forward
    try {
        return ((Invoke-WebRequest -Uri "$base/version" -UseBasicParsing -TimeoutSec 10).Content | ConvertFrom-Json).version
    }
    finally { Stop-Forward }
}

# ================================================================== the demo

foreach ($name in @("01-environment", "03-argocd", "04-app-of-apps", "05-release",
        "06a-drift", "06b-degraded", "06c-revert", "00-wait")) {
    Reset-Transcript $name
}

try {
    Write-Host ""
    Write-Host "DevOps Lab 5 - GitOps with Argo CD" -ForegroundColor White
    Write-Host ("repo {0} | branch {1} | app {2} | namespace {3}" -f $repo, $Branch, $App, $Namespace) -ForegroundColor DarkGray
    if ($WhatIfGit) { Write-Host "-WhatIfGit: no commit will be made or pushed." -ForegroundColor Yellow }

    # ------------------------------------------------------------ preflight
    Section "preflight" "the working tree is clean and on the configuration branch"
    $branchNow = (Invoke-Native $git @("-C", $repo, "rev-parse", "--abbrev-ref", "HEAD")).Trim()
    if ($branchNow -ne $Branch) { throw "checked out branch is '$branchNow', expected '$Branch'" }
    $dirty = (Invoke-Native $git @("-C", $repo, "status", "--porcelain", "--", $valuesGitPath, $appGitPath)).Trim()
    if ($dirty -and -not $WhatIfGit) { throw "the GitOps files have uncommitted changes; commit or restore them first:`n$dirty" }
    Capture "01-environment" $git @("-C", $repo, "log", "--oneline", "-3") | Out-Null
    Pass "the demo starts from a clean, pushed branch" "on $Branch, no pending edits to the GitOps files"

    # ------------------------------------------------------------ clause 3
    Section "clause 3" "Argo CD is installed in its own namespace, and the CLI talks to it"
    $argoVersion = Capture "03-argocd" $argocd @("version", "--client", "--short")
    $argoPods = Capture "03-argocd" $kubectl @("get", "pods", "-n", $ArgoNamespace, "-o", "wide")
    if ($argoPods -notmatch "argocd-server") { throw "no argocd-server pod in namespace $ArgoNamespace" }
    if ($argoPods -match "0/1|Pending|CrashLoop") { throw "not every Argo CD pod is ready" }
    Note "Argo CD runs entirely inside the cluster; the CLI and the UI are both clients of"
    Note "the same API server, and the Applications below are ordinary Kubernetes objects."
    Pass "Argo CD is installed and healthy in namespace $ArgoNamespace" (($argoVersion -split "`r?`n")[0])

    Section "clause 3" "the initial admin password has been changed"
    # The installer writes the generated password into this Secret and the
    # documented first step is to change the password and delete it. Its absence
    # is the evidence - a password that has been changed leaves nothing behind
    # that could be printed here, which is the point.
    $initialSecret = Invoke-Native $kubectl @("get", "secret", "argocd-initial-admin-secret", "-n", $ArgoNamespace)
    $changed = $initialSecret -match "NotFound|not found"
    Write-Transcript "03-argocd" @(
        "$ kubectl get secret argocd-initial-admin-secret -n $ArgoNamespace",
        $initialSecret.Trim(),
        "",
        "argocd-initial-admin-secret holds the password generated by the installer.",
        "`argocd account update-password` does not delete it, so it is removed explicitly",
        "after the change; its absence is what proves the default is no longer in use."
    )
    if (-not $changed) {
        throw "argocd-initial-admin-secret still exists - change the admin password and delete it (see scripts/devops_lab5_setup.ps1)"
    }
    $whoami = Capture "03-argocd" $argocd @("account", "get-user-info", "--port-forward", "--port-forward-namespace", $ArgoNamespace, "--insecure")
    if ($whoami -notmatch "Logged In: true") { throw "the argocd CLI is not logged in" }
    Pass "the initial admin password is no longer in use" "argocd-initial-admin-secret deleted; CLI logged in as admin"

    # ------------------------------------------------------------ clause 4
    Section "clause 4" "App of Apps: one object applied by hand, the rest created from Git"
    $rootSrc = Capture "04-app-of-apps" $kubectl @("get", "application", $RootApp, "-n", $ArgoNamespace,
        "-o", "jsonpath={.spec.source.path}{'\n'}{.spec.source.repoURL}{'\n'}{.spec.source.targetRevision}")
    if ($rootSrc -notmatch "gitops/argocd-apps") { throw "the root Application does not watch gitops/argocd-apps" }
    $apps = Capture "04-app-of-apps" $kubectl @("get", "applications", "-n", $ArgoNamespace)
    if ($apps -notmatch $App) { throw "$App was not created by the root Application" }
    Note "$App exists because the root Application found its manifest in Git - nothing"
    Note "applied it. Deleting that manifest from Git would remove the application too."
    Pass "the application is created by the root Application, not by hand" "root watches gitops/argocd-apps; $App present"

    Section "clause 4" "the application is Synced and Healthy, and its object tree is visible"
    Request-Refresh
    $state = Wait-AppState "Synced" "Healthy" 420
    $tree = Capture "04-app-of-apps" $argocd @("app", "resources", $App, "--port-forward", "--port-forward-namespace", $ArgoNamespace, "--insecure")
    $appGet = Capture "04-app-of-apps" $argocd @("app", "get", $App, "--port-forward", "--port-forward-namespace", $ArgoNamespace, "--insecure")
    $objects = Capture "04-app-of-apps" $kubectl @("get", "all", "-n", $Namespace)
    if ($objects -notmatch "deployment.apps/") { throw "the application deployed no workloads" }
    $startTag = Get-DeployedTag
    if ($startTag -ne $FromVersion) { throw "expected the cluster to start on $FromVersion, found $startTag" }
    $served = Get-ServedVersion
    Write-Transcript "04-app-of-apps" @("", "GET /version -> $served")
    if ($served -ne $FromVersion) { throw "/version reports $served, expected $FromVersion" }
    Note "the same tree is the application view in the web UI: Application -> Deployments,"
    Note "Services, ConfigMap, PVC and the Helm hook Jobs, each with its own health."
    Pass "the application reconciles to Synced/Healthy from Git alone" ("sync={0} health={1}, serving {2}" -f $state.Sync, $state.Health, $served)

    # ------------------------------------------------------------ clause 5
    Section "clause 5" "a release: change the tag in Git, commit, push - and nothing else"
    Note "no helm upgrade, no kubectl apply. The only action is a commit."
    Set-ImageTag $ToVersion
    Capture "05-release" $git @("-C", $repo, "diff", "--", $valuesGitPath) | Out-Null
    $sha = New-GitOpsCommit "05-release" $valuesGitPath "gitops: roll the CDN Control Plane to $ToVersion"
    if (-not $WhatIfGit) {
        Request-Refresh
        Wait-Revision $sha
        Wait-AppState "Synced" "Healthy" 420 | Out-Null
        $newTag = Get-DeployedTag
        if ($newTag -ne $ToVersion) { throw "the Deployment is still on $newTag after the commit" }
        $servedNow = Get-ServedVersion
        Write-Transcript "05-release" @("", "GET /version -> $servedNow", "deployment image tag -> $newTag")
        if ($servedNow -ne $ToVersion) { throw "/version still reports $servedNow after the rollout" }
        Capture "05-release" $argocd @("app", "history", $App, "--port-forward", "--port-forward-namespace", $ArgoNamespace, "--insecure") | Out-Null
        Note "the visible change is in the response itself, not only in the manifest:"
        Note "/version is read from values baked into the image, so it can only report the"
        Note "build the pod was actually made from."
        Pass "a commit alone rolled the application forward" "$FromVersion -> $ToVersion, /version reports $servedNow"
    }
    else { Pass "the release commit was prepared" "-WhatIfGit, nothing pushed" }

    # ------------------------------------------------------------ clause 6a
    Section "clause 6a" "manual drift with selfHeal off: reported, not corrected"
    $before = Get-ApiReplicas
    $deployment = Get-ApiDeployment
    Capture "06a-drift" $kubectl @("scale", "deployment/$deployment", "-n", $Namespace, "--replicas=3") | Out-Null
    Request-Refresh
    $drift = Wait-AppState "OutOfSync" "" 240
    $diff = Capture "06a-drift" $argocd @("app", "diff", $App, "--port-forward", "--port-forward-namespace", $ArgoNamespace, "--insecure")
    $scaled = Get-ApiReplicas
    if ($scaled -ne 3) { throw "the manual scale did not take effect" }
    Note "Argo CD saw the difference immediately and left it alone: detecting drift and"
    Note "correcting it are two separate settings, and only the first is on."
    Pass "drift is detected and reported while selfHeal is off" ("sync={0}, cluster has {1} replicas, Git says {2}" -f $drift.Sync, $scaled, $before)

    Section "clause 6a" "selfHeal turned on through Git: the manual change is reverted"
    Set-SelfHeal $true
    $shaHeal = New-GitOpsCommit "06a-drift" $appGitPath "gitops: enable selfHeal for $App"
    if (-not $WhatIfGit) {
        Request-Refresh
        # The Application object itself is reconciled by the root Application, so
        # wait for the new setting to land on the object before judging its effect.
        $deadline = (Get-Date).AddSeconds(300)
        while ((Get-Date) -lt $deadline) {
            if ((Get-AppField $App ".spec.syncPolicy.automated.selfHeal") -eq "true") { break }
            Request-Refresh $RootApp; Start-Sleep -Seconds 5
        }
        if ((Get-AppField $App ".spec.syncPolicy.automated.selfHeal") -ne "true") {
            throw "selfHeal was not propagated to the Application object"
        }
        Capture "06a-drift" $kubectl @("scale", "deployment/$deployment", "-n", $Namespace, "--replicas=3") | Out-Null
        Request-Refresh
        Wait-AppState "Synced" "Healthy" 300 | Out-Null
        $healed = Get-ApiReplicas
        Capture "06a-drift" $kubectl @("get", "deployment", $deployment, "-n", $Namespace) | Out-Null
        if ($healed -ne $before) { throw "selfHeal did not restore $before replicas, saw $healed" }
        Note "the same kubectl scale now survives for seconds. Git is not a record of what"
        Note "was intended - it is what the cluster is continuously forced back to."
        Pass "selfHeal reverts a manual change to the value in Git" ("scaled to 3, returned to {0} replicas on its own" -f $healed)
    }
    else { Pass "the selfHeal commit was prepared" "-WhatIfGit, nothing pushed" }

    # ------------------------------------------------------------ clause 6b
    Section "clause 6b" "a nonexistent image tag in Git: Synced, but Degraded"
    Set-ImageTag $BadVersion
    $shaBad = New-GitOpsCommit "06b-degraded" $valuesGitPath "gitops: point the image at a tag that does not exist (Lab 5 point 6b)"
    if (-not $WhatIfGit) {
        Request-Refresh
        Wait-Revision $shaBad
        $bad = Wait-AppState "Synced" "Degraded" 420
        $pods = Capture "06b-degraded" $kubectl @("get", "pods", "-n", $Namespace)
        Capture "06b-degraded" $kubectl @("get", "events", "-n", $Namespace, "--sort-by=.lastTimestamp") -Silent | Out-Null
        Capture "06b-degraded" $argocd @("app", "get", $App, "--port-forward", "--port-forward-namespace", $ArgoNamespace, "--insecure") | Out-Null
        if ($pods -notmatch "ImagePullBackOff|ErrImagePull") { throw "no pod is failing to pull the bad image" }
        Note "Synced and Degraded at once is the useful distinction: Synced means the cluster"
        Note "matches Git, Degraded means what Git asked for does not work. Argo CD did its"
        Note "job perfectly and the application is still broken - because Git is wrong."
        Note "maxUnavailable: 0 is why the old pods keep serving while the new one cannot start."
        Pass "a bad tag in Git is Synced but Degraded" ("sync={0} health={1}, ImagePullBackOff on the new pod" -f $bad.Sync, $bad.Health)
    }
    else { Pass "the bad-tag commit was prepared" "-WhatIfGit, nothing pushed" }

    # ------------------------------------------------------------ clause 6c
    Section "clause 6c" "git revert: the fix is itself a commit"
    if (-not $WhatIfGit) {
        $revert = Capture "06c-revert" $git @("-C", $repo, "revert", "--no-edit", $shaBad)
        if ($revert -notmatch "Revert") { throw "the revert did not produce a commit: $revert" }
        Capture "06c-revert" $git @("-C", $repo, "push", "origin", $Branch) -Silent | Out-Null
        $shaRevert = (Invoke-Native $git @("-C", $repo, "rev-parse", "--short", "HEAD")).Trim()
        $script:CommitsMade += $shaRevert
        Request-Refresh
        Wait-Revision $shaRevert
        $fixed = Wait-AppState "Synced" "Healthy" 420
        $tagBack = Get-DeployedTag
        if ($tagBack -ne $ToVersion) { throw "the revert did not restore $ToVersion, found $tagBack" }
        $servedBack = Get-ServedVersion
        $log = Capture "06c-revert" $git @("-C", $repo, "log", "--oneline", "-6")
        $history = Capture "06c-revert" $argocd @("app", "history", $App, "--port-forward", "--port-forward-namespace", $ArgoNamespace, "--insecure")
        if ($log -notmatch "Revert") { throw "git log does not show the revert" }
        Write-Transcript "06c-revert" @("", "GET /version -> $servedBack")
        Note "git revert adds a commit rather than deleting one, and argocd app history"
        Note "adds a deployment rather than removing one. Both are logs: the broken release"
        Note "stays visible in each, which is what makes the recovery auditable."
        Pass "reverting the commit restores the working release" ("back to {0}, sync={1} health={2}" -f $servedBack, $fixed.Sync, $fixed.Health)
    }
    else { Pass "the revert step was skipped" "-WhatIfGit, nothing to revert" }

    # ---------------------------------------------------------------- summary
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
    Stop-Forward
    # Leave the branch describing a working cluster, whichever step failed. The
    # tag is restored in the working tree only - an interrupted run is meant to
    # be inspected, so this never commits on its own.
    if (-not $WhatIfGit) {
        $leftOn = Get-ImageTag
        if ($leftOn -eq $BadVersion) {
            Write-Host ""
            Write-Host ("The run stopped with the bad tag still committed. Restore it with:") -ForegroundColor Yellow
            Write-Host ("  git -C `"$repo`" revert --no-edit $shaBad && git -C `"$repo`" push origin $Branch") -ForegroundColor Yellow
        }
    }
}
