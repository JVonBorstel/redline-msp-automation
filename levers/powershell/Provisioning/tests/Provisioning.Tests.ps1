#requires -Version 7
<#
B-35 tests (specs/B-35.md: B35-1) for levers/powershell/Provisioning. Plain PowerShell 7 (STD-PS-9 until Pester 5 is installed).
Run:  pwsh -NoProfile -File levers/powershell/Provisioning/tests/Provisioning.Tests.ps1
Exit code 0 = all pass, 1 = failures. Prints "Provisioning tests: N passed, M failed".
Works on a private copy of fixtures/tenant under $env:TEMP (removed at the end); the committed fixtures are only read. No network.
The end-to-end checks through the Python runner (registry, R3 approvals, the plan workflow) are in tests/py/onboarding/test_b35_onboarding.py.
#>
$ErrorActionPreference = 'Stop'
$ConfirmPreference = 'None'   # the lever host sets the same, so ConfirmImpact High never prompts
$here = $PSScriptRoot
$modDir = (Resolve-Path (Join-Path $here '..')).Path
$repo = (Resolve-Path (Join-Path $modDir '..\..\..')).Path

if ($PSVersionTable.PSVersion -lt [version] '7.4') {
    Write-Host "Provisioning tests: 0 passed, 0 failed (skipped: PowerShell $($PSVersionTable.PSVersion) is below 7.4, STD-PS-1)"
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

$tmp = Join-Path $env:TEMP "redline-provisioning-$PID"
$tenant = Join-Path $tmp 'tenant'
Copy-Item -LiteralPath (Join-Path $repo 'fixtures\tenant') -Destination $tenant -Recurse
$env:REDLINE_MOCK_TENANT_DIR = $tenant
Remove-Item Env:REDLINE_MOCK_GRAPH_SCOPES -ErrorAction SilentlyContinue
Import-Module (Join-Path $modDir 'Provisioning.psd1') -Force

function Bytes([string] $Rel) { [System.IO.File]::ReadAllBytes((Join-Path $tenant $Rel)) }
function Same($a, $b) { [System.Linq.Enumerable]::SequenceEqual([byte[]] $a, [byte[]] $b) }
function Doc([string] $Rel) { Get-Content -Raw -LiteralPath (Join-Path $tenant $Rel) | ConvertFrom-Json }

$C = 'contoso-dental'; $L = 'litware-legal'
$ana = 'ana.lopez@contosodental.example'; $sam = 'sam.patel@contosodental.example'
$casey = 'casey.moreno@contosodental.example'

try {
    Section 'B35-1 New-UserAccount'
    $tenantBefore = Bytes "$C.json"; $boxesBefore = Bytes "$C\mailboxes.json"
    $dry = New-UserAccount -Upn $casey -DisplayName 'Casey Moreno' -JobTitle 'Front Desk Coordinator' -Department 'Reception' -ManagerUpn $ana -Client $C -WhatIf
    Check 'B35-1: dry-run returns two adds (the user and the mailbox record) and applies nothing' ($dry.diff.Count -eq 2 -and $dry.diff[0].op -eq 'add' -and $dry.diff[0].path -like '/users/*' -and $dry.diff[1].path -like '/mailboxes/*' -and -not $dry.applied)
    Check 'B35-1: dry-run leaves both files byte-identical' ((Same $tenantBefore (Bytes "$C.json")) -and (Same $boxesBefore (Bytes "$C\mailboxes.json")))
    Check 'B35-1: the diff holds the whole user record, enabled, with the manager stored as a UPN' ($dry.diff[0].after.accountEnabled -eq $true -and $dry.diff[0].after.manager -eq $ana -and $dry.diff[0].after.userPrincipalName -eq $casey)
    Check 'B35-1: the result says no credential exists yet' ($dry.data.signIn -match 'no credential')
    $again = New-UserAccount -Upn $casey -DisplayName 'Casey Moreno' -JobTitle 'Front Desk Coordinator' -Department 'Reception' -ManagerUpn $ana -Client $C -WhatIf
    Check 'B35-1: the ids are deterministic, so a second dry-run shows the same diff' (($again.diff | ConvertTo-Json -Depth 6 -Compress) -eq ($dry.diff | ConvertTo-Json -Depth 6 -Compress))

    $run = New-UserAccount -Upn $casey -DisplayName 'Casey Moreno' -JobTitle 'Front Desk Coordinator' -Department 'Reception' -ManagerUpn $ana -Client $C
    Check 'B35-1: execute applies exactly the dry-run diff' ($run.applied -and ($run.diff | ConvertTo-Json -Depth 6 -Compress) -eq ($dry.diff | ConvertTo-Json -Depth 6 -Compress))
    $user = (Doc "$C.json").users | Where-Object { $_.userPrincipalName -eq $casey }
    Check 'B35-1: the user exists, enabled, with the form values and no credential' ($user.displayName -eq 'Casey Moreno' -and $user.jobTitle -eq 'Front Desk Coordinator' -and $user.department -eq 'Reception' -and $user.manager -eq $ana -and $user.accountEnabled -eq $true -and $null -eq $user.PSObject.Properties['passwordProfile'] -and $null -eq $user.PSObject.Properties['authentication'])
    $box = (Doc "$C\mailboxes.json").mailboxes | Where-Object { $_.userPrincipalName -eq $casey }
    Check 'B35-1: the mailbox record exists with no archive and no delegates' ($box.recipientTypeDetails -eq 'UserMailbox' -and $box.archiveStatus -eq 'None' -and @($box.fullAccess).Count -eq 0 -and $box.autoReply.state -eq 'Disabled')
    $committedCount = @((Get-Content -Raw -LiteralPath (Join-Path $repo "fixtures\tenant\$C.json") | ConvertFrom-Json).users).Count
    Check 'B35-1: exactly one user was added and the others are still there' (@((Doc "$C.json").users).Count -eq ($committedCount + 1))

    $second = New-UserAccount -Upn $casey -DisplayName 'Casey Moreno' -JobTitle 'Front Desk Coordinator' -Department 'Reception' -ManagerUpn $ana -Client $C
    Check 'B35-1: a second run is an empty diff and writes nothing (idempotent)' ($second.diff.Count -eq 0 -and -not $second.applied -and $second.data.account -eq 'already present')

    Section 'B35-1 a half-finished earlier run adds only the missing part'
    $boxPath = Join-Path $tenant "$C\mailboxes.json"
    $boxes = Get-Content -Raw -LiteralPath $boxPath | ConvertFrom-Json
    $boxes.mailboxes = @($boxes.mailboxes | Where-Object { $_.userPrincipalName -ne $casey })
    [System.IO.File]::WriteAllText($boxPath, ($boxes | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
    $fix = New-UserAccount -Upn $casey -DisplayName 'Casey Moreno' -JobTitle 'Front Desk Coordinator' -Department 'Reception' -ManagerUpn $ana -Client $C
    Check 'B35-1: user present and mailbox record missing gives one add (the mailbox) and no second user' ($fix.applied -and $fix.diff.Count -eq 1 -and $fix.diff[0].path -like '/mailboxes/*' -and @((Doc "$C.json").users | Where-Object { $_.userPrincipalName -eq $casey }).Count -eq 1)

    Section 'B35-1 refusals'
    $usersBefore = Bytes "$C.json"
    Check 'B35-1: the same upn with other values throws InvalidOperationException and changes nothing' ((Throws { New-UserAccount -Upn $casey -DisplayName 'Casey Moreno' -JobTitle 'Chief Executive' -Department 'Reception' -ManagerUpn $ana -Client $C }) -eq 'InvalidOperationException' -and (Same $usersBefore (Bytes "$C.json")))
    Check 'B35-1: an unknown manager throws KeyNotFoundException' ((Throws { New-UserAccount -Upn 'dana.new@contosodental.example' -DisplayName 'Dana New' -JobTitle 'Clerk' -Department 'Reception' -ManagerUpn 'nobody@contosodental.example' -Client $C -WhatIf }) -eq 'KeyNotFoundException')
    Check 'B35-1: a user cannot be their own manager' ((Throws { New-UserAccount -Upn $sam -DisplayName 'Dr. Sam Patel' -JobTitle 'Dentist' -Department 'Clinical' -ManagerUpn $sam -Client $C -WhatIf }) -eq 'ArgumentException')
    Check 'B35-1: a display name with a line break is refused' ((Throws { New-UserAccount -Upn 'eve.new@contosodental.example' -DisplayName "Eve`nNew" -JobTitle 'Clerk' -Department 'Reception' -ManagerUpn $ana -Client $C -WhatIf }) -eq 'ArgumentException')
    Check 'B35-1: a display name that starts with a symbol is refused' ((Throws { New-UserAccount -Upn 'eve.new@contosodental.example' -DisplayName '#hash' -JobTitle 'Clerk' -Department 'Reception' -ManagerUpn $ana -Client $C -WhatIf }) -eq 'ArgumentException')
    Check 'B35-1: a bad client slug is refused before any file is read' ((Throws { New-UserAccount -Upn 'eve.new@contosodental.example' -DisplayName 'Eve New' -JobTitle 'Clerk' -Department 'Reception' -ManagerUpn $ana -Client '..\x' -WhatIf }) -eq 'ArgumentException')
    Check 'B35-1: an unknown client has no state to read' ((Throws { New-UserAccount -Upn 'eve.new@contosodental.example' -DisplayName 'Eve New' -JobTitle 'Clerk' -Department 'Reception' -ManagerUpn $ana -Client 'no-such-client' -WhatIf }) -eq 'FileNotFoundException')

    Section 'B35-1 a client with no mailbox file'
    $litwareManager = (Doc "$L.json").users[0].userPrincipalName
    $lit = New-UserAccount -Upn 'new.hire@litwarelegal.example' -DisplayName 'New Hire' -JobTitle 'Paralegal' -Department 'Legal' -ManagerUpn $litwareManager -Client $L -WhatIf
    Check 'B35-1: only the user is in the diff, and the result says the mailbox is not tracked' ($lit.diff.Count -eq 1 -and $lit.diff[0].path -like '/users/*' -and $lit.data.mailbox -match 'not tracked')

    Section 'B35-1 scope check'
    $env:REDLINE_MOCK_GRAPH_SCOPES = 'User.RevokeSessions.All'
    $scopeBefore = Bytes "$C.json"
    Check 'B35-1: without User.ReadWrite.All it throws UnauthorizedAccessException and writes nothing' ((Throws { New-UserAccount -Upn 'eve.new@contosodental.example' -DisplayName 'Eve New' -JobTitle 'Clerk' -Department 'Reception' -ManagerUpn $ana -Client $C }) -eq 'UnauthorizedAccessException' -and (Same $scopeBefore (Bytes "$C.json")))
    $env:REDLINE_MOCK_GRAPH_SCOPES = 'User.ReadWrite.All'
    Check 'B35-1: with the permission granted it runs' ((New-UserAccount -Upn 'eve.new@contosodental.example' -DisplayName 'Eve New' -JobTitle 'Clerk' -Department 'Reception' -ManagerUpn $ana -Client $C -WhatIf).diff.Count -eq 2)
    Remove-Item Env:REDLINE_MOCK_GRAPH_SCOPES -ErrorAction SilentlyContinue
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Provisioning tests: $($script:pass) passed, $($script:fail) failed"
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
