# Privacy scan for the built site (site/dist) or any folder. Read-only. Never prints a matched value:
# each hit is reported as class, file and line only.
#
#   pwsh -NoProfile -File privacy-scan.ps1 -Root ../dist -AllowConfig ../site.config.json    # text report, exit 1 on any hit
#   pwsh -NoProfile -File privacy-scan.ps1 -Root ../dist -AllowConfig ../site.config.json -Json
#   pwsh -NoProfile -File privacy-scan.ps1 -SelfTest -AllowConfig ../site.config.json        # plants every class; all must be caught
#
# FAIL classes (must be 0 to publish):
#   local-path     a Windows or macOS user home folder path, or the profile variable
#   ts.net         a tailnet host name
#   private-ip     an address in a private range
#   email          any email not on a reserved test domain (.example, .test, .invalid, localhost)
#   secret:<shape> token and secret shapes (cloud keys, personal access tokens, private key headers, JWTs)
#   project-name   the name of a company this repository is not about and must never mention (the term is stored encoded)
#   job-words      words that belong to a job search, not to this project (stored encoded)
#   owner-name     the owner's name as written in site.config.json (author_line). Exempt ONLY where -AllowConfig lists the
#                  exact author_line and contact_url strings: they are removed from a line before it is checked
# INFO (counted, not a failure): hex64 (the audit chain's SHA-256 hashes are 64-hex by design).
param([string]$Root, [switch]$Json, [switch]$SelfTest, [string]$AllowConfig = '')
$ErrorActionPreference = 'Stop'

function Decode([string]$b64) { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64)) }

$cfgPath = if ($AllowConfig) { $AllowConfig } else { Join-Path $PSScriptRoot '..' 'site.config.json' }
$cfg = if (Test-Path -LiteralPath $cfgPath) { Get-Content -LiteralPath $cfgPath -Raw | ConvertFrom-Json } else { $null }
$allow = @()
if ($AllowConfig -and $cfg) {
    $allow = @($cfg.author_line, $cfg.contact_url) | Where-Object { $_ -and "$_".Length -ge 8 } | Sort-Object Length -Descending
}
# the owner's name: the author_line without its leading "Built by"; checked everywhere except where allowed
$ownerName = ''
if ($cfg -and $cfg.author_line) { $ownerName = ("$($cfg.author_line)" -replace '^(?i)\s*built by\s+', '').Trim() }
$problems = [Collections.Generic.List[string]]::new()

$emailOk = '(?i)(@example\.[a-z.]+$|\.example$|\.test$|\.invalid$|@localhost$|@(contosodental|fabrikamcapital|litwarelegal)\.onmicrosoft\.com$)'
$pat = [ordered]@{
    # a Windows or macOS home folder; lowercase /users/<id> is a Microsoft Graph path in the synthetic diffs, not a home folder
    'local-path'   = '(?i)([a-z]:\\\\?users\\\\?|(?-i:/Users/)|%userprofile%)'
    'ts.net'       = '[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net'
    'private-ip'   = '\b(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b'
    'project-name' = (Decode 'KD9pKWdvID93ZXN0')
    'job-words'    = (Decode 'KD9pKVxiKHNhbGFyeXxjb21wZW5zYXRpb258cmVjcnVpdGVyfGludGVydmlld2VyfG9mZmVyIGxldHRlcnxoaXJpbmcgbWFuYWdlcilcYg==')
}
$secret = [ordered]@{
    'github-token' = 'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}'
    'cloud-key'    = 'AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|AccountKey=[A-Za-z0-9+/=]{20,}'
    'api-key'      = '\bsk-[A-Za-z0-9_-]{24,}|xox[baprs]-[A-Za-z0-9-]{10,}'
    'private-key'  = 'BEGIN ([A-Z]+ )?PRIVATE KEY'
    'jwt'          = 'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}'
}
$bin = '\.(woff2?|png|jpe?g|gif|ico|webp|pdf|zip)$'

