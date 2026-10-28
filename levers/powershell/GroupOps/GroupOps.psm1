Set-StrictMode -Version Latest

# Group membership levers (B-32): group.add-member and group.remove-member on the offline mock tenant.
# Reads the client's base file (users) and its groups family file (fixtures/tenant/<client>/groups.json, or the folder
# named by $env:REDLINE_MOCK_TENANT_DIR, which the bridge sets). No network, no credentials.
#
# Contract with the lever host (B-15): the Python runner has already decided the call is allowed (role, scope, approval).
# This module adds the one rule that belongs to the data: a role-assignable group, or a group on the client's own
# privileged list, is never changed by automation (W-IDM-07). It reports that as a `refusal`, which the host turns into a
# "denied" result carrying the reason. The diff shape is the runner's (STD-LV-5): members are keyed by id, so the path is
# /groups/<group id>/members/<user id>.

function Get-GoTenantRoot {
    param([Parameter(Mandatory)][string] $Client)
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw "Client id is not a valid slug; no file was read." }
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\fixtures\tenant' }
    $root
}

function Read-GoJson {
    param([Parameter(Mandatory)][string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "A mock tenant file is missing; nothing was read." }
    # A JSON node is enumerable and PowerShell unrolls it in the pipeline, so it travels inside a plain object.
    $node = [System.Text.Json.Nodes.JsonNode]::Parse([System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false)))
    [pscustomobject]@{ Root = $node }
}

