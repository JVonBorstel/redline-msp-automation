#requires -Version 7.4
<#
TenantBaseline: a read-only Microsoft 365 security baseline check (specs/slices-abc.md, Slice B).

Data flow:  Graph snapshot (mock adapter over fixtures, or the -UseGraph stub)  ->  six checks  ->  report object
            ->  findings.json, findings.csv (Power BI), report.html, summary.txt.
Nothing here changes a tenant. A finding names a fix lever (for example user.require-mfa) as a dry-run proposal only;
executing it is the lever registry's job, behind a lead's approval (Slice C).
Fixture data is synthetic and shaped like Microsoft Graph v1.0 responses; see fixtures/graph/SOURCES.md.
#>
Set-StrictMode -Version Latest

$script:ModuleRoot = $PSScriptRoot
$script:DefaultConfigPath = Join-Path $PSScriptRoot 'TenantBaseline.config.json'
$script:DefaultFixtureRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..\fixtures\graph'))
$script:SourceLabel = 'fixture-based: mock data shaped like Microsoft Graph v1.0'
$script:CheckOrder = @('MFA', 'STALE', 'GLOBALADMIN', 'LEGACYAUTH', 'BREAKGLASS', 'GUESTADMIN')
# B-40: two opt-in identity checks (see -IncludeIdentityChecks). Off by default so the demo's 14-finding output is unchanged.
$script:IdentityCheckOrder = @('SSPR', 'BGSIGNIN')
$script:DefaultSsprMinimumPercent = 90
$script:DefaultBreakGlassSignInWindowDays = 14
$script:LegacyClientAppTypes = @('exchangeActiveSync', 'other')
# PowerShell 7.5+ can keep ISO dates as strings; older 7.x converts them to [datetime]. ConvertTo-TbDate accepts both.
$script:JsonArgs = if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) { @{ DateKind = 'String' } } else { @{} }

class TenantBaselineFinding {
    [string] $Id
    [string] $CheckId
    [ValidateSet('High', 'Medium', 'Low')] [string] $Severity
    [string] $Title
    [string] $Subject
    [string] $Evidence
    [string] $FixLever    # registry lever name, or '' when the fix is a human decision
    [ValidateSet('dry-run', 'manual')] [string] $FixMode
    [string] $FixTarget

    TenantBaselineFinding([string] $checkId, [string] $severity, [string] $title, [string] $subject, [string] $evidence,
        [string] $fixLever, [string] $fixTarget) {
        $this.CheckId = $checkId
        $this.Severity = $severity
        $this.Title = $title
        $this.Subject = $subject
        $this.Evidence = $evidence
        $this.FixLever = $fixLever
        $this.FixMode = if ($fixLever) { 'dry-run' } else { 'manual' }
        $this.FixTarget = $fixTarget
    }
}

#region helpers

function Read-TbJson([string] $Path) {
    Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json @script:JsonArgs
}

# Optional property read that is safe under StrictMode: missing or null both return $null.
function Get-TbValue($Object, [string] $Name) {
    if ($null -eq $Object) { return $null }
    $p = $Object.PSObject.Properties[$Name]
    if ($p) { $p.Value } else { $null }
}

function ConvertTo-TbDate($Value) {
    if ($null -eq $Value -or '' -eq $Value) { return $null }
    if ($Value -is [datetime]) { return [DateTimeOffset]::new($Value.ToUniversalTime()) }
    [DateTimeOffset]::Parse([string] $Value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal)
}

