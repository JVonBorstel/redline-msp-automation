#requires -Version 7
<#
B-62 tests (specs/B-62.md: B62-1 to B62-4) for levers/powershell/DeviceOps. Plain PowerShell 7 (STD-PS-9 until Pester 5 is installed).
Run:  pwsh -NoProfile -File levers/powershell/DeviceOps/tests/DeviceOps.Tests.ps1
Exit code 0 = all pass, 1 = failures. Prints "DeviceOps tests: N passed, M failed".
Works on a private copy of the synthetic mock state under $env:TEMP (removed at the end). No network. The committed mock is only read.
#>
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$moduleDir = (Resolve-Path (Join-Path $here '..')).Path

if ($PSVersionTable.PSVersion -lt [version] '7.4') {
    Write-Host "DeviceOps tests: 0 passed, 0 failed (skipped: PowerShell $($PSVersionTable.PSVersion) is below 7.4, STD-PS-1)"
    exit 0
}

$script:pass = 0; $script:fail = 0
function Check([string] $Name, [bool] $Condition, [string] $Detail = '') {
    if ($Condition) { $script:pass++; Write-Host "PASS: $Name" } else { $script:fail++; Write-Host "FAIL: $Name $Detail" -ForegroundColor Red }
}
function Section([string] $t) { Write-Host "== $t" }

$tmp = Join-Path $env:TEMP "redline-deviceops-$PID"
New-Item -ItemType Directory -Force $tmp | Out-Null
foreach ($c in 'contoso-dental', 'fabrikam-capital') { Copy-Item -Recurse -LiteralPath (Join-Path $moduleDir "mock\$c") -Destination $tmp }
$env:REDLINE_MOCK_TENANT_DIR = $tmp
$ConfirmPreference = 'None'
Import-Module (Join-Path $moduleDir 'DeviceOps.psd1') -Force

$u = 'c0000000-0000-4000-8000-0000000d'
$d1 = "${u}0001"; $d2 = "${u}0002"; $d3 = "${u}0003"; $d4 = "${u}0004"; $d9 = "${u}0009"; $decoy = "${u}0900"
$f1 = 'f0000000-0000-4000-8000-0000000d0001'
$file = Join-Path $tmp 'contoso-dental\devices.json'
$original = [System.IO.File]::ReadAllBytes($file)
function Same([string] $Path, [byte[]] $Bytes) { [System.Linq.Enumerable]::SequenceEqual([byte[]][System.IO.File]::ReadAllBytes($Path), $Bytes) }
function Paths($r) { @($r.diff | ForEach-Object { $_.path.Substring($_.path.IndexOf('/', 9)) }) -join ',' }

