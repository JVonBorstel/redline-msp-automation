# The showcase site

A static site built from real runs of this repository's code over its synthetic fixtures: triage a ticket, replay the approval queue, tamper with the audit log and verify it in the browser, read the roadmap, the levers and the evidence. It makes no third-party requests, sets no cookies and stores only the colour theme choice.

> Independently built prototype. All tenants, people and tickets are synthetic.

## Build

Needs git, [uv](https://docs.astral.sh/uv/) and PowerShell 7 (`pwsh`). From the repository root:

```bash
python site/build.py                 # builds the committed HEAD into site/dist
python site/build.py --worktree      # build the working tree instead (before a commit)
python site/build.py --offline       # forbid network access for the uv sync step (needs a warm uv cache)
```

`build.py` copies the repository (`git archive`, nothing is written inside it), runs `uv sync --frozen` in the copy, runs `exporter/export_data.py` there (the repository's own functions and command lines over the fixtures), runs the PowerShell baseline check on both synthetic tenants, reads the roadmap and proof numbers from the same copy (`stats.py`), and renders the pages (`render.py`, `render_portfolio.py`). Any failing step stops the build and leaves the previous `dist/` untouched.

Serve it locally: `python -m http.server 8765 --bind 127.0.0.1 --directory site/dist`.

## Test

```bash
python -B -m unittest discover -s site/tests
```

Needs Node (the browser-side audit-chain verifier is checked against the Python verifier), PowerShell 7 (the privacy scan) and a headless Chrome or Edge (every page is rendered and checked). Set `REDLINE_BROWSER` to the browser binary if it is not found. The tests build nothing: run `build.py` first.

## Privacy and wording

`scan/privacy-scan.ps1` scans a built folder for local paths, tailnet names, private addresses, emails outside reserved test domains, token shapes and words that do not belong on a public page; `-SelfTest` plants every class and requires it to be caught. `stats.py` refuses to build if a roadmap title contains a word on its banned list. The only place the author's name may appear is `site.config.json` (`author_line`, `contact_url`); the scan exempts exactly those two strings.

## Layout

`build.py` the build; `render.py`, `render_portfolio.py` the pages; `stats.py` roadmap and proof numbers; `exporter/` the real runs; `src/` page assets (CSS, JavaScript); `content/` the hand-written portfolio, blueprint, ideas and proof text; `scan/` the privacy scan; `tests/` the site tests; `site.config.json` name, byline and indexing.
