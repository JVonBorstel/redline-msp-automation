Set-StrictMode -Version Latest

# License levers (B-31) for the Python bridge. They work on the offline mock tenant only: the client's base file
# (<root>/<client>.json, to check the user exists) and its licenses family file (<root>/<client>/licenses.json, B-19).
# <root> is $env:REDLINE_MOCK_TENANT_DIR (the bridge sets it) or fixtures/tenant. No network, no credentials.
#
# Contract with the lever host: the Python runner has already decided the call is allowed. These functions never check
# roles or approvals. A refusal that the person should read ("no free seat", "retention window not over") is returned as
# data with an empty diff, because the host reports a thrown error as its type name only (STD-ER-5). They never buy
# anything: there is no purchase function in this module and none is exported (W-VND-02, never-automate).

function Get-LoPaths {
    # The only place a client id becomes a path (STD-ID-4): a plain slug, then two files under one folder.
    param([Parameter(Mandatory)][string] $Client)
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw "Client id is not a valid slug; no file was read." }
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\fixtures\tenant' }
    $base = Join-Path $root "$Client.json"
    $family = Join-Path (Join-Path $root $Client) 'licenses.json'
    foreach ($p in $base, $family) {
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "No mock license data for client $Client; nothing was read." }
    }
    [pscustomobject]@{ Base = $base; Family = $family }
}

function Read-LoJson {
    param([Parameter(Mandatory)][string] $Path)
    # A JSON node is enumerable and PowerShell unrolls it on return; the leading comma keeps it whole.
    $node = [System.Text.Json.Nodes.JsonNode]::Parse([System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false))).AsObject()
    , $node
}

function Open-LoClient {
    param([Parameter(Mandatory)][string] $Client)
    $paths = Get-LoPaths $Client
    $family = Read-LoJson $paths.Family
    $meta = $family['_meta']
    if ($null -eq $meta -or $meta.AsObject()['client'].GetValue[string]() -cne $Client) { throw "License data does not belong to client $Client; nothing was read." }
    [pscustomobject]@{ Path = $paths.Family; Root = $family; Base = (Read-LoJson $paths.Base) }
}