function Format-TbDate([DateTimeOffset] $Date) { $Date.UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ssZ', [Globalization.CultureInfo]::InvariantCulture) }

function Get-TbDaysBefore([DateTimeOffset] $Date, [DateTimeOffset] $AsOf) { [int][Math]::Floor(($AsOf - $Date).TotalDays) }

function Get-TbConfig([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "TenantBaseline config not found: $Path" }
    $config = Read-TbJson $Path
    foreach ($key in 'asOf', 'staleDays', 'maxGlobalAdmins', 'globalAdminRoleTemplateId', 'breakGlass', 'fixLevers', 'tenants', 'graph') {
        if ($null -eq (Get-TbValue $config $key)) { throw "TenantBaseline config is missing '$key': $Path" }
    }
    $config
}

# B-26 (DR-05): tenants are keyed by the canonical client id (contoso-dental, fabrikam-capital). The old fixture-folder
# names (contoso, clean) stay accepted as aliases. Returns the client id, display name and fixture folder, or $null.
function Resolve-TbTenant($Config, [string] $Tenant) {
    foreach ($p in $Config.tenants.PSObject.Properties) {
        if ($p.Name -eq $Tenant -or @(Get-TbValue $p.Value 'aliases') -contains $Tenant) {
            $dir = Get-TbValue $p.Value 'fixtureDir'
            return [pscustomobject]@{ ClientId = $p.Name; DisplayName = [string] $p.Value.displayName; FixtureDir = if ($dir) { [string] $dir } else { $p.Name } }
        }
    }
    $null
}

#endregion

#region Graph adapters

# Reads one fixture file and returns its 'value' array, enforcing the Graph collection response shape.
function Read-TbGraphCollection([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Graph fixture not found: $Path" }
    $doc = Read-TbJson $Path
    if ($null -eq $doc -or -not $doc.PSObject.Properties['value']) { throw "Not a Microsoft Graph collection response (no 'value' array): $Path" }
    , @($doc.value)
}

# Mock Graph adapter. Each file is the body of one Graph v1.0 GET (see fixtures/graph/SOURCES.md for the exact request).
function Get-TbFixtureSnapshot([string] $FixtureRoot, [string] $Tenant) {
    $dir = Join-Path $FixtureRoot $Tenant
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { throw "No fixtures for tenant '$Tenant' under $FixtureRoot" }
    [pscustomobject]@{
        Users         = Read-TbGraphCollection (Join-Path $dir 'users.json')
        Registrations = Read-TbGraphCollection (Join-Path $dir 'userRegistrationDetails.json')
        Roles         = Read-TbGraphCollection (Join-Path $dir 'directoryRoles.json')
        CaPolicies    = Read-TbGraphCollection (Join-Path $dir 'conditionalAccessPolicies.json')
        SecureScore   = @(Read-TbGraphCollection (Join-Path $dir 'secureScores.json')) | Select-Object -First 1
    }
}

# Real Graph adapter: a deliberate stub. It refuses before any connection is attempted, so it never touches the network.
function Assert-TbGraphAvailable($Config) {
    $envName = $Config.graph.tenantIdEnvVar
    $scopes = ($Config.graph.requiredScopes -join ', ')
    $optional = ($Config.graph.optionalScopes -join ', ')
    if (-not [Environment]::GetEnvironmentVariable($envName)) {
        throw ("-UseGraph needs a configured test tenant, but the environment variable $envName is not set. No network call was made.`n" +
            "The real adapter needs an app registration with these read-only Microsoft Graph application permissions:`n" +
            "  $scopes`n" +
            "Optional, for Secure Score context only: $optional`n" +
            'Run without -UseGraph to use the fixture-based mock adapter.')
    }
    throw ("-UseGraph: the real Graph adapter is a stub in this prototype and is not run without an approved test tenant. No network call was made.`n" +
        "Read-only permissions it will need: $scopes (optional: $optional).")
}

#endregion

#region checks (each returns TenantBaselineFinding objects; Ids are assigned afterwards)

function Get-TbMfaFinding($Snapshot, $Config) {
    $registrations = @{}
    foreach ($r in $Snapshot.Registrations) { $registrations[$r.id] = $r }
    foreach ($u in $Snapshot.Users | Where-Object { $_.accountEnabled -and $_.userType -eq 'Member' }) {
        $reg = $registrations[$u.id]
        $evidence = if ($null -eq $reg) {
            'no userRegistrationDetails record (treated as not registered)'
        } elseif (-not $reg.isMfaRegistered) {
            $methods = @(Get-TbValue $reg 'methodsRegistered')
            'isMfaRegistered=false; methodsRegistered=' + $(if ($methods.Count) { $methods -join ',' } else { 'none' })
        } else { $null }
        if ($evidence) {
            [TenantBaselineFinding]::new('MFA', 'High', 'User has no MFA method registered', $u.userPrincipalName,
                "$evidence; accountEnabled=true; userType=Member", $Config.fixLevers.MFA, $u.userPrincipalName)
        }
    }
}

# Uses lastSuccessfulSignInDateTime: lastSignInDateTime also records failed attempts, so a password-spray against a dormant
# account would otherwise make it look active.
function Get-TbStaleSignInFinding($Snapshot, $Config, [DateTimeOffset] $AsOf) {
    $staleDays = [int] $Config.staleDays
    foreach ($u in $Snapshot.Users | Where-Object { $_.accountEnabled }) {
        $activity = Get-TbValue $u 'signInActivity'
        $lastOk = ConvertTo-TbDate (Get-TbValue $activity 'lastSuccessfulSignInDateTime')
        if ($null -ne $lastOk) {
            $days = Get-TbDaysBefore $lastOk $AsOf
            if ($days -lt $staleDays) { continue }
            $evidence = "lastSuccessfulSignInDateTime=$(Format-TbDate $lastOk) ($days days before as-of)"
            $lastTry = ConvertTo-TbDate (Get-TbValue $activity 'lastSignInDateTime')
            if ($null -ne $lastTry -and $lastTry -gt $lastOk) {
                $evidence += "; later lastSignInDateTime=$(Format-TbDate $lastTry) is an attempt only (may be failed sign-ins)"
            }
        } else {
            $created = ConvertTo-TbDate $u.createdDateTime
            $days = Get-TbDaysBefore $created $AsOf
            if ($days -lt $staleDays) { continue }
            $evidence = "no successful sign-in on record; createdDateTime=$(Format-TbDate $created) ($days days before as-of)"
        }
        [TenantBaselineFinding]::new('STALE', 'Medium', "No successful sign-in for $staleDays+ days", $u.userPrincipalName,
            "$evidence; userType=$($u.userType)", $Config.fixLevers.STALE, $u.userPrincipalName)
    }
}

function Get-TbGlobalAdminMember($Snapshot, $Config) {
    $role = $Snapshot.Roles | Where-Object { $_.roleTemplateId -eq $Config.globalAdminRoleTemplateId } | Select-Object -First 1
    if ($null -eq $role) { return @() }
    @(Get-TbValue $role 'members')
}

function Get-TbGlobalAdminFinding($Snapshot, $Config) {
    $members = @(Get-TbGlobalAdminMember $Snapshot $Config)
    $max = [int] $Config.maxGlobalAdmins
    if ($members.Count -le $max) { return }
    $names = ($members | ForEach-Object { $_.userPrincipalName } | Sort-Object) -join ', '
    [TenantBaselineFinding]::new('GLOBALADMIN', 'High', "More than $max Global Administrators", 'Global Administrator',
        "$($members.Count) members of roleTemplateId $($Config.globalAdminRoleTemplateId): $names",
        $Config.fixLevers.GLOBALADMIN, 'Global Administrator')
}

# Returns why a CA policy does not block legacy auth tenant-wide, or an empty list when it does.
function Get-TbLegacyAuthGap($Policy) {
    $gaps = [Collections.Generic.List[string]]::new()
    $types = @($Policy.conditions.clientAppTypes)
    if ($Policy.state -ne 'enabled') { $gaps.Add("state=$($Policy.state)") }
    $missing = @($script:LegacyClientAppTypes | Where-Object { $_ -notin $types })
    if ($missing.Count) { $gaps.Add("clientAppTypes lacks $($missing -join ',')") }
    if ('block' -notin @(Get-TbValue $Policy.grantControls 'builtInControls')) { $gaps.Add('grant is not block') }
    if ('All' -notin @(Get-TbValue $Policy.conditions.users 'includeUsers')) { $gaps.Add('does not include All users') }
    if ('All' -notin @(Get-TbValue $Policy.conditions.applications 'includeApplications')) { $gaps.Add('does not include All apps') }
    , $gaps
}

function Get-TbLegacyAuthFinding($Snapshot, $Config, [string] $TenantName) {
    $nearMisses = [Collections.Generic.List[string]]::new()
    foreach ($p in $Snapshot.CaPolicies) {
        $gaps = Get-TbLegacyAuthGap $p
        if ($gaps.Count -eq 0) { return }   # an enabled, tenant-wide block exists: no finding
        $touchesLegacy = @($p.conditions.clientAppTypes | Where-Object { $_ -in $script:LegacyClientAppTypes }).Count -gt 0
        if ($touchesLegacy) { $nearMisses.Add("'$($p.displayName)': $($gaps -join ', ')") }
    }
    $evidence = 'no enabled policy blocks exchangeActiveSync and other for All users and All apps'
    if ($nearMisses.Count) { $evidence += '; near misses: ' + ($nearMisses -join '; ') }
    [TenantBaselineFinding]::new('LEGACYAUTH', 'High', 'Legacy authentication not blocked by an enabled Conditional Access policy',
        $TenantName, $evidence, $Config.fixLevers.LEGACYAUTH, $TenantName)
}

# Accounts that look like break-glass accounts by name prefix or display name (documented pattern in config).
function Get-TbBreakGlassCandidate($Snapshot, $Config) {
    $bg = $Config.breakGlass
    @($Snapshot.Users | Where-Object {
            $_.userPrincipalName.StartsWith($bg.namePrefix, [StringComparison]::OrdinalIgnoreCase) -or $_.displayName -match $bg.candidateDisplayNamePattern
        })
}

function Get-TbBreakGlassFinding($Snapshot, $Config, [string] $TenantName) {
    $bg = $Config.breakGlass
    $gaIds = @(Get-TbGlobalAdminMember $Snapshot $Config | ForEach-Object { $_.id })
    $enabledPolicies = @($Snapshot.CaPolicies | Where-Object { $_.state -eq 'enabled' })
    $compliant = [Collections.Generic.List[string]]::new()
    $candidates = Get-TbBreakGlassCandidate $Snapshot $Config
    foreach ($u in $candidates | Sort-Object userPrincipalName) {
        $fails = [Collections.Generic.List[string]]::new()
        if (-not $u.userPrincipalName.StartsWith($bg.namePrefix, [StringComparison]::OrdinalIgnoreCase)) { $fails.Add("name does not start with '$($bg.namePrefix)'") }
        if ($bg.requireCloudOnly -and (Get-TbValue $u 'onPremisesSyncEnabled') -eq $true) { $fails.Add('not cloud-only (onPremisesSyncEnabled=true)') }
        if ($bg.requireGlobalAdmin -and $u.id -notin $gaIds) { $fails.Add('not a Global Administrator') }
        if ($bg.requireExcludedFromEnabledCaPolicies) {
            $notExcluded = @($enabledPolicies | Where-Object { $u.id -notin @(Get-TbValue $_.conditions.users 'excludeUsers') } | ForEach-Object { "'$($_.displayName)'" })
            if ($notExcluded.Count) { $fails.Add("not excluded from enabled CA policies $($notExcluded -join ', ')") }
        }
        if (-not $u.accountEnabled) { $fails.Add('account disabled') }
        if ($fails.Count -eq 0) { $compliant.Add($u.userPrincipalName); continue }
        [TenantBaselineFinding]::new('BREAKGLASS', 'High', 'Break-glass account does not match the documented pattern', $u.userPrincipalName,
            ($fails -join '; '), $Config.fixLevers.BREAKGLASS, $u.userPrincipalName)
    }
    $minimum = [int] $bg.minimumCompliantAccounts
    if ($compliant.Count -lt $minimum) {
        $list = if ($compliant.Count) { $compliant -join ', ' } else { 'none' }
        [TenantBaselineFinding]::new('BREAKGLASS', 'High', "Fewer than $minimum break-glass accounts match the documented pattern", $TenantName,
            "$($compliant.Count) compliant ($list); documented minimum $minimum", $Config.fixLevers.BREAKGLASS, $TenantName)
    }
}

# B-40 (W-IDM-13, C-21). Share of enabled member accounts registered for self-service password reset (isSsprRegistered).
# Break-glass candidates are left out of the denominator on purpose: they are cloud-only emergency accounts kept out of
# self-service flows. A missing registration record counts as not registered (same rule as the MFA check).
function Get-TbSsprCoverage($Snapshot, $Config) {
    $bgIds = @(Get-TbBreakGlassCandidate $Snapshot $Config | ForEach-Object { $_.id })
    $registrations = @{}
    foreach ($r in $Snapshot.Registrations) { $registrations[$r.id] = $r }
    $eligible = @($Snapshot.Users | Where-Object { $_.accountEnabled -and $_.userType -eq 'Member' -and $_.id -notin $bgIds })
    $missing = @($eligible | Where-Object { -not (Get-TbValue $registrations[$_.id] 'isSsprRegistered') } | ForEach-Object { $_.userPrincipalName } | Sort-Object)
    $minimum = $script:DefaultSsprMinimumPercent
    $configured = Get-TbValue $Config 'ssprMinimumCoveragePercent'
    if ($null -ne $configured) { $minimum = [int] $configured }
    $registered = $eligible.Count - $missing.Count
    [pscustomobject]@{
        Eligible = $eligible.Count; Registered = $registered; Missing = $missing; MinimumPercent = $minimum
        Percent  = if ($eligible.Count) { Get-TbRounded (100.0 * $registered / $eligible.Count) } else { 100 }
        Below    = ($eligible.Count -gt 0 -and ($registered * 100) -lt ($minimum * $eligible.Count))
    }
}

function Get-TbSsprFinding($Snapshot, $Config, [string] $TenantName) {
    $cov = Get-TbSsprCoverage $Snapshot $Config
    if (-not $cov.Below) { return }
    [TenantBaselineFinding]::new('SSPR', 'Medium', "SSPR registration coverage is below $($cov.MinimumPercent)%", $TenantName,
        "$($cov.Registered) of $($cov.Eligible) enabled member accounts have isSsprRegistered=true ($($cov.Percent)%); minimum $($cov.MinimumPercent)%; break-glass accounts excluded; not registered: $($cov.Missing -join ', ')",
        '', $TenantName)
}

function Get-TbBreakGlassWindowDay($Config) {
    $days = Get-TbValue $Config.breakGlass 'signInWindowDays'
    if ($null -ne $days) { [int] $days } else { $script:DefaultBreakGlassSignInWindowDays }
}

# B-40 (W-IDM-08, C-20). Any sign-in by a break-glass candidate inside the window before as-of. Uses the latest of the three
# signInActivity timestamps: for an emergency account a failed attempt is as worth a look as a success. Fix is manual.
function Get-TbBreakGlassSignInFinding($Snapshot, $Config, [DateTimeOffset] $AsOf) {
    $window = Get-TbBreakGlassWindowDay $Config
    foreach ($u in Get-TbBreakGlassCandidate $Snapshot $Config | Sort-Object userPrincipalName) {
        $activity = Get-TbValue $u 'signInActivity'
        $latest = $null; $field = ''
        foreach ($name in 'lastSignInDateTime', 'lastNonInteractiveSignInDateTime', 'lastSuccessfulSignInDateTime') {
            $d = ConvertTo-TbDate (Get-TbValue $activity $name)
            if ($null -ne $d -and ($null -eq $latest -or $d -gt $latest)) { $latest = $d; $field = $name }
        }
        if ($null -eq $latest) { continue }
        $days = Get-TbDaysBefore $latest $AsOf
        if ($days -ge $window) { continue }
        [TenantBaselineFinding]::new('BGSIGNIN', 'High', "Break-glass account signed in within the last $window days", $u.userPrincipalName,
            "$field=$(Format-TbDate $latest) ($days days before as-of); window $window days", '', $u.userPrincipalName)
    }
}

function Get-TbGuestAdminFinding($Snapshot, $Config) {
    $guests = @{}
    foreach ($u in $Snapshot.Users | Where-Object { $_.userType -eq 'Guest' }) { $guests[$u.id] = $u }
    $rolesByGuest = @{}
    foreach ($role in $Snapshot.Roles) {
        foreach ($m in @(Get-TbValue $role 'members') | Where-Object { $guests.ContainsKey($_.id) }) {
            if (-not $rolesByGuest.ContainsKey($m.id)) { $rolesByGuest[$m.id] = [Collections.Generic.List[string]]::new() }
            $rolesByGuest[$m.id].Add("'$($role.displayName)' (roleTemplateId $($role.roleTemplateId))")
        }
    }
    foreach ($id in $rolesByGuest.Keys) {
        $u = $guests[$id]
        [TenantBaselineFinding]::new('GUESTADMIN', 'High', 'Guest user holds an admin role', $u.userPrincipalName,
            "userType=Guest; member of directoryRole $($rolesByGuest[$id] -join ', ')", $Config.fixLevers.GUESTADMIN, $u.userPrincipalName)
    }
}

#endregion

#region report and outputs

# Fills the client summary from computed counts only. No model is called here. The Python gateway ('summarize' route) may
# rephrase it later; Test-SummaryReconciles.ps1 is the gate any rephrased text must still pass (every number must match findings.json).
function Get-TbSummaryText($Report) {
    $c = $Report.counts.byCheck
    $m = $Report.metrics
    $s = $Report.settings
    $sev = @(foreach ($level in 'High', 'Medium', 'Low') { $n = $Report.counts.bySeverity[$level]; if ($n) { "$n $($level.ToLowerInvariant())" } })
    $sevText = if ($sev.Count -gt 1) { ($sev[0..($sev.Count - 2)] -join ', ') + ' and ' + $sev[-1] } else { $sev -join '' }
    $issues = if ($Report.counts.total -eq 1) { 'issue' } else { 'issues' }
    $lines = [Collections.Generic.List[string]]::new()
    $first = "As of $($Report.asOf), a fixture-based baseline review of $($Report.tenantDisplayName) ran $($m.checksRun) checks and found $($Report.counts.total) $issues"
    $lines.Add($(if ($Report.counts.total) { "$first ($sevText severity)." } else { "$first." }))
    $lines.Add($(if ($c.MFA) { "$($c.MFA) of $($m.enabledMemberUsers) enabled member accounts have no MFA method registered." }
            else { "All $($m.enabledMemberUsers) enabled member accounts have an MFA method registered." }))
    $lines.Add($(switch ($c.STALE) {
                0 { "No enabled account has gone $($s.staleDays) days or more without a successful sign-in." }
                1 { "1 enabled account has not signed in successfully for $($s.staleDays) days or more." }
                default { "$_ enabled accounts have not signed in successfully for $($s.staleDays) days or more." }
            }))
    $gaWord = if ($m.globalAdminCount -eq 1) { 'Global Administrator' } else { 'Global Administrators' }
    $lines.Add("The tenant has $($m.globalAdminCount) $gaWord, $(if ($c.GLOBALADMIN) { 'above' } else { 'within' }) the recommended maximum of $($s.maxGlobalAdmins).")
    $lines.Add("Legacy authentication is $(if ($c.LEGACYAUTH) { 'not blocked' } else { 'blocked' }) by an enabled Conditional Access policy.")
    $lines.Add($(switch ($c.BREAKGLASS) {
                0 { 'Break-glass accounts match the documented pattern.' }
                1 { '1 break-glass account issue was found against the documented pattern.' }
                default { "$_ break-glass account issues were found against the documented pattern." }
            }))
    $lines.Add($(switch ($c.GUESTADMIN) {
                0 { 'No guest user holds an admin role.' }
                1 { '1 guest user holds an admin role.' }
                default { "$_ guest users hold an admin role." }
            }))
    if ($c.Contains('SSPR')) {
        $lines.Add("$($m.ssprRegisteredUsers) of $($m.ssprEligibleUsers) eligible member accounts are registered for self-service password reset ($($m.ssprCoveragePercent)%), $(if ($c.SSPR) { 'below' } else { 'meeting' }) the minimum of $($s.ssprMinimumCoveragePercent)%.")
    }
    if ($c.Contains('BGSIGNIN')) {
        $lines.Add($(switch ($c.BGSIGNIN) {
                    0 { "No break-glass account signed in within the last $($s.breakGlassSignInWindowDays) days." }
                    1 { "1 break-glass account signed in within the last $($s.breakGlassSignInWindowDays) days." }
                    default { "$_ break-glass accounts signed in within the last $($s.breakGlassSignInWindowDays) days." }
                }))
    }
    if ($null -ne $m.secureScore) {
        $lines.Add("Microsoft Secure Score is $(Get-TbRounded $m.secureScore.currentScore) of $(Get-TbRounded $m.secureScore.maxScore) points.")
    }
    $lines.Add($(if ($Report.counts.total) { 'Every suggested fix is a dry-run proposal that a lead must approve before anything changes.' }
            else { 'No fixes are proposed.' }))
    $lines -join ' '
}

# B-50 (W-IDM-06, W-M365-11; C-21, C-20): drift over time. Report only. Nothing in this region reads Config.fixLevers or names a lever:
# Conditional Access changes are a human decision (governance/never-automate.json).
$script:CaAssignmentFields = @('includeUsers', 'excludeUsers', 'includeGroups', 'excludeGroups', 'includeRoles', 'excludeRoles', 'includeApplications', 'excludeApplications')

# Missing, null and empty all return nothing (callers wrap in @()). Sorted so that order alone never counts as a change.
function Get-TbList($Object, [string] $Name) {
    Get-TbValue $Object $Name | Where-Object { $null -ne $_ } | ForEach-Object { [string] $_ } | Sort-Object -Unique
}

# Small Conditional Access snapshot (id, name, state, assignments) kept in findings.json so it can be the next run's -CompareTo file.
function Get-TbCaSnapshot($Snapshot) {
    foreach ($p in @($Snapshot.CaPolicies) | Sort-Object { [string] $_.id }) {
        $conditions = Get-TbValue $p 'conditions'
        $users = Get-TbValue $conditions 'users'
        $apps = Get-TbValue $conditions 'applications'
        $assignments = [ordered]@{}
        foreach ($field in $script:CaAssignmentFields) {
            $source = if ($field -like '*Applications') { $apps } else { $users }
            $assignments[$field] = @(Get-TbList $source $field)
        }
        [ordered]@{ id = [string] $p.id; displayName = [string] $p.displayName; state = [string] $p.state; assignments = $assignments }
    }
}

function Read-TbPreviousReport([string] $Path, [string] $TenantId) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "-CompareTo file not found: $Path" }
    try { $doc = Read-TbJson $Path } catch { throw "-CompareTo file is not valid JSON: $Path" }
    if ($null -eq $doc -or $null -eq $doc.PSObject.Properties['findings']) { throw "-CompareTo file is not a TenantBaseline findings.json (no 'findings' array): $Path" }
    $prevTenant = Get-TbValue $doc 'tenant'
    if ($prevTenant -ne $TenantId) { throw "-CompareTo file is for tenant '$prevTenant', not '$TenantId': $Path" }
    $doc
}

