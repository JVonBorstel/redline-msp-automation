#requires -Version 7
<#
Slice B acceptance tests (specs/slices-abc.md: SB-1..SB-4) for levers/powershell/TenantBaseline. Plain PowerShell 7.
Run from anywhere:  pwsh -NoProfile -File tests/sliceb/Test-SliceB.ps1
Exit code 0 = all pass, 1 = failures. Prints "SliceB tests: N passed, M failed".
Writes only under $env:TEMP (a per-run folder, removed at the end). No network: -UseGraph is tested with the network
commands shadowed by recording functions, and the module source is scanned for network APIs.
#>
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$moduleDir = Join-Path $repo 'levers\powershell\TenantBaseline'
$manifest = Join-Path $moduleDir 'TenantBaseline.psd1'
$validator = Join-Path $moduleDir 'Test-SummaryReconciles.ps1'
$tmp = Join-Path $env:TEMP "redline-sliceb-$PID"
New-Item -ItemType Directory -Force $tmp | Out-Null

$script:pass = 0; $script:fail = 0
function Check([string]$Name, [bool]$Condition, [string]$Detail = '') {
    if ($Condition) { $script:pass++ } else { $script:fail++; Write-Host "FAIL: $Name $Detail" -ForegroundColor Red }
}
function Section([string]$t) { Write-Host "== $t" }
function Same([string[]]$A, [string[]]$B) { (@($A | Sort-Object) -join '|') -eq (@($B | Sort-Object) -join '|') }
function Subjects($Report, [string]$CheckId) { @($Report.findings | Where-Object CheckId -EQ $CheckId | ForEach-Object Subject) }
function Find($Report, [string]$CheckId, [string]$Subject) { $Report.findings | Where-Object { $_.CheckId -eq $CheckId -and $_.Subject -eq $Subject } }
function Validate([string]$Dir) { $out = & pwsh -NoProfile -File $validator -OutDir $Dir 2>&1 | Out-String; [pscustomobject]@{ Code = $LASTEXITCODE; Out = $out } }
function HashOf([string]$Dir) { (Get-ChildItem -LiteralPath $Dir -File | Sort-Object Name | ForEach-Object { "$($_.Name)=$((Get-FileHash -LiteralPath $_.FullName).Hash)" }) -join ';' }

Import-Module $manifest -Force
$c = 'contosodental.example'
$o = 'contosodental.onmicrosoft.com'

