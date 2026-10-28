@{
    RootModule           = 'MailboxOps.psm1'
    ModuleVersion        = '0.1.0'
    GUID                 = '6d2e9b14-83a7-4c5f-b0e1-7a4c3d9f2e58'
    Author               = 'redline-msp-automation (independently built prototype)'
    Copyright            = 'See LICENSE in the repository root.'
    Description          = 'Mailbox and OneDrive levers for joiners, movers and leavers over the offline mock tenant (synthetic fixtures): distribution list membership, Full Access and Send As, convert to shared, auto-reply, archive, and a time-bound manager grant to a leavers OneDrive. External forwarding is deliberately not offered.'
    PowerShellVersion    = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport    = @(
        'Add-MailboxDlMember', 'Remove-MailboxDlMember',
        'Grant-MailboxFullAccess', 'Revoke-MailboxFullAccess',
        'Grant-MailboxSendAs', 'Revoke-MailboxSendAs',
        'Convert-MailboxToShared',
        'Set-MailboxAutoReply', 'Clear-MailboxAutoReply',
        'Enable-MailboxArchive',
        'Grant-OneDriveManagerAccess', 'Revoke-OneDriveManagerAccess'
    )
    CmdletsToExport      = @()
    VariablesToExport    = @()
    AliasesToExport      = @()
    PrivateData          = @{
        PSData = @{
            Tags = @('Mailbox', 'OneDrive', 'MockTenant', 'Lever', 'MSP')
        }
    }
}
