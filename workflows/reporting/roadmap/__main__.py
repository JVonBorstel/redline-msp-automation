"""Technology roadmap and AI-use policy drafts (B-73). Writes draft files under build/client-roadmap; sends nothing.

    uv run --frozen python -m workflows.reporting.roadmap build contoso-dental --period 2026-10 \
        --generated-on 2026-10-31
    uv run --frozen python -m workflows.reporting.roadmap build --all --period 2026-10 --generated-on 2026-10-31
    uv run --frozen python -m workflows.reporting.roadmap verify \
        build/client-roadmap/2026-10/contoso-dental.roadmap.draft.json

Exit 0 = done (verify: matches), 1 = verify mismatch, 2 = bad input.
"""

from __future__ import annotations

import sys

from workflows.reporting.roadmap.drafts import main

if __name__ == "__main__":
    sys.exit(main())
