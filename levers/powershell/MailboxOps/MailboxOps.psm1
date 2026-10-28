Set-StrictMode -Version Latest

# MailboxOps levers (B-33). They work on the offline mock mailbox state only: <tenant folder>/<client>/mailboxes.json
# (the folder is fixtures/tenant, or $env:REDLINE_MOCK_TENANT_DIR, which the Python bridge sets). No network, no credentials.
# The real shapes these stand in for are Exchange Online PowerShell, not Graph; see SOURCES.md (all UNVERIFIED).
#
# Contract with the lever host (B-15): the Python runner has already decided that the call is allowed (role, client scope,
# approval, pause). These functions never check roles. They receive the one client id from the host (-Client), compute the
# change, and apply it only when ShouldProcess says yes (not under -WhatIf). Every function returns { data, diff, applied };
# the same call again is an empty diff (convergent, STD-LV-6).
#
# Not offered, on purpose: forwarding mail to an outside address. No function here reads or writes the forwarding address;
# the weekly audit W-M365-05 flags it instead (B33-2).

function Get-MoStatePath {
    # The only place a client id becomes a path (STD-ID-4): a plain slug, then one file under one folder.
    param([Parameter(Mandatory)][string] $Client)
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw "Client id is not a valid slug; no file was read." }
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\fixtures\tenant' }
    $path = Join-Path (Join-Path $root $Client) 'mailboxes.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "No mailbox state for client $Client; nothing was read." }
    $path
}

function Get-MoText {
    param($Node)
    if ($null -eq $Node) { $null } else { $Node.GetValue[string]() }
}

function Open-MoState {
    # JsonNode, not ConvertFrom-Json: nothing (dates, numbers, empty arrays) changes shape on the way back to disk.
    param([Parameter(Mandatory)][string] $Client)
    $path = Get-MoStatePath $Client
    $root = [System.Text.Json.Nodes.JsonNode]::Parse([System.IO.File]::ReadAllText($path, [System.Text.UTF8Encoding]::new($false)))
    $meta = $root.AsObject()['_meta']
    if ($null -eq $meta -or (Get-MoText $meta.AsObject()['client']) -cne $Client) { throw "Mailbox state does not belong to client $Client; nothing was read." }
    [pscustomobject]@{ Path = $path; Root = $root.AsObject() }
}