function Get-TbDrift($Previous, $Current) {
    $cur = $Current | ConvertTo-Json -Depth 10 | ConvertFrom-Json @script:JsonArgs   # same shape on both sides
    $keyOf = { param($f) "$(Get-TbValue $f 'CheckId')|$(Get-TbValue $f 'Subject')" }
    $brief = { param($f) [ordered]@{ Id = [string] (Get-TbValue $f 'Id'); CheckId = [string] (Get-TbValue $f 'CheckId'); Severity = [string] (Get-TbValue $f 'Severity'); Title = [string] (Get-TbValue $f 'Title'); Subject = [string] (Get-TbValue $f 'Subject') } }
    $prevByKey = @{}; foreach ($f in @($Previous.findings) | Where-Object { $null -ne $_ }) { $prevByKey[(& $keyOf $f)] = $f }
    $curByKey = @{}; foreach ($f in @($cur.findings) | Where-Object { $null -ne $_ }) { $curByKey[(& $keyOf $f)] = $f }
    $new = @($curByKey.Keys | Sort-Object | Where-Object { -not $prevByKey.ContainsKey($_) } | ForEach-Object { & $brief $curByKey[$_] })
    $resolved = @($prevByKey.Keys | Sort-Object | Where-Object { -not $curByKey.ContainsKey($_) } | ForEach-Object { & $brief $prevByKey[$_] })
    $unchanged = @($curByKey.Keys | Sort-Object | Where-Object { $prevByKey.ContainsKey($_) } | ForEach-Object { & $brief $curByKey[$_] })

    $ca = [ordered]@{ compared = $false; note = 'previous file has no CA snapshot; Conditional Access comparison skipped'; added = @(); removed = @(); stateChanged = @(); assignmentsChanged = @() }
    $prevCaProp = $Previous.PSObject.Properties['conditionalAccess']
    if ($null -ne $prevCaProp) {
        $prevCa = @{}; foreach ($p in @($prevCaProp.Value) | Where-Object { $null -ne $_ }) { $prevCa[[string] $p.id] = $p }
        $curCa = @{}; foreach ($p in @($cur.conditionalAccess) | Where-Object { $null -ne $_ }) { $curCa[[string] $p.id] = $p }
        $ca.compared = $true
        $ca.note = ''
        $ca.added = @($curCa.Keys | Sort-Object | Where-Object { -not $prevCa.ContainsKey($_) } | ForEach-Object { [ordered]@{ id = $_; displayName = [string] $curCa[$_].displayName; state = [string] $curCa[$_].state } })
        $ca.removed = @($prevCa.Keys | Sort-Object | Where-Object { -not $curCa.ContainsKey($_) } | ForEach-Object { [ordered]@{ id = $_; displayName = [string] $prevCa[$_].displayName; state = [string] $prevCa[$_].state } })
        $stateChanged = [Collections.Generic.List[object]]::new()
        $assignChanged = [Collections.Generic.List[object]]::new()
        foreach ($id in $curCa.Keys | Sort-Object | Where-Object { $prevCa.ContainsKey($_) }) {
            $a = $prevCa[$id]; $b = $curCa[$id]
            if ([string] $a.state -ne [string] $b.state) {
                $stateChanged.Add([ordered]@{ id = $id; displayName = [string] $b.displayName; from = [string] $a.state; to = [string] $b.state })
            }
            $changes = foreach ($field in $script:CaAssignmentFields) {
                $before = @(Get-TbList (Get-TbValue $a 'assignments') $field)
                $after = @(Get-TbList (Get-TbValue $b 'assignments') $field)
                $added = @($after | Where-Object { $_ -notin $before })
                $removed = @($before | Where-Object { $_ -notin $after })
                if ($added.Count -or $removed.Count) { [ordered]@{ field = $field; added = $added; removed = $removed } }
            }
            if (@($changes).Count) { $assignChanged.Add([ordered]@{ id = $id; displayName = [string] $b.displayName; changes = @($changes) }) }
        }
        $ca.stateChanged = $stateChanged.ToArray()
        $ca.assignmentsChanged = $assignChanged.ToArray()
    }
    $prevAsOf = Get-TbValue $Previous 'asOf'
    if ($prevAsOf -is [datetime]) { $prevAsOf = $prevAsOf.ToString('yyyy-MM-dd') }
    [ordered]@{
        comparedTo        = [string] $prevAsOf
        reportOnly        = $true
        note              = 'Report only; Conditional Access changes are a human decision and are never proposed as fixes.'
        counts            = [ordered]@{
            new = $new.Count; resolved = $resolved.Count; unchanged = $unchanged.Count
            caAdded = @($ca.added).Count; caRemoved = @($ca.removed).Count; caStateChanged = @($ca.stateChanged).Count; caAssignmentsChanged = @($ca.assignmentsChanged).Count
        }
        findings          = [ordered]@{ new = $new; resolved = $resolved; unchanged = $unchanged }
        conditionalAccess = $ca
    }
}

