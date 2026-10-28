Set-StrictMode -Version Latest

# Credential levers for the Python bridge (B-30): user.reset-password and user.new-tap. They work on the offline mock tenant
# only (fixtures/tenant/<client>.json, or the folder named by $env:REDLINE_MOCK_TENANT_DIR, which the bridge sets). No network.
#
# Contract with the lever host (B-15, B-16): the Python runner has already decided the call is allowed (role, scope, two
# approvals, requester+contact verification, privileged-target refusal). This module re-checks the privileged-role refusal
# anyway (defence in depth, D6-06) and never decides anything else about permissions.
#
# THE RULE (B30-1): the generated value is written to exactly one place, the out-of-band file
# <oob root>/<client>/<user id>-<type>.json (root: $env:REDLINE_OOB_DIR, else .tmp/oob in the repository). It is never put
# in the returned object, the diff, the tenant file, an error message or the log. Python reads it back with core/levers/oob.py.
#
# UNVERIFIED (no vendor page was read for this prototype): the exact Microsoft Graph shape of a Temporary Access Pass
# (temporaryAccessPassAuthenticationMethod fields isUsableOnce and lifetimeInMinutes), the tenant policy's minimum lifetime
# and its default length. The mock uses the names below and the constants in this file; the real adapter must confirm them.

$script:TapDefaultMinimumMinutes = 10   # UNVERIFIED default used when the mock tenant carries no policy
$script:PasswordHandoffMinutes = 60     # how long the out-of-band value stays readable (mock channel window)
$script:TapLength = 8                   # UNVERIFIED
$script:PasswordLength = 20

function Get-CoTenantPath {
    param([Parameter(Mandatory)][string] $Client)
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw "Client id is not a valid slug; no file was read." }
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\fixtures\tenant' }
    $path = Join-Path $root "$Client.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "No mock tenant for client $Client; nothing was read." }
    $path
}

function Open-CoTenant {
    param([Parameter(Mandatory)][string] $Client)
    $path = Get-CoTenantPath $Client
    $root = [System.Text.Json.Nodes.JsonNode]::Parse([System.IO.File]::ReadAllText($path, [System.Text.UTF8Encoding]::new($false)))
    [pscustomobject]@{ Path = $path; Root = $root }
}

function Find-CoUser {
    param([Parameter(Mandatory)] $Tenant, [Parameter(Mandatory)][string] $Upn)
    foreach ($user in $Tenant.Root.AsObject()['users'].AsArray()) {
        $name = $user.AsObject()['userPrincipalName']
        if ($null -ne $name -and [string]::Equals($name.GetValue[string](), $Upn, [System.StringComparison]::OrdinalIgnoreCase)) {
            return [pscustomobject]@{ Node = $user.AsObject() }
        }
    }
    throw "No user $Upn in this client's tenant; no credential was issued."
}

