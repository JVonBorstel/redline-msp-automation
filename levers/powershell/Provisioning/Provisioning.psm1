Set-StrictMode -Version Latest

# Provisioning lever for the Python bridge (B-35): user.new. It works on the offline mock tenant only
# (fixtures/tenant/<client>.json, <client>/mailboxes.json, or the folder named by $env:REDLINE_MOCK_TENANT_DIR, which the
# bridge sets). No network, no credentials, synthetic data only.
#
# Contract with the lever host (B-15): the Python runner has already checked role, client scope, approval (R3: two
# distinct leads), four-eyes and the requester verification. This function never checks roles or approvals. It does check
# the one thing the real adapter would be limited by: the Graph permission (scope) the lever needs (Assert-PvScope). It
# computes the change, returns it as { data, diff, applied }, and writes only when ShouldProcess says yes (not under -WhatIf).
#
# The account is created enabled and with no credential at all: the first sign-in comes from user.new-tap (B-30), a
# separate approved step, so no secret is ever produced or shown here.
#
# Refusals are thrown. The host turns a throw into "<lever> crashed: <ExceptionType>" with no message text. Called
# directly, the type says why: UnauthorizedAccessException = scope not granted, KeyNotFoundException = the manager is
# not a user of this client, InvalidOperationException = the account exists with different values, ArgumentException =
# bad value.

$script:Scope = 'User.ReadWrite.All'   # UNVERIFIED permission name, as for IdentityOps
$script:TextPattern = '^[A-Za-z0-9][A-Za-z0-9 ,&''.@_%+-]{0,112}$'
$script:UpnPattern = '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'

function Assert-PvScope {
    # Mock of "the app registration holds this Graph permission". REDLINE_MOCK_GRAPH_SCOPES (space, comma or semicolon
    # separated) lists the granted permissions; unset means the registered set is granted (the normal mock run).
    $granted = $env:REDLINE_MOCK_GRAPH_SCOPES
    if ([string]::IsNullOrWhiteSpace($granted)) { return }
    $list = @($granted -split '[\s,;]+' | Where-Object { $_ })
    if ($script:Scope -cnotin $list) {
        throw [System.UnauthorizedAccessException]::new("Graph permission $($script:Scope) is not granted; nothing was changed.")
    }
}

function Get-PvPath {
    # The only place a client id becomes a path (STD-ID-4): a plain slug, then a file under one folder.
    param([Parameter(Mandatory)][string] $Client, [ValidateSet('tenant', 'mailboxes')][string] $Kind = 'tenant')
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw [System.ArgumentException]::new('Client id is not a valid slug; no file was read.') }
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\fixtures\tenant' }
    if ($Kind -eq 'tenant') { return Join-Path $root "$Client.json" }
    Join-Path (Join-Path $root $Client) 'mailboxes.json'
}

function Open-PvJson {
    # JsonNode, not ConvertFrom-Json: nothing (dates, numbers, empty arrays) changes shape on the way back to disk.
    param([Parameter(Mandatory)][string] $Path)
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false))
    # Keep the file's own line ending so a change and its undo give back the same bytes.
    $eol = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    [pscustomobject]@{ Path = $Path; Root = [System.Text.Json.Nodes.JsonNode]::Parse($text); Eol = $eol }
}

