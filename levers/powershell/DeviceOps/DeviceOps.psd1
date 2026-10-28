@{
    RootModule           = 'DeviceOps.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '3b7f5a62-9c41-4e08-a6d3-52e1f0c8b947'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Device remediation levers over the offline mock RMM state (synthetic fixtures): print spooler restart, mapped-drive repair, Outlook profile reset, temp cleanup, approved-service restart, workstation reboot and server reboot. Each runs one vetted script named in vetted-scripts.json; there is no free-form script parameter.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @(
        'Restart-DevicePrintSpooler', 'Repair-DeviceMappedDrive', 'Reset-DeviceOutlookProfile',
        'Clear-DeviceTemp', 'Restart-DeviceService', 'Restart-DeviceWorkstation', 'Restart-DeviceServer'
    )
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('Device', 'RMM', 'MockRmm', 'Lever', 'MSP')
        }
    }
}
