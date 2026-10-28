"""Fact packs for human-only identity decisions (B-37). Read-only: no lever, no proposal.

pack = build("termination", "contoso-dental", "ana.lopez@contosodental.example")
"""

from workflows.factpack.factpack import BASELINE_DIR, KINDS, FactpackError, build

__all__ = ["BASELINE_DIR", "KINDS", "FactpackError", "build"]
