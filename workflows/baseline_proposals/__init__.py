"""Baseline-sourced user.disable proposals for stale accounts and expired guests (B-38). Proposes only; a lead approves.

result = plan("contoso-dental", findings_path, queue)
"""

from workflows.baseline_proposals.baseline_proposals import (
    BaselineProposalsError,
    Deferred,
    Plan,
    Proposed,
    Skipped,
    WorkflowConfig,
    load_config,
    plan,
    read_findings,
    read_guests,
    summary,
)

__all__ = [
    "BaselineProposalsError",
    "Deferred",
    "Plan",
    "Proposed",
    "Skipped",
    "WorkflowConfig",
    "load_config",
    "plan",
    "read_findings",
    "read_guests",
    "summary",
]
