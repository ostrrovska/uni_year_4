<#
.SYNOPSIS
    Lab 3 demo - concurrent data pipeline in Go.

.DESCRIPTION
    Builds the pipeline (go-service) once, then:
    1. Runs it with no flags - the default benchmark matrix - printing three
       tables (scaling by worker count, by channel buffer, by task count),
       each row self-checked against a deterministically expected sum.
    2. Runs a short cancellation demo (context.WithTimeout + select) showing
       a partial run that still exits cleanly, no deadlock.
    3. Runs the data race check (go run -race). This needs a C compiler
       (cgo). If none is on Windows, it falls back to WSL (gcc is there),
       using Go installed under $HOME/go-sdk in WSL.

.EXAMPLE
    ./demo.ps1
#>
[CmdletBinding()]
param(
    [string]$Go = "go"
)

$ErrorActionPreference = "Continue"
$goService = (Resolve-Path (Join-Path $PSScriptRoot "go-service")).Path

function Write-Head { param([string]$Text) Write-Host ""; Write-Host "=== $Text ===" -ForegroundColor Cyan }

function Invoke-RaceCheck {
    param([string]$ServicePath)

    Write-Host "go run -race . -tasks 2000 -workers 8 -buffer 10"
    & $Go run -race . -tasks 2000 -workers 8 -buffer 10
    if ($LASTEXITCODE -eq 0) { return }

    if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
        Write-Host "No C compiler here and no WSL available. Install one (e.g. choco install mingw) and re-run the command above." -ForegroundColor Yellow
        return
    }

    $drive = $ServicePath.Substring(0, 1).ToLower()
    $rest = $ServicePath.Substring(2) -replace '\\', '/'
    $wslPath = "/mnt/$drive$rest"
    # Absolute path to the Go binary avoids PATH quoting issues across the
    # PowerShell -> wsl.exe -> bash argument boundary.
    $bashCmd = "cd '$wslPath' && `$HOME/go-sdk/bin/go run -race . -tasks 2000 -workers 8 -buffer 10"

    Write-Host "No C compiler on Windows - running the same check via WSL (gcc is available there):" -ForegroundColor Yellow
    wsl bash -lc $bashCmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WSL run failed - Go may not be installed there. Install a C compiler on Windows instead and re-run the command above." -ForegroundColor Yellow
    }
}

Push-Location $goService
try {
    Write-Head "Build"
    & $Go build -o bin\lab3-go.exe .
    if ($LASTEXITCODE -ne 0) { throw "go build failed" }

    Write-Head "Benchmark matrix (default run, no flags)"
    & .\bin\lab3-go.exe
    if ($LASTEXITCODE -ne 0) { throw "benchmark matrix run failed" }

    Write-Head "Cancellation demo (-cancel-after 1ms, expect a partial run)"
    & .\bin\lab3-go.exe -tasks 2000 -workers 4 -buffer 10 -cancel-after 1ms
    if ($LASTEXITCODE -ne 0) { throw "cancellation demo run failed" }

    Write-Head "Data race check"
    Invoke-RaceCheck -ServicePath $goService
}
finally {
    Pop-Location
}
