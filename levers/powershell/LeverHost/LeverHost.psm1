Set-StrictMode -Version Latest

# Fields of the host result. It is a subset of schemas/lever-result.schema.json: the Python runner owns `identity`,
# `approver` and `audit_seq` (it writes the audit) and adds them after the call (B-16). The host never invents them.

function Get-LhExceptionTypeName {
    # The leaf exception type name only (never message, stack or paths): STD-ER-5.
    param([Parameter(Mandatory)] $Exception)
    $e = $Exception
    for ($i = 0; $i -lt 10; $i++) {
        if ($e -is [System.Management.Automation.ActionPreferenceStopException] -and $null -ne $e.ErrorRecord -and $null -ne $e.ErrorRecord.Exception -and -not [object]::ReferenceEquals($e.ErrorRecord.Exception, $e)) { $e = $e.ErrorRecord.Exception; continue }
        if (($e -is [System.Management.Automation.MethodInvocationException] -or $e -is [System.Reflection.TargetInvocationException]) -and $null -ne $e.InnerException) { $e = $e.InnerException; continue }
        break
    }
    $name = ($e.GetType().Name -replace '[^A-Za-z0-9_]', '')
    if ([string]::IsNullOrEmpty($name)) { 'Exception' } else { $name }
}

function New-LeverResult {
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory)][ValidateSet('ok', 'denied', 'error')][string] $Status,
        [string] $Reason = '',
        [string] $Lever = 'unknown',
        [string] $Client = 'unknown',
        [string] $Mode = 'unknown',
        $Data = $null,
        [object[]] $Diff = @(),
        [bool] $Applied = $false
    )
    [pscustomobject][ordered]@{
        status  = $Status
        reason  = $Reason
        lever   = $Lever
        client  = $Client
        mode    = $Mode
        data    = $Data
        diff    = @($Diff)
        applied = $Applied
    }
}

function ConvertTo-LeverParameterName {
    # snake_case request key -> PascalCase parameter name: ticket_id -> TicketId.
    [CmdletBinding()]
    [OutputType([string])]
    param([Parameter(Mandatory)][string] $Name)
    (($Name -split '_') | Where-Object { $_ } | ForEach-Object { $_.Substring(0, 1).ToUpperInvariant() + $_.Substring(1) }) -join ''
}

function Test-LeverRequestJson {
    # Validates the request text against schemas/lever-request.schema.json. Returns Ok and a reason that names the rule, not the content.
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param([Parameter(Mandatory)][string] $Json, [Parameter(Mandatory)][string] $SchemaFile)
    $errs = $null
    $ok = Test-Json -Json $Json -SchemaFile $SchemaFile -ErrorAction SilentlyContinue -ErrorVariable errs
    $reason = ''
    if (-not $ok) {
        $first = @($errs) | Select-Object -First 1
        $reason = if ($null -ne $first) { ($first.Exception.Message -split "`n")[0] } else { 'not valid JSON' }
    }
    [pscustomobject]@{ Ok = [bool] $ok; Reason = $reason }
}

