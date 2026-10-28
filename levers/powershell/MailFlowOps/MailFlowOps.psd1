@{
    RootModule           = 'MailFlowOps.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '3b8f1c52-9e4d-4a71-b6c2-5d0e8a7f1c93'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Mail-flow levers over the offline mock mail-flow state (synthetic fixtures): message trace of one message, and release of one quarantined message to one of its recipients. High-confidence phish and malware are never released.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @('Get-MailFlowTrace', 'Restore-QuarantinedMessage')
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('MailFlow', 'Quarantine', 'MockTenant', 'Lever', 'MSP')
        }
    }
}
