"""Monthly client health report with reconciliation (B-71). A draft a person reviews; nothing is sent.

report = build_report("contoso-dental", "2026-10", generated_on="2026-10-31")   # typed sections and figures
draft = create_draft("contoso-dental", "2026-10", generated_on="2026-10-31", out_dir=Path("build/client-health"))

Other workflows (a quarterly review, a digest) build on ``build_report``: each ``Section`` carries its figures, status,
fired rules and sources, so they can re-use a month's numbers without re-reading the fixtures.
"""

from workflows.reporting.health.health import (
    METRIC_LABELS,
    SECTION_KEYS,
    Draft,
    HealthReport,
    Section,
    SourceRef,
    Summary,
    VerifyError,
    build_report,
    create_draft,
    main,
    render_html,
    report_to_dict,
    verify_draft,
)
from workflows.reporting.health.reconcile import Mismatch, reconcile_html
from workflows.reporting.health.sources import DEFAULT_SOURCES, HealthError, Sources

__all__ = [
    "DEFAULT_SOURCES",
    "METRIC_LABELS",
    "SECTION_KEYS",
    "Draft",
    "HealthError",
    "HealthReport",
    "Mismatch",
    "Section",
    "SourceRef",
    "Sources",
    "Summary",
    "VerifyError",
    "build_report",
    "create_draft",
    "main",
    "reconcile_html",
    "render_html",
    "report_to_dict",
    "verify_draft",
]
