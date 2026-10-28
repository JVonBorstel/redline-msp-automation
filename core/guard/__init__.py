"""Guard for untrusted input (Phase 1 deliverable 5).

- ``wrap_untrusted(source, text)``: wrap ticket, email, document or tool-output text as a labelled data block.
- ``detect_injection(text)``: transparent heuristics that flag instruction-like content. Flagged input is
  reported, never obeyed.
"""

from __future__ import annotations

from core.guard.detect import RULES, Detection, Reason, Rule, detect_injection
from core.guard.normalise import normalise
from core.guard.wrap import wrap_untrusted

__all__ = ["RULES", "Detection", "Reason", "Rule", "detect_injection", "normalise", "wrap_untrusted"]
