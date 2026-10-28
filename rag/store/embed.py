"""Embedders (B-56): an interface, and a deterministic stand-in that needs no model.

``Embedder`` is the seam real embedders plug into as adapters (off by default; nothing here downloads or calls a
model). ``HashEmbedder`` is the offline stand-in: signed feature hashing of word unigrams and bigrams into a fixed
size vector, L2-normalised. It ranks text that shares words above text that does not. It is NOT a semantic model: it
knows nothing about synonyms, so any recall number measured with it describes this stand-in only.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

_TOKEN = re.compile(r"[a-z0-9]+")
MIN_DIM = 8


@runtime_checkable
class Embedder(Protocol):
    """Turns texts into vectors of a fixed size. ``id`` names the embedder in every chunk's provenance."""

    id: str
    dim: int

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...


class HashEmbedder:
    """Deterministic, stdlib-only embedder stand-in. The same text gives the same vector on every machine."""

    def __init__(self, dim: int = 64) -> None:
        if dim < MIN_DIM:
            raise ValueError(f"dim must be at least {MIN_DIM}")
        self.dim = dim
        self.id = f"hash-embedder/{dim}"

    def _feature(self, vector: list[float], feature: str, weight: float) -> None:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % self.dim
        vector[index] += weight if digest[4] & 1 else -weight

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        out: list[tuple[float, ...]] = []
        for text in texts:
            tokens = _TOKEN.findall(text.lower())
            vector = [0.0] * self.dim
            for token in tokens:
                self._feature(vector, token, 1.0)
            for left, right in zip(tokens, tokens[1:], strict=False):
                self._feature(vector, left + " " + right, 0.5)
            norm = math.sqrt(sum(x * x for x in vector))
            out.append(tuple(x / norm for x in vector) if norm else tuple(vector))
        return out
