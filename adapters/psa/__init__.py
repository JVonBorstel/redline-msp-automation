"""PSA adapters: the vendor-neutral interface and the mock."""

from __future__ import annotations

from adapters.psa.base import PsaAdapter
from adapters.psa.mock import PsaMock

__all__ = ["PsaAdapter", "PsaMock"]
