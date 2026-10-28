Set-StrictMode -Version Latest

# DeviceOps levers (B-62). They work on the offline MOCK RMM state only: <tenant folder>/<client>/devices.json when that
# file exists in the folder named by $env:REDLINE_MOCK_TENANT_DIR (the Python bridge sets it), else the committed mock in
# this module's mock/<client>/ folder. No network, no credentials, no real RMM.
#
# Each function runs exactly one vetted script named in vetted-scripts.json (one per lever, hash-pinned). The script is
# a list of plain-language steps that the mock RMM "runs" by changing the device record; nothing here executes a command
# and there is no parameter that carries a script, a path or a command line.
#
# Contract with the lever host (B-15): the Python runner has already decided that the call is allowed (role, client scope,
# approval, window, caps). These functions never check roles and hold no time logic: the window for a reboot is the
# runner's rule. They receive the client id from the host (-Client). The change is a list of field edits worked out from
# the state; a dry-run (-WhatIf) returns that list and writes nothing, and execute applies exactly that list, so the two
# diffs are the same by construction. After applying, the state is read back and each verification check is evaluated.
#
# A rule that lives in the data (wrong device, offline, unknown drive) is returned as a { refusal } object, which the host
# reports as denied with the sentence intact. Every function returns { data, diff, applied } or { refusal }.

class DoRefusal : System.Exception {
    DoRefusal([string] $Message) : base($Message) { }
}

$script:Nothing = 'nothing was changed'

function Get-DoStateDir {
    # The only place a client id becomes a path (STD-ID-4): a plain slug, then one folder.
    param([Parameter(Mandatory)][string] $Client)
    if ($Client -cnotmatch '^[a-z0-9][a-z0-9-]{0,62}$') { throw 'Client id is not a valid slug; no file was read.' }
    $root = $env:REDLINE_MOCK_TENANT_DIR
    if (-not [string]::IsNullOrWhiteSpace($root)) {
        $shared = Join-Path (Join-Path $root $Client) 'devices.json'
        if (Test-Path -LiteralPath $shared -PathType Leaf) { return (Split-Path -Parent $shared) }
    }
    Join-Path (Join-Path $PSScriptRoot 'mock') $Client
}

function Get-DoText {
    param($Node)
    if ($null -eq $Node) { $null } else { $Node.GetValue[string]() }
}

function Get-DoScalar {
    # A JSON leaf as a PowerShell value: string, whole number, boolean or $null.
    param($Node)
    if ($null -eq $Node) { return $null }
    switch ($Node.GetValueKind()) {
        'String' { $Node.GetValue[string]() }
        'Number' { $Node.GetValue[long]() }
        'True' { $true }
        'False' { $false }
        default { $null }
    }
}

function Read-DoJson {
    param([Parameter(Mandatory)][string] $Path)
    , [System.Text.Json.Nodes.JsonNode]::Parse([System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false))).AsObject()
}

function Open-DoState {
    # JsonNode, not ConvertFrom-Json: nothing (numbers, empty arrays, nulls) changes shape on the way back to disk.
    param([Parameter(Mandatory)][string] $Client)
    $path = Join-Path (Get-DoStateDir $Client) 'devices.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "No device state for client $Client; nothing was read." }
    $root = Read-DoJson $path
    $meta = $root['_meta']
    if ($null -eq $meta -or (Get-DoText $meta.AsObject()['client']) -cne $Client) { throw "Device state does not belong to client $Client; nothing was read." }
    [pscustomobject]@{ Path = $path; Root = $root; Site = (Get-DoText $meta.AsObject()['siteUid']); AsOf = (Get-DoText $meta.AsObject()['as_of']) }
}

function Save-DoState {
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

function ConvertTo-DoUtc {
    param([Parameter(Mandatory)][string] $Text)
    $parsed = [datetimeoffset]::MinValue
    $styles = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
    if (-not [datetimeoffset]::TryParse($Text, [cultureinfo]::InvariantCulture, $styles, [ref] $parsed)) { throw [DoRefusal]::new("A date is not valid; $script:Nothing.") }
    $parsed.UtcDateTime
}

function Get-DoAsOf {
    # STD-PS-10: never the wall clock. The caller's -AsOf, else the moment the mock state was written for.
    param([Parameter(Mandatory)] $State, [string] $AsOf)
    if ([string]::IsNullOrWhiteSpace($AsOf)) { $AsOf = $State.AsOf }
    $utc = ConvertTo-DoUtc $AsOf
    [pscustomobject]@{
        Utc   = $utc
        Text  = $utc.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [cultureinfo]::InvariantCulture)
        Stamp = $utc.ToString('yyyyMMdd', [cultureinfo]::InvariantCulture)
    }
}

