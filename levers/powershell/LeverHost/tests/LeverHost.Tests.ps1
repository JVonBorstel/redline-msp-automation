#requires -Version 7
<#
B-15 tests (specs/B-15.md: B15-1 to B15-3) for levers/powershell/LeverHost. Plain PowerShell 7 (STD-PS-9 until Pester 5 is installed).
Run:  pwsh -NoProfile -File levers/powershell/LeverHost/tests/LeverHost.Tests.ps1
Exit code 0 = all pass, 1 = failures. Prints "LeverHost tests: N passed, M failed".
Writes only under $env:TEMP (a per-run folder, removed at the end). No network. Fixture lever modules are written at run time
(synthetic, one fake client); the real levers/powershell tree is only read.
#>
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$hostDir = (Resolve-Path (Join-Path $here '..')).Path
$repo = (Resolve-Path (Join-Path $hostDir '..\..\..')).Path
$hostScript = Join-Path $hostDir 'Invoke-LeverRequest.ps1'
$resultSchema = Join-Path $repo 'schemas\lever-result.schema.json'

if ($PSVersionTable.PSVersion -lt [version] '7.4') {
    Write-Host "LeverHost tests: 0 passed, 0 failed (skipped: PowerShell $($PSVersionTable.PSVersion) is below 7.4, STD-PS-1)"
    exit 0
}

$script:pass = 0; $script:fail = 0
function Check([string] $Name, [bool] $Condition, [string] $Detail = '') {
    if ($Condition) { $script:pass++; Write-Host "PASS: $Name" } else { $script:fail++; Write-Host "FAIL: $Name $Detail" -ForegroundColor Red }
}
function Section([string] $t) { Write-Host "== $t" }

$tmp = Join-Path $env:TEMP "redline-leverhost-$PID"
$root = Join-Path $tmp 'modules'
New-Item -ItemType Directory -Force $root | Out-Null
$marker = Join-Path $tmp 'other-imported.txt'
# Built at run time so no secret-looking literal sits in the file (it is only a canary string).
$canary = 'CANARY-' + (-join ((1..8) | ForEach-Object { 'k' }))

function New-FixtureModule([string] $Name, [string] $Body, [string[]] $Export) {
    $dir = Join-Path $root $Name
    New-Item -ItemType Directory -Force $dir | Out-Null
    Set-Content -LiteralPath (Join-Path $dir "$Name.psm1") -Value ("Set-StrictMode -Version Latest`n" + $Body) -Encoding utf8
    $exports = ($Export | ForEach-Object { "'$_'" }) -join ', '
    Set-Content -LiteralPath (Join-Path $dir "$Name.psd1") -Value "@{ RootModule = '$Name.psm1'; ModuleVersion = '1.0.0'; GUID = '$([guid]::NewGuid())'; FunctionsToExport = @($exports); CmdletsToExport = @(); VariablesToExport = @(); AliasesToExport = @() }" -Encoding utf8
}

