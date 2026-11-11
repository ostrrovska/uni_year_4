# DevOps Lab5
<#
.SYNOPSIS
    One-time setup for DevOps Lab 5: Argo CD, the database Secret and the root Application.

.DESCRIPTION
    Everything here is done once per cluster. It is deliberately separate from
    devops_lab5_demo.ps1, which is run repeatedly and must find the cluster
    already bootstrapped - mixing the two would hide the single most important
    fact about the lab, which is how little is ever applied by hand.

    What it does:
      1. starts minikube if it is not running
      2. installs Argo CD into namespace argocd and waits for it
      3. changes the admin password and deletes argocd-initial-admin-secret
      4. creates the cdn-db Secret in the application namespace, out of Git
      5. applies the root Application - the one and only manual apply

    After this, the cluster is driven by commits. The transcripts it writes feed
    section 3 of docs/devops/lab-05.md.

.PARAMETER AdminPassword
    The new Argo CD admin password. Prompted for if not given; never written to
    a file or to the transcripts.

.PARAMETER DbPassword
    The PostgreSQL password placed in the cdn-db Secret. Prompted for if not given.

.EXAMPLE
    ./scripts/devops_lab5_setup.ps1
#>
[CmdletBinding()]
param(
    [string]$ArgoNamespace = "argocd",
    [string]$Namespace = "cdn-gitops",
    [string]$ArgoVersion = "v3.1.9",
    [securestring]$AdminPassword,
    [securestring]$DbPassword,
    [string]$KubectlPath,
    [string]$ArgocdPath,
    [string]$MinikubePath
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$outDir = Join-Path $root "docs/devops/lab-05-output"
$rootApp = Join-Path $root "gitops/bootstrap/root-app.yaml"

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
$minikube = Resolve-Tool "minikube" $MinikubePath
$argocd = Resolve-Tool "argocd" $ArgocdPath

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
$transcript = Join-Path $outDir "01-environment.txt"

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

function Record([string]$Command, [string]$Output) {
    Add-Content -Path $transcript -Encoding UTF8 -Value "$ $Command"
    Add-Content -Path $transcript -Encoding UTF8 -Value $Output
    Write-Host $Output -ForegroundColor Gray
}

function Step([string]$Text) {
    Write-Host ""
    Write-Host ("==> {0}" -f $Text) -ForegroundColor Cyan
}

function Read-Secret([string]$Prompt, [securestring]$Given) {
    if ($Given) { return $Given }
    return (Read-Host -Prompt $Prompt -AsSecureString)
}

function ConvertFrom-Secure([securestring]$Value) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

# ------------------------------------------------------------------ 1. cluster
Step "minikube"
$status = Invoke-Native $minikube @("status")
if ($status -notmatch "host: Running") {
    Write-Host "     starting minikube (this takes a few minutes the first time)" -ForegroundColor DarkGray
    # 3 GB, not the 2 GB default and not more: this host has 7.3 GB in total, so
    # a larger VM starves Docker Desktop and the editor instead of helping. It
    # fits because every request in the chart is small - the whole application
    # asks for about 420 MiB - and Argo CD's controllers are the larger half of
    # the budget.
    & $minikube start --cpus=4 --memory=3072 --driver=docker
}
Record "minikube status" (Invoke-Native $minikube @("status"))
Record "kubectl version --short" (Invoke-Native $kubectl @("version", "--output=yaml"))

# --------------------------------------------------------------- 2. argo cd
Step "Argo CD $ArgoVersion into namespace $ArgoNamespace"
$existing = Invoke-Native $kubectl @("get", "namespace", $ArgoNamespace)
if ($existing -match "NotFound|not found") {
    & $kubectl create namespace $ArgoNamespace | Out-Null
}
# The pinned release manifest, not `stable`: a bootstrap that installs a
# different version depending on the day is not a reproducible bootstrap.
$manifest = "https://raw.githubusercontent.com/argoproj/argo-cd/$ArgoVersion/manifests/install.yaml"
& $kubectl apply -n $ArgoNamespace -f $manifest | Out-Null
Write-Host "     waiting for the Argo CD deployments to become available" -ForegroundColor DarkGray
& $kubectl wait --for=condition=available --timeout=600s deployment --all -n $ArgoNamespace | Out-Null
& $kubectl rollout status statefulset/argocd-application-controller -n $ArgoNamespace --timeout=600s | Out-Null
Record "kubectl get pods -n $ArgoNamespace" (Invoke-Native $kubectl @("get", "pods", "-n", $ArgoNamespace, "-o", "wide"))
Record "argocd version --client --short" (Invoke-Native $argocd @("version", "--client", "--short"))

# ------------------------------------------------------------- 3. password
Step "admin password"
$initial = Invoke-Native $kubectl @("get", "secret", "argocd-initial-admin-secret", "-n", $ArgoNamespace,
    "-o", "jsonpath={.data.password}")
if ($initial -match "NotFound|not found" -or -not $initial.Trim()) {
    Write-Host "     argocd-initial-admin-secret is already gone - the password was changed on an earlier run." -ForegroundColor DarkGray
}
else {
    $current = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($initial.Trim()))
    $new = ConvertFrom-Secure (Read-Secret "New Argo CD admin password (at least 8 characters)" $AdminPassword)
    if ($new.Length -lt 8) { throw "Argo CD rejects passwords shorter than 8 characters" }

    # Port-forward rather than exposing the server: the CLI needs to reach the
    # API, and opening a NodePort for a one-off password change would outlive
    # the reason for it.
    $forward = Start-Process -FilePath $kubectl -PassThru -NoNewWindow -ArgumentList @(
        "port-forward", "svc/argocd-server", "8080:443", "-n", $ArgoNamespace
    )
    try {
        Start-Sleep -Seconds 5
        & $argocd login 127.0.0.1:8080 --username admin --password $current --insecure --grpc-web | Out-Null
        & $argocd account update-password --current-password $current --new-password $new --insecure --grpc-web | Out-Null
        # update-password does not remove the bootstrap Secret; leaving it would
        # leave the generated password readable by anyone with get on the
        # namespace, long after it stopped being the password.
        & $kubectl delete secret argocd-initial-admin-secret -n $ArgoNamespace | Out-Null
        & $argocd login 127.0.0.1:8080 --username admin --password $new --insecure --grpc-web | Out-Null
        Write-Host "     password changed, bootstrap secret deleted, CLI logged in with the new one." -ForegroundColor Green
    }
    finally {
        if ($forward -and -not $forward.HasExited) { Stop-Process -Id $forward.Id -Force -ErrorAction SilentlyContinue }
    }
}
Record "kubectl get secret argocd-initial-admin-secret -n $ArgoNamespace" `
    (Invoke-Native $kubectl @("get", "secret", "argocd-initial-admin-secret", "-n", $ArgoNamespace))

# --------------------------------------------------------------- 4. secret
Step "the database credential, created in the cluster and not in Git"
$ns = Invoke-Native $kubectl @("get", "namespace", $Namespace)
if ($ns -match "NotFound|not found") { & $kubectl create namespace $Namespace | Out-Null }
$existingSecret = Invoke-Native $kubectl @("get", "secret", "cdn-db", "-n", $Namespace)
if ($existingSecret -match "NotFound|not found") {
    $pg = ConvertFrom-Secure (Read-Secret "PostgreSQL password for the cdn user" $DbPassword)
    # The host is the Service the chart renders: release name "cdn" plus the
    # chart name, as cdn.fullname builds it.
    $url = "postgresql+asyncpg://cdn:$pg@cdn-cdn-control-plane-postgresql:5432/cdn_control_plane"
    & $kubectl create secret generic cdn-db -n $Namespace `
        --from-literal=POSTGRES_PASSWORD=$pg `
        --from-literal=DATABASE_URL=$url | Out-Null
    Write-Host "     cdn-db created in $Namespace." -ForegroundColor Green
}
else {
    Write-Host "     cdn-db already exists in $Namespace - left untouched." -ForegroundColor DarkGray
}
# `describe` prints each key and the byte length of its value, never the value
# itself - which is exactly the amount of evidence this step should leave behind.
Record "kubectl describe secret cdn-db -n $Namespace" `
    (Invoke-Native $kubectl @("describe", "secret", "cdn-db", "-n", $Namespace))

# ------------------------------------------------------------ 5. bootstrap
Step "the root Application - the only object applied by hand"
Record "kubectl apply -n $ArgoNamespace -f gitops/bootstrap/root-app.yaml" `
    (Invoke-Native $kubectl @("apply", "-n", $ArgoNamespace, "-f", $rootApp))
Start-Sleep -Seconds 10
Record "kubectl get applications -n $ArgoNamespace" `
    (Invoke-Native $kubectl @("get", "applications", "-n", $ArgoNamespace))

Write-Host ""
Write-Host "Bootstrap complete." -ForegroundColor Green
Write-Host "  UI:   kubectl port-forward svc/argocd-server -n $ArgoNamespace 8080:443  ->  https://localhost:8080" -ForegroundColor DarkGray
Write-Host "  then: ./scripts/devops_lab5_demo.ps1" -ForegroundColor DarkGray
Write-Host "  transcript: $transcript" -ForegroundColor DarkGray
