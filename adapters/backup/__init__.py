"""Backup adapters: the vendor-neutral interface and the mock."""

from __future__ import annotations

from adapters.backup.base import JOB_TYPES, BackupAdapter
from adapters.backup.mock import BackupMock

__all__ = ["JOB_TYPES", "BackupAdapter", "BackupMock"]
