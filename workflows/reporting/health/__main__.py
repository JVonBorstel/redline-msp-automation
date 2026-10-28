"""Monthly client health report (B-71). Writes draft files under build/client-health; sends nothing.

    uv run --frozen python -m workflows.reporting.health build contoso-dental --period 2026-10 --generated-on 2026-10-31
    uv run --frozen python -m workflows.reporting.health build --all --period 2026-10 --generated-on 2026-10-31
    uv run --frozen python -m workflows.reporting.health verify build/client-health/2026-10/contoso-dental.draft.html

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input or the report did not reconcile.
"""

from __future__ import annotations

import sys

from workflows.reporting.health.health import main

if __name__ == "__main__":
    sys.exit(main())
