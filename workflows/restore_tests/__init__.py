"""Restore requests to an alternate location and scheduled restore tests (B-69). Mock only.

catalog = RestoreCatalog.for_fixture("contoso-dental")
proposal = propose_restore("RI-1001", "ALT-RESTORE-1001", catalog, runner)   # dry-run only
record = run_restore_test(catalog, "2026-10-21", out_dir=..., audit_dir=...)  # evidence file with hashes
"""

from workflows.restore_tests.catalog import ITEM_KINDS, RestoreCatalog
from workflows.restore_tests.restore import (
    AUDIT_LEVER,
    DEFAULT_CONFIG_PATH,
    IN_PLACE_REFUSED,
    RESTORE_LEVER,
    RestoreConfig,
    RestoreError,
    RestoreProposal,
    TestRecord,
    VerifyError,
    audit_digest,
    canonical_bytes,
    load_config,
    pick_item,
    propose_restore,
    restore_test_workflow,
    run_restore_test,
    sidecar_for,
    verify_evidence,
)

__all__ = [
    "AUDIT_LEVER",
    "DEFAULT_CONFIG_PATH",
    "IN_PLACE_REFUSED",
    "ITEM_KINDS",
    "RESTORE_LEVER",
    "RestoreCatalog",
    "RestoreConfig",
    "RestoreError",
    "RestoreProposal",
    "TestRecord",
    "VerifyError",
    "audit_digest",
    "canonical_bytes",
    "load_config",
    "pick_item",
    "propose_restore",
    "restore_test_workflow",
    "run_restore_test",
    "sidecar_for",
    "verify_evidence",
]
