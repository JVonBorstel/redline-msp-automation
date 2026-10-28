@{
    RootModule           = 'LicenseOps.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '5e1c7b94-2a3d-4f68-9b07-d4a8c2e61f35'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'License assignment and removal over the offline mock tenant (synthetic fixtures). Assigns only from seats the client already owns; removes only after the retention window. There is no purchase function, on purpose (W-VND-02).'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @('Add-LicenseAssignment', 'Remove-LicenseAssignment')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('License', 'MockTenant', 'Lever', 'MSP')
        }
    }
}
