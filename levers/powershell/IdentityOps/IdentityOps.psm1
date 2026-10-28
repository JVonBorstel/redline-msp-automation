Set-StrictMode -Version Latest

# Identity levers for the Python bridge (B-29): user.revoke-sessions, user.enable, user.set-properties. They work on the
# offline mock tenant only (fixtures/tenant/<client>.json, <client>/sessions.json, or the folder named by
# $env:REDLINE_MOCK_TENANT_DIR, which the bridge sets). No network, no credentials, synthetic data only.
#
# Contract with the lever host (B-15): the Python runner has already checked role, client scope, approval, four-eyes and
# requester verification. These functions never check roles or approvals. They do check the one thing the real adapter
# would be limited by: the Graph permission (scope) the lever needs (Assert-IdScope). They compute the change, return it
# as { data, diff, applied }, and write only when ShouldProcess says yes (not under -WhatIf).
#
# Refusals are thrown. The host turns a throw into "<lever> crashed: <ExceptionType>" with no message text (it reports
# RuntimeException for all of them), so a technician sees "crashed" and the reason is in the operational log. Called
# directly, the type says why: UnauthorizedAccessException = scope not granted, KeyNotFoundException = no such user or
# session record, NotSupportedException = guest user, ArgumentException = bad value.

$script:ScopeFor = @{
    'Revoke-UserSessions' = 'User.RevokeSessions.All'
    'Enable-UserAccount'  = 'User.EnableDisableAccount.All'
    'Set-UserProperty'    = 'User.ReadWrite.All'
}

function Assert-IdScope {
    # Mock of "the app registration holds this Graph permission". REDLINE_MOCK_GRAPH_SCOPES (space, comma or semicolon
    # separated) lists the granted permissions; unset means the registered set is granted (the normal mock run).
    param([Parameter(Mandatory)][string] $Scope)
    $granted = $env:REDLINE_MOCK_GRAPH_SCOPES
    if ([string]::IsNullOrWhiteSpace($granted)) { return }
    $list = @($granted -split '[\s,;]+' | Where-Object { $_ })
    if ($Scope -cnotin $list) {
        throw [System.UnauthorizedAccessException]::new("Graph permission $Scope is not granted; nothing was changed.")
    }
}

function Get-IdTenantDir {
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\fixtures\tenant' }
    $root
}

function Get-IdPath {
    # The only place a client id becomes a path (STD-ID-4): a plain slug, then a file under one folder.
    param([Parameter(Mandatory)][string] $Client, [ValidateSet('tenant', 'sessions')][string] $Kind = 'tenant')
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw [System.ArgumentException]::new('Client id is not a valid slug; no file was read.') }
    $root = Get-IdTenantDir
    $path = if ($Kind -eq 'tenant') { Join-Path $root "$Client.json" } else { Join-Path (Join-Path $root $Client) 'sessions.json' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw [System.IO.FileNotFoundException]::new("No $Kind state for client $Client; nothing was read.") }
    $path
}

function Open-IdJson {
    # JsonNode, not ConvertFrom-Json: nothing (dates, numbers, empty arrays) changes shape on the way back to disk.
    # Nodes travel inside a plain object because PowerShell unrolls enumerable nodes in the pipeline.
    param([Parameter(Mandatory)][string] $Path)
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false))
    $root = [System.Text.Json.Nodes.JsonNode]::Parse($text)
    # Keep the file's own line ending (a Windows checkout is CRLF, and the Python writer follows the platform), so
    # a change and its undo give back the same bytes.
    $eol = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    [pscustomobject]@{ Path = $Path; Root = $root; Eol = $eol }
}