# One plain line per fact; drift.txt joins them and report.html wraps each in a list item (encoded there).
function Get-TbDriftLine($Drift) {
    $c = $Drift.counts
    $lines = [Collections.Generic.List[string]]::new()
    $lines.Add("Compared with the previous run (as-of $($Drift.comparedTo)). $($Drift.note)")
    $lines.Add("Findings: $($c.new) new, $($c.resolved) resolved, $($c.unchanged) unchanged.")
    foreach ($f in $Drift.findings.new) { $lines.Add("New: [$($f.CheckId)] $($f.Subject) ($($f.Severity))") }
    foreach ($f in $Drift.findings.resolved) { $lines.Add("Resolved: [$($f.CheckId)] $($f.Subject) ($($f.Severity))") }
    $ca = $Drift.conditionalAccess
    if (-not $ca.compared) {
        $lines.Add("Conditional Access: $($ca.note).")
    } else {
        $lines.Add("Conditional Access: $($c.caAdded) added, $($c.caRemoved) removed, $($c.caStateChanged) with a state change, $($c.caAssignmentsChanged) with an assignment change.")
        foreach ($p in $ca.added) { $lines.Add("CA policy added: '$($p.displayName)' (state $($p.state))") }
        foreach ($p in $ca.removed) { $lines.Add("CA policy removed: '$($p.displayName)' (was $($p.state))") }
        foreach ($p in $ca.stateChanged) { $lines.Add("CA state changed: '$($p.displayName)' $($p.from) -> $($p.to)") }
        foreach ($p in $ca.assignmentsChanged) {
            foreach ($ch in $p.changes) {
                $parts = @(@($ch.added | ForEach-Object { "+$_" }) + @($ch.removed | ForEach-Object { "-$_" }))
                $lines.Add("CA assignments changed: '$($p.displayName)' $($ch.field) $($parts -join ' ')")
            }
        }
    }
    $lines.ToArray()
}

