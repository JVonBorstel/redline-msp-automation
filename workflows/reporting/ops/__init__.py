"""Operations metrics and Power BI exports (B-74). Read-only; fixture-based; never per technician.

folder = export_client("contoso-dental", "2026-10-31", Path("build/ops-metrics"))
"""

from workflows.reporting.ops.ops import (
    TABLES,
    Column,
    OpsError,
    VerifyError,
    assert_no_person_columns,
    export_client,
    export_msp,
    main,
    verify,
)

__all__ = [
    "TABLES",
    "Column",
    "OpsError",
    "VerifyError",
    "assert_no_person_columns",
    "export_client",
    "export_msp",
    "main",
    "verify",
]
