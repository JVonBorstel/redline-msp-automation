#requires -Version 7.2
<#
.SYNOPSIS
Fails (exit 1) when any number in summary.txt does not reconcile to findings.json.

.DESCRIPTION
Independent of the TenantBaseline module on purpose: it recomputes every count from the findings array itself (not from
the counts block, which it also cross-checks) and then requires that each number in the summary is claimed by a known fact
phrase whose value matches. A number no fact claims, or a spelled-out number, fails too: that is what keeps a later
rephrasing (for example by the model gateway) honest. Rephrased text must keep the fact phrases below.

.EXAMPLE
pwsh -NoProfile -File levers/powershell/TenantBaseline/Test-SummaryReconciles.ps1 -OutDir $env:TEMP\baseline-contoso
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $OutDir
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$findingsPath = Join-Path $OutDir 'findings.json'
$summaryPath = Join-Path $OutDir 'summary.txt'
foreach ($p in $findingsPath, $summaryPath) {
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { Write-Output "FAIL: missing $p"; exit 1 }
}
$jsonArgs = if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) { @{ DateKind = 'String' } } else { @{} }
$report = Get-Content -LiteralPath $findingsPath -Raw -Encoding utf8 | ConvertFrom-Json @jsonArgs
$summary = (Get-Content -LiteralPath $summaryPath -Raw -Encoding utf8).Trim()
$problems = [Collections.Generic.List[string]]::new()

# Expected values, recomputed from the findings array.
$findings = @($report.findings)
function Get-CheckCount([string] $CheckId) { @($findings | Where-Object CheckId -EQ $CheckId).Count }
function Get-SeverityCount([string] $Severity) { @($findings | Where-Object Severity -EQ $Severity).Count }
function Get-Rounded([double] $Value) { [int][Math]::Round($Value, 0, [MidpointRounding]::AwayFromZero) }
$asOf = if ($report.asOf -is [datetime]) { $report.asOf.ToString('yyyy-MM-dd') } else { [string] $report.asOf }

if ($report.counts.total -ne $findings.Count) { $problems.Add("counts.total=$($report.counts.total) but findings has $($findings.Count)") }
foreach ($p in $report.counts.byCheck.PSObject.Properties) {
    if ($p.Value -ne (Get-CheckCount $p.Name)) { $problems.Add("counts.byCheck.$($p.Name)=$($p.Value) but findings has $(Get-CheckCount $p.Name)") }
}
foreach ($p in $report.counts.bySeverity.PSObject.Properties) {
    if ($p.Value -ne (Get-SeverityCount $p.Name)) { $problems.Add("counts.bySeverity.$($p.Name)=$($p.Value) but findings has $(Get-SeverityCount $p.Name)") }
}