function Get-DoHash {
    param([Parameter(Mandatory)][string] $Text)
    [System.Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($Text))).ToLowerInvariant()
}

function Get-DoScript {
    # The vetted script of one lever. The whole catalog must match its pinned hashes, or nothing runs: a changed step list
    # is a change to what the approver approved.
    param([Parameter(Mandatory)][string] $Lever)
    $path = Join-Path $PSScriptRoot 'vetted-scripts.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw [DoRefusal]::new("The list of vetted scripts is missing; $script:Nothing.") }
    $catalog = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json
    $found = $null
    foreach ($prop in $catalog.scripts.PSObject.Properties) {
        $entry = $prop.Value
        $text = (@([string] $entry.script_id, [string] $entry.version) + @($entry.steps | ForEach-Object { [string] $_ })) -join "`n"
        if ((Get-DoHash $text) -cne [string] $entry.sha256) { throw [DoRefusal]::new("A vetted script no longer matches its pinned hash, so no script ran; $script:Nothing.") }
        if ($prop.Name -ceq $Lever) { $found = $entry }
    }
    if ($null -eq $found) { throw [DoRefusal]::new("No vetted script is named for $Lever; $script:Nothing.") }
    [pscustomobject]@{ Id = [string] $found.script_id; Version = [int] $found.version; Steps = @($found.steps | ForEach-Object { [string] $_ }); Sha256 = [string] $found.sha256 }
}

function Find-DoDevice {
    # One message for "absent", "another client's" and "another site's": no existence oracle across clients (C-27).
    param([Parameter(Mandatory)] $State, [Parameter(Mandatory)][string] $Uid)
    foreach ($item in $State.Root['devices'].AsArray()) {
        $node = $item.AsObject()
        if ([string]::Equals((Get-DoText $node['uid']), $Uid, [System.StringComparison]::OrdinalIgnoreCase) -and (Get-DoText $node['siteUid']) -ceq $State.Site) {
            return [pscustomobject]@{ Node = $node; Uid = (Get-DoText $node['uid']) }
        }
    }
    throw [DoRefusal]::new("No such device for this client; $script:Nothing.")
}

function Get-DoNode {
    # A node by relative path ('services/Spooler/health'), or $null. The comma keeps an object from being unrolled.
    param($Obj, [Parameter(Mandatory)][string] $Rel)
    $cur = $Obj
    foreach ($segment in $Rel.Split('/')) {
        if ($null -eq $cur -or $cur -isnot [System.Text.Json.Nodes.JsonObject]) { return , $null }
        $cur = $cur[$segment]
    }
    , $cur
}

function Set-DoLeaf {
    param($Obj, [Parameter(Mandatory)][string] $Rel, [Parameter(Mandatory)] $Value)
    $segments = $Rel.Split('/')
    $cur = $Obj
    for ($i = 0; $i -lt $segments.Count - 1; $i++) { $cur = $cur[$segments[$i]] }
    $leaf = $segments[$segments.Count - 1]
    if ($Value -is [bool]) { $cur[$leaf] = [System.Text.Json.Nodes.JsonValue]::Create([bool] $Value) }
    elseif ($Value -is [long] -or $Value -is [int]) { $cur[$leaf] = [System.Text.Json.Nodes.JsonValue]::Create([long] $Value) }
    else { $cur[$leaf] = [System.Text.Json.Nodes.JsonValue]::Create([string] $Value) }
}

function Test-DoSame {
    param($Node, [Parameter(Mandatory)] $Wanted)
    if ($null -eq $Node) { return $false }
    $Node.ToJsonString() -ceq (ConvertTo-Json -InputObject $Wanted -Compress)
}

