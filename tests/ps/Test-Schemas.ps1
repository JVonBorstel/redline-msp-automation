#requires -Version 7
<#
B-13 schema tests (specs/B-13.md: B13-1, B13-3) for schemas/. Plain PowerShell 7 (STD-PS-9 until Pester 5 is installed).
Run from anywhere:  pwsh -NoProfile -File tests/ps/Test-Schemas.ps1
Exit code 0 = all pass (or skipped), 1 = failures. Prints "Schemas tests: N passed, M failed".
Needs PowerShell 7.4+ (Test-Json with JsonSchema.Net, STD-XL-3); on an older host it prints the summary as skipped.
Reads only. Writes nothing. No network: every schema and document is a local file or an inline string.
#>
param([string] $SchemaDir)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $SchemaDir) { $SchemaDir = Join-Path $repo 'schemas' }
$exampleDir = Join-Path $SchemaDir 'examples'
$draft = 'https://json-schema.org/draft/2020-12/schema'
$expectedNames = 'audit-record', 'change', 'client', 'finding', 'identities', 'lever-registry', 'lever-request', 'lever-result', 'proposal'

if ($PSVersionTable.PSVersion -lt [version] '7.4') {
    Write-Host "Schemas tests: 0 passed, 0 failed (skipped: PowerShell $($PSVersionTable.PSVersion) is below 7.4, STD-XL-3)"
    exit 0
}

$script:pass = 0; $script:fail = 0
function Check([string] $Name, [bool] $Condition, [string] $Detail = '') {
    if ($Condition) { $script:pass++; Write-Host "PASS: $Name" } else { $script:fail++; Write-Host "FAIL: $Name $Detail" -ForegroundColor Red }
}
function Section([string] $t) { Write-Host "== $t" }

# Validates one JSON text against a schema file. Returns @{ Ok; Errors }; never throws on a validation failure.
function Test-Doc([string] $Json, [string] $SchemaFile) {
    $errs = $null
    $ok = Test-Json -Json $Json -SchemaFile $SchemaFile -ErrorAction SilentlyContinue -ErrorVariable errs
    [pscustomobject]@{ Ok = [bool] $ok; Errors = (@($errs) | ForEach-Object { $_.Exception.Message }) -join ' | ' }
}
function Test-InlineSchema([string] $Schema, [string] $Json) {
    $errs = $null
    [bool] (Test-Json -Json $Json -Schema $Schema -ErrorAction SilentlyContinue -ErrorVariable errs)
}

# Keywords that only annotate (never reject a document), and keywords whose value is a map of subschemas.
$annotationKeywords = '$schema', '$id', '$comment', '$defs', 'title', 'description', 'default', 'examples'
$schemaMapKeywords = 'properties', '$defs', 'patternProperties', 'dependentSchemas'
$schemaKeywords = 'items', 'additionalProperties', 'propertyNames', 'not', 'if', 'then', 'else', 'contains', 'unevaluatedProperties'
$schemaListKeywords = 'anyOf', 'oneOf', 'allOf', 'prefixItems'

# Every keyword used anywhere in one schema document (walks subschemas only, never enum/const/default values).
function Get-Keyword($Node, [Collections.Generic.HashSet[string]] $Into) {
    if ($Node -isnot [Collections.IDictionary]) { return }
    foreach ($key in $Node.Keys) {
        [void] $Into.Add($key)
        $value = $Node[$key]
        if ($key -in $schemaMapKeywords) { foreach ($sub in $value.Values) { Get-Keyword $sub $Into } }
        elseif ($key -in $schemaKeywords) { Get-Keyword $value $Into }
        elseif ($key -in $schemaListKeywords) { foreach ($sub in $value) { Get-Keyword $sub $Into } }
    }
}

