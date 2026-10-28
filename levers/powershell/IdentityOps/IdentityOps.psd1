@{
    RootModule           = 'IdentityOps.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '5e2c7d14-8a39-4b60-9f1e-c3a4d8b27e65'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Identity levers over the offline mock tenant (synthetic fixtures): revoke sign-in sessions, enable an account (the undo of user.disable) and set a mover property. Mock only; nothing here has run against a real tenant.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @('Revoke-UserSessions', 'Enable-UserAccount', 'Set-UserProperty')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('Identity', 'MockTenant', 'Lever', 'MSP')
        }
    }
}
