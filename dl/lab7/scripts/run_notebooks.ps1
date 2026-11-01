# Виконання ноутбуків лабораторної 7 headless (виводи зберігаються у самих ноутбуках).
# Приклад: .\scripts\run_notebooks.ps1 -Notebooks Task3_happy_or_sad
param(
    [string[]]$Notebooks = @(
        "Task3_happy_or_sad",
        "Task0_base_no_validation",
        "Task1_validation_300",
        "Task2_resize_150",
        "Task4_dogs_vs_cats"
    )
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:TF_CPP_MIN_LOG_LEVEL = "2"

Push-Location (Join-Path $root "notebooks")
try {
    foreach ($nb in $Notebooks) {
        $file = "$nb.ipynb"
        Write-Output "=== $file : старт $(Get-Date -Format HH:mm:ss) ==="
        $t0 = Get-Date
        & $py -m jupyter nbconvert --to notebook --execute --inplace `
            --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=python3 $file
        $code = $LASTEXITCODE
        $mins = ((Get-Date) - $t0).TotalMinutes
        if ($code -ne 0) {
            Write-Output "!!! $file завершився з кодом $code (${mins} хв)"
            exit $code
        }
        Write-Output "=== $file : готово за $([math]::Round($mins,1)) хв ==="
    }
}
finally {
    Pop-Location
}
