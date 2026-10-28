Set-StrictMode -Version Latest

# DeviceR3 levers (B-65). They work on the offline mock device state only: <tenant folder>/<client>/devices.json (the folder is
# fixtures/tenant, or $env:REDLINE_MOCK_TENANT_DIR, which the Python bridge sets). No network, no credentials, no RMM, Intune or
# Defender call. The real products these stand in for are described in SOURCES.md (all UNVERIFIED).
#
# Contract with the lever host (B-15): the Python runner has already decided that the call is allowed (role, client scope, two
# lead approvals for an R3 lever, requester verification, window, caps). These functions never check roles or approvals. They
# receive the one client id from the host (-Client), compute the change for ONE device, and apply it only when ShouldProcess says
# yes (not under -WhatIf). Every function returns { data, diff, applied }; the same call again is an empty diff (convergent).
#
# Refusals are typed exceptions (a direct call shows the type and message; through the lever host the audit shows only
# 'crashed: RuntimeException', never the message text, so the reason is read from the module or its tests):
#   KeyNotFoundException       no such device for this client, or the owner does not match (one answer for all three, C-27)
#   InvalidOperationException  the device is under legal hold and may not be wiped or retired (or is in an unexpected state)
#   NotSupportedException      the device is already retired, so it is no longer managed
#
# Wipe is a REQUEST only: this module sets wipe.state to 'requested' and never anything further. A person starts the wipe in the
# console after the approval (D6-08). There is no function that undoes a wipe or a retire.

function Get-DrStatePath {
    # The only place a client id becomes a path (STD-ID-4): a plain slug, then one file under one folder.
    param([Parameter(Mandatory)][string] $Client)
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw "Client id is not a valid slug; no file was read." }
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\fixtures\tenant' }
    $path = Join-Path (Join-Path $root $Client) 'devices.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "No device state for client $Client; nothing was read." }
    $path
}

function Get-DrText {
    param($Node)
    if ($null -eq $Node) { $null } else { $Node.GetValue[string]() }
}

function Open-DrState {
    # JsonNode, not ConvertFrom-Json: nothing (dates, numbers, empty arrays) changes shape on the way back to disk.
    param([Parameter(Mandatory)][string] $Client)
    $path = Get-DrStatePath $Client
    $root = [System.Text.Json.Nodes.JsonNode]::Parse([System.IO.File]::ReadAllText($path, [System.Text.UTF8Encoding]::new($false)))
    $meta = $root.AsObject()['_meta']
    if ($null -eq $meta -or (Get-DrText $meta.AsObject()['client']) -cne $Client) { throw "Device state does not belong to client $Client; nothing was read." }
    [pscustomobject]@{ Path = $path; Root = $root.AsObject() }
}

