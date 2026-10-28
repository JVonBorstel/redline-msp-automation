#requires -Version 7
<#
B-33 tests (specs/B-33.md: B33-1, B33-2) for levers/powershell/MailboxOps. Plain PowerShell 7 (STD-PS-9 until Pester 5 is installed).
Run:  pwsh -NoProfile -File levers/powershell/MailboxOps/tests/MailboxOps.Tests.ps1
Exit code 0 = all pass, 1 = failures. Prints "MailboxOps tests: N passed, M failed".
Works on a private copy of the synthetic fixtures under $env:TEMP (removed at the end). No network. The committed fixtures are only read.
#>
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$moduleDir = (Resolve-Path (Join-Path $here '..')).Path
$repo = (Resolve-Path (Join-Path $moduleDir '..\..\..')).Path

if ($PSVersionTable.PSVersion -lt [version] '7.4') {
    Write-Host "MailboxOps tests: 0 passed, 0 failed (skipped: PowerShell $($PSVersionTable.PSVersion) is below 7.4, STD-PS-1)"
    exit 0
}

$script:pass = 0; $script:fail = 0
function Check([string] $Name, [bool] $Condition, [string] $Detail = '') {
    if ($Condition) { $script:pass++; Write-Host "PASS: $Name" } else { $script:fail++; Write-Host "FAIL: $Name $Detail" -ForegroundColor Red }
}
function Section([string] $t) { Write-Host "== $t" }
function Get-Refusal([scriptblock] $Block) {
    try { & $Block | Out-Null; $null } catch { $_.Exception.Message }
}

$tmp = Join-Path $env:TEMP "redline-mailboxops-$PID"
New-Item -ItemType Directory -Force $tmp | Out-Null
foreach ($c in 'contoso-dental', 'fabrikam-capital') { Copy-Item -Recurse -LiteralPath (Join-Path $repo "fixtures\tenant\$c") -Destination $tmp }
$env:REDLINE_MOCK_TENANT_DIR = $tmp
$ConfirmPreference = 'None'
Import-Module (Join-Path $moduleDir 'MailboxOps.psd1') -Force

$d = 'contosodental.example'
$ana = "ana.lopez@$d"; $jamie = "jamie.chen@$d"; $tom = "tom.baker@$d"; $info = "info@$d"; $front = "frontdesk@$d"
$alex = 'alex.ward@fabrikamcapital.example'
$file = Join-Path $tmp 'contoso-dental\mailboxes.json'
$original = [System.IO.File]::ReadAllBytes($file)
function Same([string] $Path, [byte[]] $Bytes) { [System.Linq.Enumerable]::SequenceEqual([byte[]][System.IO.File]::ReadAllBytes($Path), $Bytes) }

