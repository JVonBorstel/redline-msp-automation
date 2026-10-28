# Bash levers (B-66)

> Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.

Levers for macOS and Linux hosts, run by `core/levers/bridge.py` (`BashBridge`). Spec: `specs/B-66.md`.

```
manifest.json    the allowlist: every script and lib with its SHA-256
scripts/         one vetted script per lever (named in the registry by a bare file name)
lib/lever.sh     request parsing and result printing shared by the scripts
mock/<client>/   a synthetic Mac or Linux host per client (disk.tsv, services.tsv, cache/...)
golden/          expected results for the golden-output tests
```

## Rules for a script

1. Source only `lib/lever.sh`, call `lever_init "$@"` first, and accept no other argument than `--what-if`.
2. With `--what-if` report the exact diff and change nothing. Without it, change state and report the same diff with `applied: true`.
3. Parameters are read with `lever_param NAME` and checked against an exact allowlist (`case`). Never `eval`, never build a command or a path from a parameter, never run a command that a parameter names.
4. Print one JSON line through `lever_emit` or `lever_fail` and nothing else. Do not call them inside `$( )`.
5. Use bash builtins where you can (bash 3.2 must work on macOS). Keep the file LF only.

## Adding or changing a script

1. Edit the script, run `shellcheck --shell=bash --external-sources levers/bash/scripts/*.sh levers/bash/lib/*.sh` if you have it.
2. Regenerate the hashes: `sha256sum scripts/*.sh lib/*.sh` (from this folder) and put them in `manifest.json`. The registry refuses to load while they differ.
3. Add the lever to `levers/registry.d/unix.json` (`"runtime": "bash"`, `"entry": "name.sh"`), a golden file and tests, and a notice template for a write lever.
4. A reviewer reads the manifest change together with the script change.
