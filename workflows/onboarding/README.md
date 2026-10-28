# Onboarding change plan (B-35)

One structured new-hire request becomes one ordered plan of dry-run proposals. Nothing is executed and nothing is sent. Spec: `specs/B-35.md`.

```
uv run --frozen python -m workflows.onboarding plan request.json            # the plan, as JSON
uv run --frozen python -m workflows.onboarding drafts request.json --approver lead-lee --approver lead-fay
```

`request.json` holds exactly these fields (anything else is refused): `client`, `requester` (email), `upn`, `display_name`, `job_title`, `department`, `manager_upn`, `start_date` (`YYYY-MM-DD`), `role`. Each has a pattern; there is no free-text field.

## The plan

1. `contact.check` first. If the requester is not authorized for `new-account` at this client, the plan is refused with the lever's fixed words and nothing else runs.
2. Then, each dry-run through the runner as the agent identity: `user.new` (R3, two distinct leads), `license.add` per license, `group.add-member` per group, `mailbox.enable-archive` if the role asks for it, `user.new-tap` (R3).
3. The licenses, groups and archive choice come from `roles.json` (client, then role). It is synthetic, cited, and fails closed. Change it there, not in code.

Each step carries its status, its diff, its risk class and how many leads it needs. A step the runner or the lever refuses (no free seat, a privileged group) stays in the plan as `blocked` with the reason; nothing buys a seat or grants a privileged group.

**Re-running** after a partial execution proposes only what remains: a step whose dry-run diff is empty is already done and is listed under `already_done`. While the user does not exist yet, the steps after `user.new` are dry-run on a scratch copy of the tenant with `user.new`'s diff replayed into it; they are marked `simulated` and are replaced by real dry-runs on the next build.

## The drafts

`drafts` runs the plan again and writes two files under `<state-dir>/onboarding/<plan-id>/` only if nothing is left to do: `welcome.md` (from `workflows/notify/templates/user.new.md`, for the new hire) and `handoff.md` (for the manager). Each starts with the draft header. A person reviews and sends them. The sign-in pass value is never read, so it cannot appear in a draft. Same inputs give byte-identical files.

Exit codes: 0 = ran, 2 = refused or bad input.
