## CHANGELOG
- `docs/ROADMAP.md` item blocks are now generated from `map/roadmap.json` by `tools/gen_roadmap_md.py` (one `gen:items` marker pair per wave). `map/check_map.py` fails when the generated blocks differ from the file and prints the fix command. Two same-wave items sharing an existing file are a warning; two items creating the same new path stay a problem.

## Effect (L1-L4)
- L1 person: builders stop mis-typing owns, so no one is blocked by a copy that disagrees.
- L2 business: fewer false CI failures from a hand-copied roadmap.
- L3 MSP: one source of truth for owns, acceptance and standards.
- L4 community: none directly.

## Not done here
- `depends_on` is not in the item blocks (it is in each wave's table, which stays hand-written and unchecked). A follow-up can generate the tables.
- `docs/map/README.md` section 6 still describes the old Owns-line rule; it is outside this order's files.
