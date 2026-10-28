@{
    RootModule           = 'CredentialOps.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '7d4c2e91-5b3a-4f68-9a10-c2e8b6d35f47'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Password reset and Temporary Access Pass levers over the offline mock tenant (synthetic fixtures). The generated value goes only to the out-of-band channel, never into the result, the diff or the tenant file.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @('Reset-UserPassword', 'New-UserTap')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('Credential', 'MockTenant', 'Lever', 'MSP')
        }
    }
}
