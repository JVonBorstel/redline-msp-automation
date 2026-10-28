"""Lever registry and runner: permissions enforced in code, dry-run by default, every call audited.

specs/phase-1.md deliverables 2 and 6. Typical use:

    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(), AuditLog(path))
    result = runner.invoke("user.reset-mfa", {"upn": "..."}, identity="tech-ana", client="contoso-dental")
"""

from core.levers.models import Approval, Change, InvokeResult, LeverDef, ParamSpec
from core.levers.registry import DEFAULT_REGISTRY_PATH, Registry, RegistryError
from core.levers.runner import LeverRunner
from core.levers.tenant import DEFAULT_TENANT_DIR, MockTenant, TenantError

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "DEFAULT_TENANT_DIR",
    "Approval",
    "Change",
    "InvokeResult",
    "LeverDef",
    "LeverRunner",
    "MockTenant",
    "ParamSpec",
    "Registry",
    "RegistryError",
    "TenantError",
]