function Save-CoTenant {
    param([Parameter(Mandatory)] $Tenant)
    $options = [System.Text.Json.JsonSerializerOptions]::new()
    $options.WriteIndented = $true
    $options.Encoder = [System.Text.Encodings.Web.JavaScriptEncoder]::UnsafeRelaxedJsonEscaping
    $text = $Tenant.Root.ToJsonString($options).Replace("`r`n", "`n") + "`n"
    $tmp = "$($Tenant.Path).ps$PID.tmp"
    [System.IO.File]::WriteAllText($tmp, $text, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $Tenant.Path -Force
}

function Assert-CoNotPrivileged {
    # D6-06: an account holding a directory role is never reset on a phone request. The runner refuses first; this is the second lock.
    param([Parameter(Mandatory)] $Tenant, [Parameter(Mandatory)][string] $Upn)
    $roles = $Tenant.Root.AsObject()['directoryRoles']
    if ($null -eq $roles) { return }
    foreach ($role in $roles.AsArray()) {
        $members = $role.AsObject()['members']
        if ($null -eq $members) { continue }
        foreach ($member in $members.AsArray()) {
            $name = $member.AsObject()['userPrincipalName']
            if ($null -ne $name -and [string]::Equals($name.GetValue[string](), $Upn, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "$Upn holds a privileged directory role; this is a human-only procedure (D6-06). No credential was issued."
            }
        }
    }
}

function Get-CoTapLifetime {
    # The shortest lifetime the tenant policy allows (D6-06). Reads the optional mock policy; refuses when TAP is switched off.
    param([Parameter(Mandatory)] $Tenant)
    $minutes = $script:TapDefaultMinimumMinutes
    $policy = $Tenant.Root.AsObject()['authenticationMethodsPolicy']
    if ($null -ne $policy) {
        $tap = $policy.AsObject()['temporaryAccessPass']
        if ($null -ne $tap) {
            $state = $tap.AsObject()['state']
            if ($null -ne $state -and $state.GetValue[string]() -cne 'enabled') { throw "Temporary Access Pass is not enabled in this tenant's policy; no credential was issued." }
            $min = $tap.AsObject()['minimumLifetimeInMinutes']
            if ($null -ne $min) { $minutes = $min.GetValue[int]() }
        }
    }
    if ($minutes -lt 1 -or $minutes -gt 43200) { throw "The tenant policy's Temporary Access Pass lifetime is out of range; no credential was issued." }
    $minutes
}

function New-CoSecret {
    # Cryptographically random, from an alphabet without look-alike characters. The caller hands it to Write-CoOob and nowhere else.
    param([Parameter(Mandatory)][int] $Length, [switch] $Mixed)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]
    $upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ'; $lower = 'abcdefghijkmnpqrstuvwxyz'; $digit = '23456789'; $symbol = '!#%+=?@'
    $pools = if ($Mixed) { @($upper, $lower, $digit, $symbol) } else { @(($upper + $lower + $digit)) }
    $all = -join $pools
    $chars = [System.Collections.Generic.List[char]]::new()
    foreach ($pool in $pools) { $chars.Add($pool[$rng::GetInt32($pool.Length)]) }
    while ($chars.Count -lt $Length) { $chars.Add($all[$rng::GetInt32($all.Length)]) }
    for ($i = $chars.Count - 1; $i -gt 0; $i--) { $j = $rng::GetInt32($i + 1); $t = $chars[$i]; $chars[$i] = $chars[$j]; $chars[$j] = $t }
    -join $chars
}

function Get-CoOobPath {
    param([Parameter(Mandatory)][string] $Client, [Parameter(Mandatory)][string] $UserId, [Parameter(Mandatory)][ValidateSet('password', 'tap')][string] $Type)
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw "Client id is not a valid slug; nothing was written." }
    if ($UserId -cnotmatch '^[A-Za-z0-9-]{1,64}$') { throw "User id is not a plain id; nothing was written." }
    $root = $env:REDLINE_OOB_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\.tmp\oob' }
    Join-Path (Join-Path $root $Client) "$UserId-$Type.json"
}