try {
    Section 'B33-1 every function: -WhatIf returns a diff and writes nothing'
    $calls = [ordered]@{
        'Add-MailboxDlMember'         = @{ Upn = $tom; List = $front }
        'Remove-MailboxDlMember'      = @{ Upn = $jamie; List = $front }
        'Grant-MailboxFullAccess'     = @{ Upn = $jamie; Delegate = $ana }
        'Revoke-MailboxFullAccess'    = @{ Upn = $info; Delegate = $ana }
        'Grant-MailboxSendAs'         = @{ Upn = $jamie; Delegate = $ana }
        'Revoke-MailboxSendAs'        = @{ Upn = $info; Delegate = $ana }
        'Convert-MailboxToShared'     = @{ Upn = $jamie }
        'Set-MailboxAutoReply'        = @{ Upn = $jamie; Message = 'Jamie has left the practice.' }
        'Enable-MailboxArchive'       = @{ Upn = $tom }
        'Grant-OneDriveManagerAccess' = @{ Upn = $jamie; Manager = $ana; ExpiresOn = '2026-11-15' }
    }
    foreach ($name in $calls.Keys) {
        $args1 = $calls[$name]
        $r = & $name @args1 -Client 'contoso-dental' -WhatIf
        Check "$name -WhatIf: one or more changes, not applied" ((@($r.diff).Count -ge 1) -and (-not $r.applied))
        Check "$name -WhatIf: file unchanged" (Same $file $original)
        $ops = @($r.diff | ForEach-Object { $_.op })
        Check "$name diff: every change has op and path" ((@($r.diff | Where-Object { $_.op -and $_.path.StartsWith('/') }).Count -eq @($r.diff).Count) -and ($ops.Count -ge 1))
    }

    Section 'B33-1 execute, convergence, undo'
    $r1 = Add-MailboxDlMember -Upn $tom -List $front -Client 'contoso-dental'
    Check 'add-dl-member applies once' ($r1.applied -and @($r1.diff).Count -eq 1 -and $r1.diff[0].op -eq 'add')
    $r2 = Add-MailboxDlMember -Upn $tom -List $front -Client 'contoso-dental'
    Check 'add-dl-member again is an empty diff' ((-not $r2.applied) -and @($r2.diff).Count -eq 0)
    $r3 = Remove-MailboxDlMember -Upn $tom -List $front -Client 'contoso-dental'
    Check 'remove-dl-member undoes it' ($r3.applied -and $r3.diff[0].op -eq 'remove')
    Check 'DL member list is back to the original set' ((Get-Content -Raw $file | ConvertFrom-Json).distributionLists[0].members.Count -eq 2)

    Copy-Item -Force (Join-Path $repo 'fixtures\tenant\contoso-dental\mailboxes.json') $file
    $a = Set-MailboxAutoReply -Upn $jamie -Message 'Jamie has left the practice.' -Client 'contoso-dental'
    Check 'set-auto-reply changes four fields' ($a.applied -and @($a.diff).Count -eq 4)
    $a2 = Set-MailboxAutoReply -Upn $jamie -Message 'Jamie has left the practice.' -Client 'contoso-dental'
    Check 'set-auto-reply again is an empty diff' ((-not $a2.applied) -and @($a2.diff).Count -eq 0)
    $c = Clear-MailboxAutoReply -Upn $jamie -Client 'contoso-dental'
    Check 'clear-auto-reply turns the state off only' ($c.applied -and @($c.diff).Count -eq 1 -and $c.diff[0].path.EndsWith('/autoReply/state'))
    $c2 = Clear-MailboxAutoReply -Upn $jamie -Client 'contoso-dental'
    Check 'clear-auto-reply again is an empty diff' ((-not $c2.applied) -and @($c2.diff).Count -eq 0)

    Section 'B33-1 a change that is already in place leaves the file byte-identical'
    Copy-Item -Force (Join-Path $repo 'fixtures\tenant\contoso-dental\mailboxes.json') $file
    $before = [System.IO.File]::ReadAllBytes($file)
    $null = Revoke-MailboxSendAs -Upn $jamie -Delegate $ana -Client 'contoso-dental'
    $null = Clear-MailboxAutoReply -Upn $jamie -Client 'contoso-dental'
    $null = Revoke-OneDriveManagerAccess -Upn $jamie -Manager $ana -Client 'contoso-dental'
    Check 'no-op calls do not rewrite the file' (Same $file $before)
    $null = Enable-MailboxArchive -Upn $tom -Client 'contoso-dental'
    $null = Enable-MailboxArchive -Upn $tom -Client 'contoso-dental'
    $json = Get-Content -Raw $file | ConvertFrom-Json
    Check 'enable-archive sets Active once' (($json.mailboxes | Where-Object userPrincipalName -eq $tom).archiveStatus -eq 'Active')
    Check 'the save keeps the fixture formatting (LF, 2-space indent, trailing newline)' (-not (Get-Content -Raw $file).Contains("`r") -and (Get-Content -Raw $file).EndsWith("}`n"))

    Section 'B33-1 convert to shared'
    Copy-Item -Force (Join-Path $repo 'fixtures\tenant\contoso-dental\mailboxes.json') $file
    $s = Convert-MailboxToShared -Upn $jamie -Client 'contoso-dental'
    Check 'convert-shared replaces the type' ($s.applied -and $s.diff[0].before -eq 'UserMailbox' -and $s.diff[0].after -eq 'SharedMailbox')
    $s2 = Convert-MailboxToShared -Upn $jamie -Client 'contoso-dental'
    Check 'convert-shared again is an empty diff' ((-not $s2.applied) -and @($s2.diff).Count -eq 0)
    $m = Get-Refusal { Convert-MailboxToShared -Upn $alex -Client 'fabrikam-capital' }
    Check 'a 61.5 GB mailbox is refused with the reason and nothing is written' ($m -and $m.Contains('50 GB') -and $m.Contains('Nothing was changed'))
    Check 'a converted leaver can still be taken off a list and have OneDrive access granted' ((Remove-MailboxDlMember -Upn $jamie -List $front -Client 'contoso-dental').applied -and (Grant-OneDriveManagerAccess -Upn $jamie -Manager $ana -ExpiresOn '2026-11-10' -Client 'contoso-dental').applied)

    Section 'B33-1 OneDrive grant is time-bound'
    Copy-Item -Force (Join-Path $repo 'fixtures\tenant\contoso-dental\mailboxes.json') $file
    $clean = [System.IO.File]::ReadAllBytes($file)
    foreach ($case in @(
            @('2026-10-21', 'after'), @('2026-10-20', 'after'), @('2026-11-21', '30 days'), @('2026-13-45', 'must look like'), @('soon', 'must look like'))) {
        $msg = Get-Refusal { Grant-OneDriveManagerAccess -Upn $jamie -Manager $ana -ExpiresOn $case[0] -Client 'contoso-dental' }
        Check "end date $($case[0]) is refused ($($case[1]))" ($msg -and $msg.Contains($case[1]) -and ($msg -match '(?i)nothing was changed'))
    }
    Check 'refusals wrote nothing' (Same $file $clean)
    $g = Grant-OneDriveManagerAccess -Upn $jamie -Manager $ana -ExpiresOn '2026-11-20' -Client 'contoso-dental'
    Check 'the 30th day is allowed and recorded with the as-of date as grantedOn' ($g.applied -and $g.diff[0].after.grantedOn -eq '2026-10-21' -and $g.diff[0].after.expiresOn -eq '2026-11-20')
    $later = Grant-OneDriveManagerAccess -Upn $jamie -Manager $ana -ExpiresOn '2026-12-01' -Client 'contoso-dental' -AsOf '2026-11-15'
    Check '-AsOf moves the window (no wall clock): 2026-12-01 is allowed from 2026-11-15' ((@($later.diff).Count -eq 1) -and $later.diff[0].op -eq 'replace' -and $later.diff[0].path.EndsWith('/expiresOn'))
    $none = Grant-OneDriveManagerAccess -Upn $jamie -Manager $ana -ExpiresOn '2026-12-01' -Client 'contoso-dental' -AsOf '2026-11-15'
    Check 'the same grant again is an empty diff' ((-not $none.applied) -and @($none.diff).Count -eq 0)
    $e = Revoke-OneDriveManagerAccess -Upn $jamie -Manager $ana -Client 'contoso-dental'
    Check 'revoke removes it and shows what was removed' ($e.applied -and $e.diff[0].op -eq 'remove' -and $e.diff[0].before.grantee -eq $ana)
    $selfMsg = Get-Refusal { Grant-OneDriveManagerAccess -Upn $jamie -Manager $jamie -ExpiresOn '2026-11-10' -Client 'contoso-dental' }
    Check 'granting a OneDrive to its owner is refused' ($selfMsg -and $selfMsg.Contains('own owner'))

    Section 'B33-1 same client only, no existence oracle'
    $x = Get-Refusal { Enable-MailboxArchive -Upn $alex -Client 'contoso-dental' }
    $y = Get-Refusal { Enable-MailboxArchive -Upn "nobody@$d" -Client 'contoso-dental' }
    Check 'another client''s person and an absent one get the same message' ($x -and $x -ceq $y -and -not $x.Contains('alex'))
    Check 'an outside delegate is refused' ([bool](Get-Refusal { Grant-MailboxFullAccess -Upn $jamie -Delegate 'x@outside.example' -Client 'contoso-dental' }))
    Check 'a shared mailbox cannot be a delegate' ([bool](Get-Refusal { Grant-MailboxSendAs -Upn $jamie -Delegate $info -Client 'contoso-dental' }))
    Check 'a mailbox cannot be granted to itself' ([bool](Get-Refusal { Grant-MailboxFullAccess -Upn $jamie -Delegate $jamie -Client 'contoso-dental' }))
    Check 'a list of another client is not found' ([bool](Get-Refusal { Add-MailboxDlMember -Upn $tom -List 'all@fabrikamcapital.example' -Client 'contoso-dental' }))
    Check 'a client id that is not a slug never becomes a path' ((Get-Refusal { Enable-MailboxArchive -Upn $tom -Client '..\fabrikam-capital' }) -like '*not a valid slug*')
    Check 'an unknown client reads nothing' ((Get-Refusal { Enable-MailboxArchive -Upn $tom -Client 'nope-inc' }) -like 'No mailbox state*')
    $foreign = Join-Path $tmp 'fabrikam-capital\mailboxes.json'
    $mismatch = (Get-Content -Raw $foreign) -replace '"client": "fabrikam-capital"', '"client": "contoso-dental"'
    Set-Content -LiteralPath $foreign -Value $mismatch -NoNewline
    Check 'a file whose _meta.client names another client is refused' ((Get-Refusal { Enable-MailboxArchive -Upn 'riley.brooks@fabrikamcapital.example' -Client 'fabrikam-capital' }) -like '*does not belong*')

    Section 'B33-2 forwarding is not a lever'
    $exported = (Get-Module MailboxOps).ExportedFunctions.Keys
    Check 'no exported function mentions forwarding, redirect or rules' (-not ($exported | Where-Object { $_ -match 'Forward|Redirect|Rule|Transport' }))
    Check 'twelve functions are exported' ($exported.Count -eq 12)
    $verbs = (Get-Verb).Verb
    Check 'every exported function uses an approved verb' (-not ($exported | Where-Object { ($_ -split '-')[0] -notin $verbs }))
    $code = (Get-Content -Raw (Join-Path $moduleDir 'MailboxOps.psm1')) -replace '(?s)<#.*?#>', '' -split "`n" | Where-Object { $_.TrimStart() -notlike '#*' }
    Check 'the module code never names a forwarding property' (-not ($code | Where-Object { $_ -match 'forwarding|DeliverToMailboxAndForward' }))
    Check 'the manifest exports nothing but the twelve functions' ((Import-PowerShellDataFile (Join-Path $moduleDir 'MailboxOps.psd1')).FunctionsToExport.Count -eq 12)
}
finally {
    Remove-Item -Recurse -Force -LiteralPath $tmp -ErrorAction SilentlyContinue
    Remove-Item Env:REDLINE_MOCK_TENANT_DIR -ErrorAction SilentlyContinue
}
Write-Host "MailboxOps tests: $($script:pass) passed, $($script:fail) failed"
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