function Get-DoChanges {
    # The edits that bring the device to the wanted values. The same list is shown on a dry-run and applied on execute.
    param([Parameter(Mandatory)] $Found, [Parameter(Mandatory)][AllowEmptyCollection()][object[]] $Wants)
    $edits = [System.Collections.Generic.List[object]]::new()
    foreach ($want in $Wants) {
        $node = Get-DoNode $Found.Node $want.Rel
        if (Test-DoSame $node $want.Value) { continue }
        $path = "/devices/$($Found.Uid)/$($want.Rel)"
        $change = if ($null -eq $node) { [pscustomobject][ordered]@{ op = 'add'; path = $path; after = $want.Value } }
        else { [pscustomobject][ordered]@{ op = 'replace'; path = $path; before = (Get-DoScalar $node); after = $want.Value } }
        $edits.Add([pscustomobject]@{ Rel = $want.Rel; Value = $want.Value; Change = $change })
    }
    # Ordinal order by path, the same order the runner uses, so the plan digest does not depend on the culture.
    $edits.Sort([System.Comparison[object]] { param($a, $b) [string]::CompareOrdinal($a.Change.path, $b.Change.path) })
    , @($edits)
}

function Get-DoRemoteSession {
    # B62-4: the latest remote-support session on this device that ended at or before the as-of moment, from the client's
    # own session log (read only). $null when there is none. The log carries a computer name, not an RMM uid.
    param([Parameter(Mandatory)][string] $Client, [Parameter(Mandatory)][string] $Hostname, [Parameter(Mandatory)] $AsOf)
    $path = Join-Path (Get-DoStateDir $Client) 'remote-sessions.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $root = Read-DoJson $path
    if ((Get-DoText $root['_meta'].AsObject()['client']) -cne $Client) { return $null }
    $best = $null; $bestEnd = [datetime]::MinValue
    foreach ($item in $root['sessions'].AsArray()) {
        $row = $item.AsObject()
        if (-not [string]::Equals((Get-DoText $row['computer_name']), $Hostname, [System.StringComparison]::OrdinalIgnoreCase)) { continue }
        $end = ConvertTo-DoUtc (Get-DoText $row['end_time'])
        if ($end -gt $AsOf.Utc -or $end -le $bestEnd) { continue }
        $bestEnd = $end
        $best = [pscustomobject][ordered]@{
            session_id    = Get-DoText $row['session_id']
            technician    = Get-DoText $row['technician']
            started       = Get-DoText $row['start_time']
            ended         = Get-DoText $row['end_time']
            computer_name = Get-DoText $row['computer_name']
            source        = 'remote-sessions.json'
        }
    }
    $best
}

