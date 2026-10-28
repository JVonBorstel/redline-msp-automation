"""Quarterly business review draft (B-72). A draft a person reviews; nothing is sent.

report = build_qbr("contoso-dental", "2026-Q4", generated_on="2026-10-31")   # typed figures, wins, risks, suggestions
draft = create_draft("contoso-dental", "2026-Q4", generated_on="2026-10-31", out_dir=Path("build/qbr"))

Built on B-71: each month of the quarter (and of the quarter before) is a ``workflows.reporting.health.build_report``.
"""

from workflows.reporting.health import Mismatch
from workflows.reporting.qbr.policy import QbrError
from workflows.reporting.qbr.qbr import (
    Draft,
    Qbr,
    VerifyError,
    build_qbr,
    create_draft,
    main,
    qbr_to_dict,
    render_html,
    verify_draft,
)
from workflows.reporting.qbr.reconcile import reconcile_html
from workflows.reporting.qbr.sources import DEFAULT_QBR_SOURCES, QbrSources

__all__ = [
    "DEFAULT_QBR_SOURCES",
    "Draft",
    "Mismatch",
    "Qbr",
    "QbrError",
    "QbrSources",
    "VerifyError",
    "build_qbr",
    "create_draft",
    "main",
    "qbr_to_dict",
    "reconcile_html",
    "render_html",
    "verify_draft",
]
