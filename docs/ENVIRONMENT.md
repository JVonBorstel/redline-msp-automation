# Environment

Status: **built** (a requirements list, checked by running the suites on Windows and Linux runners). Nothing in this repository installs software for you; this page says what the suites need and the exact command to get it.

> Independently built prototype. Synthetic data only.

## Needed to run everything

| Tool | Version | Needed for | Install |
|------|---------|-----------|---------|
| git | any recent | clone, the site build | your package manager |
| uv | 0.9 or newer | the locked Python environment, ruff, mypy, pytest | `winget install --id astral-sh.uv -e`, or the installer on the uv website |
| Python | 3.12 | everything in `core/`, `workflows/`, `tests/` | `uv python install 3.12` (uv-managed; set `UV_PYTHON_PREFERENCE=only-managed`) |
| PowerShell 7 | 7.4 or newer | the PowerShell levers, `tests/ps`, `tests/sliceb`, `tests/demo` | `winget install --id Microsoft.PowerShell -e`, or the package for your OS |

Set up the Python side with `uv sync --frozen`. `--frozen` makes uv use `uv.lock` exactly as committed (no resolve); add `--offline` once the cache is warm.

## Optional

| Tool | Needed for | Note |
|------|-----------|------|
| Node.js 20 or newer | the browser-side audit-chain check in `site/` (parity test) | tests only |
| Chrome or Edge (headless) | the page-rendering tests in `site/tests` | tests only |
| Ollama or another OpenAI-compatible local server | a real local model behind `core/gateway` | the mock provider is the default; nothing downloads a model for you |
| Bash 4 or newer | the macOS and Linux lever runtime (`levers/bash`) | ships with Linux; on Windows use WSL or Git Bash |
| Azure CLI with Bicep | `az bicep build` and what-if on `infra/` | validate only; this repo never deploys |

## Not needed

No cloud account, no Microsoft 365 tenant, no GPU and no secrets. Every tenant, person and ticket is synthetic, and everything runs offline by default.

## Checks

```powershell
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy
uv run --frozen mypy --strict core workflows evals ui mcp rag
uv run --frozen pytest tests/py tests/phase1 tests/demo
pwsh -NoProfile -File tests/ps/Test-Modules.ps1
pwsh -NoProfile -File tests/sliceb/Test-SliceB.ps1
pwsh -NoProfile -File tests/demo/Test-Demo.ps1
```