function Invoke-LeverEntry {
    <#
    Resolves and runs one lever function in an isolated runspace. The runspace has a null host, so the "What if:" text of
    -WhatIf and any host-directed output from the lever can never reach the host's stdout. Imports only <ModulesRoot>/<Module>/<Module>.psd1.
    Always returns a result object; never throws (STD-ER-1, STD-ER-5).
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory)] $Request,
        [Parameter(Mandatory)][string] $ModulesRoot,
        [int] $TimeoutSeconds = 30,
        [string] $LogPath
    )
    $lever = [string] $Request.lever; $client = [string] $Request.client; $mode = [string] $Request.mode
    function Out-Result($Status, $Reason, $Data = $null, $Diff = @(), $Applied = $false) {
        New-LeverResult -Status $Status -Reason $Reason -Lever $lever -Client $client -Mode $mode -Data $Data -Diff $Diff -Applied $Applied
    }
    $moduleName = [string] $Request.entry.module
    $function = [string] $Request.entry.function
    $manifest = Join-Path (Join-Path $ModulesRoot $moduleName) "$moduleName.psd1"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
        return (Out-Result 'denied' "module $moduleName is not installed under levers/powershell; nothing ran")
    }
    $ps = $null
    try {
        $ps = [powershell]::Create()
        $null = $ps.AddScript('$ErrorActionPreference = "Stop"; $ConfirmPreference = "None"; $ProgressPreference = "SilentlyContinue"').Invoke()
        $ps.Commands.Clear()
        $mod = $ps.AddCommand('Import-Module').AddParameter('Name', $manifest).AddParameter('Force').AddParameter('PassThru').Invoke() | Select-Object -First 1
        $ps.Commands.Clear()
        if ($null -eq $mod) { return (Out-Result 'error' "$lever could not load module $moduleName; nothing ran") }
        if (-not $mod.ExportedFunctions.ContainsKey($function)) {
            return (Out-Result 'denied' "function $function is not exported by module $moduleName; nothing ran")
        }
        $cmd = $mod.ExportedFunctions[$function]
        $accepted = $cmd.Parameters
        $common = @([System.Management.Automation.PSCmdlet]::CommonParameters) + @([System.Management.Automation.PSCmdlet]::OptionalCommonParameters)
        $splat = [ordered]@{}
        $params = $Request.params
        foreach ($prop in $params.PSObject.Properties) {
            $pname = ConvertTo-LeverParameterName $prop.Name
            if ($pname -in $common -or $pname -in 'Client', 'AsOf') { return (Out-Result 'denied' "parameter $($prop.Name) is reserved by the host; nothing ran") }
            if (-not $accepted.ContainsKey($pname)) { return (Out-Result 'denied' "function $function has no parameter $pname for $($prop.Name); nothing ran") }
            $splat[$pname] = $prop.Value
        }
        if ($accepted.ContainsKey('Client')) { $splat['Client'] = $client }
        if ($accepted.ContainsKey('AsOf') -and $null -ne $Request.PSObject.Properties['as_of']) { $splat['AsOf'] = [string] $Request.as_of }
        if ($mode -eq 'dry-run') {
            # Fail closed: a function that cannot do -WhatIf might change state, so it never runs as a dry-run (STD-PS-4).
            if (-not $accepted.ContainsKey('WhatIf')) { return (Out-Result 'denied' "function $function does not support -WhatIf, so it cannot run as a dry-run; nothing ran") }
            $splat['WhatIf'] = $true
        }
        $null = $ps.AddCommand($function)
        foreach ($k in $splat.Keys) { $null = $ps.AddParameter($k, $splat[$k]) }
        $handle = $ps.BeginInvoke()
        if (-not $handle.AsyncWaitHandle.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds))) {
            try { $ps.Stop() } catch { }
            return (Out-Result 'error' "$lever timed out after $TimeoutSeconds seconds; the host stopped it")
        }
        $output = @($ps.EndInvoke($handle))
    }
    catch {
        $type = Get-LhExceptionTypeName $_.Exception
        if ($LogPath) { try { Add-Content -LiteralPath $LogPath -Value ("{0} {1} crashed: {2}`n{3}" -f ([datetime]::UtcNow.ToString('o')), $lever, $type, $_.Exception.ToString()) } catch { } }
        return (Out-Result 'error' "$lever crashed: $type")
    }
    finally { if ($null -ne $ps) { $ps.Dispose() } }

    # Contract: the lever returns one object (or nothing). Optional members `data`, `diff` and `applied` map to the result
    # fields; otherwise the whole object is `data`.
    # A lever may refuse on a rule that lives in its data (for example a privileged group): it returns one object with a
    # `refusal` string, and the host reports denied with that reason. Nothing else about the object is trusted (B-32).
    if ($output.Count -eq 1 -and $output[0] -is [psobject] -and $null -ne $output[0].PSObject.Properties['refusal'] -and $output[0].refusal -is [string] -and $output[0].refusal.Length -gt 0) {
        return (Out-Result 'denied' ($output[0].refusal.Substring(0, [Math]::Min(300, $output[0].refusal.Length))))
    }
    $data = $null; $diff = @(); $applied = $false
    if ($output.Count -eq 1 -and $output[0] -is [psobject] -and $null -ne $output[0].PSObject.Properties['diff']) {
        $o = $output[0]
        $data = if ($null -ne $o.PSObject.Properties['data']) { $o.data } else { $null }
        $diff = @($o.diff)
        if ($null -ne $o.PSObject.Properties['applied']) { $applied = ($o.applied -eq $true) }
    }
    elseif ($output.Count -eq 1) { $data = $output[0] }
    elseif ($output.Count -gt 1) { $data = $output }
    foreach ($d in $diff) {
        $okShape = $d -is [psobject] -and $null -ne $d.PSObject.Properties['op'] -and $null -ne $d.PSObject.Properties['path'] -and $d.op -in 'add', 'remove', 'replace' -and $d.path -is [string] -and
        @(@($d.PSObject.Properties.Name) | Where-Object { $_ -notin 'op', 'path', 'before', 'after' }).Count -eq 0
        if (-not $okShape) { return (Out-Result 'error' "$lever returned a diff entry that is not a change (op, path, before, after); nothing was reported as applied") }
    }
    if ($mode -eq 'dry-run' -and $applied) { return (Out-Result 'error' "$lever reported a change as applied during a dry-run; treat it as not trusted") }
    Out-Result 'ok' '' $data $diff $applied
}

Export-ModuleMember -Function Test-LeverRequestJson, New-LeverResult, ConvertTo-LeverParameterName, Invoke-LeverEntry
