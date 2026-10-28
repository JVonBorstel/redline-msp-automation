@{
    RootModule           = 'Provisioning.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '7b3e91a6-2c58-4d07-b4f1-e6a09c35d812'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Provisioning lever over the offline mock tenant (synthetic fixtures): create a new hire account and its mailbox record, enabled and with no credential. Mock only; nothing here has run against a real tenant.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @('New-UserAccount')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('Provisioning', 'MockTenant', 'Lever', 'MSP')
        }
    }
}