# One probe per validation keyword: a schema that uses only that keyword, a document it must accept and one it must reject.
$probes = [ordered]@{
    'type'                 = '{"type":"string"}', '"a"', '1'
    'properties'           = '{"properties":{"a":{"type":"string"}}}', '{"a":"x"}', '{"a":1}'
    'required'             = '{"required":["a"]}', '{"a":1}', '{}'
    'additionalProperties' = '{"properties":{"a":{}},"additionalProperties":false}', '{"a":1}', '{"a":1,"b":2}'
    'pattern'              = '{"pattern":"^[a-z]+$"}', '"abc"', '"ab1"'
    'enum'                 = '{"enum":["x","y"]}', '"x"', '"z"'
    'const'                = '{"const":1}', '1', '2'
    'minLength'            = '{"minLength":2}', '"ab"', '"a"'
    'maxLength'            = '{"maxLength":2}', '"ab"', '"abc"'
    'minimum'              = '{"minimum":1}', '1', '0'
    'maximum'              = '{"maximum":1}', '1', '2'
    'exclusiveMinimum'     = '{"exclusiveMinimum":0}', '0.5', '0'
    'items'                = '{"items":{"type":"integer"}}', '[1,2]', '[1,"a"]'
    'minItems'             = '{"minItems":1}', '[1]', '[]'
    'uniqueItems'          = '{"uniqueItems":true}', '[1,2]', '[1,1]'
    'minProperties'        = '{"minProperties":1}', '{"a":1}', '{}'
    'propertyNames'        = '{"propertyNames":{"pattern":"^[a-z]+$"}}', '{"ab":1}', '{"A":1}'
    'anyOf'                = '{"anyOf":[{"type":"string"},{"type":"integer"}]}', '1', 'true'
    'oneOf'                = '{"oneOf":[{"minimum":1},{"maximum":5}]}', '9', '3'
    'allOf'                = '{"allOf":[{"minimum":1},{"maximum":5}]}', '3', '9'
    '$ref'                 = '{"$defs":{"S":{"pattern":"^a+$"}},"$ref":"#/$defs/S"}', '"aa"', '"b"'
    'if'                   = '{"if":{"const":""},"then":{"type":"string"},"else":{"type":"integer"}}', '""', '"x"'
    'then'                 = '{"if":{"type":"integer"},"then":{"minimum":5}}', '6', '4'
    'else'                 = '{"if":{"type":"integer"},"else":{"maxLength":1}}', '"a"', '"ab"'
    'null type'            = '{"anyOf":[{"type":"string"},{"type":"null"}]}', 'null', '1'
}

