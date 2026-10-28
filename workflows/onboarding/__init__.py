"""New-hire change plan (B-35): one form becomes one ordered dry-run plan; drafts follow once it is executed.

plan = build_plan(runner, parse_request(form))   # raises PlanRefused if contact.check says no
drafts = welcome_and_handoff(runner, parse_request(form), approvers=["lead-lee", "lead-fay"], state_dir=Path(".tmp"))
"""

from workflows.onboarding.onboarding import (
    DEFAULT_ROLES_PATH,
    Drafts,
    NewHireRequest,
    OnboardingError,
    Plan,
    PlanIncomplete,
    PlanRefused,
    PlanStep,
    RoleTable,
    build_plan,
    load_roles,
    parse_request,
    plan_id,
    welcome_and_handoff,
)

__all__ = [
    "DEFAULT_ROLES_PATH",
    "Drafts",
    "NewHireRequest",
    "OnboardingError",
    "Plan",
    "PlanIncomplete",
    "PlanRefused",
    "PlanStep",
    "RoleTable",
    "build_plan",
    "load_roles",
    "parse_request",
    "plan_id",
    "welcome_and_handoff",
]
