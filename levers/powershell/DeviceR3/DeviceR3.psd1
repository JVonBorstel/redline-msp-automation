@{
    RootModule           = 'DeviceR3.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '3b8f6a52-1c47-4e9d-a0d3-5e7c2f94b816'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'R3 device levers over the offline mock device state (synthetic fixtures): lock and unlock, network isolation and release, retire, and a wipe request. One device per call; the Python runner enforces two approvals. Nothing here starts a wipe.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @(
        'Lock-ManagedDevice', 'Unlock-ManagedDevice',
        'Block-DeviceNetwork', 'Unblock-DeviceNetwork',
        'Remove-ManagedDevice', 'Clear-ManagedDevice'
    )
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('Device', 'R3', 'MockTenant', 'Lever', 'MSP')
        }
    }
}
