"""Teams approval prompts (B-88): one card per pending proposal of one client, recorded in dry-run. Never decides.

run = plan_posts(queue, "contoso-dental", base_url="http://127.0.0.1:8765")
path = record_dry_run(run, Path(".tmp/demo"))
"""

from workflows.teams_approvals.approvals import (
    OUTBOX,
    PlannedPost,
    TeamsApprovalsError,
    TeamsRun,
    plan_posts,
    record_dry_run,
    summary,
)

__all__ = ["OUTBOX", "PlannedPost", "TeamsApprovalsError", "TeamsRun", "plan_posts", "record_dry_run", "summary"]
