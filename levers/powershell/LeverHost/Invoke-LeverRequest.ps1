#requires -Version 7.4
<#
.SYNOPSIS
  The PowerShell lever host (B-15): one JSON lever request on stdin, one JSON lever result on stdout.
.DESCRIPTION
  Python orchestrates and PowerShell acts. The Python runner has already checked registry, schema, role, client scope,
  approval, pause and verification (B-16); this host re-checks only the request shape and the entry, never permissions.
  Reads one request (schemas/lever-request.schema.json), imports only levers/powershell/<entry.module>, calls
  <entry.function> (with -WhatIf for mode dry-run) and writes one compact JSON result on stdout, nothing else.
  The result is a subset of schemas/lever-result.schema.json (status, reason, lever, client, mode, data, diff, applied);
  the runner adds identity, approver and audit_seq.
  Exit codes (STD-ER-6): 0 ok; 1 denied or error (a normal outcome); 2 usage or configuration error
  (stdin is not a valid request, or the host's own files are missing). Stack text never reaches stdout (STD-ER-5, STD-ER-7).
  No network, no credentials. Synthetic data only.
.PARAMETER ModulesRoot
  Folder holding the lever modules. Default: levers/powershell next to this module. Tests point it at a fixture folder.
.PARAMETER TimeoutSeconds
  Hard stop for one lever call (default 30).
.PARAMETER LogPath
  Optional file for the operational log: the crash type and stack go here, never to stdout or the audit.
.EXAMPLE
  Get-Content request.json -Raw | pwsh -NoProfile -NonInteractive -File Invoke-LeverRequest.ps1
#>
[CmdletBinding()]
param(
    [string] $ModulesRoot,
    [ValidateRange(1, 600)][int] $TimeoutSeconds = 30,
    [string] $LogPath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$script:exitCode = 2
$script:result = $null
function Write-Stdout([string] $Text) {
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($Text + "`n")
    $stream = [Console]::OpenStandardOutput(); $stream.Write($bytes, 0, $bytes.Length); $stream.Flush()
}

try {
    $hostDir = $PSScriptRoot
    $repo = (Resolve-Path (Join-Path $hostDir '..\..\..')).Path
    if (-not $ModulesRoot) { $ModulesRoot = Join-Path $repo 'levers\powershell' }
    $schema = Join-Path $repo 'schemas\lever-request.schema.json'
    Import-Module (Join-Path $hostDir 'LeverHost.psd1') -Force

    $stdin = [Console]::OpenStandardInput()
    $reader = [System.IO.StreamReader]::new($stdin, [System.Text.UTF8Encoding]::new($false))
    $text = $reader.ReadToEnd()

    if (-not (Test-Path -LiteralPath $schema -PathType Leaf)) {
        $script:result = New-LeverResult -Status error -Reason 'the host cannot find schemas/lever-request.schema.json; nothing ran'
    }
    elseif (-not (Test-Path -LiteralPath $ModulesRoot -PathType Container)) {
        $script:result = New-LeverResult -Status error -Reason 'the lever modules folder does not exist; nothing ran'
    }
    elseif ([string]::IsNullOrWhiteSpace($text)) {
        $script:result = New-LeverResult -Status error -Reason 'no request on stdin; send one lever-request JSON document; nothing ran'
    }
    else {
        $check = Test-LeverRequestJson -Json $text -SchemaFile $schema
        if (-not $check.Ok) {
            $script:result = New-LeverResult -Status error -Reason "the request is not a valid lever-request: $($check.Reason); nothing ran"
        }
        else {
            $request = $text | ConvertFrom-Json -Depth 20
            $script:result = Invoke-LeverEntry -Request $request -ModulesRoot $ModulesRoot -TimeoutSeconds $TimeoutSeconds -LogPath $LogPath
            $script:exitCode = if ($script:result.status -eq 'ok') { 0 } else { 1 }
        }
    }
}
catch {
    # The host's own failure. Type name only (STD-ER-5); the detail goes to the log file if one was asked for.
    $type = ($_.Exception.GetType().Name -replace '[^A-Za-z0-9_]', '')
    if ($LogPath) { try { Add-Content -LiteralPath $LogPath -Value ("{0} lever host crashed: {1}`n{2}" -f ([datetime]::UtcNow.ToString('o')), $type, $_.Exception.ToString()) } catch { } }
    $script:result = [pscustomobject][ordered]@{ status = 'error'; reason = "lever host crashed: $type"; lever = 'unknown'; client = 'unknown'; mode = 'unknown'; data = $null; diff = @(); applied = $false }
    $script:exitCode = 2
}
Write-Stdout ($script:result | ConvertTo-Json -Depth 20 -Compress)
exit $script:exitCode
