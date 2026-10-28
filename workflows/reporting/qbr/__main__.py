"""Quarterly business review draft (B-72). Writes draft files under build/qbr; sends nothing.

    uv run --frozen python -m workflows.reporting.qbr build contoso-dental --quarter 2026-Q4 --generated-on 2026-10-31
    uv run --frozen python -m workflows.reporting.qbr verify build/qbr/2026-Q4/contoso-dental.draft.html

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input or the review did not reconcile.
"""

from __future__ import annotations

import sys

from workflows.reporting.qbr.qbr import main

if __name__ == "__main__":
    sys.exit(main())