function Save-DrState {
    # Atomic: write a temp file beside the target, then replace it, so a kill never leaves half a file.
    param([Parameter(Mandatory)] $State)
    $options = [System.Text.Json.JsonSerializerOptions]::new()
    $options.WriteIndented = $true
    $options.Encoder = [System.Text.Encodings.Web.JavaScriptEncoder]::UnsafeRelaxedJsonEscaping
    $text = $State.Root.ToJsonString($options).Replace("`r`n", "`n") + "`n"
    $tmp = "$($State.Path).ps$PID.tmp"
    [System.IO.File]::WriteAllText($tmp, $text, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $State.Path -Force
}

function Find-DrDevice {
    # One answer for "absent", "belongs to another client" (it is simply not in this client's file) and "owner does not match".
    param([Parameter(Mandatory)] $State, [Parameter(Mandatory)][string] $Device, [Parameter(Mandatory)][string] $Upn)
    foreach ($item in $State.Root['devices'].AsArray()) {
        $dev = $item.AsObject()
        $sameUid = [string]::Equals((Get-DrText $dev['uid']), $Device, [System.StringComparison]::OrdinalIgnoreCase)
        $sameOwner = [string]::Equals((Get-DrText $dev['owner']), $Upn, [System.StringComparison]::OrdinalIgnoreCase)
        if ($sameUid -and $sameOwner) { return ,$dev }
    }
    throw [System.Collections.Generic.KeyNotFoundException]::new('No such device for this user in this client; nothing was changed.')
}

function New-DrChange {
    param([Parameter(Mandatory)][string] $Path, $Before, $After)
    [pscustomobject][ordered]@{ op = 'replace'; path = $Path; before = $Before; after = $After }
}

# action -> section inside the device that holds the state, the state before and after, the undo line, and what it is called.
# Managed: the action needs a device that is still enrolled. Destructive: refused for a device under legal hold.
$script:DrActions = @{
    lock    = @{ Section = 'lock'; From = 'unlocked'; To = 'locked'; Undo = 'undo: device.unlock'; Words = 'lock'; Managed = $true; Destructive = $false }
    unlock  = @{ Section = 'lock'; From = 'locked'; To = 'unlocked'; Undo = 'undo: device.lock'; Words = 'unlock'; Managed = $true; Destructive = $false }
    isolate = @{ Section = 'isolation'; From = 'none'; To = 'isolated'; Undo = 'undo: device.release'; Words = 'isolate from the network'; Managed = $true; Destructive = $false }
    release = @{ Section = 'isolation'; From = 'isolated'; To = 'none'; Undo = 'undo: device.isolate'; Words = 'release from network isolation'; Managed = $true; Destructive = $false }
    retire  = @{ Section = 'enrollment'; From = 'enrolled'; To = 'retired'; Undo = 'no undo'; Words = 'retire (remove company data and management)'; Managed = $false; Destructive = $true }
    wipe    = @{ Section = 'wipe'; From = 'none'; To = 'requested'; Undo = 'no undo'; Words = 'request a full wipe'; Managed = $true; Destructive = $true }
}

$script:DrNext = @{
    lock    = 'The device locks at once if it is online, otherwise at its next check-in. The data stays on it.'
    unlock  = 'The user can use the device again at its next check-in.'
    isolate = 'The device is cut off from the network except the management service; the user cannot work online until it is released.'
    release = 'The device gets its normal network access back. Check it is clean first.'
    retire  = 'Company data and management are removed at the next check-in. Re-enrolling the device does not bring the removed data back.'
    wipe    = 'A person starts the wipe in the RMM or Intune console after this approval; nothing in this repository starts it.'
}

function Get-DrBlastRadius {
    param([Parameter(Mandatory)] $State, [Parameter(Mandatory)] $Dev)
    $count = $State.Root['devices'].AsArray().Count
    $role = Get-DrText $Dev['role']
    $online = $Dev['online'].GetValue[bool]()
    $sole = $Dev['onlyDeviceForRole'].GetValue[bool]()
    $regulated = $Dev['holdsRegulatedData'].GetValue[bool]()
    $hold = $Dev['legalHold'].GetValue[bool]()
    $notes = [System.Collections.Generic.List[string]]::new()
    if ($sole) { $notes.Add("This is the only $role device of the client; $role work stops while the action is in force.") }
    if (-not $online) { $notes.Add("The device is offline (last seen $(Get-DrText $Dev['lastSeen'])); the action applies at its next check-in.") }
    if ($regulated) { $notes.Add('The device holds regulated data; a lost device may need a human breach assessment (W-SEC-07).') }
    if ($hold) { $notes.Add('The device is under legal hold: it must not be wiped or retired.') }
    [pscustomobject][ordered]@{
        devices_affected                = 1
        users_affected                  = 1
        device_class                    = Get-DrText $Dev['deviceClass']
        online                          = $online
        last_seen                       = Get-DrText $Dev['lastSeen']
        role                            = $role
        only_device_for_role            = $sole
        regulated_data                  = $regulated
        legal_hold                      = $hold
        client_device_count             = $count
        share_of_client_devices_percent = [int][math]::Round(100.0 / $count, [System.MidpointRounding]::AwayFromZero)
        notes                           = @($notes)
    }
}

function Invoke-DrChange {
    param(
        [Parameter(Mandatory)] $Cmdlet, [Parameter(Mandatory)][string] $Device, [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $Client, [Parameter(Mandatory)][ValidateSet('lock', 'unlock', 'isolate', 'release', 'retire', 'wipe')][string] $Action
    )
    $a = $script:DrActions[$Action]
    $state = Open-DrState $Client
    $dev = Find-DrDevice $state $Device $Upn
    $uid = Get-DrText $dev['uid']
    $retired = (Get-DrText $dev['enrollment'].AsObject()['state']) -ceq 'retired'
    if ($a.Destructive -and $dev['legalHold'].GetValue[bool]()) {
        throw [System.InvalidOperationException]::new('The device is under legal hold; nothing was changed.')
    }
    if ($retired -and $a.Managed) {
        throw [System.NotSupportedException]::new('The device is retired and no longer managed; nothing was changed.')
    }
    $section = $dev[$a.Section].AsObject()
    $current = Get-DrText $section['state']
    $diff = @()
    if ($current -cne $a.To) {
        if ($current -cne $a.From) { throw [System.InvalidOperationException]::new('The device is in an unexpected state; nothing was changed.') }
        $diff = @(New-DrChange "/devices/$uid/$($a.Section)/state" $current $a.To)
    }
    $data = [pscustomobject][ordered]@{
        action       = $Action
        device       = $uid
        hostname     = Get-DrText $dev['hostname']
        owner        = Get-DrText $dev['owner']
        blast_radius = Get-DrBlastRadius $state $dev
        undo         = $a.Undo
        next_step    = $script:DrNext[$Action]
    }
    $applied = $false
    if (@($diff).Count -gt 0 -and $Cmdlet.ShouldProcess($Device, $a.Words)) {
        $section['state'] = [System.Text.Json.Nodes.JsonValue]::Create($a.To)
        Save-DrState $state
        $applied = $true
    }
    [pscustomobject][ordered]@{ data = $data; diff = @($diff); applied = $applied }
}

function Lock-ManagedDevice {
    <#
    .SYNOPSIS
      Lever device.lock: lock one device (screen lock; data stays). Stands in for an Intune remote lock (UNVERIFIED).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Device, [Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DrChange -Cmdlet $PSCmdlet -Device $Device -Upn $Upn -Client $Client -Action lock
}

function Unlock-ManagedDevice {
    <# .SYNOPSIS Lever device.unlock (the undo of device.lock): clear the lock state of one device. #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Device, [Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DrChange -Cmdlet $PSCmdlet -Device $Device -Upn $Upn -Client $Client -Action unlock
}

function Block-DeviceNetwork {
    <#
    .SYNOPSIS
      Lever device.isolate: isolate one device from the network. Stands in for a Defender for Endpoint machine isolation (UNVERIFIED).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Device, [Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DrChange -Cmdlet $PSCmdlet -Device $Device -Upn $Upn -Client $Client -Action isolate
}

function Unblock-DeviceNetwork {
    <# .SYNOPSIS Lever device.release (the undo of device.isolate): release one device from isolation. #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Device, [Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DrChange -Cmdlet $PSCmdlet -Device $Device -Upn $Upn -Client $Client -Action release
}

function Remove-ManagedDevice {
    <#
    .SYNOPSIS
      Lever device.retire: retire one device (remove company data and management). No undo. Stands in for an Intune retire (UNVERIFIED).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Device, [Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DrChange -Cmdlet $PSCmdlet -Device $Device -Upn $Upn -Client $Client -Action retire
}

function Clear-ManagedDevice {
    <#
    .SYNOPSIS
      Lever device.wipe: record a wipe REQUEST for one device. No undo. A person starts the wipe in the console; this never does.
      Stands in for an Intune wipe (UNVERIFIED).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Device, [Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DrChange -Cmdlet $PSCmdlet -Device $Device -Upn $Upn -Client $Client -Action wipe
}

Export-ModuleMember -Function Lock-ManagedDevice, Unlock-ManagedDevice, Block-DeviceNetwork, Unblock-DeviceNetwork,
    Remove-ManagedDevice, Clear-ManagedDevice
