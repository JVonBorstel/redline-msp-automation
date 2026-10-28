@{
    RootModule           = 'GroupOps.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '7d2c5e91-4b3a-4f68-9a0e-1c8b6d3f5a24'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Group membership levers (group.add-member, group.remove-member) over the offline mock tenant (synthetic fixtures). They refuse any role-assignable or client-privileged group (W-IDM-07).'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @('Add-GroupMember', 'Remove-GroupMember')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('Groups', 'MockTenant', 'Lever', 'MSP')
        }
    }
}