function Invoke-DoLever {
    param(
        [Parameter(Mandatory)] $Cmdlet, [Parameter(Mandatory)][string] $Lever, [Parameter(Mandatory)][string] $Client,
        [Parameter(Mandatory)][string] $Uid, [string] $AsOfText,
        [Parameter(Mandatory)][ValidateSet('any', 'workstation', 'server')][string] $Kind,
        [Parameter(Mandatory)][string] $FaultKey, [Parameter(Mandatory)][string] $Action,
        [Parameter(Mandatory)][scriptblock] $Spec
    )
    try {
        $entry = Get-DoScript $Lever
        $state = Open-DoState $Client
        $when = Get-DoAsOf $state $AsOfText
        $found = Find-DoDevice $state $Uid
        $category = Get-DoText $found.Node['deviceType'].AsObject()['category']
        $class = if ($category -ceq 'Server') { 'server' } else { 'workstation' }
        $hostname = Get-DoText $found.Node['hostname']
        if ($Kind -ceq 'workstation' -and $class -ceq 'server') { throw [DoRefusal]::new("This device is a server; servers use the lever device.reboot-server; $script:Nothing.") }
        if ($Kind -ceq 'server' -and $class -ceq 'workstation') { throw [DoRefusal]::new("This device is a workstation; workstations use the lever device.reboot; $script:Nothing.") }
        if (-not $found.Node['online'].GetValue[bool]()) { throw [DoRefusal]::new("The device is offline, so no script can run on it; $script:Nothing.") }

        # The lever's own part: what to bring the device to, how to check it, and how a person would go back.
        $ctx = [pscustomobject]@{ Node = $found.Node; Uid = $found.Uid; AsOf = $when.Text; Stamp = $when.Stamp }
        $wanted = & $Spec $ctx
        $edits = Get-DoChanges $found @($wanted.Wants)
        $diff = @($edits | ForEach-Object { $_.Change })

        $digestText = (@($Lever, $Client, $found.Uid, $entry.Sha256) + @($diff | ForEach-Object { ConvertTo-Json -InputObject $_ -Compress })) -join '|'
        $verification = [ordered]@{
            status = 'planned'
            checks = @($wanted.Checks | ForEach-Object { [pscustomobject][ordered]@{ check = $_.Check; expected = $_.Value } })
        }
        $data = [pscustomobject][ordered]@{
            lever          = $Lever
            script         = [pscustomobject][ordered]@{ id = $entry.Id; version = $entry.Version; digest = $entry.Sha256.Substring(0, 16) }
            device         = [pscustomobject][ordered]@{ uid = $found.Uid; hostname = $hostname; class = $class }
            would_run      = @($entry.Steps)
            mode           = 'planned'
            verification   = [pscustomobject]$verification
            rollback       = [pscustomobject][ordered]@{ automated = $false; undo_lever = $null; kind = $wanted.RollbackKind; proposal = @($wanted.Rollback) }
            remote_session = Get-DoRemoteSession $Client $hostname $when
            plan_digest    = (Get-DoHash $digestText).Substring(0, 24)
        }

        $applied = $false
        if (@($edits).Count -gt 0 -and $Cmdlet.ShouldProcess($hostname, $Action)) {
            # The script "runs": it makes exactly the listed edits, unless this mock device is set to fail this script.
            $faults = @($found.Node['faults'].AsArray() | ForEach-Object { Get-DoText $_ })
            if ($faults -notcontains $FaultKey) {
                foreach ($edit in $edits) { Set-DoLeaf $found.Node $edit.Rel $edit.Value }
                Save-DoState $state
            }
            $applied = $true
            # Verification reads the state back from disk; it does not trust what the script said.
            $again = Find-DoDevice (Open-DoState $Client) $Uid
            foreach ($check in $wanted.Checks) {
                if (-not (Test-DoSame (Get-DoNode $again.Node $check.Rel) $check.Value)) {
                    $seen = Get-DoScalar (Get-DoNode $again.Node $check.Rel)
                    return [pscustomobject][ordered]@{ refusal = "Verification failed: $($check.Check) (expected $($check.Value), found $seen). The script made its changes; rollback: $(@($wanted.Rollback)[0])" }
                }
            }
            $data.mode = 'executed'
            $data.verification.status = 'passed'
        }
        [pscustomobject][ordered]@{ data = $data; diff = $diff; applied = $applied }
    }
    catch [DoRefusal] {
        [pscustomobject][ordered]@{ refusal = $_.Exception.Message }
    }
}

function New-DoWant {
    param([Parameter(Mandatory)][string] $Rel, [Parameter(Mandatory)] $Value, [Parameter(Mandatory)][string] $Check)
    [pscustomobject]@{ Rel = $Rel; Value = $Value; Check = $Check }
}

function Assert-DoNode {
    param([Parameter(Mandatory)] $Ctx, [Parameter(Mandatory)][string] $Rel, [Parameter(Mandatory)][string] $What)
    if ($null -eq (Get-DoNode $Ctx.Node $Rel)) { throw [DoRefusal]::new("$What is not present on this device; $script:Nothing.") }
}

# -- the seven levers ---------------------------------------------------------------------------------------------

function Restart-DevicePrintSpooler {
    <#
    .SYNOPSIS
      Lever device.restart-spooler: restart the Print Spooler on one device and clear its stuck print jobs.
    .DESCRIPTION
      Vetted script dev-spooler-restart. Print jobs that were stuck are removed; the user prints them again.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')][string] $Device, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DoLever -Cmdlet $PSCmdlet -Lever 'device.restart-spooler' -Client $Client -Uid $Device -AsOfText $AsOf `
        -Kind any -FaultKey 'spooler-fails' -Action 'run the vetted script that restarts the Print Spooler' -Spec {
        param($c)
        Assert-DoNode $c 'services/Spooler' 'The Print Spooler service'
        $wants = @(
            (New-DoWant 'services/Spooler/status' 'Running' 'Print Spooler is Running')
            (New-DoWant 'services/Spooler/health' 'Ok' 'Print Spooler reports healthy')
            (New-DoWant 'printQueue/stuckJobs' ([long] 0) 'The print queue has no stuck jobs')
        )
        [pscustomobject]@{
            Wants        = $wants
            Checks       = $wants
            RollbackKind = 'none-needed'
            Rollback     = @('Nothing to restore: restarting the spooler changes no settings.', 'The print jobs that were stuck were removed; ask the user to print them again.')
        }
    }
}

