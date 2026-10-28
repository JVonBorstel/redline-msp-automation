# Backup fixture sources

These fixtures are **synthetic**: invented clients (Contoso Dental, Fabrikam Capital) and invented machine names. Nothing was captured from a real backup product. They are pinned to `asOf` 2026-10-21T07:00:00Z. Results computed from them are fixture-based.

- One file per client, `fixtures/backup/<client>.json`; its `client` matches the file name and `organization.id` equals the client's backup organization id (the binding's `external_id`).
- The mock adapter is `adapters/backup/mock.py` (`BackupMock`). It only reads these files.
- Each file also holds one job that belongs to the **other** client's organization. It is there on purpose: a test shows the adapter and the review never show it (C-27, B68-3).

## Not verified (D6-24, B68-4)

The MSP sells backup and disaster recovery and managed Microsoft 365 backup (service CONFIRMED); the vendor is INFERRED (Datto continuity class) or UNKNOWN (Microsoft 365 product), see `docs/map/07-msp-profile.md` MP-15, MP-16. **No vendor API documentation was read for this item.** Every field name and every value is therefore **UNVERIFIED**: it is a neutral stand-in for "what a job record needs to say", not a claim about any product. The per-field table is in `specs/B-68.md`, and a test checks that every fixture field appears there.

## Two job types

| `jobType` | What it stands for |
| --- | --- |
| `image-appliance` | an image-based backup of a server or workstation, taken by an agent and stored on an appliance, with a boot check (the image is started in a sandbox and a screenshot says whether it reached a login screen) |
| `m365-saas` | a Microsoft 365 SaaS backup job for one service of the client's tenant (Exchange, OneDrive, SharePoint, Teams) |

## Seeded problems

- Contoso Dental: a server that fails two nights running (BJ-1002, BJ-1003); a workstation image whose boot check failed although the backup finished (BJ-1005); a Microsoft 365 job still running well past its expected duration (BJ-1007); a job that never started (BJ-1008).
- Fabrikam Capital: a file server that fails three nights running (BJ-2002 to BJ-2004); a Microsoft 365 job that fails two nights running (BJ-2011, BJ-2012); a failed job whose error text is an instruction aimed at an AI (BJ-2005), to prove such text is withheld; an image job running 6 hours against an expected 2 (BJ-2006); a job scheduled for 04:00 with no start recorded (BJ-2007).
- Decoys: BJ-9001 (in Contoso's file) belongs to Fabrikam's organization and BJ-9002 (in Fabrikam's file) to Contoso's.