function Save-MoState {
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

function Get-MoAsOf {
    # STD-PS-10: never the wall clock. The caller's -AsOf, else the date the fixture was written for.
    param([Parameter(Mandatory)] $State, [string] $AsOf)
    if ([string]::IsNullOrWhiteSpace($AsOf)) { $AsOf = Get-MoText $State.Root['_meta'].AsObject()['as_of'] }
    $parsed = [datetime]::MinValue
    $styles = [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor [System.Globalization.DateTimeStyles]::AssumeUniversal
    if (-not [datetime]::TryParse($AsOf, [cultureinfo]::InvariantCulture, $styles, [ref] $parsed)) {
        throw "As-of date is not a valid date; nothing was changed."
    }
    $parsed.Date
}

function Find-MoMailbox {
    # One message for "absent" and "belongs to someone else": no existence oracle across clients (C-27).
    param([Parameter(Mandatory)] $State, [Parameter(Mandatory)][string] $Upn, [switch] $UserOnly)
    foreach ($item in $State.Root['mailboxes'].AsArray()) {
        $box = $item.AsObject()
        if ([string]::Equals((Get-MoText $box['userPrincipalName']), $Upn, [System.StringComparison]::OrdinalIgnoreCase)) {
            if ($UserOnly -and (Get-MoText $box['recipientTypeDetails']) -cne 'UserMailbox') { break }
            return ,$box
        }
    }
    throw "No such mailbox for this client; nothing was changed."
}

function Find-MoList {
    param([Parameter(Mandatory)] $State, [Parameter(Mandatory)][string] $List)
    foreach ($item in $State.Root['distributionLists'].AsArray()) {
        $dl = $item.AsObject()
        if ([string]::Equals((Get-MoText $dl['primarySmtpAddress']), $List, [System.StringComparison]::OrdinalIgnoreCase)) { return ,$dl }
    }
    throw "No such distribution list for this client; nothing was changed."
}

function Find-MoOneDrive {
    param([Parameter(Mandatory)] $State, [Parameter(Mandatory)][string] $Owner)
    foreach ($item in $State.Root['oneDrive'].AsArray()) {
        $drive = $item.AsObject()
        if ([string]::Equals((Get-MoText $drive['owner']), $Owner, [System.StringComparison]::OrdinalIgnoreCase)) { return ,$drive }
    }
    throw "No OneDrive for that user in this client; nothing was changed."
}

function Find-MoString {
    # Index of a string in a JsonArray of strings (case-insensitive), or -1.
    param([Parameter(Mandatory)] $Array, [Parameter(Mandatory)][string] $Value)
    for ($i = 0; $i -lt $Array.Count; $i++) {
        if ([string]::Equals((Get-MoText $Array[$i]), $Value, [System.StringComparison]::OrdinalIgnoreCase)) { return $i }
    }
    -1
}

function Find-MoGrant {
    # Index of the OneDrive access entry for one grantee, or -1.
    param([Parameter(Mandatory)] $Access, [Parameter(Mandatory)][string] $Grantee)
    for ($i = 0; $i -lt $Access.Count; $i++) {
        if ([string]::Equals((Get-MoText $Access[$i].AsObject()['grantee']), $Grantee, [System.StringComparison]::OrdinalIgnoreCase)) { return $i }
    }
    -1
}

function New-MoChange {
    param([Parameter(Mandatory)][string] $Op, [Parameter(Mandatory)][string] $Path, $Before, $After)
    switch ($Op) {
        'add' { [pscustomobject][ordered]@{ op = 'add'; path = $Path; after = $After } }
        'remove' { [pscustomobject][ordered]@{ op = 'remove'; path = $Path; before = $Before } }
        default { [pscustomobject][ordered]@{ op = 'replace'; path = $Path; before = $Before; after = $After } }
    }
}

function Complete-MoChange {
    # Applies exactly the diff it was given, in one atomic file replace, and only when ShouldProcess says yes.
    param(
        [Parameter(Mandatory)] $Cmdlet, [Parameter(Mandatory)] $State, [AllowEmptyCollection()][object[]] $Diff,
        [Parameter(Mandatory)][string] $Target, [Parameter(Mandatory)][string] $Action,
        [Parameter(Mandatory)][scriptblock] $Apply, [Parameter(Mandatory)] $Data
    )
    $applied = $false
    if (@($Diff).Count -gt 0 -and $Cmdlet.ShouldProcess($Target, $Action)) {
        & $Apply
        Save-MoState $State
        $applied = $true
    }
    [pscustomobject][ordered]@{ data = $Data; diff = @($Diff); applied = $applied }
}

function Set-MoMember {
    # Shared by the mailbox permission levers and the DL levers: add or remove one string in a list, convergent.
    param(
        [Parameter(Mandatory)] $Cmdlet, [Parameter(Mandatory)] $State, [Parameter(Mandatory)] $Array,
        [Parameter(Mandatory)][string] $Value, [Parameter(Mandatory)][string] $Path, [Parameter(Mandatory)][ValidateSet('add', 'remove')][string] $Op,
        [Parameter(Mandatory)][string] $Target, [Parameter(Mandatory)][string] $Action, [Parameter(Mandatory)] $Data
    )
    $at = Find-MoString $Array $Value
    $diff = @()
    if ($Op -eq 'add' -and $at -lt 0) { $diff = @(New-MoChange 'add' $Path -After $Value) }
    if ($Op -eq 'remove' -and $at -ge 0) { $diff = @(New-MoChange 'remove' $Path -Before (Get-MoText $Array[$at])) }
    Complete-MoChange -Cmdlet $Cmdlet -State $State -Diff $diff -Target $Target -Action $Action -Data $Data -Apply {
        if ($Op -eq 'add') { $Array.Add([System.Text.Json.Nodes.JsonValue]::Create($Value)) }
        else { $Array.RemoveAt((Find-MoString $Array $Value)) }
    }
}

function Invoke-MoDlChange {
    param(
        [Parameter(Mandatory)] $Cmdlet, [Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $List,
        [Parameter(Mandatory)][string] $Client, [Parameter(Mandatory)][ValidateSet('add', 'remove')][string] $Op
    )
    $state = Open-MoState $Client
    $box = Find-MoMailbox $state $Upn
    $dl = Find-MoList $state $List
    $stored = Get-MoText $box['userPrincipalName']
    $words = if ($Op -eq 'add') { "add to distribution list $List" } else { "remove from distribution list $List" }
    Set-MoMember -Cmdlet $Cmdlet -State $state -Array $dl['members'].AsArray() -Value $stored -Op $Op `
        -Path "/distributionLists/$(Get-MoText $dl['id'])/members/$stored" `
        -Target $Upn -Action $words -Data ([pscustomobject][ordered]@{ user = $Upn; list = $List })
}

function Invoke-MoPermissionChange {
    # Shared body for Full Access and Send As. The delegate must be a user mailbox of the same client, so a grant to an
    # outside address or to another client's person cannot be expressed. Granting a mailbox to itself is refused.
    param(
        [Parameter(Mandatory)] $Cmdlet, [Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Delegate,
        [Parameter(Mandatory)][string] $Client, [Parameter(Mandatory)][ValidateSet('fullAccess', 'sendAs')][string] $Kind,
        [Parameter(Mandatory)][ValidateSet('add', 'remove')][string] $Op
    )
    $state = Open-MoState $Client
    $box = Find-MoMailbox $state $Upn
    $delegateBox = Find-MoMailbox $state $Delegate -UserOnly
    $stored = Get-MoText $delegateBox['userPrincipalName']
    if ([string]::Equals((Get-MoText $box['userPrincipalName']), $stored, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "A mailbox cannot be granted to itself; nothing was changed."
    }
    $label = if ($Kind -eq 'fullAccess') { 'Full Access' } else { 'Send As' }
    $verb = if ($Op -eq 'add') { 'grant' } else { 'revoke' }
    Set-MoMember -Cmdlet $Cmdlet -State $state -Array $box[$Kind].AsArray() -Value $stored `
        -Path "/mailboxes/$(Get-MoText $box['id'])/$Kind/$stored" -Op $Op `
        -Target $Upn -Action "$verb $label on this mailbox for $Delegate" `
        -Data ([pscustomobject][ordered]@{ mailbox = $Upn; delegate = $Delegate; permission = $label })
}

# -- distribution lists (W-M365-01) -----------------------------------------------------------------------------

function Add-MailboxDlMember {
    <#
    .SYNOPSIS
      Lever mailbox.add-dl-member: add one person's mailbox to a distribution list of the same client.
    .DESCRIPTION
      Stands in for Exchange Online Add-DistributionGroupMember (UNVERIFIED). Returns { data, diff, applied }.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $List, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-MoDlChange -Cmdlet $PSCmdlet -Upn $Upn -List $List -Client $Client -Op add
}

function Remove-MailboxDlMember {
    <# .SYNOPSIS Lever mailbox.remove-dl-member (the undo of mailbox.add-dl-member): remove one person from a distribution list. #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $List, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-MoDlChange -Cmdlet $PSCmdlet -Upn $Upn -List $List -Client $Client -Op remove
}

# -- Full Access and Send As (W-M365-02) ------------------------------------------------------------------------

function Grant-MailboxFullAccess {
    <#
    .SYNOPSIS
      Lever mailbox.grant-full-access: give one named person of the same client Full Access to a mailbox.
    .DESCRIPTION
      Stands in for Exchange Online Add-MailboxPermission -AccessRights FullAccess (UNVERIFIED). Auto-mapping is not modelled.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Delegate, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-MoPermissionChange -Cmdlet $PSCmdlet -Upn $Upn -Delegate $Delegate -Client $Client -Kind fullAccess -Op add
}

function Revoke-MailboxFullAccess {
    <# .SYNOPSIS Lever mailbox.revoke-full-access (the undo of mailbox.grant-full-access). #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Delegate, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-MoPermissionChange -Cmdlet $PSCmdlet -Upn $Upn -Delegate $Delegate -Client $Client -Kind fullAccess -Op remove
}

function Grant-MailboxSendAs {
    <#
    .SYNOPSIS
      Lever mailbox.grant-send-as: let one named person of the same client send mail as a mailbox.
    .DESCRIPTION
      Stands in for Exchange Online Add-RecipientPermission -AccessRights SendAs (UNVERIFIED).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Delegate, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-MoPermissionChange -Cmdlet $PSCmdlet -Upn $Upn -Delegate $Delegate -Client $Client -Kind sendAs -Op add
}

function Revoke-MailboxSendAs {
    <# .SYNOPSIS Lever mailbox.revoke-send-as (the undo of mailbox.grant-send-as). #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Delegate, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-MoPermissionChange -Cmdlet $PSCmdlet -Upn $Upn -Delegate $Delegate -Client $Client -Kind sendAs -Op remove
}

# -- convert, auto-reply, archive (W-ONB-09, W-M365-09) ----------------------------------------------------------

function Convert-MailboxToShared {
    <#
    .SYNOPSIS
      Lever mailbox.convert-shared: convert a user mailbox to a shared mailbox (a leaver's mailbox keeps its mail without a licence).
    .DESCRIPTION
      Stands in for Exchange Online Set-Mailbox -Type Shared (UNVERIFIED). A mailbox larger than 50 GB is refused: the
      limit for an unlicensed shared mailbox is recalled from memory and UNVERIFIED here; it is a guard, not a claim.
      There is no undo lever: converting back to a user mailbox needs a licence, which is a person's decision.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    $state = Open-MoState $Client
    $box = Find-MoMailbox $state $Upn
    $current = Get-MoText $box['recipientTypeDetails']
    $diff = @()
    if ($current -cne 'SharedMailbox') {
        $size = $box['totalItemSizeGb'].GetValue[double]()
        if ($size -gt 50) { throw "This mailbox is $size GB, over the 50 GB limit for an unlicensed shared mailbox; it needs a licence decision first. Nothing was changed." }
        $diff = @(New-MoChange 'replace' "/mailboxes/$(Get-MoText $box['id'])/recipientTypeDetails" -Before $current -After 'SharedMailbox')
    }
    Complete-MoChange -Cmdlet $PSCmdlet -State $state -Diff $diff -Target $Upn -Action 'convert to a shared mailbox' `
        -Data ([pscustomobject][ordered]@{ mailbox = $Upn; recipientTypeDetails = 'SharedMailbox' }) -Apply {
        $box['recipientTypeDetails'] = [System.Text.Json.Nodes.JsonValue]::Create('SharedMailbox')
    }
}

function Set-MailboxAutoReply {
    <#
    .SYNOPSIS
      Lever mailbox.set-auto-reply: turn on an automatic reply (same text inside and outside) for one mailbox.
    .DESCRIPTION
      Stands in for Exchange Online Set-MailboxAutoReplyConfiguration -AutoReplyState Enabled (UNVERIFIED). The text is
      validated by the registry pattern (letters, digits and basic punctuation, no markup, no links). Scheduling is not modelled.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Message, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    $state = Open-MoState $Client
    $box = Find-MoMailbox $state $Upn
    $id = Get-MoText $box['id']
    $reply = $box['autoReply'].AsObject()
    $wanted = [ordered]@{ state = 'Enabled'; internalMessage = $Message; externalMessage = $Message; externalAudience = 'All' }
    $diff = @()
    foreach ($key in $wanted.Keys) {
        $before = Get-MoText $reply[$key]
        if ($before -cne $wanted[$key]) { $diff += New-MoChange 'replace' "/mailboxes/$id/autoReply/$key" -Before $before -After $wanted[$key] }
    }
    Complete-MoChange -Cmdlet $PSCmdlet -State $state -Diff $diff -Target $Upn -Action 'turn on the automatic reply' `
        -Data ([pscustomobject][ordered]@{ mailbox = $Upn; autoReplyState = 'Enabled' }) -Apply {
        foreach ($key in $wanted.Keys) { $reply[$key] = [System.Text.Json.Nodes.JsonValue]::Create([string] $wanted[$key]) }
    }
}

function Clear-MailboxAutoReply {
    <# .SYNOPSIS Lever mailbox.clear-auto-reply (the undo of mailbox.set-auto-reply): turn the automatic reply off. #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    $state = Open-MoState $Client
    $box = Find-MoMailbox $state $Upn
    $reply = $box['autoReply'].AsObject()
    $before = Get-MoText $reply['state']
    $diff = @()
    if ($before -cne 'Disabled') { $diff = @(New-MoChange 'replace' "/mailboxes/$(Get-MoText $box['id'])/autoReply/state" -Before $before -After 'Disabled') }
    Complete-MoChange -Cmdlet $PSCmdlet -State $state -Diff $diff -Target $Upn -Action 'turn off the automatic reply' `
        -Data ([pscustomobject][ordered]@{ mailbox = $Upn; autoReplyState = 'Disabled' }) -Apply {
        $reply['state'] = [System.Text.Json.Nodes.JsonValue]::Create('Disabled')
    }
}

function Enable-MailboxArchive {
    <#
    .SYNOPSIS
      Lever mailbox.enable-archive: switch on the online archive for one mailbox.
    .DESCRIPTION
      Stands in for Exchange Online Enable-Mailbox -Archive (UNVERIFIED). No undo lever is offered: switching an archive
      off can delete what it holds, which is a person's decision.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    $state = Open-MoState $Client
    $box = Find-MoMailbox $state $Upn
    $before = Get-MoText $box['archiveStatus']
    $diff = @()
    if ($before -cne 'Active') { $diff = @(New-MoChange 'replace' "/mailboxes/$(Get-MoText $box['id'])/archiveStatus" -Before $before -After 'Active') }
    Complete-MoChange -Cmdlet $PSCmdlet -State $state -Diff $diff -Target $Upn -Action 'enable the online archive' `
        -Data ([pscustomobject][ordered]@{ mailbox = $Upn; archiveStatus = 'Active' }) -Apply {
        $box['archiveStatus'] = [System.Text.Json.Nodes.JsonValue]::Create('Active')
    }
}

# -- OneDrive manager access (W-ONB-10) -------------------------------------------------------------------------

function Grant-OneDriveManagerAccess {
    <#
    .SYNOPSIS
      Lever mailbox.grant-onedrive-manager: give a named manager of the same client access to a leaver's OneDrive until a date.
    .DESCRIPTION
      The end date is required, must be after the as-of date and at most 30 days away. Nothing here removes the access when
      the date passes; the revoke lever does, and a person or a scheduled job must run it (see the change note).
      Stands in for a SharePoint Online site collection administrator grant (UNVERIFIED).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Manager, [Parameter(Mandatory)][string] $ExpiresOn, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    $maxDays = 30
    $state = Open-MoState $Client
    $today = Get-MoAsOf $state $AsOf
    $until = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($ExpiresOn, 'yyyy-MM-dd', [cultureinfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::None, [ref] $until)) {
        throw "The end date must look like 2026-11-20; nothing was changed."
    }
    if ($until -le $today) { throw "The end date must be after $($today.ToString('yyyy-MM-dd')); nothing was changed." }
    if ($until -gt $today.AddDays($maxDays)) { throw "The end date is more than $maxDays days away; a longer grant needs a new request. Nothing was changed." }
    $owner = Find-MoMailbox $state $Upn
    $managerBox = Find-MoMailbox $state $Manager -UserOnly
    $ownerStored = Get-MoText $owner['userPrincipalName']
    $managerStored = Get-MoText $managerBox['userPrincipalName']
    if ([string]::Equals($ownerStored, $managerStored, [System.StringComparison]::OrdinalIgnoreCase)) { throw "A OneDrive cannot be granted to its own owner; nothing was changed." }
    $drive = Find-MoOneDrive $state $ownerStored
    $access = $drive['access'].AsArray()
    $at = Find-MoGrant $access $managerStored
    $path = "/oneDrive/$(Get-MoText $drive['id'])/access/$managerStored"
    $untilText = $until.ToString('yyyy-MM-dd')
    $entry = [ordered]@{ grantee = $managerStored; grantedOn = $today.ToString('yyyy-MM-dd'); expiresOn = $untilText; accessLevel = 'SiteCollectionAdmin' }
    $diff = @()
    if ($at -lt 0) {
        $diff = @(New-MoChange 'add' $path -After ([pscustomobject]$entry))
    }
    elseif ((Get-MoText $access[$at].AsObject()['expiresOn']) -cne $untilText) {
        $diff = @(New-MoChange 'replace' "$path/expiresOn" -Before (Get-MoText $access[$at].AsObject()['expiresOn']) -After $untilText)
    }
    Complete-MoChange -Cmdlet $PSCmdlet -State $state -Diff $diff -Target $Upn -Action "give $Manager access to this OneDrive until $untilText" `
        -Data ([pscustomobject][ordered]@{ owner = $Upn; manager = $Manager; expiresOn = $untilText }) -Apply {
        if ($at -lt 0) {
            $node = [System.Text.Json.Nodes.JsonObject]::new()
            foreach ($key in $entry.Keys) { $node[$key] = [System.Text.Json.Nodes.JsonValue]::Create([string] $entry[$key]) }
            $access.Add($node)
        }
        else { $access[$at].AsObject()['expiresOn'] = [System.Text.Json.Nodes.JsonValue]::Create($untilText) }
    }
}

function Revoke-OneDriveManagerAccess {
    <# .SYNOPSIS Lever mailbox.revoke-onedrive-manager (the undo of mailbox.grant-onedrive-manager, and what ends a grant on its date). #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $Manager, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    $state = Open-MoState $Client
    $owner = Find-MoMailbox $state $Upn
    $managerBox = Find-MoMailbox $state $Manager -UserOnly
    $managerStored = Get-MoText $managerBox['userPrincipalName']
    $drive = Find-MoOneDrive $state (Get-MoText $owner['userPrincipalName'])
    $access = $drive['access'].AsArray()
    $at = Find-MoGrant $access $managerStored
    $diff = @()
    if ($at -ge 0) {
        $old = $access[$at].AsObject()
        $before = [pscustomobject][ordered]@{ grantee = (Get-MoText $old['grantee']); grantedOn = (Get-MoText $old['grantedOn']); expiresOn = (Get-MoText $old['expiresOn']); accessLevel = (Get-MoText $old['accessLevel']) }
        $diff = @(New-MoChange 'remove' "/oneDrive/$(Get-MoText $drive['id'])/access/$managerStored" -Before $before)
    }
    Complete-MoChange -Cmdlet $PSCmdlet -State $state -Diff $diff -Target $Upn -Action "end $Manager's access to this OneDrive" `
        -Data ([pscustomobject][ordered]@{ owner = $Upn; manager = $Manager }) -Apply { $access.RemoveAt($at) }
}

Export-ModuleMember -Function Add-MailboxDlMember, Remove-MailboxDlMember, Grant-MailboxFullAccess, Revoke-MailboxFullAccess,
    Grant-MailboxSendAs, Revoke-MailboxSendAs, Convert-MailboxToShared, Set-MailboxAutoReply, Clear-MailboxAutoReply,
    Enable-MailboxArchive, Grant-OneDriveManagerAccess, Revoke-OneDriveManagerAccess