function Repair-DeviceMappedDrive {
    <#
    .SYNOPSIS
      Lever device.repair-mapped-drive: reconnect one mapped network drive letter on one device.
    .DESCRIPTION
      Vetted script dev-drive-repair. The share path is the one already saved on the device; the lever cannot name another.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')][string] $Device,
        [Parameter(Mandatory)][ValidatePattern('^[D-Z]$')][string] $Drive, [Parameter(Mandatory)][string] $Client, [string] $AsOf
    )
    Invoke-DoLever -Cmdlet $PSCmdlet -Lever 'device.repair-mapped-drive' -Client $Client -Uid $Device -AsOfText $AsOf `
        -Kind any -FaultKey 'drive-fails' -Action "run the vetted script that reconnects drive ${Drive}:" -Spec {
        param($c)
        Assert-DoNode $c "mappedDrives/$Drive" "Drive ${Drive}:"
        $want = New-DoWant "mappedDrives/$Drive/state" 'Connected' "Drive ${Drive}: reports Connected"
        [pscustomobject]@{
            Wants        = @($want)
            Checks       = @($want)
            RollbackKind = 'none-needed'
            Rollback     = @('Nothing to restore: the saved path was reconnected as it was.', 'If the mapping itself was wrong, a person disconnects the drive letter and maps the right path by hand.')
        }
    }
}

function Reset-DeviceOutlookProfile {
    <#
    .SYNOPSIS
      Lever device.reset-outlook-profile: rename one user's Outlook profile data to a dated backup so a new profile is built.
    .DESCRIPTION
      Vetted script dev-outlook-reset. Mail stored on the server is not touched; cached data is rebuilt on the next start.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')][string] $Device,
        [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9._-]{1,31}$')][string] $User, [Parameter(Mandatory)][string] $Client, [string] $AsOf
    )
    Invoke-DoLever -Cmdlet $PSCmdlet -Lever 'device.reset-outlook-profile' -Client $Client -Uid $Device -AsOfText $AsOf `
        -Kind any -FaultKey 'outlook-fails' -Action "run the vetted script that resets the Outlook profile of $User" -Spec {
        param($c)
        Assert-DoNode $c "outlookProfiles/$User" "An Outlook profile for $User"
        $backup = "Outlook-$User.bak-$($c.Stamp)"
        $state = New-DoWant "outlookProfiles/$User/state" 'Reset' "The Outlook profile of $User is marked Reset"
        $wants = @($state)
        $checks = @($state)
        if ((Get-DoText (Get-DoNode $c.Node "outlookProfiles/$User/state")) -cne 'Reset') {
            $name = New-DoWant "outlookProfiles/$User/backup" $backup 'The old profile data is kept under its backup name'
            $wants += $name
            $checks += $name
        }
        [pscustomobject]@{
            Wants        = $wants
            Checks       = $checks
            RollbackKind = 'restore-from-backup'
            Rollback     = @(
                "To go back, close Outlook and rename the backup $backup to the profile name.",
                'Mail stored on the server is not affected; cached data is rebuilt on the next start.'
            )
        }
    }
}

function Clear-DeviceTemp {
    <#
    .SYNOPSIS
      Lever device.cleanup-temp: move temp files older than 7 days into a dated quarantine folder. Nothing is deleted.
    .DESCRIPTION
      Vetted script dev-temp-cleanup. No purge job exists in this repo, so quarantined files stay until a person removes them.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')][string] $Device, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DoLever -Cmdlet $PSCmdlet -Lever 'device.cleanup-temp' -Client $Client -Uid $Device -AsOfText $AsOf `
        -Kind any -FaultKey 'temp-fails' -Action 'run the vetted script that moves old temp files to quarantine' -Spec {
        param($c)
        $total = $c.Node['tempBytes'].GetValue[long]()
        $stale = $c.Node['tempStaleBytes'].GetValue[long]()
        $held = $c.Node['tempQuarantineBytes'].GetValue[long]()
        $wants = @(
            (New-DoWant 'tempBytes' ([long] ($total - $stale)) 'Temp folders no longer hold the old files')
            (New-DoWant 'tempStaleBytes' ([long] 0) 'No temp files older than 7 days are left')
            (New-DoWant 'tempQuarantineBytes' ([long] ($held + $stale)) 'The quarantine holds the moved files')
        )
        [pscustomobject]@{
            Wants        = $wants
            Checks       = $wants
            RollbackKind = 'restore-from-backup'
            Rollback     = @(
                "To go back, move the files from the quarantine folder temp-quarantine-$($c.Stamp) to the temp folders.",
                'Nothing was deleted. Quarantined files stay until a person removes them; no purge job exists in this repo.'
            )
        }
    }
}