# Each fact: a phrase pattern, and a check that returns $null when the captured values match, or a problem message.
$m = $report.metrics
$s = $report.settings
$facts = @(
    @{ Name = 'as-of date'; Required = $true; Pattern = 'As of (\d{4}-\d{2}-\d{2})'
        Check = { param($g) if ($g[1] -ne $asOf) { "as-of $($g[1]) but findings.json says $asOf" } } }
    @{ Name = 'checks and total'; Required = $true; Pattern = 'ran (\d+) checks and found (\d+) issues?'
        Check = { param($g) if ([int]$g[1] -ne $m.checksRun -or [int]$g[2] -ne $findings.Count) { "says $($g[1]) checks / $($g[2]) issues, findings.json has $($m.checksRun) / $($findings.Count)" } } }
    @{ Name = 'severity'; Pattern = '(\d+) (high|medium|low)\b'
        Check = { param($g) $n = Get-SeverityCount ([cultureinfo]::InvariantCulture.TextInfo.ToTitleCase($g[2].ToLowerInvariant())); if ([int]$g[1] -ne $n) { "says $($g[1]) $($g[2]), findings has $n" } } }
    @{ Name = 'MFA'; Pattern = '(\d+) of (\d+) enabled member accounts? (?:has|have) no MFA'
        Check = { param($g) if ([int]$g[1] -ne (Get-CheckCount 'MFA') -or [int]$g[2] -ne $m.enabledMemberUsers) { "says $($g[1]) of $($g[2]) without MFA, expected $(Get-CheckCount 'MFA') of $($m.enabledMemberUsers)" } } }
    @{ Name = 'MFA (none)'; Pattern = 'All (\d+) enabled member accounts have an MFA'
        Check = { param($g) if ((Get-CheckCount 'MFA') -ne 0 -or [int]$g[1] -ne $m.enabledMemberUsers) { "says all $($g[1]) registered, expected $(Get-CheckCount 'MFA') unregistered of $($m.enabledMemberUsers)" } } }
    @{ Name = 'stale'; Pattern = '(\d+) enabled accounts? (?:has|have) not signed in successfully for (\d+) days'
        Check = { param($g) if ([int]$g[1] -ne (Get-CheckCount 'STALE') -or [int]$g[2] -ne $s.staleDays) { "says $($g[1]) stale at $($g[2]) days, expected $(Get-CheckCount 'STALE') at $($s.staleDays)" } } }
    @{ Name = 'stale (none)'; Pattern = 'No enabled account has gone (\d+) days'
        Check = { param($g) if ((Get-CheckCount 'STALE') -ne 0 -or [int]$g[1] -ne $s.staleDays) { "says none stale at $($g[1]) days, expected $(Get-CheckCount 'STALE') at $($s.staleDays)" } } }
    @{ Name = 'global admins'; Pattern = '(\d+) Global Administrators?, (above|within) the recommended maximum of (\d+)'
        Check = { param($g)
            $above = (Get-CheckCount 'GLOBALADMIN') -gt 0
            if ([int]$g[1] -ne $m.globalAdminCount -or [int]$g[3] -ne $s.maxGlobalAdmins -or (($g[2] -eq 'above') -ne $above)) {
                "says $($g[1]) admins $($g[2]) max $($g[3]), expected $($m.globalAdminCount) $(if ($above) { 'above' } else { 'within' }) max $($s.maxGlobalAdmins)"
            } } }
    @{ Name = 'legacy auth'; Pattern = 'Legacy authentication is (not )?blocked'
        Check = { param($g) if ([bool]$g[1] -ne ((Get-CheckCount 'LEGACYAUTH') -gt 0)) { "legacy-auth claim contradicts $(Get-CheckCount 'LEGACYAUTH') LEGACYAUTH findings" } } }
    @{ Name = 'break-glass'; Pattern = '(\d+) break-glass account issues? (?:was|were) found'
        Check = { param($g) if ([int]$g[1] -ne (Get-CheckCount 'BREAKGLASS')) { "says $($g[1]) break-glass issues, findings has $(Get-CheckCount 'BREAKGLASS')" } } }
    @{ Name = 'break-glass (none)'; Pattern = 'Break-glass accounts match the documented pattern'
        Check = { param($g) [void]$g; if ((Get-CheckCount 'BREAKGLASS') -ne 0) { "says break-glass is fine, findings has $(Get-CheckCount 'BREAKGLASS')" } } }
    @{ Name = 'guest admins'; Pattern = '(\d+) guest users? holds? an admin role'
        Check = { param($g) if ([int]$g[1] -ne (Get-CheckCount 'GUESTADMIN')) { "says $($g[1]) guest admins, findings has $(Get-CheckCount 'GUESTADMIN')" } } }
    @{ Name = 'guest admins (none)'; Pattern = 'No guest user holds an admin role'
        Check = { param($g) [void]$g; if ((Get-CheckCount 'GUESTADMIN') -ne 0) { "says no guest admins, findings has $(Get-CheckCount 'GUESTADMIN')" } } }
    @{ Name = 'SSPR coverage'; Pattern = '(\d+) of (\d+) eligible member accounts are registered for self-service password reset \((\d+)%\), (below|meeting) the minimum of (\d+)%'
        Check = { param($g)
            $below = (Get-CheckCount 'SSPR') -gt 0
            if ([int]$g[1] -ne $m.ssprRegisteredUsers -or [int]$g[2] -ne $m.ssprEligibleUsers -or [int]$g[3] -ne $m.ssprCoveragePercent -or [int]$g[5] -ne $s.ssprMinimumCoveragePercent -or (($g[4] -eq 'below') -ne $below)) {
                "says $($g[1]) of $($g[2]) ($($g[3])%) $($g[4]) minimum $($g[5])%, expected $($m.ssprRegisteredUsers) of $($m.ssprEligibleUsers) ($($m.ssprCoveragePercent)%) $(if ($below) { 'below' } else { 'meeting' }) minimum $($s.ssprMinimumCoveragePercent)%"
            } } }
    @{ Name = 'break-glass sign-ins'; Pattern = '(\d+) break-glass accounts? signed in within the last (\d+) days'
        Check = { param($g) if ([int]$g[1] -ne (Get-CheckCount 'BGSIGNIN') -or [int]$g[2] -ne $s.breakGlassSignInWindowDays) { "says $($g[1]) break-glass sign-ins in $($g[2]) days, expected $(Get-CheckCount 'BGSIGNIN') in $($s.breakGlassSignInWindowDays)" } } }
    @{ Name = 'break-glass sign-ins (none)'; Pattern = 'No break-glass account signed in within the last (\d+) days'
        Check = { param($g) if ((Get-CheckCount 'BGSIGNIN') -ne 0 -or [int]$g[1] -ne $s.breakGlassSignInWindowDays) { "says none in $($g[1]) days, expected $(Get-CheckCount 'BGSIGNIN') in $($s.breakGlassSignInWindowDays)" } } }
    @{ Name = 'secure score'; Pattern = 'Secure Score is (\d+) of (\d+) points'
        Check = { param($g)
            if ($null -eq $m.secureScore) { 'mentions Secure Score but findings.json has none' }
            elseif ([int]$g[1] -ne (Get-Rounded $m.secureScore.currentScore) -or [int]$g[2] -ne (Get-Rounded $m.secureScore.maxScore)) {
                "says $($g[1]) of $($g[2]), findings.json has $(Get-Rounded $m.secureScore.currentScore) of $(Get-Rounded $m.secureScore.maxScore)"
            } } }
)