try {
    Section 'B62-3 each function: -WhatIf returns the golden diff and writes nothing'
    $golden = [ordered]@{
        'Restart-DevicePrintSpooler'  = @{ Args = @{ Device = $d1 }; Paths = '/printQueue/stuckJobs,/services/Spooler/health' }
        'Repair-DeviceMappedDrive'    = @{ Args = @{ Device = $d1; Drive = 'S' }; Paths = '/mappedDrives/S/state' }
        'Reset-DeviceOutlookProfile'  = @{ Args = @{ Device = $d1; User = 'ana.lopez' }; Paths = '/outlookProfiles/ana.lopez/backup,/outlookProfiles/ana.lopez/state' }
        'Clear-DeviceTemp'            = @{ Args = @{ Device = $d1 }; Paths = '/tempBytes,/tempQuarantineBytes,/tempStaleBytes' }
        'Restart-DeviceService'       = @{ Args = @{ Device = $d1; Service = 'W32Time' }; Paths = '/services/W32Time/health' }
        'Restart-DeviceWorkstation'   = @{ Args = @{ Device = $d1 }; Paths = '/lastBoot,/pendingReboot' }
        'Restart-DeviceServer'        = @{ Args = @{ Device = $d3 }; Paths = '/lastBoot,/pendingReboot' }
    }
    foreach ($name in $golden.Keys) {
        $a = $golden[$name].Args
        $r = & $name @a -Client 'contoso-dental' -WhatIf
        Check "$name -WhatIf: golden diff paths" ((Paths $r) -ceq $golden[$name].Paths) (Paths $r)
        Check "$name -WhatIf: not applied, planned, file unchanged" ((-not $r.applied) -and $r.data.mode -ceq 'planned' -and (Same $file $original))
        Check "$name -WhatIf: names the script, the device, the steps, verification and a rollback proposal" (
            $r.data.script.id -match '^dev-' -and $r.data.device.hostname -and @($r.data.would_run).Count -ge 3 -and
            @($r.data.verification.checks).Count -ge 1 -and $r.data.rollback.automated -eq $false -and @($r.data.rollback.proposal).Count -ge 1)
        Check "$name -WhatIf: a 24-hex plan digest" ($r.data.plan_digest -match '^[0-9a-f]{24}$')
    }

    Section 'B62-3 execute applies the same diff, verifies, and a second run is empty'
    foreach ($name in $golden.Keys) {
        $a = $golden[$name].Args
        $dry = & $name @a -Client 'contoso-dental' -WhatIf
        $done = & $name @a -Client 'contoso-dental'
        Check "$name execute: applied, same diff as the dry-run" ($done.applied -and ((Paths $done) -ceq (Paths $dry)) -and (($done.diff | ConvertTo-Json -Depth 5 -Compress) -ceq ($dry.diff | ConvertTo-Json -Depth 5 -Compress)))
        Check "$name execute: verification passed" ($done.data.mode -ceq 'executed' -and $done.data.verification.status -ceq 'passed')
        $again = & $name @a -Client 'contoso-dental'
        Check "$name again: empty diff, not applied" ((@($again.diff).Count -eq 0) -and (-not $again.applied))
    }
    Check 'the files differ from the original after the executes' (-not (Same $file $original))
    $state = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
    $dev1 = $state.devices | Where-Object { $_.uid -eq $d1 }
    Check 'golden state: spooler, queue, drive, profile, temp, service, boot' (
        $dev1.services.Spooler.health -ceq 'Ok' -and $dev1.printQueue.stuckJobs -eq 0 -and $dev1.mappedDrives.S.state -ceq 'Connected' -and
        $dev1.outlookProfiles.'ana.lopez'.state -ceq 'Reset' -and $dev1.outlookProfiles.'ana.lopez'.backup -ceq 'Outlook-ana.lopez.bak-20261022' -and
        $dev1.tempBytes -eq 700000000 -and $dev1.tempQuarantineBytes -eq 4100000000 -and $dev1.services.W32Time.health -ceq 'Ok' -and
        $dev1.lastBoot.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'") -ceq '2026-10-22T12:00:00Z' -and $dev1.pendingReboot -eq $false)
    Check 'a device that was not named is untouched' ((($state.devices | Where-Object { $_.uid -eq $d9 }).services.wuauserv.health) -ceq 'Hung')

    Section 'refusals are returned as { refusal }, never a throw, and change nothing'
    $before = [System.IO.File]::ReadAllBytes($file)
    $cases = [ordered]@{
        'unknown device'            = { Restart-DevicePrintSpooler -Device "${u}0777" -Client 'contoso-dental' -WhatIf }
        'another clients device'    = { Restart-DevicePrintSpooler -Device $f1 -Client 'contoso-dental' -WhatIf }
        'the planted decoy'         = { Restart-DevicePrintSpooler -Device $decoy -Client 'contoso-dental' -WhatIf }
        'an offline device'         = { Restart-DevicePrintSpooler -Device $d4 -Client 'contoso-dental' -WhatIf }
        'a server to the reboot'    = { Restart-DeviceWorkstation -Device $d3 -Client 'contoso-dental' -WhatIf }
        'a workstation to the server reboot' = { Restart-DeviceServer -Device $d1 -Client 'contoso-dental' -WhatIf }
        'a drive that is not there' = { Repair-DeviceMappedDrive -Device $d1 -Drive 'Z' -Client 'contoso-dental' -WhatIf }
        'a profile that is not there' = { Reset-DeviceOutlookProfile -Device $d1 -User 'nobody.here' -Client 'contoso-dental' -WhatIf }
        'a service the device lacks' = { Restart-DeviceService -Device $d2 -Service 'wuauserv' -Client 'contoso-dental' -WhatIf }
    }
    $sentences = @{}
    foreach ($k in $cases.Keys) {
        $r = & $cases[$k]
        $sentences[$k] = [string] $r.refusal
        Check "refusal: $k" ($r.refusal -is [string] -and $r.refusal.Length -gt 10 -and $r.refusal -match 'nothing was changed')
    }
    Check 'another client, the decoy and an unknown uid answer with one and the same sentence' (
        $sentences['unknown device'] -ceq $sentences['another clients device'] -and $sentences['unknown device'] -ceq $sentences['the planted decoy'])
    Check 'the file is byte-identical after the refusals' (Same $file $before)
    $bad = $null; try { Restart-DevicePrintSpooler -Device 'not-a-uid' -Client 'contoso-dental' -WhatIf | Out-Null } catch { $bad = $_.Exception.GetType().Name }
    Check 'a device value that is not a uid is rejected at binding' ($null -ne $bad)
    $slug = $null; try { Restart-DevicePrintSpooler -Device $d1 -Client '..\x' -WhatIf | Out-Null } catch { $slug = $_.Exception.Message }
    Check 'a client id that is not a slug never becomes a path' ($slug -match 'not a valid slug')

    Section 'B62-3 verification: a mock device that fails a script is an error after the change'
    $f = Restart-DevicePrintSpooler -Device "${u}0006" -Client 'contoso-dental'
    Check 'faulted spooler returns Verification failed with the rollback line' ($f.refusal -match '^Verification failed' -and $f.refusal -match 'rollback:')
    $f2 = Restart-DeviceWorkstation -Device "${u}0006" -Client 'contoso-dental'
    Check 'faulted reboot returns Verification failed' ($f2.refusal -match '^Verification failed')

    Section 'B62-1 the vetted list: a changed step stops every script'
    $copy = Join-Path $tmp 'module-copy'
    New-Item -ItemType Directory -Force $copy | Out-Null
    Copy-Item -LiteralPath (Join-Path $moduleDir 'DeviceOps.psd1'), (Join-Path $moduleDir 'DeviceOps.psm1'), (Join-Path $moduleDir 'vetted-scripts.json') -Destination $copy
    $path = Join-Path $copy 'vetted-scripts.json'
    $text = Get-Content -LiteralPath $path -Raw
    Set-Content -LiteralPath $path -Value $text.Replace('Restart the named service', 'Restart the named service and anything else') -NoNewline
    Import-Module (Join-Path $copy 'DeviceOps.psd1') -Force
    $t1 = Restart-DevicePrintSpooler -Device $d2 -Client 'contoso-dental' -WhatIf
    $t2 = Clear-DeviceTemp -Device $d1 -Client 'contoso-dental' -WhatIf
    Check 'with a tampered catalog even an untouched script refuses' ($t1.refusal -match 'vetted' -and $t2.refusal -match 'vetted')
    Import-Module (Join-Path $moduleDir 'DeviceOps.psd1') -Force

    Section 'B62-4 the remote-support session link'
    $s = Restart-DevicePrintSpooler -Device $d2 -Client 'contoso-dental' -WhatIf
    Check 'a device with no session has remote_session null' ($null -eq $s.data.remote_session)
    $s1 = Restart-DeviceServer -Device $d3 -Client 'contoso-dental' -WhatIf
    Check 'the server links its latest session' ($s1.data.remote_session.session_id -ceq 'SESS-C-0001')
    $s2 = Restart-DevicePrintSpooler -Device $f1 -Client 'fabrikam-capital' -WhatIf
    Check 'another client has its own session log' ($s2.data.remote_session.session_id -ceq 'SESS-F-0001')
    $early = Restart-DeviceService -Device $d1 -Service 'Dnscache' -Client 'contoso-dental' -AsOf '2026-10-15T00:00:00Z' -WhatIf
    Check 'with an earlier -AsOf the later sessions are not linked' ($early.data.remote_session.session_id -ceq 'SESS-C-0002')

    Section 'no time logic and no clock: -AsOf decides'
    $boot = Restart-DeviceWorkstation -Device $d9 -Client 'contoso-dental' -AsOf '2027-01-02T03:04:05Z' -WhatIf
    Check '-AsOf sets the boot time that would be written' (($boot.diff | Where-Object { $_.path -like '*/lastBoot' }).after -ceq '2027-01-02T03:04:05Z')
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "DeviceOps tests: $($script:pass) passed, $($script:fail) failed"
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