function Get-TbDriftHtml($Drift) {
    $items = foreach ($l in Get-TbDriftLine $Drift) { "<li>$(ConvertTo-TbHtmlText $l)</li>" }
    "`n<section class=`"summary`"><h2>Changes since previous run</h2><ul>`n$($items -join "`n")`n</ul></section>"
}

function Get-TbRounded([double] $Value) { [int][Math]::Round($Value, 0, [MidpointRounding]::AwayFromZero) }

function ConvertTo-TbHtmlText([string] $Text) { [Net.WebUtility]::HtmlEncode($Text) }

function Get-TbHtmlReport($Report, [string] $Summary) {
    $e = { param($t) ConvertTo-TbHtmlText ([string] $t) }
    $rows = foreach ($f in $Report.findings) {
        $fix = if ($f.FixLever) { "<code>$(& $e $f.FixLever)</code> <span class=`"muted`">(dry-run)</span>" } else { '<span class="muted">manual (human decision)</span>' }
        "<tr><td>$(& $e $f.Id)</td><td><span class=`"sev sev-$(& $e $f.Severity.ToLowerInvariant())`">$(& $e $f.Severity)</span></td>" +
        "<td>$(& $e $f.Title)</td><td>$(& $e $f.Subject)</td><td class=`"evidence`">$(& $e $f.Evidence)</td><td>$fix</td></tr>"
    }
    if (-not $rows) { $rows = '<tr><td colspan="6" class="muted">No findings.</td></tr>' }
    $m = $Report.metrics
    $score = if ($null -ne $m.secureScore) { "$(Get-TbRounded $m.secureScore.currentScore) / $(Get-TbRounded $m.secureScore.maxScore)" } else { 'n/a' }
    $tile = { param($label, $value) "<div class=`"tile`"><div class=`"tile-value`">$(& $e $value)</div><div class=`"tile-label`">$(& $e $label)</div></div>" }
    $driftHtml = if ($Report.Contains('drift')) { Get-TbDriftHtml $Report.drift } else { '' }
    @"
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>$(& $e "Security baseline: $($Report.tenantDisplayName)")</title>
<style>
:root { --bg:#fbfbfa; --fg:#1d1d1b; --muted:#6b6b66; --line:#e2e1dc; --card:#ffffff; --high:#b42318; --medium:#b54708; --low:#475467; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecebe6; --muted:#a3a29b; --line:#33332f; --card:#1f1f1d; --high:#f97066; --medium:#fdb022; --low:#98a2b3; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1100px; margin:0 auto; padding:32px 16px 48px; }
h1 { font-size:24px; margin:0 0 4px; }
.muted { color:var(--muted); }
.label { font-size:13px; color:var(--muted); margin:0 0 24px; }
.summary { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:16px 20px; margin:0 0 24px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:12px; margin:0 0 24px; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 16px; }
.tile-value { font-size:24px; font-weight:600; font-variant-numeric:tabular-nums; }
.tile-label { font-size:13px; color:var(--muted); }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--card); }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { text-align:left; vertical-align:top; padding:8px 12px; border-bottom:1px solid var(--line); }
th { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
tr:last-child td { border-bottom:0; }
.evidence { color:var(--muted); font-size:13px; word-break:break-word; }
.sev { font-weight:600; }
.sev-high { color:var(--high); } .sev-medium { color:var(--medium); } .sev-low { color:var(--low); }
code { font-size:13px; }
footer { margin-top:24px; font-size:13px; color:var(--muted); }
</style>
</head>
<body>
<main>
<h1>$(& $e "Microsoft 365 security baseline: $($Report.tenantDisplayName)")</h1>
<p class="label">$(& $e "As of $($Report.asOf) | $($Report.sourceLabel) | independently built prototype, synthetic tenant")</p>
<section class="summary"><p>$(& $e $Summary)</p></section>
<section class="tiles">
$(& $tile 'Findings' $Report.counts.total)
$(& $tile 'High' $Report.counts.bySeverity['High'])
$(& $tile 'Medium' $Report.counts.bySeverity['Medium'])
$(& $tile 'Global admins' $m.globalAdminCount)
$(& $tile 'Secure Score' $score)
</section>
<div class="table-wrap">
<table>
<thead><tr><th>Id</th><th>Severity</th><th>Finding</th><th>Subject</th><th>Evidence</th><th>Suggested fix</th></tr></thead>
<tbody>
$($rows -join "`n")
</tbody>
</table>
</div>$driftHtml
<footer>$(& $e "Thresholds: no successful sign-in for $($Report.settings.staleDays)+ days; more than $($Report.settings.maxGlobalAdmins) Global Administrators. Suggested fixes are lever names proposed in dry-run; nothing in the tenant was changed.")</footer>
</main>
</body>
</html>
"@
}

