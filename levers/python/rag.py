"""Knowledge-base passage search for the caller's client (B-57, C-26). Read lever, offline, mock only.

``rag.search`` returns passages (text, chunk id, article id, score) from the runner's client namespace and the
``msp-internal`` namespace, nothing else. The client is taken from the state the runner hands over (``_meta.client``),
never from a parameter, and the namespace filter is applied inside the vector store (``rag.retrieve.search``). The
index is the synthetic corpus of ``fixtures/kb/`` embedded with the offline ``HashEmbedder`` stand-in, built once per
process. The runner audits who asked, never the passages (D-017).
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from core.levers.handlers import LeverFailed
from core.levers.tenant import JsonDict
from rag.retrieve import DEFAULT_K, Index, build_index, search

NOTE = (
    "Passages come from this client's articles and MSP-internal articles only. Ranking uses a word-overlap stand-in, "
    "not a language model: a missing result does not mean there is no article."
)


@lru_cache(maxsize=1)
def get_index() -> Index:
    """The process-wide index of the synthetic corpus (tests replace this function)."""
    return build_index()


def rag_search(state: JsonDict, params: Mapping[str, Any]) -> Any:
    """Passages for ``query`` for the runner's client; at most ``k`` (default 5)."""
    meta = state.get("_meta")
    client = meta.get("client") if isinstance(meta, dict) else None
    if not isinstance(client, str) or not client:
        raise LeverFailed("the client of this tenant is not known")
    index = get_index()
    try:
        passages = search(index.store, index.embedder, client, str(params["query"]), k=int(params.get("k", DEFAULT_K)))
    except ValueError as exc:
        raise LeverFailed(str(exc)) from exc
    return {"passages": [p.to_dict() for p in passages], "note": NOTE}
