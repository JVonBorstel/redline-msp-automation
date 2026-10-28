"""Phase 1 smoke test: the toolchain runs. Acceptance tests P1-1 to P1-9 (specs/phase-1.md) come with each module."""

import core


def test_core_package_imports() -> None:
    assert core.__doc__ is not None
