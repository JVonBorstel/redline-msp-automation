#requires -Version 7
<#
B-29 tests (specs/B-29.md: B29-1 to B29-3) for levers/powershell/IdentityOps. Plain PowerShell 7 (STD-PS-9 until Pester 5 is installed).
Run:  pwsh -NoProfile -File levers/powershell/IdentityOps/tests/IdentityOps.Tests.ps1
Exit code 0 = all pass, 1 = failures. Prints "IdentityOps tests: N passed, M failed".
Works on a private copy of fixtures/tenant under $env:TEMP (removed at the end); the committed fixtures are only read. No network.
The end-to-end checks through the Python runner (registry, undo, byte-identical disable then enable) are in tests/py/levers/test_b29_identity.py.
#>
$ErrorActionPreference = 'Stop'
$ConfirmPreference = 'None'   # the lever host sets the same, so ConfirmImpact High never prompts
$here = $PSScriptRoot
$modDir = (Resolve-Path (Join-Path $here '..')).Path
$repo = (Resolve-Path (Join-Path $modDir '..\..\..')).Path

if ($PSVersionTable.PSVersion -lt [version] '7.4') {
    Write-Host "IdentityOps tests: 0 passed, 0 failed (skipped: PowerShell $($PSVersionTable.PSVersion) is below 7.4, STD-PS-1)"
    exit 0
}

$script:pass = 0; $script:fail = 0
function Check([string] $Name, [bool] $Condition, [string] $Detail = '') {
    if ($Condition) { $script:pass++; Write-Host "PASS: $Name" } else { $script:fail++; Write-Host "FAIL: $Name $Detail" -ForegroundColor Red }
}
function Section([string] $t) { Write-Host "== $t" }
function Throws([scriptblock] $Block) {
    try { & $Block | Out-Null; return '' } catch { return $_.Exception.GetType().Name }
}

$tmp = Join-Path $env:TEMP "redline-identityops-$PID"
$tenant = Join-Path $tmp 'tenant'
Copy-Item -LiteralPath (Join-Path $repo 'fixtures\tenant') -Destination $tenant -Recurse
$env:REDLINE_MOCK_TENANT_DIR = $tenant
Remove-Item Env:REDLINE_MOCK_GRAPH_SCOPES -ErrorAction SilentlyContinue
Import-Module (Join-Path $modDir 'IdentityOps.psd1') -Force

function Bytes([string] $Rel) { [System.IO.File]::ReadAllBytes((Join-Path $tenant $Rel)) }
function Same($a, $b) { [System.Linq.Enumerable]::SequenceEqual([byte[]] $a, [byte[]] $b) }
function UserOf([string] $Client, [string] $Upn) {
    $d = Get-Content -Raw -LiteralPath (Join-Path $tenant "$Client.json") | ConvertFrom-Json
    $d.users | Where-Object { $_.userPrincipalName -eq $Upn }
}

$C = 'contoso-dental'; $F = 'fabrikam-capital'
$ana = 'ana.lopez@contosodental.example'; $jamie = 'jamie.chen@contosodental.example'; $sam = 'sam.patel@contosodental.example'
$alex = 'alex.ward@fabrikamcapital.example'; $morgan = 'morgan.reyes@fabrikamcapital.example'

