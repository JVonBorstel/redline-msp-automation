"""Weekly 'what we did for you' digest draft (B-72). A draft a person reviews; nothing is sent.

item = build_digest("contoso-dental", "2026-W42", generated_on="2026-10-26")   # typed figures and the closed tickets
draft = create_draft("contoso-dental", "2026-W42", generated_on="2026-10-26", out_dir=Path("build/digest"))

Closed tickets are listed by id, channel and dates only: no ticket text, people or labels. An Outlook draft is W9.
"""

from workflows.reporting.digest.digest import (
    ClosedTicket,
    Digest,
    Draft,
    VerifyError,
    build_digest,
    create_draft,
    digest_to_dict,
    main,
    render_html,
    verify_draft,
)
from workflows.reporting.digest.reconcile import reconcile_html
from workflows.reporting.digest.window import DigestError, week_bounds
from workflows.reporting.health import Mismatch

__all__ = [
    "ClosedTicket",
    "Digest",
    "DigestError",
    "Draft",
    "Mismatch",
    "VerifyError",
    "build_digest",
    "create_draft",
    "digest_to_dict",
    "main",
    "reconcile_html",
    "render_html",
    "verify_draft",
    "week_bounds",
]
