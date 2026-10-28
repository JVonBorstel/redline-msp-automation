# workflows/rollback (B-41)

Status: **built** on synthetic fixtures (change note `docs/changes/B-41.md`). Synthetic data only.

Reads one applied audit record. If the lever has a registered undo, it dry-runs that undo and checks its diff is exactly the recorded change reversed, then queues a rollback proposal a lead approves. If there is no undo it returns the manual steps from the lever README. It never executes a write lever.

## Command

```
uv run --frozen python -m workflows.rollback <audit_seq> --client contoso-dental [--as tech-ana] [--state .tmp/demo]
```

## Inputs

The client's audit chain in the state folder, the lever registry and the mock tenant.

## Outputs

JSON on stdout: a queued rollback proposal, manual steps, or why nothing was proposed. Exit 0 proposed, manual or nothing to undo, 2 refused, drifted or bad input.

## What is mock

Runs against the mock tenant; a masked value in the audit diff is reported as drifted rather than guessed.

## Spec and tests

Spec: `specs/B-41.md`. Tests: `tests/py/rollback/test_b41_rollback.py`.
