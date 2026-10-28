"""Weekly 'what we did for you' digest draft (B-72). Writes draft files under build/digest; sends nothing.

    uv run --frozen python -m workflows.reporting.digest build contoso-dental --week 2026-W42 --generated-on 2026-10-26
    uv run --frozen python -m workflows.reporting.digest build --all --week 2026-W42 --generated-on 2026-10-26
    uv run --frozen python -m workflows.reporting.digest verify build/digest/2026-W42/contoso-dental.draft.html

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input or the digest did not reconcile.
"""

from __future__ import annotations

import sys

from workflows.reporting.digest.digest import main

if __name__ == "__main__":
    sys.exit(main())