function Save-PvJson {
    # Atomic: write a temp file beside the target, then replace it. Same layout as the Python MockTenant.save.
    param([Parameter(Mandatory)] $Doc)
    $options = [System.Text.Json.JsonSerializerOptions]::new()
    $options.WriteIndented = $true
    $options.Encoder = [System.Text.Encodings.Web.JavaScriptEncoder]::UnsafeRelaxedJsonEscaping
    $text = $Doc.Root.ToJsonString($options).Replace("`r`n", "`n").Replace("`n", $Doc.Eol) + $Doc.Eol
    $tmp = "$($Doc.Path).ps$PID.tmp"
    [System.IO.File]::WriteAllText($tmp, $text, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $Doc.Path -Force
}

function Find-PvEntry {
    # The entry of an array whose userPrincipalName matches (inside a plain object, because PowerShell unrolls
    # enumerable nodes in the pipeline), or $null.
    param([Parameter(Mandatory)] $Doc, [Parameter(Mandatory)][string] $ArrayName, [Parameter(Mandatory)][string] $Upn)
    foreach ($item in $Doc.Root.AsObject()[$ArrayName].AsArray()) {
        $name = $item.AsObject()['userPrincipalName']
        if ($null -ne $name -and [string]::Equals($name.GetValue[string](), $Upn, [System.StringComparison]::OrdinalIgnoreCase)) { return [pscustomobject]@{ Node = $item.AsObject() } }
    }
    $null
}

function Get-PvText {
    param($Node)
    if ($null -eq $Node) { return '' }
    $Node.GetValue[string]()
}

function New-PvId {
    # An invented, deterministic id (a hash of the seed in GUID shape; not an Entra object id), so a dry-run and the
    # real run agree on every path in the diff.
    param([Parameter(Mandatory)][string] $Seed)
    $hash = [System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($Seed))
    [guid]::new([byte[]] $hash[0..15]).ToString()
}

function Assert-PvText {
    param([Parameter(Mandatory)][string] $Name, [Parameter(Mandatory)][string] $Value, [Parameter(Mandatory)][string] $Pattern)
    if ($Value -cnotmatch $Pattern) { throw [System.ArgumentException]::new("$Name is not an allowed value; nothing was changed.") }
}

function ConvertTo-PvNode {
    # One ordered record to a JsonNode, keys in the order given.
    param([Parameter(Mandatory)] $Record)
    $node = [System.Text.Json.Nodes.JsonNode]::Parse((ConvertTo-Json -InputObject $Record -Depth 6 -Compress))
    , $node   # the comma keeps PowerShell from unrolling the node into its properties
}

function New-UserAccount {
    <#
    .SYNOPSIS
      Lever user.new: create one member user (and its mailbox record) in the mock tenant, enabled, with no credential.
    .DESCRIPTION
      Mock of a Graph user create plus the Exchange mailbox that follows from it (UNVERIFIED: a real tenant creates the
      mailbox from the license, and Graph field names here are the mock's own). Convergent: the same upn with the same
      values gives an empty diff; a half-finished earlier run (user without mailbox record, or the reverse) adds only the
      missing part. The same upn with different values is refused (InvalidOperationException); nothing is overwritten.
      The manager must already be a user of this client. Needs Graph permission User.ReadWrite.All (UNVERIFIED name).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $DisplayName,
        [Parameter(Mandatory)][string] $JobTitle,
        [Parameter(Mandatory)][string] $Department,
        [Parameter(Mandatory)][string] $ManagerUpn,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    Assert-PvScope
    Assert-PvText 'upn' $Upn $script:UpnPattern
    Assert-PvText 'manager_upn' $ManagerUpn $script:UpnPattern
    foreach ($pair in @(@('display_name', $DisplayName), @('job_title', $JobTitle), @('department', $Department))) {
        Assert-PvText $pair[0] $pair[1] $script:TextPattern
    }
    $tenantPath = Get-PvPath $Client 'tenant'
    if (-not (Test-Path -LiteralPath $tenantPath -PathType Leaf)) { throw [System.IO.FileNotFoundException]::new("No tenant state for client $Client; nothing was read.") }
    $doc = Open-PvJson $tenantPath
    $boss = Find-PvEntry $doc 'users' $ManagerUpn
    if ($null -eq $boss) { throw [System.Collections.Generic.KeyNotFoundException]::new("No manager $ManagerUpn in this client's state.") }
    $bossUpn = Get-PvText $boss.Node['userPrincipalName']
    if ([string]::Equals($bossUpn, $Upn, [System.StringComparison]::OrdinalIgnoreCase)) { throw [System.ArgumentException]::new('A user cannot be their own manager.') }

    $id = New-PvId "user|$Client|$($Upn.ToLowerInvariant())"
    $existing = Find-PvEntry $doc 'users' $Upn
    $diff = @()
    $userAction = 'created'
    if ($null -ne $existing) {
        $node = $existing.Node
        $id = Get-PvText $node['id']
        $found = @((Get-PvText $node['displayName']), (Get-PvText $node['jobTitle']), (Get-PvText $node['department']), (Get-PvText $node['manager']))
        $wanted = @($DisplayName, $JobTitle, $Department, $bossUpn)
        $same = $true
        for ($i = 0; $i -lt $wanted.Count; $i++) { if ($found[$i] -cne $wanted[$i]) { $same = $false } }
        if (-not $same) { throw [System.InvalidOperationException]::new("User $Upn already exists with different values; nothing was changed.") }
        $userAction = 'already present'
    }
    else {
        # The diff carries the whole record, so what is applied is exactly what was shown (and a plan can replay it).
        $userRecord = [ordered]@{ id = $id; displayName = $DisplayName; userPrincipalName = $Upn; jobTitle = $JobTitle; department = $Department; manager = $bossUpn; accountEnabled = $true }
        $diff += [pscustomobject][ordered]@{ op = 'add'; path = "/users/$id"; after = $userRecord }
    }

    # The mailbox record is optional in the mock: a client with no mailboxes.json has none to keep.
    $mailPath = Get-PvPath $Client 'mailboxes'
    $mailDoc = $null; $mailId = $null; $mailAction = 'not tracked for this client'
    if (Test-Path -LiteralPath $mailPath -PathType Leaf) {
        $mailDoc = Open-PvJson $mailPath
        if ($null -ne (Find-PvEntry $mailDoc 'mailboxes' $Upn)) { $mailAction = 'already present' }
        else {
            $mailAction = 'created'
            $mailId = New-PvId "mailbox|$Client|$($Upn.ToLowerInvariant())"
            $mailRecord = [ordered]@{
                id = $mailId; userPrincipalName = $Upn; displayName = $DisplayName; recipientTypeDetails = 'UserMailbox'
                totalItemSizeGb = 0; archiveStatus = 'None'
                autoReply = [ordered]@{ state = 'Disabled'; internalMessage = $null; externalMessage = $null; externalAudience = 'None' }
                forwardingSmtpAddress = $null; fullAccess = @(); sendAs = @()
            }
            $diff += [pscustomobject][ordered]@{ op = 'add'; path = "/mailboxes/$mailId"; after = $mailRecord }
        }
    }

    $applied = $false
    if ($diff.Count -gt 0 -and $PSCmdlet.ShouldProcess($Upn, 'create the account')) {
        # Mailbox first: a crash between the two saves leaves a mailbox record, and the next run adds only the user.
        if ($mailAction -eq 'created') {
            $mailDoc.Root.AsObject()['mailboxes'].AsArray().Add((ConvertTo-PvNode $mailRecord))
            Save-PvJson $mailDoc
        }
        if ($userAction -eq 'created') {
            $doc.Root.AsObject()['users'].AsArray().Add((ConvertTo-PvNode $userRecord))
            Save-PvJson $doc
        }
        $applied = $true
    }
    [pscustomobject][ordered]@{
        data    = [pscustomobject][ordered]@{
            user = $Upn; id = $id; account = $userAction; mailbox = $mailAction; accountEnabled = $true
            signIn = 'no credential yet; user.new-tap issues the first sign-in as a separate approved step'
        }
        diff    = @($diff)
        applied = $applied
    }
}

Export-ModuleMember -Function New-UserAccount
