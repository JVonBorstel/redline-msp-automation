#requires -Version 7
<#
B-65 tests (specs/B-65.md: B65-1 to B65-3) for levers/powershell/DeviceR3. Plain PowerShell 7 (STD-PS-9 until Pester 5 is installed).
Run:  pwsh -NoProfile -File levers/powershell/DeviceR3/tests/DeviceR3.Tests.ps1
Exit code 0 = all pass, 1 = failures. Prints "DeviceR3 tests: N passed, M failed".
Works on a private copy of the synthetic fixtures under $env:TEMP (removed at the end). No network. The committed fixtures are only read.
#>
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$moduleDir = (Resolve-Path (Join-Path $here '..')).Path
$repo = (Resolve-Path (Join-Path $moduleDir '..\..\..')).Path

if ($PSVersionTable.PSVersion -lt [version] '7.4') {
    Write-Host "DeviceR3 tests: 0 passed, 0 failed (skipped: PowerShell $($PSVersionTable.PSVersion) is below 7.4, STD-PS-1)"
    exit 0
}

$script:pass = 0; $script:fail = 0
function Check([string] $Name, [bool] $Condition, [string] $Detail = '') {
    if ($Condition) { $script:pass++; Write-Host "PASS: $Name" } else { $script:fail++; Write-Host "FAIL: $Name $Detail" -ForegroundColor Red }
}
function Section([string] $t) { Write-Host "== $t" }
function Get-Refusal([scriptblock] $Block) {
    try { & $Block | Out-Null; $null } catch { $_.Exception }
}

$tmp = Join-Path $env:TEMP "redline-devicer3-$PID"
New-Item -ItemType Directory -Force $tmp | Out-Null
foreach ($c in 'contoso-dental', 'fabrikam-capital') { Copy-Item -Recurse -LiteralPath (Join-Path $repo "fixtures\tenant\$c") -Destination $tmp }
$env:REDLINE_MOCK_TENANT_DIR = $tmp
$ConfirmPreference = 'None'
Import-Module (Join-Path $moduleDir 'DeviceR3.psd1') -Force

$d = 'contosodental.example'
$front = 'c0000000-0000-4000-8000-0000000d0001'; $frontOwner = "ana.lopez@$d"
$office = 'c0000000-0000-4000-8000-0000000d0006'; $officeOwner = "lena.fischer@$d"
$hygOld = 'c0000000-0000-4000-8000-0000000d0007'; $hygHold = 'c0000000-0000-4000-8000-0000000d0008'; $tom = "tom.baker@$d"
$fab = 'f0000000-0000-4000-8000-0000000d0001'; $fabOwner = 'morgan.reyes@fabrikamcapital.example'
$file = Join-Path $tmp 'contoso-dental\devices.json'
$original = [System.IO.File]::ReadAllBytes($file)
function Same([string] $Path, [byte[]] $Bytes) { [System.Linq.Enumerable]::SequenceEqual([byte[]][System.IO.File]::ReadAllBytes($Path), $Bytes) }

