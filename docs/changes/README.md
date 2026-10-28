# Change fragments

Every build item `B-nn` owns one fragment, `docs/changes/B-nn.md`. Builders never edit the shared ledgers (`docs/DECISIONS.md`, `docs/COVERAGE.md`, `CHANGELOG.md`, `docs/RUNBOOKS.md`); they write their entries here, and the wave's exit step folds them in (see `docs/ROADMAP.md`, DOD-9).

## Format

One `## <LEDGER>` section per ledger the item changes. The names are `DECISIONS`, `COVERAGE`, `CHANGELOG` and `RUNBOOKS`. A section that is empty or says `none` is skipped. Other sections (for example inventory or control status changes) are for the human fold and are ignored by the tool.

## Folding a wave

```
uv run python tools/fold_changes.py --wave W1 --dry-run   # print the edits, change nothing
uv run python tools/fold_changes.py --wave W1             # append them
```

- Each block is appended to its ledger after a marker line `<!-- fold:B-nn:LEDGER -->`.
- A block whose marker is already in the ledger is skipped, so running the tool twice changes nothing.
- Items of the wave without a fragment are skipped.
- Status words in COVERAGE stay strict: "built" only with a passing test.