function Restart-DeviceService {
    <#
    .SYNOPSIS
      Lever device.restart-service: restart one service from the approved list on one device.
    .DESCRIPTION
      Vetted script dev-service-restart. The service names the registry allows are an enum there; a service the device does not have is refused.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')][string] $Device,
        [Parameter(Mandatory)][ValidateSet('Dnscache', 'W32Time', 'BITS', 'wuauserv', 'LanmanWorkstation')][string] $Service,
        [Parameter(Mandatory)][string] $Client, [string] $AsOf
    )
    Invoke-DoLever -Cmdlet $PSCmdlet -Lever 'device.restart-service' -Client $Client -Uid $Device -AsOfText $AsOf `
        -Kind any -FaultKey 'service-fails' -Action "run the vetted script that restarts the $Service service" -Spec {
        param($c)
        Assert-DoNode $c "services/$Service" "The $Service service"
        $wants = @(
            (New-DoWant "services/$Service/status" 'Running' "$Service is Running")
            (New-DoWant "services/$Service/health" 'Ok' "$Service reports healthy")
        )
        [pscustomobject]@{
            Wants        = $wants
            Checks       = $wants
            RollbackKind = 'none-needed'
            Rollback     = @('Nothing to restore: restarting a service changes no settings.')
        }
    }
}

function Restart-DeviceWorkstation {
    <#
    .SYNOPSIS
      Lever device.reboot: restart one workstation. The runner's window rule decides when; this function holds no time logic.
    .DESCRIPTION
      Vetted script dev-reboot-workstation. A server is refused: servers use device.reboot-server.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')][string] $Device, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DoLever -Cmdlet $PSCmdlet -Lever 'device.reboot' -Client $Client -Uid $Device -AsOfText $AsOf `
        -Kind workstation -FaultKey 'reboot-fails' -Action 'run the vetted script that restarts the workstation' -Spec {
        param($c)
        $wants = @(
            (New-DoWant 'lastBoot' $c.AsOf 'A new boot time is reported')
            (New-DoWant 'pendingReboot' $false 'No restart is pending')
        )
        [pscustomobject]@{
            Wants        = $wants
            Checks       = $wants
            RollbackKind = 'cannot-undo'
            Rollback     = @(
                'A restart cannot be undone.',
                'Unsaved work in open programs is lost; tell the user before the approval is used.',
                'If the device does not come back, a technician opens a remote session.'
            )
        }
    }
}

function Restart-DeviceServer {
    <#
    .SYNOPSIS
      Lever device.reboot-server: restart one server. The runner's window rule decides when; this function holds no time logic.
    .DESCRIPTION
      Vetted script dev-reboot-server. A workstation is refused: workstations use device.reboot.
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param([Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')][string] $Device, [Parameter(Mandatory)][string] $Client, [string] $AsOf)
    Invoke-DoLever -Cmdlet $PSCmdlet -Lever 'device.reboot-server' -Client $Client -Uid $Device -AsOfText $AsOf `
        -Kind server -FaultKey 'reboot-fails' -Action 'run the vetted script that restarts the server' -Spec {
        param($c)
        $wants = @(
            (New-DoWant 'lastBoot' $c.AsOf 'A new boot time is reported')
            (New-DoWant 'pendingReboot' $false 'No restart is pending')
        )
        [pscustomobject]@{
            Wants        = $wants
            Checks       = $wants
            RollbackKind = 'cannot-undo'
            Rollback     = @(
                'A restart cannot be undone.',
                'People using the server''s shares and applications lose their connection while it restarts.',
                'If a service does not start afterwards, a technician checks it by hand; this lever does not.'
            )
        }
    }
}
