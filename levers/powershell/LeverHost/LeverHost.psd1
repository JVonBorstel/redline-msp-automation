@{
    RootModule           = 'LeverHost.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '9d2a6c1e-4b7f-4f0e-8a53-6c1b0e7d2f41'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Helpers for the PowerShell lever host (Invoke-LeverRequest.ps1): request validation, entry resolution, isolated invocation and result shaping. Synthetic data only.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @('Test-LeverRequestJson', 'New-LeverResult', 'ConvertTo-LeverParameterName', 'Invoke-LeverEntry')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('MSP', 'Lever', 'Bridge')
        }
    }
}
