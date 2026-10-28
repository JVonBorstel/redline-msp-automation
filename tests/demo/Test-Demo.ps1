#requires -Version 7
<#
Demo smoke suite (specs/B-10.md: B10-1..B10-4). Runs every typed command of docs/DEMO.md end to end, offline, in temp
state folders, through tests/demo/test_b10_demo_smoke.py (pytest via uv, never bare python).
Run from anywhere:  pwsh -NoProfile -File tests/demo/Test-Demo.ps1
Prints "Demo tests: N passed, M failed". Exit 0 = all pass, 1 = failures. A run over 120 seconds counts as a failure (B10-3).
Writes only under the pytest temp folder; never touches the repo's .tmp/demo or the committed fixtures.
#>
$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$env:UV_PYTHON_PREFERENCE = 'only-managed'   # never the Microsoft Store python stub (it hangs)
$budgetSeconds = 120
Push-Location $repo
# Same Low-integrity handling as Test-Phase1.ps1: when the repo folder is read-only (a sandbox), the venv and the
# caches go to the writable TEMP. Elsewhere (a normal shell, CI) nothing changes.
$probe = Join-Path $repo '.venv-write-probe'
try { [IO.File]::WriteAllText($probe, 'x'); [IO.File]::Delete($probe) } catch {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP 'redline-venv'; $env:UV_CACHE_DIR = Join-Path $env:TEMP 'uv-cache'; $env:UV_LINK_MODE = 'copy'
    $real = Join-Path $env:SystemDrive "Users\$env:USERNAME\AppData\Roaming\uv\python"
    if (Test-Path -LiteralPath $real) { $env:UV_PYTHON_INSTALL_DIR = $real; $env:UV_PYTHON_DOWNLOADS = 'never' }
}
try {
    $pass = 0; $fail = 0
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $py = & uv run --frozen pytest -p no:cacheprovider tests/demo 2>&1 | Out-String; $pyCode = $LASTEXITCODE
    $clock.Stop()
    Write-Host $py
    if ($py -match '(\d+) passed') { $pass += [int]$Matches[1] }
    if ($py -match '(\d+) failed') { $fail += [int]$Matches[1] }
    if ($py -match '(\d+) error') { $fail += [int]$Matches[1] }
    if ($py -match '(\d+) skipped') { Write-Host "SKIPPED: $($Matches[1]) (not counted as passed; is pwsh on PATH?)" }
    if ($pyCode -ne 0 -and $fail -eq 0) { $fail++; Write-Host "FAIL: pytest exited $pyCode" }
    $seconds = [math]::Round($clock.Elapsed.TotalSeconds, 1)
    if ($seconds -lt $budgetSeconds) { $pass++; Write-Host "PASS: B10-3 smoke run took $seconds s (budget $budgetSeconds s)" }
    else { $fail++; Write-Host "FAIL: B10-3 smoke run took $seconds s (budget $budgetSeconds s)" }
    Write-Host "Demo tests: $pass passed, $fail failed"
    exit ([int]($fail -ne 0))
} finally { Pop-Location }
