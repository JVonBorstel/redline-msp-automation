# Python test suite runner for the build automation and CI (B-06): pytest over tests/py and the map integrity check, through uv (never bare python).
# Prints one summary line the test runner reads: "Py tests: N passed, M failed in S s" (S = pytest wall time).
param([string] $TestPath = 'tests/py')   # the orphan-test guard points this at a one-test folder so it cannot run itself again
$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$env:UV_PYTHON_PREFERENCE = 'only-managed'   # never the Microsoft Store python stub (it hangs)
Push-Location $repo
# Low-integrity runs (a sandbox) have a read-only repo folder: send the venv and caches to TEMP. Elsewhere nothing changes.
$probe = Join-Path $repo '.venv-write-probe'
try { [IO.File]::WriteAllText($probe, 'x'); [IO.File]::Delete($probe) } catch {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP 'redline-venv'; $env:UV_CACHE_DIR = Join-Path $env:TEMP 'uv-cache'; $env:UV_LINK_MODE = 'copy'
    $env:MYPY_CACHE_DIR = Join-Path $env:TEMP 'mypy-cache'; $env:RUFF_CACHE_DIR = Join-Path $env:TEMP 'ruff-cache'
    $real = Join-Path $env:SystemDrive "Users\$env:USERNAME\AppData\Roaming\uv\python"
    if (Test-Path -LiteralPath $real) { $env:UV_PYTHON_INSTALL_DIR = $real; $env:UV_PYTHON_DOWNLOADS = 'never' }
}
$fail = 0; $pass = 0; $clock = New-Object Diagnostics.Stopwatch
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        $fail++; Write-Host 'FAIL: uv is not installed, so the Python suite was skipped, not passed'
    } else {
        # tests/py may hold no tests yet: pytest then exits 5 ("no tests collected"), which counts as zero tests, not a failure.
        $clock.Start()
        $py = & uv run --frozen pytest -p no:cacheprovider $TestPath 2>&1 | Out-String; $pyCode = $LASTEXITCODE
        $clock.Stop()
        Write-Host $py
        if ($py -match '(\d+) passed') { $pass += [int]$Matches[1] }
        if ($py -match '(\d+) failed') { $fail += [int]$Matches[1] }
        if ($pyCode -ne 0 -and $pyCode -ne 5 -and $fail -eq 0) { $fail++; Write-Host "FAIL: pytest exited $pyCode" }
        $mc = & uv run --frozen python map/check_map.py 2>&1 | Out-String
        if ($LASTEXITCODE) { $fail++; Write-Host "FAIL: map check`n$mc" } else { $pass++; Write-Host $mc }
    }
} catch {
    $fail++; Write-Host "FAIL: runner error: $($_.Exception.Message)"
} finally { Pop-Location }
$secs = $clock.Elapsed.TotalSeconds.ToString('0.0', [Globalization.CultureInfo]::InvariantCulture)   # pytest wall time only; 0.0 when uv is missing
Write-Host "Py tests: $pass passed, $fail failed in $secs s"
exit ([int]($fail -ne 0))
