#requires -Version 7
<#
B-15 (specs/B-15.md: B15-3). Runs every levers/powershell/<Module>/tests/*.ps1 file, each in its own pwsh process, and
prints one summary line:  PS modules tests: N passed, M failed
Each test file prints its own `... tests: N passed, M failed` line (plain-script style, STD-PS-9). This runner sums them.
A file that exits non-zero without a summary, crashes, or prints no summary line counts as 1 failed: silence is not a pass.
A module with no tests folder is fine (TenantBaseline's tests live in tests/sliceb until it is moved).
Exit code 0 = all pass, 1 = any failed. Reads only; each test file decides what it writes (under $env:TEMP).
Run from anywhere:  pwsh -NoProfile -File tests/ps/Test-Modules.ps1
-ModulesRoot points at another tree (used by LeverHost's own tests); default is levers/powershell.
#>
param([string] $ModulesRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $ModulesRoot) { $ModulesRoot = Join-Path $repo 'levers\powershell' }

$passed = 0; $failed = 0
$files = @(Get-ChildItem -LiteralPath $ModulesRoot -Directory | Sort-Object Name | ForEach-Object {
        $tests = Join-Path $_.FullName 'tests'
        if (Test-Path -LiteralPath $tests -PathType Container) { Get-ChildItem -LiteralPath $tests -Filter '*.ps1' -File | Sort-Object Name }
    })
foreach ($file in $files) {
    $label = "$($file.Directory.Parent.Name)/tests/$($file.Name)"
    $out = & pwsh -NoProfile -NonInteractive -File $file.FullName 2>&1 | Out-String
    $code = $LASTEXITCODE
    $m = [regex]::Matches($out, '(?m)^\S[^\r\n]*? tests: (\d+) passed, (\d+) failed')
    if ($m.Count -eq 0) {
        $failed++
        Write-Host "FAIL: $label printed no 'N passed, M failed' summary (exit code $code)" -ForegroundColor Red
        continue
    }
    $p = 0; $f = 0
    foreach ($x in $m) { $p += [int] $x.Groups[1].Value; $f += [int] $x.Groups[2].Value }
    if ($code -ne 0 -and $f -eq 0) { $f = 1 }   # failed exit with a clean summary still counts
    $passed += $p; $failed += $f
    Write-Host ("{0}: {1} passed, {2} failed" -f $label, $p, $f)
    if ($f -gt 0) { $out -split "`r?`n" | Where-Object { $_ -match '^FAIL' } | ForEach-Object { Write-Host "  $_" } }
}
Write-Host "PS modules tests: $passed passed, $failed failed"
if ($failed -gt 0) { exit 1 } else { exit 0 }