function Write-TbFile([string] $Path, [string] $Text) {
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

#endregion

function Get-TenantBaselineReport {
    <#
    .SYNOPSIS
    Runs the six baseline checks for one tenant and returns the report object (no files written).
    .PARAMETER Tenant
    Canonical client id (for example 'contoso-dental' or 'fabrikam-capital'). The fixture folder names 'contoso' and 'clean'
    are accepted as aliases (DR-05). The report always carries the canonical id.
    .PARAMETER UseGraph
    Use the real Microsoft Graph adapter. It is a stub: it refuses with the required read-only scopes and makes no network call.
    .PARAMETER IncludeIdentityChecks
    B-40: also run SSPR registration coverage (SSPR, medium) and sign-ins by break-glass accounts in the window (BGSIGNIN, high).
    Off by default, so the default output is still the six checks of the demo.
    .PARAMETER CompareTo
    B-50: path to a previous findings.json of the same tenant. Adds a 'drift' section: new, resolved and unchanged findings, and
    Conditional Access policies added, removed or changed in state or assignments. Report only; no fix is proposed for any of it.
    #>
    [CmdletBinding()]
    [OutputType([System.Collections.Specialized.OrderedDictionary])]
    param(
        [Parameter(Mandatory)] [ValidatePattern('^[a-z0-9][a-z0-9-]{0,31}$')] [string] $Tenant,
        [string] $FixtureRoot = $script:DefaultFixtureRoot,
        [string] $ConfigPath = $script:DefaultConfigPath,
        [switch] $UseGraph,
        [switch] $IncludeIdentityChecks,
        [string] $CompareTo
    )
    $config = Get-TbConfig $ConfigPath
    if ($UseGraph) { Assert-TbGraphAvailable $config }
    $tenantInfo = Resolve-TbTenant $config $Tenant
    if ($null -eq $tenantInfo) { throw "Unknown tenant '$Tenant'. Configured: $(@($config.tenants.PSObject.Properties.Name) -join ', ')" }
    $previous = if ($CompareTo) { Read-TbPreviousReport $CompareTo $tenantInfo.ClientId }
    $tenantName = $tenantInfo.DisplayName
    $asOfText = if ($config.asOf -is [datetime]) { $config.asOf.ToString('yyyy-MM-dd') } else { [string] $config.asOf }
    $asOf = [DateTimeOffset]::ParseExact($asOfText, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal)

    $checkOrder = if ($IncludeIdentityChecks) { @($script:CheckOrder) + $script:IdentityCheckOrder } else { @($script:CheckOrder) }
    $snapshot = Get-TbFixtureSnapshot $FixtureRoot $tenantInfo.FixtureDir
    $raw = @(
        Get-TbMfaFinding -Snapshot $snapshot -Config $config
        Get-TbStaleSignInFinding -Snapshot $snapshot -Config $config -AsOf $asOf
        Get-TbGlobalAdminFinding -Snapshot $snapshot -Config $config
        Get-TbLegacyAuthFinding -Snapshot $snapshot -Config $config -TenantName $tenantName
        Get-TbBreakGlassFinding -Snapshot $snapshot -Config $config -TenantName $tenantName
        Get-TbGuestAdminFinding -Snapshot $snapshot -Config $config
        if ($IncludeIdentityChecks) {
            Get-TbSsprFinding -Snapshot $snapshot -Config $config -TenantName $tenantName
            Get-TbBreakGlassSignInFinding -Snapshot $snapshot -Config $config -AsOf $asOf
        }
    )
    # Stable order and Ids: check order, then subject. Ids look like TB-MFA-01.
    $findings = foreach ($checkId in $checkOrder) {
        $n = 0
        foreach ($f in $raw | Where-Object CheckId -EQ $checkId | Sort-Object Subject, Title) {
            $n++; $f.Id = 'TB-{0}-{1:00}' -f $checkId, $n; $f
        }
    }
    $findings = @($findings)

    $byCheck = [ordered]@{}
    foreach ($checkId in $checkOrder) { $byCheck[$checkId] = @($findings | Where-Object CheckId -EQ $checkId).Count }
    $bySeverity = [ordered]@{}
    foreach ($level in 'High', 'Medium', 'Low') { $bySeverity[$level] = @($findings | Where-Object Severity -EQ $level).Count }
    $score = $snapshot.SecureScore
    $settings = [ordered]@{
        staleDays                 = [int] $config.staleDays
        maxGlobalAdmins           = [int] $config.maxGlobalAdmins
        breakGlassNamePrefix      = [string] $config.breakGlass.namePrefix
        breakGlassMinimumAccounts = [int] $config.breakGlass.minimumCompliantAccounts
    }
    $metrics = [ordered]@{
        checksRun          = $checkOrder.Count
        usersEvaluated     = @($snapshot.Users).Count
        enabledMemberUsers = @($snapshot.Users | Where-Object { $_.accountEnabled -and $_.userType -eq 'Member' }).Count
        globalAdminCount   = @(Get-TbGlobalAdminMember $snapshot $config).Count
        enabledCaPolicies  = @($snapshot.CaPolicies | Where-Object { $_.state -eq 'enabled' }).Count
        secureScore        = if ($null -ne $score) { [ordered]@{ currentScore = [double] $score.currentScore; maxScore = [double] $score.maxScore } } else { $null }
    }
    if ($IncludeIdentityChecks) {
        $cov = Get-TbSsprCoverage $snapshot $config
        $settings['ssprMinimumCoveragePercent'] = $cov.MinimumPercent
        $settings['breakGlassSignInWindowDays'] = Get-TbBreakGlassWindowDay $config
        $metrics['ssprEligibleUsers'] = $cov.Eligible
        $metrics['ssprRegisteredUsers'] = $cov.Registered
        $metrics['ssprCoveragePercent'] = $cov.Percent
    }
    $report = [ordered]@{
        schemaVersion     = 1
        tool              = 'TenantBaseline'
        tenant            = $tenantInfo.ClientId
        tenantDisplayName = $tenantName
        source            = 'fixture'
        sourceLabel       = $script:SourceLabel
        asOf              = $asOfText
        fixPolicy         = 'Suggested fixes are registry lever names proposed in dry-run only; nothing is changed.'
        settings          = $settings
        metrics           = $metrics
        conditionalAccess = @(Get-TbCaSnapshot $snapshot)
        counts            = [ordered]@{ total = $findings.Count; bySeverity = $bySeverity; byCheck = $byCheck }
        findings          = $findings
    }
    if ($null -ne $previous) { $report['drift'] = Get-TbDrift $previous $report }
    $report
}

function Invoke-TenantBaseline {
    <#
    .SYNOPSIS
    Runs the Microsoft 365 security baseline for one tenant and writes findings.json, findings.csv, report.html and summary.txt.
    .DESCRIPTION
    Read-only. Default data source is the fixture-based mock Graph adapter (synthetic data shaped like Microsoft Graph v1.0).
    Output is deterministic for a given fixture set and config (the as-of date is pinned in TenantBaseline.config.json).
    .EXAMPLE
    Invoke-TenantBaseline -Tenant contoso-dental -OutDir $env:TEMP\baseline-contoso
    #>
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory)] [ValidatePattern('^[a-z0-9][a-z0-9-]{0,31}$')] [string] $Tenant,
        [Parameter(Mandatory)] [string] $OutDir,
        [string] $FixtureRoot = $script:DefaultFixtureRoot,
        [string] $ConfigPath = $script:DefaultConfigPath,
        [switch] $UseGraph,
        [switch] $IncludeIdentityChecks,
        [string] $CompareTo
    )
    $report = Get-TenantBaselineReport -Tenant $Tenant -FixtureRoot $FixtureRoot -ConfigPath $ConfigPath -UseGraph:$UseGraph -IncludeIdentityChecks:$IncludeIdentityChecks -CompareTo $CompareTo
    $summary = Get-TbSummaryText $report
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $paths = [ordered]@{
        Json    = Join-Path $OutDir 'findings.json'
        Csv     = Join-Path $OutDir 'findings.csv'
        Html    = Join-Path $OutDir 'report.html'
        Summary = Join-Path $OutDir 'summary.txt'
    }
    if ($report.Contains('drift')) { $paths['Drift'] = Join-Path $OutDir 'drift.txt' }   # B-50: written only with -CompareTo
    Write-TbFile $paths.Json (($report | ConvertTo-Json -Depth 10) + "`n")
    # Flat, one row per finding, stable column order: loads straight into Power BI (Get data > Text/CSV).
    $columns = 'Tenant', 'TenantName', 'AsOf', 'Id', 'CheckId', 'Severity', 'Title', 'Subject', 'Evidence', 'FixLever', 'FixMode', 'FixTarget', 'Source'
    $csvRows = foreach ($f in $report.findings) {
        [pscustomobject][ordered]@{
            Tenant = $report.tenant; TenantName = $report.tenantDisplayName; AsOf = $report.asOf; Id = $f.Id; CheckId = $f.CheckId
            Severity = $f.Severity; Title = $f.Title; Subject = $f.Subject; Evidence = $f.Evidence; FixLever = $f.FixLever
            FixMode = $f.FixMode; FixTarget = $f.FixTarget; Source = $report.sourceLabel
        }
    }
    $csvLines = if ($csvRows) { $csvRows | ConvertTo-Csv -NoTypeInformation -UseQuotes AsNeeded } else { $columns -join ',' }
    Write-TbFile $paths.Csv ((@($csvLines) -join "`r`n") + "`r`n")
    Write-TbFile $paths.Html (Get-TbHtmlReport $report $summary)
    Write-TbFile $paths.Summary ($summary + "`n")
    if ($report.Contains('drift')) { Write-TbFile $paths.Drift (((Get-TbDriftLine $report.drift) -join "`n") + "`n") }
    [pscustomobject]@{
        Tenant   = $report.tenant
        Findings = $report.counts.total
        High     = $report.counts.bySeverity['High']
        Medium   = $report.counts.bySeverity['Medium']
        OutDir   = (Resolve-Path -LiteralPath $OutDir).Path
        Files    = @($paths.Values | ForEach-Object { Split-Path $_ -Leaf })
    }
}

Export-ModuleMember -Function Invoke-TenantBaseline, Get-TenantBaselineReport