function Save-IdJson {
    # Atomic: write a temp file beside the target, then replace it. Same text layout as the Python MockTenant.save
    # (2-space indent, no ASCII escaping, one trailing newline, the file's own line ending), so disable then enable is byte-identical.
    param([Parameter(Mandatory)] $Doc)
    $options = [System.Text.Json.JsonSerializerOptions]::new()
    $options.WriteIndented = $true
    $options.Encoder = [System.Text.Encodings.Web.JavaScriptEncoder]::UnsafeRelaxedJsonEscaping
    $text = $Doc.Root.ToJsonString($options).Replace("`r`n", "`n").Replace("`n", $Doc.Eol) + $Doc.Eol
    $tmp = "$($Doc.Path).ps$PID.tmp"
    [System.IO.File]::WriteAllText($tmp, $text, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $Doc.Path -Force
}

function Find-IdEntry {
    param([Parameter(Mandatory)] $Doc, [Parameter(Mandatory)][string] $ArrayName, [Parameter(Mandatory)][string] $Upn)
    foreach ($item in $Doc.Root.AsObject()[$ArrayName].AsArray()) {
        $name = $item.AsObject()['userPrincipalName']
        if ($null -ne $name -and [string]::Equals($name.GetValue[string](), $Upn, [System.StringComparison]::OrdinalIgnoreCase)) { return [pscustomobject]@{ Node = $item.AsObject() } }
    }
    throw [System.Collections.Generic.KeyNotFoundException]::new("No user $Upn in this client's state.")
}

function New-IdChange {
    param([string] $Op, [string] $Path, $Before, $After)
    if ($Op -eq 'add') { return [pscustomobject][ordered]@{ op = 'add'; path = $Path; after = $After } }
    [pscustomobject][ordered]@{ op = $Op; path = $Path; before = $Before; after = $After }
}

function Revoke-UserSessions {
    <#
    .SYNOPSIS
      Lever user.revoke-sessions: end a member user's sign-in sessions in the mock (activeSessionCount to 0).
    .DESCRIPTION
      Mock of Graph revokeSignInSessions. A guest user is refused (NotSupportedException): the lever does not apply to
      guests. Convergent: a user with no active sessions gives an empty diff. Needs Graph permission User.RevokeSessions.All.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    Assert-IdScope $script:ScopeFor['Revoke-UserSessions']
    $doc = Open-IdJson (Get-IdPath $Client 'sessions')
    $entry = (Find-IdEntry $doc 'value' $Upn).Node
    if ($entry['userType'].GetValue[string]() -ceq 'Guest') {
        throw [System.NotSupportedException]::new('Revoking sessions does not apply to guest users; nothing was changed.')
    }
    $id = $entry['userId'].GetValue[string]()
    $count = $entry['activeSessionCount'].GetValue[int]()
    $diff = @()
    if ($count -ne 0) { $diff = @(New-IdChange 'replace' "/sessions/$id/activeSessionCount" $count 0) }
    $applied = $false
    if ($diff.Count -gt 0 -and $PSCmdlet.ShouldProcess($Upn, 'revoke sign-in sessions')) {
        $entry['activeSessionCount'] = [System.Text.Json.Nodes.JsonValue]::Create([int] 0)
        Save-IdJson $doc
        $applied = $true
    }
    [pscustomobject][ordered]@{
        data    = [pscustomobject][ordered]@{ user = $Upn; sessionsEnded = $count; lag = 'access tokens already issued can keep working for a short while after revocation' }
        diff    = @($diff)
        applied = $applied
    }
}

function Enable-UserAccount {
    <#
    .SYNOPSIS
      Lever user.enable: set accountEnabled to true. The registered undo of user.disable. Convergent.
    .DESCRIPTION
      Needs Graph permission User.EnableDisableAccount.All (UNVERIFIED name).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    Assert-IdScope $script:ScopeFor['Enable-UserAccount']
    $doc = Open-IdJson (Get-IdPath $Client 'tenant')
    $user = (Find-IdEntry $doc 'users' $Upn).Node
    $id = $user['id'].GetValue[string]()
    $flag = $user['accountEnabled']
    $diff = @()
    if ($null -eq $flag) { $diff = @(New-IdChange 'add' "/users/$id/accountEnabled" $null $true) }
    elseif (-not $flag.GetValue[bool]()) { $diff = @(New-IdChange 'replace' "/users/$id/accountEnabled" $false $true) }
    $applied = $false
    if ($diff.Count -gt 0 -and $PSCmdlet.ShouldProcess($Upn, 'enable the account')) {
        $user['accountEnabled'] = [System.Text.Json.Nodes.JsonValue]::Create($true)
        Save-IdJson $doc
        $applied = $true
    }
    [pscustomobject][ordered]@{
        data    = [pscustomobject][ordered]@{ user = $Upn; accountEnabled = $true }
        diff    = @($diff)
        applied = $applied
    }
}

function Set-UserProperty {
    <#
    .SYNOPSIS
      Lever user.set-properties: set one of department, jobTitle or manager. Nothing else can be set. Convergent.
    .DESCRIPTION
      Field is a closed set (ValidateSet); any other name is refused before a file is read. For manager the value is the
      manager's userPrincipalName; it must be another user of the same client, and is stored as that user's UPN (a mock
      shape: Graph models manager as a relationship, UNVERIFIED here). Needs Graph permission User.ReadWrite.All (UNVERIFIED name).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][ValidateSet('department', 'jobTitle', 'manager')][string] $Field,
        [Parameter(Mandatory)][ValidateLength(1, 113)][string] $Value,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    Assert-IdScope $script:ScopeFor['Set-UserProperty']
    $doc = Open-IdJson (Get-IdPath $Client 'tenant')
    $user = (Find-IdEntry $doc 'users' $Upn).Node
    $id = $user['id'].GetValue[string]()
    $new = $Value
    if ($Field -eq 'manager') {
        $boss = (Find-IdEntry $doc 'users' $Value).Node
        if ([object]::ReferenceEquals($boss, $user)) { throw [System.ArgumentException]::new('A user cannot be their own manager.') }
        $new = $boss['userPrincipalName'].GetValue[string]()
    }
    $current = $user[$Field]
    $path = "/users/$id/$Field"
    $diff = @()
    if ($null -eq $current) { $diff = @(New-IdChange 'add' $path $null $new) }
    elseif ($current.GetValue[string]() -cne $new) { $diff = @(New-IdChange 'replace' $path ($current.GetValue[string]()) $new) }
    $applied = $false
    if ($diff.Count -gt 0 -and $PSCmdlet.ShouldProcess($Upn, "set $Field to '$new'")) {
        $user[$Field] = [System.Text.Json.Nodes.JsonValue]::Create($new)
        Save-IdJson $doc
        $applied = $true
    }
    [pscustomobject][ordered]@{
        data    = [pscustomobject][ordered]@{ user = $Upn; field = $Field; value = $new }
        diff    = @($diff)
        applied = $applied
    }
}

Export-ModuleMember -Function Revoke-UserSessions, Enable-UserAccount, Set-UserProperty
