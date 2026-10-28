Set-StrictMode -Version Latest

# MailFlowOps levers (B-45). They work on the offline mock mail-flow state only: <folder beside the tenant folder>/mailflow/
# <client>.json (the tenant folder is fixtures/tenant, or $env:REDLINE_MOCK_TENANT_DIR, which the Python bridge sets; so
# fixtures/mailflow by default). No network, no credentials. The real shapes these stand in for are Exchange Online
# message trace and quarantine cmdlets; see fixtures/mailflow/SOURCES.md (all UNVERIFIED).
#
# Contract with the lever host (B-15): the Python runner has already decided that the call is allowed (role, client scope,
# approval, pause). These functions never check roles. One rule lives in the data and is enforced here: a message held
# as high-confidence phish or malware is never released (B45-2). That refusal is returned as { refusal }, so the host
# reports it as denied and the runner audits it.

# The one list of quarantine types a lever never releases. A person can still decide in the admin portal.
$script:ReleaseRefused = @('HighConfPhish', 'Malware')

function Get-MfStatePath {
    # The only place a client id becomes a path (STD-ID-4): a plain slug, then one file under one folder.
    param([Parameter(Mandatory)][string] $Client)
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw "Client id is not a valid slug; no file was read." }
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if ([string]::IsNullOrWhiteSpace($root)) { $root = Join-Path $PSScriptRoot '..\..\..\fixtures\tenant' }
    $parent = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($root).TrimEnd('\', '/'))
    $path = Join-Path (Join-Path $parent 'mailflow') "$Client.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "No mail-flow state for client $Client; nothing was read." }
    $path
}

function Get-MfText {
    param($Node)
    if ($null -eq $Node) { $null } else { $Node.GetValue[string]() }
}

function Open-MfState {
    # JsonNode, not ConvertFrom-Json: nothing (dates, nulls, empty arrays) changes shape on the way back to disk.
    param([Parameter(Mandatory)][string] $Client)
    $path = Get-MfStatePath $Client
    $root = [System.Text.Json.Nodes.JsonNode]::Parse([System.IO.File]::ReadAllText($path, [System.Text.UTF8Encoding]::new($false)))
    $meta = $root.AsObject()['_meta']
    if ($null -eq $meta -or (Get-MfText $meta.AsObject()['client']) -cne $Client) { throw "Mail-flow state does not belong to client $Client; nothing was read." }
    [pscustomobject]@{ Path = $path; Root = $root.AsObject() }
}

function Save-MfState {
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

function Find-MfString {
    # The stored value of a string in a JsonArray of strings (case-insensitive), or $null. The array may be empty.
    param($Array, [Parameter(Mandatory)][string] $Value)
    foreach ($item in $Array) {
        if ([string]::Equals((Get-MfText $item), $Value, [System.StringComparison]::OrdinalIgnoreCase)) { return (Get-MfText $item) }
    }
    $null
}

function Get-MailFlowTrace {
    <#
    .SYNOPSIS
      Lever message.trace: every recipient of one message in this client's mail flow, with its delivery status.
    .DESCRIPTION
      Stands in for Exchange Online Get-MessageTrace / Get-MessageTraceV2 (UNVERIFIED). Read only: nothing is saved.
      No subject or body comes back. A message id of another client answers exactly like an unknown one: no rows.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $MessageId, [Parameter(Mandatory)][string] $Client)
    $state = Open-MfState $Client
    $rows = @(foreach ($item in $state.Root['messageTrace'].AsArray()) {
            $row = $item.AsObject()
            if ((Get-MfText $row['messageId']) -ceq $MessageId) {
                [pscustomobject][ordered]@{
                    recipientAddress = Get-MfText $row['recipientAddress']
                    status           = Get-MfText $row['status']
                    received         = Get-MfText $row['received']
                    quarantineId     = Get-MfText $row['quarantineId']
                }
            }
        })
    [pscustomobject][ordered]@{ messageId = $MessageId; count = $rows.Count; recipients = $rows }
}

function Restore-QuarantinedMessage {
    <#
    .SYNOPSIS
      Lever quarantine.release: release one quarantined message to one of its own recipients.
    .DESCRIPTION
      Stands in for Exchange Online Release-QuarantineMessage (UNVERIFIED). "Release" is not an approved PowerShell verb,
      so the function is Restore-. Refused, as { refusal }, for a message held as high-confidence phish or malware and
      for a person who was not a recipient of it. Releasing again to the same person is an empty diff (STD-LV-6).
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][string] $Upn, [Parameter(Mandatory)][string] $QuarantineId, [Parameter(Mandatory)][string] $Client)
    $state = Open-MfState $Client
    $held = $null
    foreach ($item in $state.Root['quarantine'].AsArray()) {
        if ((Get-MfText $item.AsObject()['id']) -ceq $QuarantineId) { $held = $item.AsObject(); break }
    }
    if ($null -eq $held) { throw "No such quarantined message for this client; nothing was changed." }
    $type = Get-MfText $held['quarantineType']
    if ($type -in $script:ReleaseRefused) {
        return [pscustomobject]@{ refusal = "Message $QuarantineId is held as $type; a lever never releases high-confidence phish or malware. Nothing was changed." }
    }
    $recipients = $held['recipients'].AsArray()
    $stored = Find-MfString -Array $recipients -Value $Upn
    if ($null -eq $stored) {
        return [pscustomobject]@{ refusal = "That person was not a recipient of message $QuarantineId; it is released only to its own recipients. Nothing was changed." }
    }
    $released = $held['releasedTo'].AsArray()
    $diff = @()
    if ($null -eq (Find-MfString -Array $released -Value $stored)) {
        $diff = @([pscustomobject][ordered]@{ op = 'add'; path = "/quarantine/$QuarantineId/releasedTo/$stored"; after = $stored })
    }
    $applied = $false
    if ($diff.Count -gt 0 -and $PSCmdlet.ShouldProcess($QuarantineId, "release to $stored")) {
        $released.Add([System.Text.Json.Nodes.JsonValue]::Create($stored))
        Save-MfState $state
        $applied = $true
    }
    $data = [pscustomobject][ordered]@{ quarantineId = $QuarantineId; releasedTo = $stored; quarantineType = $type }
    [pscustomobject][ordered]@{ data = $data; diff = @($diff); applied = $applied }
}

Export-ModuleMember -Function Get-MailFlowTrace, Restore-QuarantinedMessage
