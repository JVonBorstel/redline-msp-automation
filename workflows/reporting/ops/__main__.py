"""Operations metrics export (B-74). Writes files under build/ops-metrics; changes nothing else.

    uv run --frozen python -m workflows.reporting.ops export contoso-dental --as-of 2026-10-31
    uv run --frozen python -m workflows.reporting.ops export --msp --as-of 2026-10-31
    uv run --frozen python -m workflows.reporting.ops verify build/ops-metrics/contoso-dental

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input.
"""

from __future__ import annotations

import sys

from workflows.reporting.ops.ops import main

if __name__ == "__main__":
    sys.exit(main())
