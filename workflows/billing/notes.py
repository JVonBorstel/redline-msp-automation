"""Time-entry note quality (B-76, B76-2): does a note say what was done, why, and the outcome, in specific words.

Rule-based and offline. Each missing element gets a cited reason: the rule id and the evidence (the word that was
found, or the fact that none was). The score is a fixed sum, so it can be recomputed by hand:
what 40 + why 25 + outcome 25 + specific wording 10. A score belongs to one note; this module has no notion of who
wrote it and nothing aggregates it per person (B76-3).

The rewrite draft is a template for the technician: it keeps their own words, adds only facts already on the ticket
(its title), and leaves a bracketed blank for anything only the technician knows. It is a proposal, never saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

WEIGHTS: dict[str, int] = {"what": 40, "why": 25, "outcome": 25, "specific": 10}
MAX_HOURS = 24.0
MIN_CONTENT_WORDS = 4
_WORD = re.compile(r"[a-z][a-z'-]*")
_STOP = frozenset(
    "a an the and or of to for on in at by with from is was were are be been it its this that as per i we he she they "
    "his her their our user".split()
)
_ACTIONS = frozenset(
    "added applied cleared closed configured created deleted disabled enabled enrolled imaged installed migrated "
    "patched reinstalled rebooted removed renewed replaced reset resized restarted restored revoked rotated "
    "tested unlocked updated upgraded reconfigured registered moved sent found compared reviewed".split()
)
_WHY = re.compile(
    r"\b(because|due to|after|since|caused by|so that|in order to|reported|requested|asked|could not|cannot|can't"
    r"|unable|failed|failing|keeps?|kept|needed|alert|advisory|as scheduled|as part of)\b"
)
_OUTCOME = re.compile(
    r"\b(confirmed|verified|resolved|completed|working|works|passed|stable|closed|restored|connected again"
    r"|no further|no longer|waiting|awaiting|pending|escalated|follow-up|handed over|applied|tested|registered"
    r"|printed|rebooted cleanly|compliant|opens)\b"
)
_VAGUE = (
    "worked on",
    "looked at",
    "per request",
    "see ticket",
    "as discussed",
    "troubleshoot",
    "misc",
    "various",
    "issue",
    "ongoing",
    "assisted",
    "helped",
    "fixed",
)


@dataclass(frozen=True)
class NoteQuality:
    score: int
    band: str
    missing: list[str]
    vague_terms: list[str]
    reasons: list[dict[str, str]]
    draft: str | None


def _words(note: str) -> list[str]:
    return _WORD.findall(note.lower())


def _vague_hits(note: str) -> list[str]:
    text = note.lower()
    return [term for term in _VAGUE if re.search(rf"\b{re.escape(term)}", text)]


def assess(entry: dict[str, Any], ticket_title: str | None) -> NoteQuality:
    note = entry.get("note")
    note = note.strip() if isinstance(note, str) else ""
    words = _words(note)
    content = [w for w in words if w not in _STOP]
    actions = [w for w in words if w in _ACTIONS]
    reasons: list[dict[str, str]] = []
    missing: list[str] = []

    if actions and len(content) >= MIN_CONTENT_WORDS:
        score = WEIGHTS["what"]
    else:
        score = 0
        missing.append("what")
        if actions:
            evidence = f"only {len(content)} content words after the action {actions[0]!r}; need {MIN_CONTENT_WORDS}"
        else:
            evidence = "no past-tense action word (reset, installed, replaced, ...) in the note"
        reasons.append({"element": "what", "rule": "NQ-WHAT", "evidence": evidence})

    why_hit = _WHY.search(note.lower())
    if why_hit:
        score += WEIGHTS["why"]
    else:
        missing.append("why")
        reasons.append(
            {
                "element": "why",
                "rule": "NQ-WHY",
                "evidence": "no reason or trigger word (because, after, reported, ...)",
            }
        )

    outcome_hit = _OUTCOME.search(note.lower())
    if outcome_hit:
        score += WEIGHTS["outcome"]
    else:
        missing.append("outcome")
        reasons.append(
            {
                "element": "outcome",
                "rule": "NQ-OUT",
                "evidence": "no result word (confirmed, resolved, waiting on, ...)",
            }
        )

    vague = _vague_hits(note)
    if len(content) < MIN_CONTENT_WORDS:
        vague = [*vague, "too-short"]
    if vague:
        reasons.append(
            {
                "element": "specific",
                "rule": "NQ-VAGUE",
                "evidence": "vague wording: " + ", ".join(repr(v) for v in vague),
            }
        )
    else:
        score += WEIGHTS["specific"]

    hours = entry.get("hours")
    time_bad = isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0 or hours > MAX_HOURS
    if time_bad:
        missing.append("time")
        reasons.append(
            {
                "element": "time",
                "rule": "NQ-TIME",
                "evidence": f"hours {hours!r} is missing, zero or above {MAX_HOURS:g}",
            }
        )

    band = "good" if not missing and not vague else "needs-work"
    return NoteQuality(
        score, band, missing, vague, reasons, None if band == "good" else _draft(note, missing, ticket_title)
    )


def _draft(note: str, missing: list[str], ticket_title: str | None) -> str:
    parts = [note.strip(" .") + "." if note.strip(" .") else "[What was done: name the action and the item.]"]
    if "what" in missing and note.strip(" ."):
        parts.append("[What was done: name the action and the item.]")
    if "why" in missing:
        parts.append(f"Reason: ticket '{ticket_title}'. [Add what the user reported.]" if ticket_title else "[Why.]")
    if "outcome" in missing:
        parts.append("Outcome: [state the result and whether the user confirmed it.]")
    if "time" in missing:
        parts.append("Time: [enter the hours worked.]")
    return "DRAFT for the technician to edit and approve, not saved: " + " ".join(parts)