New-FixtureModule 'Probe' @"
function Get-ProbeThing {
    [CmdletBinding()] param([Parameter(Mandatory)][string] `$TicketId, [string] `$Client)
    [pscustomobject]@{ ticket_id = `$TicketId; client = `$Client; note = 'read only' }
}
function Set-ProbeThing {
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')] param([Parameter(Mandatory)][string] `$Upn, [string] `$AsOf)
    `$changed = `$false
    if (`$PSCmdlet.ShouldProcess(`$Upn, 'set flag')) { `$changed = `$true }
    [pscustomobject]@{
        data    = [pscustomobject]@{ upn = `$Upn; as_of = `$AsOf }
        diff    = @([pscustomobject]@{ op = 'replace'; path = 'flag'; before = `$false; after = `$true })
        applied = `$changed
    }
}
function Get-ProbeCrash { [CmdletBinding()] param() throw "boom `$env:USERNAME at C:\secret\path $canary" }
function Get-ProbeWriteError { [CmdletBinding()] param() Write-Error 'non-terminating'; 'unreached' }
function Get-ProbeNoisy { [CmdletBinding(SupportsShouldProcess)] param() Write-Host 'host chatter'; Write-Output 'out'; Write-Warning 'warn' }
function Set-ProbeLiar { [CmdletBinding(SupportsShouldProcess)] param() [pscustomobject]@{ diff = @(); applied = `$true } }
function Set-ProbeBadDiff { [CmdletBinding(SupportsShouldProcess)] param() [pscustomobject]@{ diff = @([pscustomobject]@{ op = 'rewrite'; path = 'x' }); applied = `$false } }
function Set-ProbeNoWhatIf { [CmdletBinding()] param() 'would have changed state' }
function Get-ProbeSlow { [CmdletBinding()] param() Start-Sleep -Seconds 20; 'late' }
function Get-ProbeHidden { [CmdletBinding()] param() 'private helper' }
"@ -Export 'Get-ProbeThing', 'Set-ProbeThing', 'Get-ProbeCrash', 'Get-ProbeWriteError', 'Get-ProbeNoisy', 'Set-ProbeLiar', 'Set-ProbeBadDiff', 'Set-ProbeNoWhatIf', 'Get-ProbeSlow'

# A second module that records, on disk, if it is ever imported: the host must import only the module named in `entry`.
New-FixtureModule 'Bystander' @"
Set-Content -LiteralPath '$marker' -Value 'imported'
function Get-BystanderThing { [CmdletBinding()] param() 'x' }
"@ -Export 'Get-BystanderThing'

function New-Request([hashtable] $Override = @{}) {
    $r = [ordered]@{
        version = 1; request_id = 'req-b15-0001'; lever = 'ticket.get'; lever_version = 1; client = 'contoso-dental'; mode = 'execute'
        params = [ordered]@{ ticket_id = 'T-3101' }
        entry = [ordered]@{ module = 'Probe'; function = 'Get-ProbeThing' }
    }
    foreach ($k in $Override.Keys) { $r[$k] = $Override[$k] }
    $r
}
# Runs the real host as a child process, as the Python bridge will: JSON on stdin, JSON on stdout, exit code.
function Invoke-Host($Request, [string[]] $Extra = @(), [string] $Raw) {
    $json = if ($PSBoundParameters.ContainsKey('Raw')) { $Raw } else { $Request | ConvertTo-Json -Depth 20 -Compress }
    $stdout = $json | & pwsh -NoProfile -NonInteractive -File $hostScript -ModulesRoot $root @Extra 2>$null
    $code = $LASTEXITCODE
    $text = (@($stdout) -join "`n")
    $parsed = $null
    try { $parsed = $text | ConvertFrom-Json -Depth 20 } catch { }
    [pscustomobject]@{ Code = $code; Text = $text; Lines = @($stdout).Count; Result = $parsed }
}
function Test-ResultShape($Result) {
    # The host result is the runner's InvokeResult minus the fields only Python can know. Adding them must give a valid lever-result.
    $full = [ordered]@{}
    foreach ($p in $Result.PSObject.Properties) { $full[$p.Name] = $p.Value }
    $full['identity'] = 'tech-1'; $full['audit_seq'] = 1
    [bool] (Test-Json -Json ($full | ConvertTo-Json -Depth 20 -Compress) -SchemaFile $resultSchema -ErrorAction SilentlyContinue)
}

try {
    Section 'B15-1 one JSON request in, one JSON result out, exit 0/1/2'
    $r = Invoke-Host (New-Request)
    Check 'B15-1 ok read: exit 0, one line, status ok' ($r.Code -eq 0 -and $r.Lines -eq 1 -and $r.Result.status -eq 'ok') $r.Text
    Check 'B15-1 result echoes lever, client, mode and carries the function output as data' ($r.Result.lever -eq 'ticket.get' -and $r.Result.client -eq 'contoso-dental' -and $r.Result.mode -eq 'execute' -and $r.Result.data.ticket_id -eq 'T-3101')
    Check 'B15-1 the host passes the request client to a function that has a -Client parameter' ($r.Result.data.client -eq 'contoso-dental')
    Check 'B15-1 stdout is valid JSON with no BOM and nothing else' ($r.Text.Length -gt 0 -and $r.Text[0] -eq '{' -and $r.Text[-1] -eq '}')
    Check 'B15-1 the result fits lever-result once the runner adds identity and audit_seq' (Test-ResultShape $r.Result)

    $w = Invoke-Host (New-Request @{ mode = 'dry-run'; lever = 'user.set-flag'; params = [ordered]@{ upn = 'priya.nair@contosodental.example' }; entry = [ordered]@{ module = 'Probe'; function = 'Set-ProbeThing' }; as_of = '2026-10-21' })
    Check 'B15-1 dry-run calls the function with -WhatIf: ok, applied false, diff present' ($w.Code -eq 0 -and $w.Result.status -eq 'ok' -and $w.Result.applied -eq $false -and @($w.Result.diff).Count -eq 1 -and $w.Result.diff[0].path -eq 'flag') $w.Text
    Check 'B15-1 dry-run stdout is only the result line (no "What if:" text leaks)' ($w.Lines -eq 1 -and $w.Text -notmatch 'What if')
    Check 'B15-1 the pinned as_of reaches a function with -AsOf' ($w.Result.data.as_of -eq '2026-10-21')
    Check 'B15-1 dry-run result fits lever-result' (Test-ResultShape $w.Result)
    $x = Invoke-Host (New-Request @{ mode = 'execute'; lever = 'user.set-flag'; params = [ordered]@{ upn = 'priya.nair@contosodental.example' }; entry = [ordered]@{ module = 'Probe'; function = 'Set-ProbeThing' } })
    Check 'B15-1 execute runs without -WhatIf and without a confirmation prompt: applied true' ($x.Code -eq 0 -and $x.Result.applied -eq $true) $x.Text

    $n = Invoke-Host (New-Request @{ lever = 'ticket.get'; entry = [ordered]@{ module = 'Probe'; function = 'Get-ProbeNoisy' }; params = [ordered]@{} })
    Check 'B15-1 Write-Host, warnings and host output from a lever never reach stdout' ($n.Lines -eq 1 -and $n.Text -notmatch 'chatter' -and $n.Text -notmatch 'warn' -and $n.Result.data -eq 'out') $n.Text

    $b = Invoke-Host (New-Request @{ entry = [ordered]@{ module = 'Probe'; function = 'Get-ProbeThing' } }) -Extra @()
    Check 'B15-1 only the module named in entry is imported (a sibling module never runs)' (-not (Test-Path -LiteralPath $marker))
    $b2 = Invoke-Host (New-Request @{ lever = 'bystander.get'; entry = [ordered]@{ module = 'Bystander'; function = 'Get-BystanderThing' }; params = [ordered]@{} })
    Check 'B15-1 naming the sibling module does import it (the canary is live, so the check above means something)' ((Test-Path -LiteralPath $marker) -and $b2.Result.status -eq 'ok')

    $bad = Invoke-Host $null -Raw '{ not json'
    Check 'B15-1 not JSON: exit 2, a result with status error, nothing ran' ($bad.Code -eq 2 -and $bad.Result.status -eq 'error' -and $bad.Result.reason -match 'not a valid lever-request') $bad.Text
    $empty = Invoke-Host $null -Raw ''
    Check 'B15-1 empty stdin: exit 2' ($empty.Code -eq 2 -and $empty.Result.status -eq 'error')
    $req = New-Request; $req['mode'] = 'apply'
    $badMode = Invoke-Host $req
    Check 'B15-1 a request that breaks the schema (mode apply): exit 2' ($badMode.Code -eq 2 -and $badMode.Result.status -eq 'error')
    $req = New-Request; $req['version'] = 2
    Check 'B15-1 an unknown request version: exit 2' ((Invoke-Host $req).Code -eq 2)
    $req = New-Request; $req['extra'] = 'x'
    Check 'B15-1 an unknown request field: exit 2' ((Invoke-Host $req).Code -eq 2)
    $req = New-Request; $req['entry'] = [ordered]@{ module = '..\Probe'; function = 'Get-ProbeThing' }
    Check 'B15-1 a path-shaped module name is refused by the schema before any import: exit 2' ((Invoke-Host $req).Code -eq 2)
    $missingMod = Invoke-Host (New-Request @{ entry = [ordered]@{ module = 'NoSuchModule'; function = 'Get-NoThing' } })
    Check 'B15-1 a module that is not installed: denied, exit 1' ($missingMod.Code -eq 1 -and $missingMod.Result.status -eq 'denied' -and $missingMod.Result.reason -match 'not installed') $missingMod.Text
    $noRoot = $null | & pwsh -NoProfile -NonInteractive -File $hostScript -ModulesRoot (Join-Path $tmp 'missing') 2>$null
    Check 'B15-1 a missing modules folder is a configuration error: exit 2' ($LASTEXITCODE -eq 2)

    $missingParam = Invoke-Host (New-Request @{ params = [ordered]@{ nope = 'x' } })
    Check 'B15-1 a param the function does not take is denied, exit 1' ($missingParam.Code -eq 1 -and $missingParam.Result.status -eq 'denied' -and $missingParam.Result.reason -match 'no parameter') $missingParam.Text
    $reserved = Invoke-Host (New-Request @{ params = [ordered]@{ client = 'fabrikam-capital' } })
    Check 'B15-1 a param that would override the request client (or any common parameter) is denied' ($reserved.Code -eq 1 -and $reserved.Result.reason -match 'reserved')
    $reserved2 = Invoke-Host (New-Request @{ params = [ordered]@{ error_action = 'SilentlyContinue' } })
    Check 'B15-1 common parameters such as ErrorAction cannot be set through params' ($reserved2.Code -eq 1 -and $reserved2.Result.reason -match 'reserved')
    $noWhatIf = Invoke-Host (New-Request @{ mode = 'dry-run'; lever = 'user.set-flag'; params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Set-ProbeNoWhatIf' } })
    Check 'B15-1 a dry-run of a function with no -WhatIf is denied (fail closed): it never runs' ($noWhatIf.Code -eq 1 -and $noWhatIf.Result.status -eq 'denied' -and $noWhatIf.Result.reason -match 'WhatIf' -and $noWhatIf.Text -notmatch 'would have changed') $noWhatIf.Text
    $liar = Invoke-Host (New-Request @{ mode = 'dry-run'; lever = 'user.set-flag'; params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Set-ProbeLiar' } })
    Check 'B15-1 a lever that reports applied during a dry-run is an error, not an ok' ($liar.Code -eq 1 -and $liar.Result.status -eq 'error' -and $liar.Result.reason -match 'dry-run')
    $badDiff = Invoke-Host (New-Request @{ mode = 'dry-run'; lever = 'user.set-flag'; params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Set-ProbeBadDiff' } })
    Check 'B15-1 a diff entry that is not a change is an error' ($badDiff.Code -eq 1 -and $badDiff.Result.status -eq 'error' -and $badDiff.Result.reason -match 'diff')
    $slow = Invoke-Host (New-Request @{ lever = 'ticket.slow'; params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Get-ProbeSlow' } }) -Extra @('-TimeoutSeconds', '1')
    Check 'B15-1 a lever that runs past the timeout is stopped: error, exit 1' ($slow.Code -eq 1 -and $slow.Result.status -eq 'error' -and $slow.Result.reason -match 'timed out') $slow.Text

    Section 'B15-2 a thrown error becomes a crash result with no stack text'
    $log = Join-Path $tmp 'host.log'
    $c = Invoke-Host (New-Request @{ lever = 'ticket.crash'; params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Get-ProbeCrash' } }) -Extra @('-LogPath', $log)
    Check 'B15-2 a throw inside a lever: exit 1, status error, reason "ticket.crash crashed: RuntimeException"' ($c.Code -eq 1 -and $c.Result.status -eq 'error' -and $c.Result.reason -eq 'ticket.crash crashed: RuntimeException') $c.Text
    Check 'B15-2 stdout is one line and holds no exception message, path, stack frame or canary' ($c.Lines -eq 1 -and $c.Text -notmatch 'boom' -and $c.Text -notmatch 'secret' -and $c.Text -notmatch [regex]::Escape($canary) -and $c.Text -notmatch ' at ' -and $c.Text -notmatch '\.ps1' -and $c.Text -notmatch 'StackTrace' -and $c.Text -notmatch 'C:\\')
    Check 'B15-2 the detail goes to the operational log file only, when one is asked for' ((Test-Path -LiteralPath $log) -and ((Get-Content -LiteralPath $log -Raw) -match 'boom'))
    Check 'B15-2 the crash result fits lever-result once the runner adds identity and audit_seq' (Test-ResultShape $c.Result)
    $c2 = Invoke-Host (New-Request @{ lever = 'ticket.crash'; params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Get-ProbeWriteError' } })
    Check 'B15-2 a Write-Error inside a lever counts as a failure, not an ok (errors are terminating)' ($c2.Code -eq 1 -and $c2.Result.status -eq 'error' -and $c2.Result.reason -match 'crashed: ' -and $c2.Text -notmatch 'non-terminating') $c2.Text
    $noLog = Invoke-Host (New-Request @{ lever = 'ticket.crash'; params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Get-ProbeCrash' } })
    Check 'B15-2 with no -LogPath nothing is written and nothing leaks' ($noLog.Result.reason -eq 'ticket.crash crashed: RuntimeException' -and $noLog.Text -notmatch 'boom')

    Section 'B15-3 a function the module does not export is refused'
    $h = Invoke-Host (New-Request @{ params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Get-ProbeHidden' } })
    Check 'B15-3 a function defined in the module but not exported is refused: denied, exit 1, nothing ran' ($h.Code -eq 1 -and $h.Result.status -eq 'denied' -and $h.Result.reason -match 'not exported' -and $h.Text -notmatch 'private helper') $h.Text
    $h2 = Invoke-Host (New-Request @{ params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Get-Process' } })
    Check 'B15-3 a built-in command name is refused: it is not exported by the named module' ($h2.Code -eq 1 -and $h2.Result.status -eq 'denied' -and $h2.Result.reason -match 'not exported')
    $h3 = Invoke-Host (New-Request @{ params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Get-NoSuchThing' } })
    Check 'B15-3 a function that does not exist is refused the same way' ($h3.Code -eq 1 -and $h3.Result.status -eq 'denied')
    $h4 = Invoke-Host (New-Request @{ params = [ordered]@{}; entry = [ordered]@{ module = 'Probe'; function = 'Get-BystanderThing' } })
    Check 'B15-3 another module''s function is refused under this module name' ($h4.Code -eq 1 -and $h4.Result.status -eq 'denied')
    Check 'B15-3 each refusal result fits lever-result once the runner adds identity and audit_seq' ((Test-ResultShape $h.Result) -and (Test-ResultShape $h2.Result))

    Section 'B15-3 tests/ps/Test-Modules.ps1 aggregates every levers/powershell/*/tests file'
    $modRunner = Join-Path $repo 'tests\ps\Test-Modules.ps1'
    Check 'B15-3 tests/ps/Test-Modules.ps1 exists' (Test-Path -LiteralPath $modRunner)
    # A fixture tree with two modules: one passing test file, one failing, one that crashes, one that prints nothing parseable.
    $fx = Join-Path $tmp 'tree'
    foreach ($m in 'AaPass', 'BbFail', 'CcCrash', 'DdNoTests', 'EeSilent') { New-Item -ItemType Directory -Force (Join-Path $fx "$m\tests") | Out-Null }
    Set-Content -LiteralPath (Join-Path $fx 'AaPass\tests\AaPass.Tests.ps1') -Value 'Write-Host "AaPass tests: 3 passed, 0 failed"; exit 0'
    Set-Content -LiteralPath (Join-Path $fx 'BbFail\tests\BbFail.Tests.ps1') -Value 'Write-Host "BbFail tests: 1 passed, 2 failed"; exit 1'
    Set-Content -LiteralPath (Join-Path $fx 'CcCrash\tests\CcCrash.Tests.ps1') -Value 'throw "x"'
    Set-Content -LiteralPath (Join-Path $fx 'EeSilent\tests\EeSilent.Tests.ps1') -Value 'exit 0'
    Remove-Item -LiteralPath (Join-Path $fx 'DdNoTests\tests') -Recurse
    $mr = & pwsh -NoProfile -NonInteractive -File $modRunner -ModulesRoot $fx 2>&1 | Out-String
    $mrCode = $LASTEXITCODE
    # AaPass 3 passed; BbFail 1 passed 2 failed; CcCrash counts 1 failed (it crashed); EeSilent counts 1 failed (no summary line, cannot be trusted).
    Check 'B15-3 prints the summary `PS modules tests: N passed, M failed` summed over every tests file' ($mr -match '(?m)^PS modules tests: 4 passed, 4 failed\s*$') $mr
    Check 'B15-3 exit code 1 when anything failed, and a module without a tests folder is not an error' ($mrCode -eq 1)
    $treePass = Join-Path $tmp 'tree-pass'
    New-Item -ItemType Directory -Force (Join-Path $treePass 'Aa\tests') | Out-Null
    Set-Content -LiteralPath (Join-Path $treePass 'Aa\tests\Aa.Tests.ps1') -Value 'Write-Host "Aa tests: 5 passed, 0 failed"'
    $mp = & pwsh -NoProfile -NonInteractive -File $modRunner -ModulesRoot $treePass 2>&1 | Out-String
    Check 'B15-3 exit code 0 and the summary when everything passes' ($LASTEXITCODE -eq 0 -and $mp -match '(?m)^PS modules tests: 5 passed, 0 failed\s*$') $mp
    $files = @(Get-ChildItem -Path (Join-Path $repo 'levers\powershell') -Directory | ForEach-Object { Get-ChildItem -LiteralPath (Join-Path $_.FullName 'tests') -Filter '*.ps1' -File -ErrorAction SilentlyContinue })
    Check 'B15-3 the real tree has this file among the tests files the runner will find' (@($files | Where-Object Name -EQ 'LeverHost.Tests.ps1').Count -eq 1)

    Section 'STD checks on the module itself'
    $manifest = Test-ModuleManifest -Path (Join-Path $hostDir 'LeverHost.psd1')
    Check 'STD-PS-2 the manifest lists exactly the exported functions, no wildcards' ((@($manifest.ExportedFunctions.Keys | Sort-Object) -join ',') -eq 'ConvertTo-LeverParameterName,Invoke-LeverEntry,New-LeverResult,Test-LeverRequestJson')
    $verbs = @(Get-Verb | ForEach-Object Verb)
    Check 'STD-PS-3 every function uses an approved verb' (@($manifest.ExportedFunctions.Keys | Where-Object { ($_ -split '-')[0] -notin $verbs }).Count -eq 0)
    $src = (Get-Content -LiteralPath (Join-Path $hostDir 'LeverHost.psm1') -Raw) + (Get-Content -LiteralPath $hostScript -Raw)
    Check 'STD-PS-6 strict mode is set' ($src -match 'Set-StrictMode -Version Latest')
    Check 'no network call and no credential parameter in the host' ($src -notmatch 'Invoke-WebRequest|Invoke-RestMethod|HttpClient|WebClient|Connect-MgGraph|ClientSecret|-Password|Credential\b')
    Check 'STD-PS-5 no Write-Host in the host (stdout is the result, nothing else)' ($src -notmatch 'Write-Host')
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "LeverHost tests: $($script:pass) passed, $($script:fail) failed"
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
