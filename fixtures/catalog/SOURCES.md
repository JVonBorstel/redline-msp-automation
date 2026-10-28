# Approved-software catalog fixture sources

Status: **mocked**. These fixtures are **synthetic**: invented vendors, package ids, versions, installer names (`.example`) and device inventories for the invented clients Contoso Dental and Fabrikam Capital. Nothing was captured from a real catalog, RMM or installer. Pinned to `asOf` 2026-10-22T12:00:00Z. Results computed from them are fixture-based.

- `approved-software.json`: the catalog (B-63). `packages[]` holds one entry per package id with exactly the fields `id`, `name`, `publisher`, `version` (digits and dots, pinned) and `sha256` (64 hex), plus the `installer` file name. `clients.<client>.approved` is that client's approved subset. A client without an entry has no approved software. The loader (`levers/python/software.py`, `load_catalog`) refuses the whole file on any bad entry.
- Each `sha256` is the SHA-256 of the text `synthetic-installer:<id>:<version>`, so a test can re-derive it. It is **not** the hash of a real installer: no installer exists here. In real use the hash comes from the vendor's published value or from the MSP's own vetting of the file, and the RMM (or the install step) must refuse a file whose hash differs. That check is not built here.
- `installed-software.json`: per client and RMM device uid, the update `ring` (`pilot`, `broad`, or `hold` for devices that are never proposed, such as a server) and the `installed` map of package id to version. Each client's list also holds one record of the **other** client's device (the RMM decoy uid); a test shows it is never proposed.

## Field status

No external API is mirrored, so no field is Verified. Every field is this repo's own invention.

| File | Field | Status |
| --- | --- | --- |
| both | `_note`, `asOf` | UNVERIFIED (this repo's own keys) |
| approved-software | `catalog_version`, `packages`, `clients` | UNVERIFIED (this repo's own keys) |
| approved-software | `id`, `name`, `publisher`, `version`, `sha256`, `installer` | UNVERIFIED (invented; real installer metadata and hash source not checked) |
| approved-software | `approved` | UNVERIFIED (this repo's own key) |
| installed-software | `clients`, `devices`, `ring`, `installed` | UNVERIFIED (this repo's own keys; a real RMM software audit has a different shape, not checked) |