# Mask every span a fact claims; whatever digits remain afterwards are unreconciled numbers.
$mask = [char[]] $summary
$tenantName = [string] $report.tenantDisplayName
if ($tenantName) {
    foreach ($hit in [regex]::Matches($summary, [regex]::Escape($tenantName))) { for ($i = $hit.Index; $i -lt $hit.Index + $hit.Length; $i++) { $mask[$i] = ' ' } }
}
foreach ($fact in $facts) {
    $hits = [regex]::Matches($summary, $fact.Pattern, 'IgnoreCase')
    if ($fact['Required'] -and $hits.Count -eq 0) { $problems.Add("required fact '$($fact.Name)' not found in summary") }
    foreach ($hit in $hits) {
        $groups = @($hit.Groups | ForEach-Object { $_.Value })
        $msg = & $fact.Check $groups
        if ($msg) { $problems.Add("$($fact.Name): $msg") }
        for ($i = $hit.Index; $i -lt $hit.Index + $hit.Length; $i++) { $mask[$i] = ' ' }
    }
}
$rest = -join $mask
foreach ($n in [regex]::Matches($rest, '\d+(?:[.,]\d+)?')) { $problems.Add("unreconciled number '$($n.Value)' (no fact phrase claims it)") }
$words = 'zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|dozen|hundred'
foreach ($w in [regex]::Matches($rest, "\b($words)\b", 'IgnoreCase')) { $problems.Add("spelled-out number '$($w.Value)' cannot be reconciled; use digits") }

if ($problems.Count) {
    foreach ($p in $problems) { Write-Output "FAIL: $p" }
    Write-Output "Summary does NOT reconcile with findings.json ($($problems.Count) problem(s))."
    exit 1
}
Write-Output "OK: every number in summary.txt reconciles with findings.json ($($findings.Count) findings)."
exit 0
