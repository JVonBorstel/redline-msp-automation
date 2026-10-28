@{
    RootModule           = 'Sample.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '3b8f6a52-9c1d-4e07-8a35-6d2f41c7b9e0'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Two sample PowerShell levers over the offline mock tenant (synthetic fixtures): one read, one write. They prove the Python-to-PowerShell bridge (B-16); they are not part of the live registry.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @('Get-SampleUser', 'Set-SampleUserTitle')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('Sample', 'MockTenant', 'Lever', 'MSP')
        }
    }
}