try {
    Section 'B65-1 every function: -WhatIf returns one diff and writes nothing'
    $calls = [ordered]@{
        'Lock-ManagedDevice'    = $true
        'Block-DeviceNetwork'   = $true
        'Remove-ManagedDevice'  = $true
        'Clear-ManagedDevice'   = $true
    }
    foreach ($name in $calls.Keys) {
        $r = & $name -Device $office -Upn $officeOwner -Client 'contoso-dental' -WhatIf
        Check "$name -WhatIf: one change, not applied" ((@($r.diff).Count -eq 1) -and (-not $r.applied))
        Check "$name -WhatIf: file unchanged" (Same $file $original)
        Check "$name diff: replace with a /devices/<uid>/... path" (($r.diff[0].op -eq 'replace') -and $r.diff[0].path.StartsWith("/devices/$office/"))
        Check "$name data: one device, one user, an undo line" (($r.data.blast_radius.devices_affected -eq 1) -and ($r.data.blast_radius.users_affected -eq 1) -and ($r.data.undo -match '^(undo: device\.\w+|no undo)$'))
    }
    foreach ($name in 'Unlock-ManagedDevice', 'Unblock-DeviceNetwork') {
        $r = & $name -Device $office -Upn $officeOwner -Client 'contoso-dental' -WhatIf
        Check "$name -WhatIf on a device that is not locked or isolated: empty diff" ((@($r.diff).Count -eq 0) -and (-not $r.applied))
    }

    Section 'B65-1 blast radius'
    $r = Lock-ManagedDevice -Device $front -Upn $frontOwner -Client 'contoso-dental' -WhatIf
    $b = $r.data.blast_radius
    Check 'front desk: only device for its role, noted' ($b.only_device_for_role -and ($b.notes -match 'only front-desk device').Count -eq 1)
    Check 'front desk: 1 of 6 devices is 17 percent' (($b.client_device_count -eq 6) -and ($b.share_of_client_devices_percent -eq 17))
    $r = Lock-ManagedDevice -Device $hygOld -Upn $tom -Client 'contoso-dental' -WhatIf
    Check 'offline device: noted that it applies at the next check-in' (($r.data.blast_radius.online -eq $false) -and (($r.data.blast_radius.notes -match 'next check-in').Count -eq 1))
    $r = Lock-ManagedDevice -Device $hygHold -Upn $tom -Client 'contoso-dental' -WhatIf
    Check 'legal hold is shown on a lock dry-run' (($r.data.blast_radius.legal_hold -eq $true) -and (($r.data.blast_radius.notes -match 'legal hold').Count -eq 1))

    Section 'B65-1 execute, convergence, undo restores the bytes'
    $r1 = Lock-ManagedDevice -Device $office -Upn $officeOwner -Client 'contoso-dental'
    Check 'lock applies once' ($r1.applied -and @($r1.diff).Count -eq 1 -and $r1.diff[0].after -eq 'locked')
    $r2 = Lock-ManagedDevice -Device $office -Upn $officeOwner -Client 'contoso-dental'
    Check 'lock again is an empty diff' ((-not $r2.applied) -and @($r2.diff).Count -eq 0)
    $r3 = Unlock-ManagedDevice -Device $office -Upn $officeOwner -Client 'contoso-dental'
    Check 'unlock undoes it' ($r3.applied -and $r3.diff[0].before -eq 'locked')
    $r4 = Block-DeviceNetwork -Device $office -Upn $officeOwner -Client 'contoso-dental'
    $r5 = Unblock-DeviceNetwork -Device $office -Upn $officeOwner -Client 'contoso-dental'
    Check 'isolate then release' ($r4.applied -and $r5.applied)
    $afterRoundTrip = [System.IO.File]::ReadAllBytes($file)
    Lock-ManagedDevice -Device $office -Upn $officeOwner -Client 'contoso-dental' | Out-Null
    Unlock-ManagedDevice -Device $office -Upn $officeOwner -Client 'contoso-dental' | Out-Null
    Check 'a second round trip gives the same bytes' (Same $file $afterRoundTrip)

    Section 'B65-1 one answer for absent, other-client and wrong-owner'
    $absent = Get-Refusal { Lock-ManagedDevice -Device 'c0000000-0000-4000-8000-0000000d0999' -Upn $frontOwner -Client 'contoso-dental' }
    $other = Get-Refusal { Lock-ManagedDevice -Device $fab -Upn $fabOwner -Client 'contoso-dental' }
    $wrong = Get-Refusal { Lock-ManagedDevice -Device $front -Upn $officeOwner -Client 'contoso-dental' }
    Check 'absent device: KeyNotFoundException' ($absent -is [System.Collections.Generic.KeyNotFoundException])
    Check 'other-client device and wrong owner give the same message' (($other.Message -eq $absent.Message) -and ($wrong.Message -eq $absent.Message))
    Check 'the message names neither the other client nor its people' ($other.Message -notmatch 'fabrikam|morgan')
    $bad = Get-Refusal { Lock-ManagedDevice -Device $front -Upn $frontOwner -Client '..\fabrikam-capital' }
    Check 'a client id that is not a slug is refused before any file is read' ($null -ne $bad -and $bad.Message -match 'not a valid slug')

    Section 'B65-3 wipe is a request, and there is no way back'
    $w = Clear-ManagedDevice -Device $office -Upn $officeOwner -Client 'contoso-dental' -WhatIf
    Check 'wipe dry-run: none to requested' ($w.diff[0].before -eq 'none' -and $w.diff[0].after -eq 'requested' -and $w.data.undo -eq 'no undo')
    Check 'wipe next step is a person in the console' (($w.data.next_step -match 'person') -and ($w.data.next_step -match 'console'))
    $w1 = Clear-ManagedDevice -Device $office -Upn $officeOwner -Client 'contoso-dental'
    $w2 = Clear-ManagedDevice -Device $office -Upn $officeOwner -Client 'contoso-dental'
    Check 'wipe applies once and then converges' ($w1.applied -and (-not $w2.applied) -and @($w2.diff).Count -eq 0)
    $json = Get-Content -Raw -LiteralPath $file | ConvertFrom-Json
    $row = $json.devices | Where-Object { $_.uid -eq $office }
    Check 'the stored state never goes past requested' ($row.wipe.state -eq 'requested')
    $exported = (Get-Module DeviceR3).ExportedFunctions.Keys
    Check 'no exported function undoes a wipe or a retire' (-not ($exported | Where-Object { $_ -match 'Restore|Undo|Reset|Reenroll' }))
    Check 'six functions are exported' ($exported.Count -eq 6)

    Section 'legal hold and retired devices'
    foreach ($fn in 'Clear-ManagedDevice', 'Remove-ManagedDevice') {
        $held = Get-Refusal { & $fn -Device $hygHold -Upn $tom -Client 'contoso-dental' }
        Check "$fn on a device under legal hold: InvalidOperationException" ($held -is [System.InvalidOperationException])
        $heldDry = Get-Refusal { & $fn -Device $hygHold -Upn $tom -Client 'contoso-dental' -WhatIf }
        Check "$fn -WhatIf on a device under legal hold is refused too" ($heldDry -is [System.InvalidOperationException])
    }
    Remove-ManagedDevice -Device $front -Upn $frontOwner -Client 'contoso-dental' | Out-Null
    $again = Remove-ManagedDevice -Device $front -Upn $frontOwner -Client 'contoso-dental'
    Check 'retire twice is an empty diff' ((-not $again.applied) -and @($again.diff).Count -eq 0)
    foreach ($fn in 'Lock-ManagedDevice', 'Block-DeviceNetwork', 'Clear-ManagedDevice') {
        $gone = Get-Refusal { & $fn -Device $front -Upn $frontOwner -Client 'contoso-dental' }
        Check "$fn on a retired device: NotSupportedException" ($gone -is [System.NotSupportedException])
    }

    Section 'per client'
    $fabFile = Join-Path $tmp 'fabrikam-capital\devices.json'
    $fabBefore = [System.IO.File]::ReadAllBytes($fabFile)
    $contosoNow = [System.IO.File]::ReadAllBytes($file)
    Lock-ManagedDevice -Device $fab -Upn $fabOwner -Client 'fabrikam-capital' | Out-Null
    Check 'a Fabrikam lock changes Fabrikam only' ((-not (Same $fabFile $fabBefore)) -and (Same $file $contosoNow))
    $noState = Get-Refusal { Lock-ManagedDevice -Device $fab -Upn $fabOwner -Client 'litware-legal' }
    Check 'a client with no device state is refused' ($null -ne $noState)
}
finally {
    Remove-Item -Recurse -Force -LiteralPath $tmp -ErrorAction SilentlyContinue
}

Write-Host "DeviceR3 tests: $($script:pass) passed, $($script:fail) failed"
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
