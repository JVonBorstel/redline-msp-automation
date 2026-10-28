# Phase 1 acceptance suite runner for the build automation and CI: pytest (specs/phase-1.md), ruff and mypy through uv (never bare python).
# Prints one summary line the test runner reads: "Phase1 tests: N passed, M failed".
$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$env:UV_PYTHON_PREFERENCE = 'only-managed'   # never the Microsoft Store python stub (it hangs)
Push-Location $repo
# When the repo folder is read-only (a sandboxed run), the venv and the uv cache go to the writable TEMP, and a Python that uv already
# installed is used read-only. Elsewhere (a normal shell, CI) nothing changes.
$probe = Join-Path $repo '.venv-write-probe'
try { [IO.File]::WriteAllText($probe, 'x'); [IO.File]::Delete($probe) } catch {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP 'redline-venv'; $env:UV_CACHE_DIR = Join-Path $env:TEMP 'uv-cache'; $env:UV_LINK_MODE = 'copy'
    $env:MYPY_CACHE_DIR = Join-Path $env:TEMP 'mypy-cache'; $env:RUFF_CACHE_DIR = Join-Path $env:TEMP 'ruff-cache'   # their caches default to the repo
    $real = Join-Path $env:SystemDrive "Users\$env:USERNAME\AppData\Roaming\uv\python"
    if (Test-Path -LiteralPath $real) { $env:UV_PYTHON_INSTALL_DIR = $real; $env:UV_PYTHON_DOWNLOADS = 'never' }
}
try {
    $fail = 0; $pass = 0
    $py = & uv run --frozen pytest -p no:cacheprovider 2>&1 | Out-String; $pyCode = $LASTEXITCODE
    Write-Host $py
    if ($py -match '(\d+) passed') { $pass += [int]$Matches[1] }
    if ($py -match '(\d+) failed') { $fail += [int]$Matches[1] }
    if ($pyCode -ne 0 -and $fail -eq 0) { $fail++; Write-Host "FAIL: pytest exited $pyCode" }
    $rf = & uv run --frozen ruff check . 2>&1 | Out-String; if ($LASTEXITCODE) { $fail++; Write-Host "FAIL: ruff`n$rf" } else { $pass++ }
    $mp = & uv run --frozen mypy 2>&1 | Out-String; if ($LASTEXITCODE) { $fail++; Write-Host "FAIL: mypy`n$mp" } else { $pass++ }
    Write-Host "Phase1 tests: $pass passed, $fail failed"
    exit ([int]($fail -ne 0))
} finally { Pop-Location }