try {
    Section 'B29-1 Revoke-UserSessions'
    $before = Bytes "$C\sessions.json"
    $dry = Revoke-UserSessions -Upn $ana -Client $C -WhatIf
    Check 'B29-1: dry-run returns a one-entry diff on activeSessionCount (3 to 0) and applies nothing' ($dry.diff.Count -eq 1 -and $dry.diff[0].op -eq 'replace' -and $dry.diff[0].path -like '/sessions/*/activeSessionCount' -and $dry.diff[0].before -eq 3 -and $dry.diff[0].after -eq 0 -and -not $dry.applied)
    Check 'B29-1: dry-run leaves sessions.json byte-identical' (Same $before (Bytes "$C\sessions.json"))
    Check 'B29-1: the result states the lag' ($dry.data.lag -match 'short while')
    $run = Revoke-UserSessions -Upn $ana -Client $C
    Check 'B29-1: execute applies exactly the dry-run diff' ($run.applied -and ($run.diff | ConvertTo-Json -Compress) -eq ($dry.diff | ConvertTo-Json -Compress))
    $after = Get-Content -Raw -LiteralPath (Join-Path $tenant "$C\sessions.json") | ConvertFrom-Json
    Check 'B29-1: only Ana changed' ((@($after.value | Where-Object { $_.activeSessionCount -eq 0 }).Count -eq 2) -and (($after.value | Where-Object { $_.userPrincipalName -eq $sam }).activeSessionCount -eq 2))
    $again = Revoke-UserSessions -Upn $ana -Client $C
    Check 'B29-1: a second revoke is an empty diff and writes nothing (idempotent)' ($again.diff.Count -eq 0 -and -not $again.applied)
    $guestBefore = Bytes "$F\sessions.json"
    Check 'B29-1: a guest user is refused (NotSupportedException) and nothing is written' ((Throws { Revoke-UserSessions -Upn $alex -Client $F }) -eq 'NotSupportedException' -and (Same $guestBefore (Bytes "$F\sessions.json")))
    Check 'B29-1: a user of another client is not found (KeyNotFoundException)' ((Throws { Revoke-UserSessions -Upn $morgan -Client $C }) -eq 'KeyNotFoundException')
    Check 'B29-1: a client without a sessions file is refused (FileNotFoundException)' ((Throws { Revoke-UserSessions -Upn 'hannah.ortiz@litwarelegal.example' -Client 'litware-legal' }) -eq 'FileNotFoundException')
    Check 'B29-1: a client id that is not a slug is refused (ArgumentException)' ((Throws { Revoke-UserSessions -Upn $ana -Client '..\x' }) -eq 'ArgumentException')

    Section 'B29-2 Enable-UserAccount'
    # The committed fixture is hand-formatted (compact inline objects), and the first write by any writer, Python
    # MockTenant.save included, lays the whole file out in the canonical 2-space form. So "byte-identical" is measured
    # against the canonical form of the original: write it once unchanged ($orig), disable by hand (the Python
    # user.disable handler makes the same edit; the Python round trip is in the pytest file), enable, compare.
    $path = Join-Path $tenant "$C.json"
    $text = [System.IO.File]::ReadAllText($path)
    $eolOrig = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $o = [System.Text.Json.JsonSerializerOptions]::new(); $o.WriteIndented = $true; $o.Encoder = [System.Text.Encodings.Web.JavaScriptEncoder]::UnsafeRelaxedJsonEscaping
    function WriteCanon($n) { [System.IO.File]::WriteAllText($path, $n.ToJsonString($o).Replace("`r`n", "`n").Replace("`n", $eolOrig) + $eolOrig, [System.Text.UTF8Encoding]::new($false)) }
    $node = [System.Text.Json.Nodes.JsonNode]::Parse($text)
    WriteCanon $node
    $orig = Bytes "$C.json"
    foreach ($u in $node['users'].AsArray()) { if ($u['userPrincipalName'].GetValue[string]() -eq $jamie) { $u['accountEnabled'] = [System.Text.Json.Nodes.JsonValue]::Create($false) } }
    WriteCanon $node
    $disabled = Bytes "$C.json"
    $dry = Enable-UserAccount -Upn $jamie -Client $C -WhatIf
    Check 'B29-2: dry-run diff is accountEnabled false to true and writes nothing' ($dry.diff.Count -eq 1 -and $dry.diff[0].path -like '/users/*/accountEnabled' -and $dry.diff[0].before -eq $false -and $dry.diff[0].after -eq $true -and -not $dry.applied -and (Same $disabled (Bytes "$C.json")))
    $run = Enable-UserAccount -Upn $jamie -Client $C
    Check 'B29-2: execute re-enables the user and the file is byte-identical to its state before the disable' ($run.applied -and (Same $orig (Bytes "$C.json")))
    $again = Enable-UserAccount -Upn $jamie -Client $C
    Check 'B29-2: a second enable is an empty diff (idempotent)' ($again.diff.Count -eq 0 -and -not $again.applied)

    Section 'B29-3 Set-UserProperty'
    $base = Bytes "$C.json"
    $dry = Set-UserProperty -Upn $ana -Field department -Value 'Front Office' -Client $C -WhatIf
    Check 'B29-3: dry-run of a new field is an add diff and writes nothing' ($dry.diff.Count -eq 1 -and $dry.diff[0].op -eq 'add' -and $dry.diff[0].path -like '/users/*/department' -and $dry.diff[0].after -eq 'Front Office' -and -not $dry.applied -and (Same $base (Bytes "$C.json")))
    $run = Set-UserProperty -Upn $ana -Field department -Value 'Front Office' -Client $C
    $u = UserOf $C $ana
    Check 'B29-3: execute sets department and keeps every other field' ($run.applied -and $u.department -eq 'Front Office' -and $u.jobTitle -eq 'Office Manager' -and $u.accountEnabled -eq $true)
    $again = Set-UserProperty -Upn $ana -Field department -Value 'Front Office' -Client $C
    Check 'B29-3: the same value again is an empty diff (idempotent)' ($again.diff.Count -eq 0 -and -not $again.applied)
    $title = Set-UserProperty -Upn $ana -Field jobTitle -Value 'Practice Director' -Client $C
    Check 'B29-3: jobTitle change is a replace diff with before and after' ($title.applied -and $title.diff[0].op -eq 'replace' -and $title.diff[0].before -eq 'Office Manager' -and (UserOf $C $ana).jobTitle -eq 'Practice Director')
    $mgr = Set-UserProperty -Upn $ana -Field manager -Value $sam.ToUpper() -Client $C
    Check 'B29-3: manager is stored as the manager''s canonical UPN' ($mgr.applied -and (UserOf $C $ana).manager -ceq $sam)
    Check 'B29-3: a field outside the enum is refused before any file is read' ((Throws { Set-UserProperty -Upn $ana -Field accountEnabled -Value 'false' -Client $C }) -eq 'ParameterBindingValidationException')
    $snap = Bytes "$C.json"
    Check 'B29-3: a manager who is not a user of this client is refused (KeyNotFoundException)' ((Throws { Set-UserProperty -Upn $ana -Field manager -Value $morgan -Client $C }) -eq 'KeyNotFoundException')
    Check 'B29-3: a user cannot be their own manager (ArgumentException)' ((Throws { Set-UserProperty -Upn $ana -Field manager -Value $ana -Client $C }) -eq 'ArgumentException')
    Check 'B29-3: refused calls wrote nothing' (Same $snap (Bytes "$C.json"))

    Section 'Scope denial (B29-1 to B29-3)'
    $snapC = Bytes "$C.json"; $snapS = Bytes "$C\sessions.json"
    $env:REDLINE_MOCK_GRAPH_SCOPES = 'User.Read.All'
    Check 'B29-1: revoke without User.RevokeSessions.All is denied (UnauthorizedAccessException)' ((Throws { Revoke-UserSessions -Upn $sam -Client $C }) -eq 'UnauthorizedAccessException')
    Check 'B29-2: enable without User.EnableDisableAccount.All is denied' ((Throws { Enable-UserAccount -Upn $jamie -Client $C }) -eq 'UnauthorizedAccessException')
    Check 'B29-3: set-properties without User.ReadWrite.All is denied' ((Throws { Set-UserProperty -Upn $sam -Field department -Value 'Clinical' -Client $C }) -eq 'UnauthorizedAccessException')
    Check 'B29-3: a denied call wrote nothing, even a dry-run that would have changed something' ((Throws { Set-UserProperty -Upn $sam -Field department -Value 'Clinical' -Client $C -WhatIf }) -eq 'UnauthorizedAccessException' -and (Same $snapC (Bytes "$C.json")) -and (Same $snapS (Bytes "$C\sessions.json")))
    $env:REDLINE_MOCK_GRAPH_SCOPES = 'User.RevokeSessions.All User.ReadWrite.All'
    Check 'B29-1: with the permission granted the call works' ((Revoke-UserSessions -Upn $sam -Client $C -WhatIf).diff.Count -eq 1)
    Remove-Item Env:REDLINE_MOCK_GRAPH_SCOPES

    Section 'Through the lever host (B-15)'
    $hostScript = Join-Path $repo 'levers\powershell\LeverHost\Invoke-LeverRequest.ps1'
    $req = @{ version = 1; request_id = 'req-b29-0001'; lever = 'user.revoke-sessions'; lever_version = 1; client = $C; mode = 'dry-run'; params = @{ upn = $sam }; entry = @{ module = 'IdentityOps'; function = 'Revoke-UserSessions' } } | ConvertTo-Json -Depth 5 -Compress
    $out = $req | & pwsh -NoProfile -NonInteractive -File $hostScript
    $res = $out | ConvertFrom-Json
    Check 'B29-1: the host runs the lever as a dry-run and reports the diff, applied false' ($LASTEXITCODE -eq 0 -and $res.status -eq 'ok' -and $res.diff.Count -eq 1 -and $res.applied -eq $false)
    $env:REDLINE_MOCK_GRAPH_SCOPES = 'User.Read.All'
    $out = $req | & pwsh -NoProfile -NonInteractive -File $hostScript
    $res = $out | ConvertFrom-Json
    Check 'B29-1: a scope denial through the host is an error that carries no message text, only an exception type name' ($LASTEXITCODE -eq 1 -and $res.status -eq 'error' -and $res.reason -eq 'user.revoke-sessions crashed: RuntimeException' -and $res.applied -eq $false)
    Remove-Item Env:REDLINE_MOCK_GRAPH_SCOPES

    Section 'Layout (STD-PS)'
    $manifest = Import-PowerShellDataFile (Join-Path $modDir 'IdentityOps.psd1')
    Check 'manifest exports exactly the three lever functions' (($manifest.FunctionsToExport | Sort-Object) -join ',' -eq 'Enable-UserAccount,Revoke-UserSessions,Set-UserProperty')
    $bad = @('Revoke-UserSessions', 'Enable-UserAccount', 'Set-UserProperty' | Where-Object {
            $c = Get-Command $_; -not ($c.Parameters.ContainsKey('WhatIf') -and $c.Parameters.ContainsKey('Client'))
        })
    Check 'every lever function supports -WhatIf and takes -Client' ($bad.Count -eq 0)
}
catch {
    $script:fail++
    Write-Host "FAIL: tests crashed: $($_.Exception.GetType().Name): $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Remove-Item Env:REDLINE_MOCK_GRAPH_SCOPES -ErrorAction SilentlyContinue
    Remove-Item Env:REDLINE_MOCK_TENANT_DIR -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "IdentityOps tests: $script:pass passed, $script:fail failed"
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
