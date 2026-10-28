Set-StrictMode -Version Latest

# Sample levers for the Python bridge (B-16). They work on the offline mock tenant only (fixtures/tenant/<client>.json,
# or the folder named by $env:REDLINE_MOCK_TENANT_DIR, which the bridge sets). No network, no credentials.
#
# Contract with the lever host (B-15): the Python runner has already decided that the call is allowed. These functions
# never check roles or approvals. They receive the one client id from the host (-Client), compute the change, and apply it
# only when ShouldProcess says yes (not under -WhatIf). The diff shape is the one the Python runner produces (STD-LV-5):
# users are keyed by id, so the path is /users/<id>/<field>.

function Get-SmTenantPath {
    # The only place a client id becomes a path (STD-ID-4): a plain slug, then a file under one folder.
    param([Parameter(Mandatory)][string] $Client)
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw "Client id is not a valid slug; no file was read." }
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\fixtures\tenant' }
    $path = Join-Path $root "$Client.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "No mock tenant for client $Client; nothing was read." }
    $path
}

function Open-SmTenant {
    # JsonNode, not ConvertFrom-Json: nothing (dates, numbers, empty arrays) changes shape on the way back to disk.
    # A JSON node is enumerable and PowerShell unrolls it in the pipeline, so nodes travel inside a plain object.
    param([Parameter(Mandatory)][string] $Client)
    $path = Get-SmTenantPath $Client
    $root = [System.Text.Json.Nodes.JsonNode]::Parse([System.IO.File]::ReadAllText($path, [System.Text.UTF8Encoding]::new($false)))
    [pscustomobject]@{ Path = $path; Root = $root }
}

function Find-SmUser {
    param([Parameter(Mandatory)] $Tenant, [Parameter(Mandatory)][string] $Upn)
    foreach ($user in $Tenant.Root.AsObject()['users'].AsArray()) {
        $name = $user.AsObject()['userPrincipalName']
        if ($null -ne $name -and [string]::Equals($name.GetValue[string](), $Upn, [System.StringComparison]::OrdinalIgnoreCase)) {
            return [pscustomobject]@{ Node = $user.AsObject() }
        }
    }
    throw "No user $Upn in this client's tenant."
}

function Save-SmTenant {
    # Atomic: write a temp file beside the target, then replace it, so a kill never leaves half a file.
    param([Parameter(Mandatory)] $Tenant)
    $options = [System.Text.Json.JsonSerializerOptions]::new()
    $options.WriteIndented = $true
    $options.Encoder = [System.Text.Encodings.Web.JavaScriptEncoder]::UnsafeRelaxedJsonEscaping
    $text = $Tenant.Root.ToJsonString($options).Replace("`r`n", "`n") + "`n"
    $tmp = "$($Tenant.Path).ps$PID.tmp"
    [System.IO.File]::WriteAllText($tmp, $text, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $Tenant.Path -Force
}

function Get-SampleUser {
    <#
    .SYNOPSIS
      Sample read lever sampleuser.get: one user's display name, title and enabled flag (no contact or sign-in details).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    $tenant = Open-SmTenant $Client
    $user = (Find-SmUser $tenant $Upn).Node
    $title = $user['jobTitle']
    [pscustomobject][ordered]@{
        id                = $user['id'].GetValue[string]()
        displayName       = $user['displayName'].GetValue[string]()
        userPrincipalName = $user['userPrincipalName'].GetValue[string]()
        jobTitle          = if ($null -eq $title) { $null } else { $title.GetValue[string]() }
        accountEnabled    = $user['accountEnabled'].GetValue[bool]()
    }
}

function Set-SampleUserTitle {
    <#
    .SYNOPSIS
      Sample write lever sampleuser.set-title: set one user's job title. Convergent: the same title again is an empty diff.
    .DESCRIPTION
      Returns { data, diff, applied }. Under -WhatIf it computes the diff and applies nothing. Otherwise it applies exactly
      the diff it returns, in one atomic file replace.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $Title,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    $tenant = Open-SmTenant $Client
    $user = (Find-SmUser $tenant $Upn).Node
    $id = $user['id'].GetValue[string]()
    $current = $user['jobTitle']
    $diff = @()
    if ($null -eq $current) {
        $diff = @([pscustomobject][ordered]@{ op = 'add'; path = "/users/$id/jobTitle"; after = $Title })
    }
    elseif ($current.GetValue[string]() -cne $Title) {
        $diff = @([pscustomobject][ordered]@{ op = 'replace'; path = "/users/$id/jobTitle"; before = $current.GetValue[string](); after = $Title })
    }
    $applied = $false
    if ($diff.Count -gt 0 -and $PSCmdlet.ShouldProcess($Upn, "set job title to '$Title'")) {
        $user['jobTitle'] = [System.Text.Json.Nodes.JsonValue]::Create($Title)
        Save-SmTenant $tenant
        $applied = $true
    }
    [pscustomobject][ordered]@{
        data    = [pscustomobject][ordered]@{ user = $Upn; jobTitle = $Title }
        diff    = @($diff)
        applied = $applied
    }
}

Export-ModuleMember -Function Get-SampleUser, Set-SampleUserTitle
