"""MSP client lifecycle (B-77): discovery pack for a new client and migration pre-flight checks. Read-only.

pack = discover("contoso-dental", out_dir)           # baseline, devices, licences; lists gaps
result = run_preflight("contoso-dental")              # mailbox sizes, licence availability, conflicting addresses

Offboarding a client from the MSP is a human runbook (docs/runbooks/client-offboarding.md); nothing here automates it.

The function is exported as `run_preflight`: a package attribute named `preflight` would shadow the submodule
`workflows.client_lifecycle.preflight`. `from workflows.client_lifecycle.preflight import preflight` still works.
"""

from workflows.client_lifecycle.discovery import (
    DiscoveryError,
    Gap,
    LifecycleConfig,
    Pack,
    Step,
    StepOutcome,
    discover,
    licence_report,
    load_config,
    summary,
)
from workflows.client_lifecycle.preflight import Check, MigrationPlan, Preflight, PreflightError
from workflows.client_lifecycle.preflight import preflight as run_preflight

__all__ = [
    "Check",
    "DiscoveryError",
    "Gap",
    "LifecycleConfig",
    "MigrationPlan",
    "Pack",
    "Preflight",
    "PreflightError",
    "Step",
    "StepOutcome",
    "discover",
    "licence_report",
    "load_config",
    "run_preflight",
    "summary",
]