function Save-LoFamily {
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

function Get-LoToday {
    # Anything time-based takes an explicit as-of date (STD-PS-10); without one, today in UTC.
    param([string] $AsOf)
    if ([string]::IsNullOrWhiteSpace($AsOf)) { return [datetime]::UtcNow.ToString('yyyy-MM-dd') }
    if ($AsOf -cnotmatch '^\d{4}-\d{2}-\d{2}') { throw "AsOf is not a date; nothing was read." }
    $AsOf.Substring(0, 10)
}

function Find-LoSku {
    param([Parameter(Mandatory)] $State, [Parameter(Mandatory)][string] $Sku)
    foreach ($s in $State.Root['skus'].AsArray()) {
        $o = $s.AsObject()
        if ($o['skuPartNumber'].GetValue[string]() -ceq $Sku) { return , $o }
    }
    $null
}

function Get-LoConsumed {
    param([Parameter(Mandatory)] $State, [Parameter(Mandatory)][string] $SkuId)
    $n = 0
    foreach ($a in $State.Root['assignments'].AsArray()) {
        if ($a.AsObject()['skuId'].GetValue[string]() -ceq $SkuId) { $n++ }
    }
    $n
}

function Find-LoAssignment {
    param([Parameter(Mandatory)] $State, [Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $SkuId)
    foreach ($a in $State.Root['assignments'].AsArray()) {
        $o = $a.AsObject()
        if ([string]::Equals($o['userPrincipalName'].GetValue[string](), $Upn, [System.StringComparison]::OrdinalIgnoreCase) -and $o['skuId'].GetValue[string]() -ceq $SkuId) { return , $o }
    }
    $null
}

function New-LoOutcome {
    # The result shape the host maps to data, diff and applied. A refusal is outcome 'refused' with an empty diff.
    param([string] $Outcome, [string] $Message, $Diff = @(), [bool] $Applied = $false, $Extra = $null)
    $data = [ordered]@{ outcome = $Outcome; message = $Message }
    if ($null -ne $Extra) { foreach ($k in $Extra.Keys) { $data[$k] = $Extra[$k] } }
    [pscustomobject][ordered]@{ data = [pscustomobject]$data; diff = @($Diff); applied = $Applied }
}

function Add-LicenseAssignment {
    <#
    .SYNOPSIS
      Lever license.add: give one user a license from a seat the client already owns. Never buys a seat.
    .DESCRIPTION
      Returns { data, diff, applied }. Under -WhatIf it computes the diff and applies nothing. With no free seat it returns
      data.outcome 'refused', the message "no free seat: a purchase needs the client's consent (W-VND-02)" and an empty diff.
      Convergent: a user who already holds the license is an empty diff.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $Sku,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    $state = Open-LoClient $Client
    $today = Get-LoToday $AsOf
    $user = $null
    foreach ($u in $state.Base['users'].AsArray()) {
        $name = $u.AsObject()['userPrincipalName']
        if ($null -ne $name -and [string]::Equals($name.GetValue[string](), $Upn, [System.StringComparison]::OrdinalIgnoreCase)) { $user = $u.AsObject(); break }
    }
    if ($null -eq $user) { return New-LoOutcome 'refused' 'no such user for this client' }
    $canonical = $user['userPrincipalName'].GetValue[string]()
    $skuNode = Find-LoSku $state $Sku
    if ($null -eq $skuNode) { return New-LoOutcome 'refused' "no such SKU $Sku for this client" }
    $skuId = $skuNode['skuId'].GetValue[string]()
    if ($null -ne (Find-LoAssignment $state $canonical $skuId)) {
        return New-LoOutcome 'unchanged' "$canonical already holds $Sku; nothing to do"
    }
    $enabled = $skuNode['prepaidUnits'].AsObject()['enabled'].GetValue[int]()
    $consumed = Get-LoConsumed $state $skuId
    $free = $enabled - $consumed
    $counts = @{ sku = $Sku; seatsOwned = $enabled; seatsUsed = $consumed; seatsFree = [Math]::Max(0, $free) }
    if ($free -lt 1) {
        return New-LoOutcome 'refused' "no free seat: a purchase needs the client's consent (W-VND-02)" @() $false $counts
    }
    $after = [pscustomobject][ordered]@{ skuPartNumber = $Sku; skuId = $skuId; assignedOn = $today; retentionEndsOn = $null }
    $diff = @([pscustomobject][ordered]@{ op = 'add'; path = "/licenses/$canonical/$Sku"; after = $after })
    $applied = $false
    if ($PSCmdlet.ShouldProcess($canonical, "assign license $Sku from a free seat")) {
        $row = [System.Text.Json.Nodes.JsonObject]::new()
        $row['userPrincipalName'] = [System.Text.Json.Nodes.JsonValue]::Create($canonical)
        $row['skuId'] = [System.Text.Json.Nodes.JsonValue]::Create($skuId)
        $row['skuPartNumber'] = [System.Text.Json.Nodes.JsonValue]::Create($Sku)
        $row['assignedOn'] = [System.Text.Json.Nodes.JsonValue]::Create($today)
        $row['retentionEndsOn'] = [System.Text.Json.Nodes.JsonNode]$null
        $state.Root['assignments'].AsArray().Add($row)
        Save-LoFamily $state
        $applied = $true
    }
    $counts['seatsUsed'] = $consumed + 1
    $counts['seatsFree'] = $free - 1
    New-LoOutcome 'assign' "assign $Sku to $canonical from a seat the client already owns" $diff $applied $counts
}

function Remove-LicenseAssignment {
    <#
    .SYNOPSIS
      Lever license.remove: take a license from an offboarded user, only after the retention window has ended.
    .DESCRIPTION
      The window is the assignment's retentionEndsOn (its last day). Removal is allowed when AsOf is later than that day.
      No window recorded, or the window still open, is a refusal with an empty diff. The diff shows the SKU and the date the
      window ended. Convergent: no such assignment is an empty diff.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][string] $Upn,
        [Parameter(Mandatory)][string] $Sku,
        [Parameter(Mandatory)][string] $Client,
        [string] $AsOf
    )
    $state = Open-LoClient $Client
    $today = Get-LoToday $AsOf
    $skuNode = Find-LoSku $state $Sku
    if ($null -eq $skuNode) { return New-LoOutcome 'refused' "no such SKU $Sku for this client" }
    $row = Find-LoAssignment $state $Upn ($skuNode['skuId'].GetValue[string]())
    if ($null -eq $row) { return New-LoOutcome 'unchanged' "$Upn does not hold $Sku; nothing to do" }
    $canonical = $row['userPrincipalName'].GetValue[string]()
    $endsNode = $row['retentionEndsOn']
    if ($null -eq $endsNode) {
        return New-LoOutcome 'refused' "no retention window is recorded for $canonical on $Sku, so the license is not due for removal"
    }
    $ends = $endsNode.GetValue[string]()
    if ([string]::CompareOrdinal($today, $ends) -le 0) {
        return New-LoOutcome 'refused' "retention window for $canonical on $Sku ends $ends and is not over on $today; nothing removed" @() $false @{ sku = $Sku; retentionEndsOn = $ends }
    }
    $before = [pscustomobject][ordered]@{ skuPartNumber = $Sku; skuId = $row['skuId'].GetValue[string](); retentionEndsOn = $ends }
    $diff = @([pscustomobject][ordered]@{ op = 'remove'; path = "/licenses/$canonical/$Sku"; before = $before })
    $applied = $false
    if ($PSCmdlet.ShouldProcess($canonical, "remove license $Sku (retention window ended $ends)")) {
        [void] $state.Root['assignments'].AsArray().Remove($row)
        Save-LoFamily $state
        $applied = $true
    }
    New-LoOutcome 'remove' "remove $Sku from $canonical; the retention window ended $ends" $diff $applied @{ sku = $Sku; retentionEndsOn = $ends }
}

Export-ModuleMember -Function Add-LicenseAssignment, Remove-LicenseAssignment
