# Registry fragments

Every `*.json` file in this folder is loaded together with `levers/registry.json` as **one registry** (B-14, `STD-LV-2`,
`STD-CF-3`). Add a lever family by adding one fragment and one module, without touching the main file.

## File shape

```json
{
  "version": 1,
  "_note": "optional, for humans, ignored by the loader",
  "levers": [ { "name": "group.add-member", "...": "same fields as levers/registry.json" } ]
}
```

- `version` is required and must be `1`. A fragment without it fails the whole load.
- Files load in name order. The same lever name in two files (or in the main file) fails the whole load and names both files.
- An unknown field, on the file or on a lever, fails the whole load. There is no partial load: one bad fragment and nothing is registered.
- Every rule of `levers/registry.json` applies unchanged: write levers need `risk_class` and `impact`, `undo` must name a
  registered write lever, and so on (`STD-LV-1` to `STD-LV-10`).

## Where the implementation comes from

- No `entry` field: the handler is the one registered under the lever's name in `core.levers.handlers.HANDLERS` (the four original levers).
- `"entry": "levers.python.<module>:<function>"` (with `"runtime": "python"`, the default): the function is imported from the
  `levers.python` package and nowhere else. Any other module path, a missing function, or a function defined outside
  `levers.python` is refused at load. `"runtime": "powershell"` is refused until the bridge exists (`B-16`).

## The never-automate gate

`governance/never-automate.json` lists the work that stays with people (the `none-keep-human` inventory ids) with lever-name
patterns, for example `role.grant*`, `ca.set*`, `hold.*`, `vault.*`, `license.purchase*`. The loader refuses a lever whose name
matches, and the error names the inventory id and the reason. Read-only fact packs for that work use other names (`B-37`, `B-48`).
Changing the list is a reviewed change with a DECISIONS entry, like code.
