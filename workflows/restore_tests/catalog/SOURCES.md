# Restore catalog sources

These files are **synthetic**: invented clients (Contoso Dental, Fabrikam Capital), invented machine, mailbox and file names, and invented content. Nothing was captured from a real backup product. They are pinned to `asOf` 2026-10-21T07:00:00Z. Results computed from them are fixture-based.

- One file per client, `workflows/restore_tests/catalog/<client>.json`; its `client` matches the file name and `organizationId` equals the client's backup organization id in `fixtures/backup/<client>.json`.
- Each item's `sourceJobId` is a job in that client's B-68 backup fixture. An item is restorable only if that job has status `success`.
- `sha256` is the SHA-256 of the item's UTF-8 `content`, as if recorded at backup time. A test recomputes it.
- Each file holds one decoy item of the **other** client's organization (RI-9001 in Contoso's file, RI-9002 in Fabrikam's); tests show it is never listed, picked or restored. Contoso's RI-1002 comes from a failed backup job and is not restorable.

## Not verified (D6-24)

**No vendor API documentation was read for this item.** Every field name and every value is **UNVERIFIED**: a neutral stand-in for "what a restore needs to know", not a claim about any product. The per-field table is in `specs/B-69.md`, and a test checks that every field in these files appears in it.
