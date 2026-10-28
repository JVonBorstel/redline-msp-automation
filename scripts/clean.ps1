# The only sanctioned recursive delete. Removes known, regenerable artifact folders inside this repo, nothing else.
# Cache folders are removed at any depth; build-output folders only at the repo root (so a tracked docs/build is never touched).
# The pre-tool hook blocks ad-hoc recursive deletes; this script is the safe path (and is itself human-only to edit).
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
$anywhere = '.pytest_cache', '.ruff_cache', '.mypy_cache', '__pycache__', 'htmlcov'
$rootOnly = '.tmp', 'build', 'dist', 'TestResults'
$removed = 0
$targets = @()
$targets += Get-ChildItem $repo -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in $anywhere -and $_.FullName -notmatch '\\(\.git|\.venv|node_modules)\\' }
$targets += $rootOnly | ForEach-Object { Join-Path $repo $_ } | Where-Object { Test-Path $_ } | ForEach-Object { Get-Item $_ -Force }
$targets | Sort-Object { $_.FullName.Length } -Descending | ForEach-Object {
    $full = [IO.Path]::GetFullPath($_.FullName)
    # never follow or delete through links, never leave the repo
    if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($full); $removed++; return }
    if ($full.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $full)) { Remove-Item -LiteralPath $full -Recurse -Force; $removed++ }
}
Write-Host "removed $removed artifact folder(s)"
