"""Repo-relative locations from one place (STD-PY-8, DR-08).

``REPO_ROOT`` is the repository root, found from this file's own location, never from the current working
directory. Loaders use it as their default root, so a command run from any folder reads the same files.
Modules that still compute ``Path(__file__).resolve().parents[2]`` themselves adopt this when next touched.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]

__all__ = ["REPO_ROOT"]