try {
    Section 'B13-1 the folder holds the nine schemas, each draft 2020-12, each with good and bad examples'
    $files = @(Get-ChildItem -LiteralPath $SchemaDir -Filter '*.schema.json' -File | ForEach-Object { $_.Name -replace '\.schema\.json$', '' } | Sort-Object)
    Check 'B13-1 schemas/ holds exactly the nine schemas' ((($files) -join ',') -eq (($expectedNames | Sort-Object) -join ',')) "(got: $($files -join ', '))"
    $parsed = @{}
    foreach ($name in $expectedNames) {
        $path = Join-Path $SchemaDir "$name.schema.json"
        if (-not (Test-Path -LiteralPath $path)) { Check "B13-1 $name schema exists" $false; continue }
        $doc = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
        $parsed[$name] = $doc
        Check "B13-1 $name declares draft 2020-12" ($doc['$schema'] -eq $draft) "(got: $($doc['$schema']))"
        Check "B13-1 $name has an `$id and a `$comment" ([bool] $doc['$id'] -and [bool] $doc['$comment'])
        $good = @(Get-ChildItem -LiteralPath $exampleDir -Filter "$name.good*.json" -File)
        $bad = @(Get-ChildItem -LiteralPath $exampleDir -Filter "$name.bad-*.json" -File)
        Check "B13-1 $name has at least one good and one bad example" ($good.Count -ge 1 -and $bad.Count -ge 1) "(good $($good.Count), bad $($bad.Count))"
    }
    $orphans = @(Get-ChildItem -LiteralPath $exampleDir -Filter '*.json' -File | Where-Object { ($_.Name -split '\.')[0] -notin $expectedNames })
    Check 'B13-1 every example names a known schema' ($orphans.Count -eq 0) "(orphans: $(@($orphans | ForEach-Object Name) -join ', '))"

    Section 'B13-3 Test-Json -SchemaFile accepts every good example and rejects every bad one'
    foreach ($name in $expectedNames) {
        $schemaFile = Join-Path $SchemaDir "$name.schema.json"
        foreach ($f in Get-ChildItem -LiteralPath $exampleDir -Filter "$name.good*.json" -File) {
            $r = Test-Doc (Get-Content -LiteralPath $f.FullName -Raw -Encoding utf8) $schemaFile
            Check "B13-3 $($f.Name) is accepted" $r.Ok "($($r.Errors))"
        }
        foreach ($f in Get-ChildItem -LiteralPath $exampleDir -Filter "$name.bad-*.json" -File) {
            $r = Test-Doc (Get-Content -LiteralPath $f.FullName -Raw -Encoding utf8) $schemaFile
            Check "B13-3 $($f.Name) is rejected" (-not $r.Ok)
        }
    }

    Section 'B13-3 the real files and the real TenantBaseline output pass'
    $r = Test-Doc (Get-Content -LiteralPath (Join-Path $repo 'levers\registry.json') -Raw -Encoding utf8) (Join-Path $SchemaDir 'lever-registry.schema.json')
    Check 'B13-3 levers/registry.json passes lever-registry' $r.Ok "($($r.Errors))"
    $r = Test-Doc (Get-Content -LiteralPath (Join-Path $repo 'config\identities.json') -Raw -Encoding utf8) (Join-Path $SchemaDir 'identities.schema.json')
    Check 'B13-3 config/identities.json passes identities' $r.Ok "($($r.Errors))"
    Import-Module (Join-Path $repo 'levers\powershell\TenantBaseline\TenantBaseline.psd1') -Force
    $tbConfig = Get-Content -LiteralPath (Join-Path $repo 'levers\powershell\TenantBaseline\TenantBaseline.config.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $findingSchema = Join-Path $SchemaDir 'finding.schema.json'
    foreach ($tenant in @($tbConfig.tenants.PSObject.Properties.Name)) {
        $report = Get-TenantBaselineReport -Tenant $tenant
        $badFindings = @(foreach ($finding in $report.findings) {
                $one = Test-Doc ($finding | ConvertTo-Json -Depth 5 -Compress) $findingSchema
                if (-not $one.Ok) { "$($finding.Id): $($one.Errors)" }
            })
        Check "B13-3 every $tenant finding ($(@($report.findings).Count)) passes finding" ($badFindings.Count -eq 0) "($($badFindings -join '; '))"
    }
    # The class is module-internal, so read its properties from a real finding object.
    $findingType = @((Get-TenantBaselineReport -Tenant contoso).findings)[0].GetType()
    Check 'B13-3 the finding objects are TenantBaselineFinding' ($findingType.Name -eq 'TenantBaselineFinding') "(got $($findingType.Name))"
    $classProps = @($findingType.GetProperties() | ForEach-Object Name | Sort-Object) -join ','
    Check 'B13-3 finding schema properties are exactly the TenantBaselineFinding class properties' ($classProps -eq (@($parsed['finding'].properties.Keys | Sort-Object) -join ','))

    Section 'B13-3 keyword probe: each validation keyword our schemas use rejects a document that breaks only it'
    foreach ($kw in $probes.Keys) {
        $schema, $goodDoc, $badDoc = $probes[$kw]
        $okGood = Test-InlineSchema $schema $goodDoc
        $okBad = Test-InlineSchema $schema $badDoc
        Check "B13-3 keyword $kw accepts good and rejects bad" ($okGood -and -not $okBad) "(good=$okGood bad=$okBad)"
    }
    $used = [Collections.Generic.HashSet[string]]::new()
    foreach ($doc in $parsed.Values) { Get-Keyword $doc $used }
    $uncovered = @($used | Where-Object { $_ -notin $annotationKeywords -and $_ -ne 'format' -and -not $probes.Contains($_) } | Sort-Object)
    Check 'B13-3 every keyword used in schemas/ is probed or listed as an annotation' ($uncovered.Count -eq 0) "(not probed: $($uncovered -join ', '))"

    # Recorded result (STD-XL-3): JsonSchema.Net as bundled treats `format` as an annotation, so a bad date-time passes.
    # If this check fails, PowerShell now enforces format: update schemas/README.md, specs/B-13.md and STD-XL-3.
    $formatEnforced = -not (Test-InlineSchema '{"type":"string","format":"date-time"}' '"not-a-date"')
    Check 'B13-3 recorded: format date-time is annotation-only in Test-Json (Python checks date-times)' (-not $formatEnforced)
    $jsn = [AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetName().Name -eq 'JsonSchema.Net' } | Select-Object -First 1
    Write-Host "NOTE: PowerShell $($PSVersionTable.PSVersion), JsonSchema.Net $(if ($jsn) { $jsn.GetName().Version } else { 'unknown' }); format enforced: $formatEnforced"
}
catch {
    $script:fail++
    Write-Host "FAIL: unexpected error: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "Schemas tests: $script:pass passed, $script:fail failed"
exit $(if ($script:fail) { 1 } else { 0 })