function Save-GoJson {
    # Atomic: temp file beside the target, then replace, so a kill never leaves half a file.
    param([Parameter(Mandatory)][string] $Path, [Parameter(Mandatory)] $Root)
    $options = [System.Text.Json.JsonSerializerOptions]::new()
    $options.WriteIndented = $true
    $options.Encoder = [System.Text.Encodings.Web.JavaScriptEncoder]::UnsafeRelaxedJsonEscaping
    $text = $Root.ToJsonString($options).Replace("`r`n", "`n") + "`n"
    $tmp = "$Path.ps$PID.tmp"
    [System.IO.File]::WriteAllText($tmp, $text, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Get-GoString {
    param($Node)
    if ($null -eq $Node) { return $null }
    $Node.GetValue[string]()
}

function Invoke-GoMembership {
    param(
        [Parameter(Mandatory)][ValidateSet('add', 'remove')][string] $Action,
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $GroupId,
        [Parameter(Mandatory)][string] $Client,
        [Parameter(Mandatory)] $Cmdlet
    )
    $root = Get-GoTenantRoot $Client
    $groupsPath = Join-Path (Join-Path $root $Client) 'groups.json'
    $groupsRoot = (Read-GoJson $groupsPath).Root
    $tenantRoot = (Read-GoJson (Join-Path $root "$Client.json")).Root

    $group = $null
    foreach ($candidate in $groupsRoot.AsObject()['value'].AsArray()) {
        if ((Get-GoString ($candidate.AsObject()['id'])) -ceq $GroupId) { $group = $candidate.AsObject(); break }
    }
    if ($null -eq $group) { return [pscustomobject]@{ refusal = "No group $GroupId in this client's tenant; nothing changed." } }
    $name = Get-GoString $group['displayName']

    # W-IDM-07: admin rights are never granted or taken away by automation, and a group that can hold a directory role,
    # or that the client listed as privileged, is exactly that.
    $assignable = $false
    if ($null -ne $group['isAssignableToRole']) { $assignable = $group['isAssignableToRole'].GetValue[bool]() }
    $listed = $false
    $privileged = $groupsRoot.AsObject()['redlinePrivilegedGroups']
    if ($null -ne $privileged) {
        foreach ($item in $privileged.AsArray()) {
            if ([string]::Equals((Get-GoString $item), $name, [System.StringComparison]::OrdinalIgnoreCase)) { $listed = $true }
        }
    }
    if ($assignable -or $listed) {
        $why = if ($assignable) { 'it can be assigned a directory role' } else { "it is on $Client's privileged group list" }
        return [pscustomobject]@{ refusal = "Refused (W-IDM-07): group '$name' is privileged because $why. Privileged access is granted by a person, never by automation; nothing changed." }
    }

    $user = $null
    foreach ($candidate in $tenantRoot.AsObject()['users'].AsArray()) {
        $upnNode = $candidate.AsObject()['userPrincipalName']
        if ([string]::Equals((Get-GoString $upnNode), $Upn, [System.StringComparison]::OrdinalIgnoreCase)) { $user = $candidate.AsObject(); break }
    }
    if ($null -eq $user) { return [pscustomobject]@{ refusal = "No user $Upn in this client's tenant; nothing changed." } }
    $userId = Get-GoString $user['id']
    $userUpn = Get-GoString $user['userPrincipalName']

    $members = $group['members'].AsArray()
    $index = -1
    for ($i = 0; $i -lt $members.Count; $i++) {
        if ((Get-GoString ($members[$i].AsObject()['id'])) -ceq $userId) { $index = $i; break }
    }
    # R1 only for a group that is known to be distribution only; anything else (data, unknown, missing) is R2.
    $accessClass = if ($null -ne $group['redlineAccessClass']) { Get-GoString $group['redlineAccessClass'] } else { 'unknown' }
    $class = if ($accessClass -ceq 'distribution') { 'R1' } else { 'R2' }

    $path = "/groups/$GroupId/members/$userId"
    $entry = [pscustomobject][ordered]@{ id = $userId; userPrincipalName = $userUpn }
    $diff = @()
    if ($Action -ceq 'add' -and $index -lt 0) {
        $diff = @([pscustomobject][ordered]@{ op = 'add'; path = $path; after = $entry })
    }
    elseif ($Action -ceq 'remove' -and $index -ge 0) {
        $diff = @([pscustomobject][ordered]@{ op = 'remove'; path = $path; before = $entry })
    }

    $applied = $false
    $verb = if ($Action -ceq 'add') { "add to group '$name'" } else { "remove from group '$name'" }
    if ($diff.Count -gt 0 -and $Cmdlet.ShouldProcess($userUpn, $verb)) {
        if ($Action -ceq 'add') {
            $node = [System.Text.Json.Nodes.JsonObject]::new()
            $node.Add('id', [System.Text.Json.Nodes.JsonValue]::Create($userId))
            $node.Add('userPrincipalName', [System.Text.Json.Nodes.JsonValue]::Create($userUpn))
            $members.Add($node)
        }
        else {
            $members.RemoveAt($index)
        }
        Save-GoJson $groupsPath $groupsRoot
        $applied = $true
    }
    [pscustomobject][ordered]@{
        data    = [pscustomobject][ordered]@{ group = $name; groupId = $GroupId; user = $userUpn; accessClass = $accessClass; riskClass = $class }
        diff    = @($diff)
        applied = $applied
    }
}

function Add-GroupMember {
    <#
    .SYNOPSIS
      Lever group.add-member: add one user to one group. Convergent: a user already in the group is an empty diff.
    .DESCRIPTION
      Refuses a role-assignable group or a group on the client's privileged list (W-IDM-07). Returns { data, diff, applied };
      data.riskClass says R2 (group grants data access) or R1 (distribution only). Under -WhatIf nothing is written.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $GroupId,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    Invoke-GoMembership -Action add -Upn $Upn -GroupId $GroupId -Client $Client -Cmdlet $PSCmdlet
}

function Remove-GroupMember {
    <#
    .SYNOPSIS
      Lever group.remove-member: remove one user from one group; the undo of Add-GroupMember. Convergent.
    .DESCRIPTION
      Same refusal rule as Add-GroupMember (a person, not automation, changes privileged groups).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $GroupId,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    Invoke-GoMembership -Action remove -Upn $Upn -GroupId $GroupId -Client $Client -Cmdlet $PSCmdlet
}

Export-ModuleMember -Function Add-GroupMember, Remove-GroupMember