function Write-CoOob {
    # The only place a secret leaves this module. Atomic write to the out-of-band file; the value is never returned.
    param([Parameter(Mandatory)][string] $Path, [Parameter(Mandatory)] $Record)
    $dir = Split-Path -Parent $Path
    [void][System.IO.Directory]::CreateDirectory($dir)
    $tmp = "$Path.ps$PID.tmp"
    [System.IO.File]::WriteAllText($tmp, ($Record | ConvertTo-Json -Depth 5 -Compress), [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Get-CoMethodId {
    # A fixed id per user and kind, so the dry-run diff and the execute diff are identical (the runner compares them).
    param([Parameter(Mandatory)][string] $UserId, [Parameter(Mandatory)][string] $Kind)
    $md5 = [System.Security.Cryptography.MD5]::Create()
    try { ([guid]::new($md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes("credentialops/$UserId/$Kind")))).ToString() } finally { $md5.Dispose() }
}

function Test-CoPending {
    param([Parameter(Mandatory)] $User, [Parameter(Mandatory)][string] $Type)
    $all = $User['pendingCredentials']
    $null -ne $all -and $null -ne $all.AsObject()[$Type]
}

function Set-CoPending {
    # The audit-safe marker that a credential was issued: type, single-use flag and lifetime. Never the value.
    param([Parameter(Mandatory)] $User, [Parameter(Mandatory)][string] $Type, [Parameter(Mandatory)][int] $Minutes)
    $all = $User['pendingCredentials']
    if ($null -eq $all) { $all = [System.Text.Json.Nodes.JsonObject]::new(); $User['pendingCredentials'] = $all }
    $node = [System.Text.Json.Nodes.JsonObject]::new()
    $node['type'] = [System.Text.Json.Nodes.JsonValue]::Create($Type)
    $node['singleUse'] = [System.Text.Json.Nodes.JsonValue]::Create($true)
    $node['expiryMinutes'] = [System.Text.Json.Nodes.JsonValue]::Create($Minutes)
    $all.AsObject()[$Type] = $node
}

function Reset-UserPassword {
    <#
    .SYNOPSIS
      Lever user.reset-password: issue a new one-time password to the out-of-band channel and force a change at next sign-in.
    .DESCRIPTION
      Returns { data, diff, applied }. The data holds the target id, the credential type, the handoff window in minutes and
      the word "out-of-band" and nothing else: never the password. Under -WhatIf nothing is generated and nothing is written.
      Convergent: while a credential is pending for the user, the diff is empty and no second value is issued.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    $tenant = Open-CoTenant $Client
    $user = (Find-CoUser $tenant $Upn).Node
    Assert-CoNotPrivileged $tenant $Upn
    $id = $user['id'].GetValue[string]()
    $minutes = $script:PasswordHandoffMinutes
    $diff = @()
    if (-not (Test-CoPending $user 'password')) {
        $pp = $user['passwordProfile']
        if ($null -eq $pp) {
            $diff += [pscustomobject][ordered]@{ op = 'add'; path = "/users/$id/passwordProfile"; after = [ordered]@{ forceChangePasswordNextSignIn = $true } }
        }
        else {
            $flag = $pp.AsObject()['forceChangePasswordNextSignIn']
            if ($null -eq $flag) { $diff += [pscustomobject][ordered]@{ op = 'add'; path = "/users/$id/passwordProfile/forceChangePasswordNextSignIn"; after = $true } }
            elseif (-not $flag.GetValue[bool]()) { $diff += [pscustomobject][ordered]@{ op = 'replace'; path = "/users/$id/passwordProfile/forceChangePasswordNextSignIn"; before = $false; after = $true } }
        }
        $diff += [pscustomobject][ordered]@{ op = 'add'; path = "/users/$id/pendingCredentials/password"; after = [ordered]@{ type = 'password'; singleUse = $true; expiryMinutes = $minutes } }
    }
    $applied = $false
    if ($diff.Count -gt 0 -and $PSCmdlet.ShouldProcess($Upn, 'issue a one-time password through the out-of-band channel')) {
        $oob = Get-CoOobPath $Client $id 'password'
        $now = [datetime]::UtcNow
        $secret = New-CoSecret -Length $script:PasswordLength -Mixed
        Write-CoOob $oob ([ordered]@{ v = 1; client = $Client; target_id = $id; upn = $Upn; type = 'password'; single_use = $true
                issued_at = $now.ToString('o'); expires_at = $now.AddMinutes($minutes).ToString('o'); value = $secret })
        $secret = $null
        try {
            $profileNode = $user['passwordProfile']
            if ($null -eq $profileNode) { $profileNode = [System.Text.Json.Nodes.JsonObject]::new(); $user['passwordProfile'] = $profileNode }
            $profileNode['forceChangePasswordNextSignIn'] = [System.Text.Json.Nodes.JsonValue]::Create($true)
            Set-CoPending $user 'password' $minutes
            Save-CoTenant $tenant
        }
        catch {
            Remove-Item -LiteralPath $oob -Force -ErrorAction SilentlyContinue
            throw
        }
        $applied = $true
    }
    [pscustomobject][ordered]@{
        data    = [pscustomobject][ordered]@{ target_id = $id; credential_type = 'password'; expiry_minutes = $minutes; delivery = 'out-of-band' }
        diff    = @($diff)
        applied = $applied
    }
}

function New-UserTap {
    <#
    .SYNOPSIS
      Lever user.new-tap: issue a single-use Temporary Access Pass with the shortest lifetime the tenant policy allows.
    .DESCRIPTION
      Returns { data, diff, applied }. The pass goes only to the out-of-band file. The tenant file records the method
      (single-use flag and lifetime), never the pass. Convergent: while a pass exists for the user, the diff is empty.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    $tenant = Open-CoTenant $Client
    $user = (Find-CoUser $tenant $Upn).Node
    Assert-CoNotPrivileged $tenant $Upn
    $id = $user['id'].GetValue[string]()
    $minutes = Get-CoTapLifetime $tenant
    $tapType = '#microsoft.graph.temporaryAccessPassAuthenticationMethod'
    $existing = Test-CoPending $user 'tap'
    $auth = $user['authentication']
    if ($null -ne $auth -and $null -ne $auth.AsObject()['methods']) {
        foreach ($m in $auth.AsObject()['methods'].AsArray()) {
            $t = $m.AsObject()['@odata.type']
            if ($null -ne $t -and $t.GetValue[string]() -ceq $tapType) { $existing = $true }
        }
    }
    $methodId = Get-CoMethodId $id 'tap'
    $diff = @()
    if (-not $existing) {
        $diff += [pscustomobject][ordered]@{ op = 'add'; path = "/users/$id/authentication/methods/$methodId"
            after = [ordered]@{ '@odata.type' = $tapType; id = $methodId; isUsableOnce = $true; lifetimeInMinutes = $minutes } }
        $diff += [pscustomobject][ordered]@{ op = 'add'; path = "/users/$id/pendingCredentials/tap"; after = [ordered]@{ type = 'tap'; singleUse = $true; expiryMinutes = $minutes } }
    }
    $applied = $false
    if ($diff.Count -gt 0 -and $PSCmdlet.ShouldProcess($Upn, 'issue a single-use Temporary Access Pass through the out-of-band channel')) {
        $oob = Get-CoOobPath $Client $id 'tap'
        $now = [datetime]::UtcNow
        $secret = New-CoSecret -Length $script:TapLength
        Write-CoOob $oob ([ordered]@{ v = 1; client = $Client; target_id = $id; upn = $Upn; type = 'tap'; single_use = $true
                issued_at = $now.ToString('o'); expires_at = $now.AddMinutes($minutes).ToString('o'); value = $secret })
        $secret = $null
        try {
            if ($null -eq $auth) { $auth = [System.Text.Json.Nodes.JsonObject]::new(); $user['authentication'] = $auth }
            if ($null -eq $auth.AsObject()['methods']) { $auth.AsObject()['methods'] = [System.Text.Json.Nodes.JsonArray]::new() }
            $node = [System.Text.Json.Nodes.JsonObject]::new()
            $node['@odata.type'] = [System.Text.Json.Nodes.JsonValue]::Create($tapType)
            $node['id'] = [System.Text.Json.Nodes.JsonValue]::Create($methodId)
            $node['isUsableOnce'] = [System.Text.Json.Nodes.JsonValue]::Create($true)
            $node['lifetimeInMinutes'] = [System.Text.Json.Nodes.JsonValue]::Create($minutes)
            $auth.AsObject()['methods'].AsArray().Add($node)
            Set-CoPending $user 'tap' $minutes
            Save-CoTenant $tenant
        }
        catch {
            Remove-Item -LiteralPath $oob -Force -ErrorAction SilentlyContinue
            throw
        }
        $applied = $true
    }
    [pscustomobject][ordered]@{
        data    = [pscustomobject][ordered]@{ target_id = $id; credential_type = 'tap'; expiry_minutes = $minutes; delivery = 'out-of-band' }
        diff    = @($diff)
        applied = $applied
    }
}

Export-ModuleMember -Function Reset-UserPassword, New-UserTap
