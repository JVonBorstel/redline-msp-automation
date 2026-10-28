@{
    RootModule           = 'TenantBaseline.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '5fac5436-72ae-4e5a-a87d-02288ab6dd1a'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Read-only Microsoft 365 security baseline check over a mock Microsoft Graph v1.0 adapter (synthetic fixtures). Fix levers are suggested by name, dry-run only.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @('Invoke-TenantBaseline', 'Get-TenantBaselineReport')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('Microsoft365', 'Graph', 'Security', 'Baseline', 'MSP')
        }
    }
}