try {
    Section 'SB-1 each check finds exactly the seeded problems (Contoso) and none (clean)'
    $r = Get-TenantBaselineReport -Tenant contoso
    $expected = [ordered]@{
        MFA         = "ben.carter@$c", "carl.reyes@$c", "dana.lopez@$c", "nina.shah@$c"
        STALE       = "carl.reyes@$c", "dana.lopez@$c", "frank.ortiz@$c", "omar.hassan@$c"
        GLOBALADMIN = @('Global Administrator')
        LEGACYAUTH  = @('Contoso Dental')
        BREAKGLASS  = "bg-beta@$o", "emergency.admin@$c", 'Contoso Dental'
        GUESTADMIN  = @("pat_northwind.example#EXT#@$o")
    }
    foreach ($check in $expected.Keys) {
        $got = Subjects $r $check
        Check "SB-1 contoso $check finds exactly the seeded subjects" (Same $got $expected[$check]) "(got: $($got -join ', '))"
    }
    Check 'SB-1 contoso total is 14' ($r.counts.total -eq 14) "(got $($r.counts.total))"
    Check 'SB-1 ids are unique' (@($r.findings.Id | Select-Object -Unique).Count -eq $r.findings.Count)
    Check 'SB-1 every finding has Id, Severity, Title, Evidence' (-not ($r.findings | Where-Object { -not ($_.Id -and $_.Severity -and $_.Title -and $_.Evidence) }))
    # Edges the seeded data was built to exercise.
    Check 'SB-1 exactly 90 days without success is stale (frank)' ([bool](Find $r STALE "frank.ortiz@$c"))
    Check 'SB-1 89 days is not stale (kyle)' (-not (Find $r STALE "kyle.moss@$c"))
    Check 'SB-1 recent non-interactive success counts as activity (erin)' (-not (Find $r STALE "erin.brooks@$c"))
    Check 'SB-1 recent failed attempts do not hide staleness (omar)' ((Find $r STALE "omar.hassan@$c").Evidence -match 'attempt only')
    Check 'SB-1 never signed in and older than 90 days is stale (carl)' ((Find $r STALE "carl.reyes@$c").Evidence -match 'no successful sign-in')
    Check 'SB-1 new account never signed in is not stale (nina)' (-not (Find $r STALE "nina.shah@$c"))
    Check 'SB-1 missing registration record counts as no MFA (nina)' ((Find $r MFA "nina.shah@$c").Evidence -match 'no userRegistrationDetails record')
    Check 'SB-1 disabled account is in no finding' (-not ($r.findings | Where-Object Subject -EQ "old.contractor@$c"))
    Check 'SB-1 guests are outside the MFA check' (-not ($r.findings | Where-Object { $_.CheckId -eq 'MFA' -and $_.Subject -match '#EXT#' }))
    Check 'SB-1 report-only legacy policy does not count' ((Find $r LEGACYAUTH 'Contoso Dental').Evidence -match 'enabledForReportingButNotEnforced')
    $ea = (Find $r BREAKGLASS "emergency.admin@$c").Evidence
    Check 'SB-1 break-glass names prefix, cloud-only and CA exclusion' ($ea -match "start with 'bg-'" -and $ea -match 'cloud-only' -and $ea -match 'not excluded')
    Check 'SB-1 compliant break-glass account is not flagged (bg-alpha)' (-not (Find $r BREAKGLASS "bg-alpha@$o"))
    Check 'SB-1 fix levers are named and dry-run' ((Find $r MFA "ben.carter@$c").FixLever -eq 'user.require-mfa' -and (Find $r STALE "dana.lopez@$c").FixLever -eq 'user.disable' -and
        -not ($r.findings | Where-Object { $_.FixLever -and $_.FixMode -ne 'dry-run' }))
    Check 'SB-1 break-glass fixes stay manual' (-not ($r.findings | Where-Object { $_.CheckId -eq 'BREAKGLASS' -and ($_.FixLever -or $_.FixMode -ne 'manual') }))
    $clean = Get-TenantBaselineReport -Tenant clean
    Check 'SB-1 clean fixture has zero findings' ($clean.counts.total -eq 0 -and @($clean.findings).Count -eq 0) "(got $($clean.counts.total): $($clean.findings.Id -join ', '))"
    foreach ($check in $expected.Keys) { Check "SB-1 clean $check count is 0" ($clean.counts.byCheck[$check] -eq 0) }
    # The admin threshold N is config, not code.
    $cfg = Get-Content -Raw (Join-Path $moduleDir 'TenantBaseline.config.json') | ConvertFrom-Json
    $cfg.maxGlobalAdmins = 6
    $cfgPath = Join-Path $tmp 'config-max6.json'; $cfg | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $cfgPath
    Check 'SB-1 maxGlobalAdmins comes from config' (-not (Subjects (Get-TenantBaselineReport -Tenant contoso -ConfigPath $cfgPath) GLOBALADMIN))
    $threw = $false; try { Get-TenantBaselineReport -Tenant '..\contoso' | Out-Null } catch { $threw = $true }
    Check 'SB-1 tenant name with a path is rejected' $threw
    $bad = Join-Path $tmp 'badfx\contoso'; New-Item -ItemType Directory -Force $bad | Out-Null
    Copy-Item (Join-Path $repo 'fixtures\graph\contoso\*.json') $bad
    Set-Content -LiteralPath (Join-Path $bad 'users.json') '{"users": []}'
    $msg = ''; try { Get-TenantBaselineReport -Tenant contoso -FixtureRoot (Join-Path $tmp 'badfx') | Out-Null } catch { $msg = $_.Exception.Message }
    Check 'SB-1 a fixture without a Graph value array is refused' ($msg -match "no 'value' array") "(got: $msg)"

    Section 'SB-2 outputs exist and the summary reconciles'
    $out = Join-Path $tmp 'contoso'
    $res = Invoke-TenantBaseline -Tenant contoso -OutDir $out
    foreach ($f in 'findings.json', 'findings.csv', 'report.html', 'summary.txt') { Check "SB-2 $f written" (Test-Path -LiteralPath (Join-Path $out $f)) }
    Check 'SB-2 result object reports 14 findings' ($res.Findings -eq 14)
    $json = Get-Content -Raw (Join-Path $out 'findings.json') | ConvertFrom-Json
    Check 'SB-2 findings.json has 14 findings and the source label' (@($json.findings).Count -eq 14 -and $json.sourceLabel -match 'fixture-based' -and $json.sourceLabel -match 'Graph v1.0')
    $csv = @(Import-Csv (Join-Path $out 'findings.csv'))
    $cols = 'Tenant', 'TenantName', 'AsOf', 'Id', 'CheckId', 'Severity', 'Title', 'Subject', 'Evidence', 'FixLever', 'FixMode', 'FixTarget', 'Source'
    Check 'SB-2 CSV has 14 flat rows' ($csv.Count -eq 14)
    Check 'SB-2 CSV columns are the fixed flat set' ((($csv[0].PSObject.Properties.Name) -join ',') -eq ($cols -join ','))
    $html = Get-Content -Raw (Join-Path $out 'report.html')
    Check 'SB-2 HTML names the tenant and the fixture label' ($html -match 'Contoso Dental' -and $html -match 'fixture-based')
    Check 'SB-2 HTML is self-contained (no script, no external src/href)' ($html -notmatch '<script' -and $html -notmatch '\s(src|href)=' -and $html -match 'Content-Security-Policy')
    $v = Validate $out
    Check 'SB-2 reconcile validator passes on Contoso' ($v.Code -eq 0) "(out: $($v.Out))"
    $cleanOut = Join-Path $tmp 'clean'
    Invoke-TenantBaseline -Tenant clean -OutDir $cleanOut | Out-Null
    $v = Validate $cleanOut
    Check 'SB-2 reconcile validator passes on clean' ($v.Code -eq 0) "(out: $($v.Out))"
    Check 'SB-2 clean CSV is header-only (still loads in Power BI)' ((Get-Content (Join-Path $cleanOut 'findings.csv')).Count -eq 1)
    Check 'SB-2 summary uses the fixture label' ((Get-Content -Raw (Join-Path $out 'summary.txt')) -match 'fixture-based')

    # Tampering: each must make the validator fail.
    $summaryText = Get-Content -Raw (Join-Path $out 'summary.txt')
    $tampers = [ordered]@{
        'changed MFA count'         = $summaryText.Replace('4 of 16 enabled', '3 of 16 enabled')
        'changed total'             = $summaryText.Replace('found 14 issues', 'found 12 issues')
        'changed secure score'      = $summaryText.Replace('41 of 120', '61 of 120')
        'flipped legacy-auth claim' = $summaryText.Replace('is not blocked', 'is blocked')
        'added unclaimed number'    = $summaryText.TrimEnd() + " Fixing this saves 3 hours.`n"
        'spelled-out number'        = $summaryText.TrimEnd() + " Two admins share a mailbox.`n"
    }
    foreach ($name in $tampers.Keys) {
        Check "SB-2 tamper text differs ($name)" ($tampers[$name] -ne $summaryText)
        $dir = Join-Path $tmp ("tamper-" + ($name -replace '\W', '-'))
        New-Item -ItemType Directory -Force $dir | Out-Null
        Copy-Item (Join-Path $out 'findings.json') $dir
        Set-Content -LiteralPath (Join-Path $dir 'summary.txt') -Value $tampers[$name] -NoNewline
        $v = Validate $dir
        Check "SB-2 validator fails on tampered summary: $name" ($v.Code -ne 0 -and $v.Out -match 'FAIL') "(exit $($v.Code))"
    }
    # Tampering the findings instead (drop one) must fail too: the summary no longer matches.
    $dir = Join-Path $tmp 'tamper-findings'; New-Item -ItemType Directory -Force $dir | Out-Null
    Copy-Item (Join-Path $out 'summary.txt') $dir
    $j = Get-Content -Raw (Join-Path $out 'findings.json') | ConvertFrom-Json
    $j.findings = @($j.findings | Select-Object -Skip 1)
    $j | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $dir 'findings.json')
    $v = Validate $dir
    Check 'SB-2 validator fails when a finding is removed from findings.json' ($v.Code -ne 0) "(exit $($v.Code))"

    $again = Join-Path $tmp 'contoso-again'
    Invoke-TenantBaseline -Tenant contoso -OutDir $again | Out-Null
    Check 'SB-2 output is deterministic (byte-identical on a second run)' ((HashOf $out) -eq (HashOf $again))

    # Values from the tenant are HTML-encoded: a hostile display name or UPN cannot inject markup.
    $xfx = Join-Path $tmp 'xssfx\contoso'; New-Item -ItemType Directory -Force $xfx | Out-Null
    Copy-Item (Join-Path $repo 'fixtures\graph\contoso\*.json') $xfx
    $users = Get-Content -Raw (Join-Path $xfx 'users.json')
    $users = $users.Replace("`"ben.carter@$c`"", "`"ben<script>alert(1)</script>@$c`"")
    Set-Content -LiteralPath (Join-Path $xfx 'users.json') -Value $users
    $xout = Join-Path $tmp 'xss'
    Invoke-TenantBaseline -Tenant contoso -OutDir $xout -FixtureRoot (Join-Path $tmp 'xssfx') | Out-Null
    $xhtml = Get-Content -Raw (Join-Path $xout 'report.html')
    Check 'SB-2 hostile value is encoded in the HTML' ($xhtml -notmatch '<script' -and $xhtml -match '&lt;script&gt;alert\(1\)&lt;/script&gt;')

    Section 'B40 identity checks: SSPR coverage and break-glass sign-in watch (opt-in, -IncludeIdentityChecks)'
    $x = Get-TenantBaselineReport -Tenant contoso -IncludeIdentityChecks
    $sspr = Find $x SSPR 'Contoso Dental'
    Check 'B40-1 SSPR coverage finding per client is medium, names the counts and the missing accounts' ($sspr -and $sspr.Severity -eq 'Medium' -and $sspr.Evidence -match '9 of 13' -and $sspr.Evidence -match '69%' -and $sspr.Evidence -match "ben\.carter@$c" -and $sspr.Evidence -match "nina\.shah@$c") "(got: $($sspr.Evidence))"
    Check 'B40-1 exactly one SSPR finding for the client' ((Subjects $x SSPR).Count -eq 1)
    Check 'B40-1 SSPR denominator leaves out break-glass accounts' ($sspr.Evidence -notmatch 'bg-alpha|bg-beta|emergency\.admin' -or $sspr.Evidence -match 'break-glass accounts excluded')
    Check 'B40-1 SSPR coverage metrics are in the report' ($x.metrics.ssprEligibleUsers -eq 13 -and $x.metrics.ssprRegisteredUsers -eq 9 -and $x.metrics.ssprCoveragePercent -eq 69)
    $bgs = Find $x BGSIGNIN "bg-alpha@$o"
    Check 'B40-1 break-glass sign-in inside the window is high severity' ($bgs -and $bgs.Severity -eq 'High' -and $bgs.Evidence -match '2026-09-27' -and $bgs.Evidence -match '3 days before as-of') "(got: $($bgs.Evidence))"
    Check 'B40-1 only bg-alpha signed in within 14 days (beta 47 days, emergency.admin 29 days are outside)' (Same (Subjects $x BGSIGNIN) @("bg-alpha@$o")) "(got: $((Subjects $x BGSIGNIN) -join ', '))"
    Check 'B40-1 the break-glass sign-in fix stays manual' ($bgs.FixLever -eq '' -and $bgs.FixMode -eq 'manual' -and $sspr.FixMode -eq 'manual')
    $cfg2 = Get-Content -Raw (Join-Path $moduleDir 'TenantBaseline.config.json') | ConvertFrom-Json
    $cfg2.breakGlass | Add-Member -NotePropertyName signInWindowDays -NotePropertyValue 30
    $cfg2 | Add-Member -NotePropertyName ssprMinimumCoveragePercent -NotePropertyValue 60
    $cfg2Path = Join-Path $tmp 'config-b40.json'; $cfg2 | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $cfg2Path
    $x2 = Get-TenantBaselineReport -Tenant contoso -ConfigPath $cfg2Path -IncludeIdentityChecks
    Check 'B40-1 the window comes from config (30 days adds emergency.admin at 29 days)' (Same (Subjects $x2 BGSIGNIN) @("bg-alpha@$o", "emergency.admin@$c")) "(got: $((Subjects $x2 BGSIGNIN) -join ', '))"
    Check 'B40-1 the SSPR minimum comes from config (60 percent: 69 percent passes)' (-not (Subjects $x2 SSPR))
    Check 'B40-1 the new findings get ids after the six checks (TB-SSPR-01, TB-BGSIGNIN-01)' ((Find $x SSPR 'Contoso Dental').Id -eq 'TB-SSPR-01' -and $bgs.Id -eq 'TB-BGSIGNIN-01')

    $xc = Get-TenantBaselineReport -Tenant clean -IncludeIdentityChecks
    Check 'B40-2 SB-1: Contoso has exactly the seeded new findings (16 in total)' ($x.counts.total -eq 16 -and $x.counts.byCheck['SSPR'] -eq 1 -and $x.counts.byCheck['BGSIGNIN'] -eq 1 -and $x.metrics.checksRun -eq 8) "(got $($x.counts.total))"
    Check 'B40-2 SB-1: the clean fixture has none of the new findings and zero in total' ($xc.counts.total -eq 0 -and $xc.counts.byCheck['SSPR'] -eq 0 -and $xc.counts.byCheck['BGSIGNIN'] -eq 0) "(got $($xc.counts.total))"
    Check 'B40-2 SB-1: the existing six checks find the same subjects with the new checks on' ((@($x.findings | Where-Object { $_.CheckId -notin 'SSPR', 'BGSIGNIN' } | ForEach-Object Id) -join ',') -eq (@($r.findings | ForEach-Object Id) -join ','))
    $xo = Join-Path $tmp 'b40-contoso'
    $xres = Invoke-TenantBaseline -Tenant contoso -OutDir $xo -IncludeIdentityChecks
    Check 'B40-2 SB-2: the result object reports 16 findings' ($xres.Findings -eq 16)
    $xs = Get-Content -Raw (Join-Path $xo 'summary.txt')
    Check 'B40-2 SB-2: the summary states the SSPR and break-glass sign-in counts' ($xs -match '9 of 13 eligible member accounts are registered for self-service password reset \(69%\), below the minimum of 90%' -and $xs -match '1 break-glass account signed in within the last 14 days') "(got: $xs)"
    $v = Validate $xo
    Check 'B40-2 SB-2: reconcile validator passes with the new counts (Contoso)' ($v.Code -eq 0) "(out: $($v.Out))"
    $xco = Join-Path $tmp 'b40-clean'
    Invoke-TenantBaseline -Tenant clean -OutDir $xco -IncludeIdentityChecks | Out-Null
    $v = Validate $xco
    Check 'B40-2 SB-2: reconcile validator passes with the new counts (clean)' ($v.Code -eq 0) "(out: $($v.Out))"
    Check 'B40-2 SB-2: clean summary says no break-glass sign-in and SSPR meeting the minimum' ((Get-Content -Raw (Join-Path $xco 'summary.txt')) -match 'No break-glass account signed in within the last 14 days' -and (Get-Content -Raw (Join-Path $xco 'summary.txt')) -match 'meeting the minimum of 90%')
    $b40tamper = [ordered]@{
        'SSPR registered count'    = $xs.Replace('9 of 13', '10 of 13')
        'SSPR below to meeting'    = $xs.Replace('below the minimum', 'meeting the minimum')
        'break-glass sign-in count' = $xs.Replace('1 break-glass account signed in', '2 break-glass accounts signed in')
        'break-glass window'       = $xs.Replace('last 14 days', 'last 7 days')
    }
    foreach ($name in $b40tamper.Keys) {
        Check "B40-2 SB-2 tamper text differs ($name)" ($b40tamper[$name] -ne $xs)
        $dir = Join-Path $tmp ('b40-tamper-' + ($name -replace '\W', '-'))
        New-Item -ItemType Directory -Force $dir | Out-Null
        Copy-Item (Join-Path $xo 'findings.json') $dir
        Set-Content -LiteralPath (Join-Path $dir 'summary.txt') -Value $b40tamper[$name] -NoNewline
        $v = Validate $dir
        Check "B40-2 SB-2 validator fails on tampered summary: $name" ($v.Code -ne 0 -and $v.Out -match 'FAIL') "(exit $($v.Code))"
    }

    $d = Get-TenantBaselineReport -Tenant contoso
    Check 'B40-3 default run keeps the demo output: 14 findings, six checks, same ids' ($d.counts.total -eq 14 -and $d.metrics.checksRun -eq 6 -and (@($d.counts.byCheck.Keys) -join ',') -eq 'MFA,STALE,GLOBALADMIN,LEGACYAUTH,BREAKGLASS,GUESTADMIN' -and (@($d.findings.Id) -join ',') -eq (@($r.findings.Id) -join ','))
    Check 'B40-3 default report has no new settings or metrics keys' (-not $d.metrics.Contains('ssprEligibleUsers') -and -not $d.settings.Contains('ssprMinimumCoveragePercent'))
    Check 'B40-3 default summary does not mention the new checks' ((Get-Content -Raw (Join-Path $out 'summary.txt')) -notmatch 'self-service|signed in within')

    Section 'B50 drift over time: -CompareTo reports finding and Conditional Access changes (report only)'
    $configBefore = (Get-FileHash -LiteralPath (Join-Path $moduleDir 'TenantBaseline.config.json')).Hash
    $prevJson = Join-Path $out 'findings.json'   # the SB-2 run of the unmodified Contoso fixture
    function NewFx([string]$Name) {
        $d = Join-Path $tmp "$Name\contoso"; New-Item -ItemType Directory -Force $d | Out-Null
        Copy-Item (Join-Path $repo 'fixtures\graph\contoso\*.json') $d
        $d
    }
    function ReadFx([string]$Dir, [string]$File) { Get-Content -Raw -LiteralPath (Join-Path $Dir $File) | ConvertFrom-Json }
    function WriteFx([string]$Dir, [string]$File, $Doc) { $Doc | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $Dir $File) }

    # Findings: ben registers for MFA (resolved), a new unregistered member appears (new).
    $fx1 = NewFx 'b50-findings'
    $regs = ReadFx $fx1 'userRegistrationDetails.json'
    $ben = $regs.value | Where-Object userPrincipalName -EQ "ben.carter@$c"
    $ben.isMfaRegistered = $true; $ben.methodsRegistered = @('microsoftAuthenticatorPush')
    WriteFx $fx1 'userRegistrationDetails.json' $regs
    $us = ReadFx $fx1 'users.json'
    $nu = ($us.value | Where-Object userPrincipalName -EQ "ben.carter@$c") | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    $nu.id = 'c0000000-0000-4000-8000-000000000099'; $nu.userPrincipalName = "new.hire@$c"; $nu.displayName = 'New Hire'
    $nu.createdDateTime = '2026-09-29T00:00:00Z'; $nu.PSObject.Properties.Remove('signInActivity')
    $us.value = @($us.value) + $nu
    WriteFx $fx1 'users.json' $us
    $d1 = (Get-TenantBaselineReport -Tenant contoso -FixtureRoot (Join-Path $tmp 'b50-findings') -CompareTo $prevJson).drift
    Check 'B50-1 the new finding is reported as new' (Same @($d1.findings.new | ForEach-Object { $_.Subject }) @("new.hire@$c")) "(got: $(@($d1.findings.new | ForEach-Object { $_.Subject }) -join ', '))"
    Check 'B50-1 the fixed finding is reported as resolved' (Same @($d1.findings.resolved | ForEach-Object { $_.Subject }) @("ben.carter@$c"))
    Check 'B50-1 the unchanged findings are counted (13) and the counts add up to both totals' ($d1.counts.unchanged -eq 13 -and ($d1.counts.new + $d1.counts.unchanged) -eq 14 -and ($d1.counts.resolved + $d1.counts.unchanged) -eq 14) "(got $($d1.counts.unchanged))"
    Check 'B50-1 findings-only changes report no Conditional Access change' (($d1.counts.caAdded + $d1.counts.caRemoved + $d1.counts.caStateChanged + $d1.counts.caAssignmentsChanged) -eq 0)

    # Conditional Access: state, assignments (two policies), one removed, one added with a hostile name.
    $fx2 = NewFx 'b50-ca'
    $ca = ReadFx $fx2 'conditionalAccessPolicies.json'
    $p201 = $ca.value | Where-Object id -EQ 'c0000000-0000-4000-8000-000000000201'
    $p202 = $ca.value | Where-Object id -EQ 'c0000000-0000-4000-8000-000000000202'
    $p203 = $ca.value | Where-Object id -EQ 'c0000000-0000-4000-8000-000000000203'
    $added = $p201 | ConvertTo-Json -Depth 12 | ConvertFrom-Json
    $added.id = 'c0000000-0000-4000-8000-000000000299'; $added.displayName = '<script>alert(2)</script> device policy'
    $p201.state = 'disabled'
    $p202.conditions.users.excludeUsers = @($p202.conditions.users.excludeUsers) + 'c0000000-0000-4000-8000-000000000999'
    $p202.conditions.users.includeGroups = @('c0000000-0000-4000-8000-000000000777')
    $ca.value = @($ca.value | Where-Object { $_.id -ne $p203.id }) + $added
    WriteFx $fx2 'conditionalAccessPolicies.json' $ca
    $rep2 = Get-TenantBaselineReport -Tenant contoso -FixtureRoot (Join-Path $tmp 'b50-ca') -CompareTo $prevJson
    $d2 = $rep2.drift.conditionalAccess
    Check 'B50-1 a CA state change shows old and new state' (@($d2.stateChanged).Count -eq 1 -and $d2.stateChanged[0].id -eq $p201.id -and $d2.stateChanged[0].from -eq 'enabled' -and $d2.stateChanged[0].to -eq 'disabled') "(got: $($d2.stateChanged | ConvertTo-Json -Depth 5 -Compress))"
    $ac = @($d2.assignmentsChanged)
    Check 'B50-1 a CA assignment change names the policy and each added value' ($ac.Count -eq 1 -and $ac[0].id -eq $p202.id -and @($ac[0].changes).Count -eq 2) "(got: $($ac | ConvertTo-Json -Depth 6 -Compress))"
    $exc = @($ac[0].changes) | Where-Object { $_.field -eq 'excludeUsers' }
    $inc = @($ac[0].changes) | Where-Object { $_.field -eq 'includeGroups' }
    Check 'B50-1 the excluded user is an added value' (@($exc.added) -contains 'c0000000-0000-4000-8000-000000000999' -and @($exc.removed).Count -eq 0)
    Check 'B50-1 the group is an added value' (@($inc.added) -contains 'c0000000-0000-4000-8000-000000000777')
    Check 'B50-1 a new CA policy is added and a deleted one is removed' (@($d2.added).Count -eq 1 -and $d2.added[0].id -eq 'c0000000-0000-4000-8000-000000000299' -and @($d2.removed).Count -eq 1 -and $d2.removed[0].id -eq $p203.id)
    Check 'B50-1 a CA comparison was made (not skipped)' ($d2.compared -eq $true)

    # No false positives: the same run, and the same data in a different order.
    $self = (Get-TenantBaselineReport -Tenant contoso -CompareTo $prevJson).drift
    Check 'B50-1 comparing a run with itself gives no new, no resolved, 14 unchanged' ($self.counts.new -eq 0 -and $self.counts.resolved -eq 0 -and $self.counts.unchanged -eq 14)
    Check 'B50-1 comparing a run with itself gives no CA change' (($self.counts.caAdded + $self.counts.caRemoved + $self.counts.caStateChanged + $self.counts.caAssignmentsChanged) -eq 0 -and $self.conditionalAccess.compared)
    $fx3 = NewFx 'b50-order'
    $ca3 = ReadFx $fx3 'conditionalAccessPolicies.json'
    $ca3.value = @($ca3.value)[(@($ca3.value).Count - 1)..0]
    $first = $ca3.value | Where-Object id -EQ 'c0000000-0000-4000-8000-000000000201'
    $first.conditions.users.excludeUsers = @($first.conditions.users.excludeUsers)[1..0]
    WriteFx $fx3 'conditionalAccessPolicies.json' $ca3
    $ord = (Get-TenantBaselineReport -Tenant contoso -FixtureRoot (Join-Path $tmp 'b50-order') -CompareTo $prevJson).drift
    Check 'B50-1 reordered policies and lists are not a change' (($ord.counts.caAdded + $ord.counts.caRemoved + $ord.counts.caStateChanged + $ord.counts.caAssignmentsChanged) -eq 0)

    # Errors and old files.
    $msg = ''; try { Get-TenantBaselineReport -Tenant contoso -CompareTo (Join-Path $tmp 'nope.json') | Out-Null } catch { $msg = $_.Exception.Message }
    Check 'B50-1 a missing -CompareTo file throws a clear error' ($msg -match 'not found') "(got: $msg)"
    $badPrev = Join-Path $tmp 'b50-bad.json'; Set-Content -LiteralPath $badPrev -Value 'not json {'
    $msg = ''; try { Get-TenantBaselineReport -Tenant contoso -CompareTo $badPrev | Out-Null } catch { $msg = $_.Exception.Message }
    Check 'B50-1 a malformed -CompareTo file throws a clear error' ($msg -match 'not valid JSON') "(got: $msg)"
    $noFindings = Join-Path $tmp 'b50-nofindings.json'; Set-Content -LiteralPath $noFindings -Value '{"tenant":"contoso-dental"}'
    $msg = ''; try { Get-TenantBaselineReport -Tenant contoso -CompareTo $noFindings | Out-Null } catch { $msg = $_.Exception.Message }
    Check 'B50-1 a file without a findings array throws' ($msg -match "no 'findings' array") "(got: $msg)"
    $msg = ''; try { Get-TenantBaselineReport -Tenant contoso -CompareTo (Join-Path $cleanOut 'findings.json') | Out-Null } catch { $msg = $_.Exception.Message }
    Check 'B50-1 a file for a different tenant throws' ($msg -match 'is for tenant' ) "(got: $msg)"
    $old = ReadFx $out 'findings.json'; $old.PSObject.Properties.Remove('conditionalAccess')
    $oldPath = Join-Path $tmp 'b50-old.json'; $old | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $oldPath
    $od = (Get-TenantBaselineReport -Tenant contoso -CompareTo $oldPath).drift
    Check 'B50-1 a previous file without a CA snapshot skips the CA diff with a note, not a crash' ($od.conditionalAccess.compared -eq $false -and $od.conditionalAccess.note -match 'no CA snapshot' -and $od.counts.caAdded -eq 0 -and $od.counts.unchanged -eq 14)

    # Outputs: findings.json, report.html and drift.txt carry the drift; nothing else changes.
    $bout = Join-Path $tmp 'b50-out'
    $bres = Invoke-TenantBaseline -Tenant contoso -OutDir $bout -FixtureRoot (Join-Path $tmp 'b50-ca') -CompareTo $prevJson
    $bj = Get-Content -Raw (Join-Path $bout 'findings.json') | ConvertFrom-Json
    Check 'B50-1 findings.json carries the drift section' ($bj.drift.counts.caStateChanged -eq 1 -and $bj.drift.comparedTo -eq $json.asOf -and @($bj.conditionalAccess).Count -eq @($ca.value).Count)
    $bhtml = Get-Content -Raw (Join-Path $bout 'report.html')
    Check 'B50-1 report.html has the changes section with the hostile name encoded' ($bhtml -match 'Changes since previous run' -and $bhtml -match '&lt;script&gt;alert\(2\)&lt;/script&gt;' -and $bhtml -notmatch '<script' -and $bhtml -notmatch '\s(src|href)=')
    $btxt = Get-Content -Raw (Join-Path $bout 'drift.txt')
    Check 'B50-1 drift.txt lists the state change and the new finding' ($btxt -match "CA state changed: 'Require MFA for all users' enabled -> disabled" -and $btxt -match 'Findings: ')
    Check 'B50-1 drift.txt is the fifth file only in compare mode' (@($bres.Files).Count -eq 5 -and $bres.Files -contains 'drift.txt')
    $v = Validate $bout
    Check 'B50-1 reconcile validator still passes on a compare run' ($v.Code -eq 0) "(out: $($v.Out))"

    # B50-2: report only. Never a lever, never a fix mode, config untouched.
    $driftText = $rep2.drift | ConvertTo-Json -Depth 12
    $entries = @($rep2.drift.findings.new) + @($rep2.drift.findings.resolved) + @($rep2.drift.findings.unchanged)
    Check 'B50-2 no drift finding entry carries a fix lever, mode or target' ($entries.Count -gt 0 -and -not ($entries | Where-Object { $_.Contains('FixLever') -or $_.Contains('FixMode') -or $_.Contains('FixTarget') }))
    Check 'B50-2 drift names no fix and no ca.* lever' ($driftText -notmatch '"Fix(Lever|Mode|Target)"' -and $driftText -notmatch '(?i)\bca\.[a-z]' -and $rep2.drift.reportOnly -eq $true)
    Check 'B50-2 drift says it is report only and a human decision' ($btxt -match 'Report only' -and $btxt -match 'human decision' -and $bhtml -match 'human decision')
    $driftFn = [regex]::Match((Get-Content -Raw (Join-Path $moduleDir 'TenantBaseline.psm1')), '(?ms)^function Get-TbDrift\b.*?^}').Value
    Check 'B50-2 the drift code never reads the fix levers' ($driftFn.Length -gt 0 -and $driftFn -notmatch 'fixLevers|FixLever')
    Check 'B50-2 the config (fixLevers, plannedFixLevers) is unchanged by compare runs' ((Get-FileHash -LiteralPath (Join-Path $moduleDir 'TenantBaseline.config.json')).Hash -eq $configBefore)

    # B50-3: the default run is what it was.
    $plain = Get-TenantBaselineReport -Tenant contoso
    Check 'B50-3 a default run has no drift key' (-not $plain.Contains('drift'))
    Check 'B50-3 a default run writes exactly the four files and no drift.txt' ((@($res.Files) -join ',') -eq 'findings.json,findings.csv,report.html,summary.txt' -and -not (Test-Path -LiteralPath (Join-Path $out 'drift.txt')))
    Check 'B50-3 a default report html has no changes section' ($html -notmatch 'Changes since previous run')
    Check 'B50-3 the default report still has 14 findings (the demo)' ($plain.counts.total -eq 14 -and $plain.metrics.checksRun -eq 6)
    $rep1 = Join-Path $tmp 'b50-repeat1'; $rep2Dir = Join-Path $tmp 'b50-repeat2'
    Invoke-TenantBaseline -Tenant contoso -OutDir $rep1 | Out-Null
    Invoke-TenantBaseline -Tenant contoso -OutDir $rep2Dir | Out-Null
    $differs = @('findings.json', 'findings.csv', 'report.html', 'summary.txt') | Where-Object { (Get-FileHash -LiteralPath (Join-Path $rep1 $_)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $rep2Dir $_)).Hash }
    Check 'B50-3 a default run is byte-identical on a second run' (@($differs).Count -eq 0) "(differs: $(@($differs) -join ', '))"

    Section 'SB-3 -UseGraph without a tenant refuses with the scopes and makes no network call'
    $scopes = 'User.Read.All', 'AuditLog.Read.All', 'Policy.Read.All', 'RoleManagement.Read.Directory', 'Reports.Read.All'
    $netNames = 'Invoke-RestMethod', 'Invoke-WebRequest', 'Connect-MgGraph', 'Invoke-MgGraphRequest', 'Get-MgUser'
    $global:SbNetCalls = [Collections.Generic.List[string]]::new()
    foreach ($n in $netNames) { Set-Item -Path "function:global:$n" -Value ([scriptblock]::Create("`$global:SbNetCalls.Add('$n')")) }
    $savedTenant = $env:REDLINE_TENANT_ID
    try {
        $env:REDLINE_TENANT_ID = $null
        $gout = Join-Path $tmp 'graph'
        $msg = ''; try { Invoke-TenantBaseline -Tenant contoso -OutDir $gout -UseGraph | Out-Null } catch { $msg = $_.Exception.Message }
        Check 'SB-3 -UseGraph without REDLINE_TENANT_ID throws' ([bool]$msg)
        Check 'SB-3 message names the missing variable' ($msg -match 'REDLINE_TENANT_ID')
        foreach ($s in $scopes) { Check "SB-3 message lists read-only scope $s" ($msg.Contains($s)) }
        Check 'SB-3 message says no network call was made' ($msg -match 'No network call was made')
        Check 'SB-3 no network command was called' ($global:SbNetCalls.Count -eq 0) "(called: $($global:SbNetCalls -join ', '))"
        Check 'SB-3 nothing written' (-not (Test-Path -LiteralPath $gout))

        $env:REDLINE_TENANT_ID = 'test-tenant-placeholder'
        $msg = ''; try { Invoke-TenantBaseline -Tenant contoso -OutDir $gout -UseGraph | Out-Null } catch { $msg = $_.Exception.Message }
        Check 'SB-3 with a tenant id set, the stub still refuses' ($msg -match 'stub' -and $msg -match 'No network call was made')
        Check 'SB-3 the stub does not echo the tenant id' ($msg -notmatch 'test-tenant-placeholder')
        Check 'SB-3 still no network command called' ($global:SbNetCalls.Count -eq 0)
        $env:REDLINE_TENANT_ID = $null

        # As a process: non-zero exit, clear message. Network commands are shadowed there too and would leave a marker file.
        $marker = Join-Path $tmp 'net-called.txt'
        $child = Join-Path $tmp 'child-usegraph.ps1'
        $shadows = ($netNames | ForEach-Object { "function global:$_ { Add-Content -LiteralPath '$marker' '$_' }" }) -join "`n"
        Set-Content -LiteralPath $child -Value "$shadows`nImport-Module '$manifest'`nInvoke-TenantBaseline -Tenant contoso -OutDir '$gout' -UseGraph`n"
        $cout = & pwsh -NoProfile -File $child 2>&1 | Out-String
        Check 'SB-3 process exits non-zero' ($LASTEXITCODE -ne 0) "(exit $LASTEXITCODE)"
        Check 'SB-3 process prints the scopes' ($cout -match 'RoleManagement\.Read\.Directory') "(out: $cout)"
        Check 'SB-3 process made no network call' (-not (Test-Path -LiteralPath $marker))
    } finally {
        $env:REDLINE_TENANT_ID = $savedTenant
        foreach ($n in $netNames) { Remove-Item -Path "function:global:$n" -ErrorAction SilentlyContinue }
    }
    $src = (Get-ChildItem -LiteralPath $moduleDir -File -Include *.ps1, *.psm1 -Recurse | ForEach-Object { Get-Content -Raw $_.FullName }) -join "`n"
    Check 'SB-3 module source has no network API' ($src -notmatch 'Invoke-RestMethod|Invoke-WebRequest|Connect-MgGraph|Invoke-MgGraphRequest|HttpClient|WebClient|Net\.Sockets|Start-BitsTransfer')

    Section 'SB-4 PSScriptAnalyzer clean (no Error or Warning)'
    $manifestOk = $true; try { Test-ModuleManifest -Path $manifest | Out-Null } catch { $manifestOk = $false }
    Check 'SB-4 module manifest is valid' $manifestOk
    if (Get-Module -ListAvailable -Name PSScriptAnalyzer) {
        $issues = @(Invoke-ScriptAnalyzer -Path $moduleDir -Recurse -Severity Error, Warning)
        Check 'SB-4 PSScriptAnalyzer reports no Error/Warning' ($issues.Count -eq 0) "($(($issues | ForEach-Object { "$($_.RuleName) $($_.ScriptName):$($_.Line)" }) -join '; '))"
    } else {
        Write-Host 'SKIP: SB-4 PSScriptAnalyzer is not installed (not counted as a pass)'
    }
} finally {
    Remove-Module TenantBaseline -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host "SliceB tests: $($script:pass) passed, $($script:fail) failed"
if ($script:fail) { exit 1 } else { exit 0 }
