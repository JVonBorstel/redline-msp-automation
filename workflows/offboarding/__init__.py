"""Offboarding change plan with completion proof (B-36). Proposes each change for a lead; verify is read-only.

p = plan(runner, "contoso-dental", upn, "tech-ana", manager=..., queue=queue)
"""

from workflows.offboarding.offboarding import (
    OffboardingError,
    OffboardPlan,
    Step,
    lob_checklist,
    plan,
    reconcile,
    record_path,
    summary,
    verify,
)

__all__ = [
    "OffboardPlan",
    "OffboardingError",
    "Step",
    "lob_checklist",
    "plan",
    "reconcile",
    "record_path",
    "summary",
    "verify",
]
