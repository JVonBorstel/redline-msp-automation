# Point git at the repo's commit hooks (secret scan). Run once after cloning.
$repo = Split-Path -Parent $PSScriptRoot
git -C $repo config core.hooksPath scripts/hooks
Write-Host "git hooks path set to scripts/hooks in $repo"