function Invoke-Scan([string]$ScanRoot) {
    $hits = [Collections.Generic.List[object]]::new()
    $hex = 0
    # .git is skipped (compressed objects); commit metadata is checked by the export tooling
    $files = @(Get-ChildItem $ScanRoot -Recurse -File -Force | Where-Object { $_.Name -notmatch $bin -and $_.FullName -notmatch '[\\/]\.git[\\/]' })
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($ScanRoot.TrimEnd('\', '/').Length + 1)
        $lines = [IO.File]::ReadAllLines($f.FullName)
        for ($i = 0; $i -lt $lines.Count; $i++) {
            $L = $lines[$i]; $n = $i + 1
            foreach ($a in $allow) { $L = $L.Replace($a, '') }   # only the exact configured byline strings
            $found = [Collections.Generic.List[string]]::new()
            foreach ($k in $pat.Keys) { if ($L -match $pat[$k]) { $found.Add($k) } }
            foreach ($k in $secret.Keys) { if ($L -match $secret[$k]) { $found.Add("secret:$k") } }
            foreach ($m in [regex]::Matches($L, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')) { if ($m.Value -notmatch $emailOk) { $found.Add('email') } }
            $hex += [regex]::Matches($L, '\b[0-9a-f]{64}\b').Count
            if ($ownerName -and $L.IndexOf($ownerName, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $found.Add('owner-name') }
            foreach ($c in $found) { $hits.Add([ordered]@{ class = $c; file = $rel; line = $n }) }
        }
    }
    [pscustomobject]@{ files = $files.Count; hits = $hits; hex64 = $hex }
}

if ($SelfTest) {
    # Negative control: plant one value of every class in a temp folder, scan it, and require every class to be caught.
    # The planted folder is deleted at once; no value is printed, only class names and caught or missed.
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("pscan-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory $tmp | Out-Null
    $expect = [ordered]@{}
    if ($ownerName) { $expect['owner-name'] = "by $ownerName" }
    $expect['local-path'] = 'C:\Users\someone\Documents\thing'
    $expect['project-name'] = (Decode 'YnVpbHQgZm9yIEdvIFdlc3Q=')
    $expect['job-words'] = (Decode 'YXNrIHRoZSByZWNydWl0ZXI=')
    $expect['email'] = 'someone@realcompany.com'
    $expect['private-ip'] = 'host 192.168.4.20'
    $expect['ts.net'] = 'host.tail1234.ts.net'
    $expect['secret:github-token'] = 'ghp_' + ('A1b2C3d4E5' * 4)
    $expect['secret:private-key'] = '-----BEGIN RSA PRIVATE ' + 'KEY-----'
    $i = 0; foreach ($k in $expect.Keys) { $i++; [IO.File]::WriteAllText((Join-Path $tmp "plant$i.txt"), $expect[$k]) }
    # with -AllowConfig: the exact byline must pass, and must not hide anything else on the same line
    if ($allow) {
        [IO.File]::WriteAllText((Join-Path $tmp 'allowed-byline.txt'), "<p><a href=`"$($cfg.contact_url)`" rel=`"author`">$($cfg.author_line)</a></p>")
        [IO.File]::WriteAllText((Join-Path $tmp 'byline-plus.txt'), "$($cfg.author_line) " + (Decode 'YXNrIHRoZSByZWNydWl0ZXI='))
    }
    try { $r = Invoke-Scan $tmp } finally { [IO.Directory]::Delete($tmp, $true) }
    $caught = @($r.hits | Where-Object { $_.file -like 'plant*' } | ForEach-Object { $_.class }) | Sort-Object -Unique
    $missed = @($expect.Keys | Where-Object { $_ -notin $caught })
    if ($allow) {
        if (@($r.hits | Where-Object file -EQ 'allowed-byline.txt').Count) { $missed += 'allowed byline was flagged' }
        if (-not @($r.hits | Where-Object { $_.file -eq 'byline-plus.txt' -and $_.class -eq 'job-words' }).Count) { $missed += 'byline hid the rest of its line' }
    }
    $report = [ordered]@{ planted = $expect.Count; caught = $expect.Count - @($missed | Where-Object { $_ -in $expect.Keys }).Count; missed = $missed
        allow_checked = [bool]$allow; problems = @($problems) }
    if ($Json) { ConvertTo-Json $report -Compress } else { "self-test: planted $($expect.Count) classes, caught $($report.caught)"; $missed | ForEach-Object { "MISSED: $_" } }
    if ($missed.Count -or $problems.Count) { exit 1 } else { exit 0 }
}

if (-not $Root) { throw '-Root is required (or use -SelfTest)' }
$Root = (Resolve-Path -LiteralPath $Root).Path
$r = Invoke-Scan $Root
$hits = $r.hits
$byClass = [ordered]@{}; foreach ($h in $hits) { $byClass[$h.class] = 1 + [int]$byClass[$h.class] }
$result = [ordered]@{ root_files = $r.files; owner_name_checked = [bool]$ownerName; allowed_strings = @($allow).Count
    problems = @($problems); hits = $hits.Count; by_class = $byClass; hit_list = @($hits); info = [ordered]@{ hex64 = $r.hex64 } }
if ($Json) { ConvertTo-Json -InputObject $result -Depth 5 -Compress }
else {
    "files scanned: $($r.files); owner name checked: $([bool]$ownerName)"
    if ($problems.Count) { $problems | ForEach-Object { "PROBLEM: $_" } }
    "info (not failures): hex64=$($r.hex64) (audit-chain SHA-256 hashes)"
    if (-not $hits.Count) { 'NO HITS' } else { $hits | ForEach-Object { "$($_.class)  $($_.file):$($_.line)" } }
}
if ($hits.Count -or $problems.Count) { exit 1 } else { exit 0 }
