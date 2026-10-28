"""Technician corrections to triage, kept as eval data (evals/triage/corrections.jsonl, one JSON object per line).

A correction says "for this ticket, the right <field> is <value>". It is validated before it is written: the field
must be one triage sets, the value must be legal for that field, and the author must be a known human (an agent
cannot correct its own homework). The eval report applies corrections over the fixture labels, latest one wins.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from core.identity import IdentityStore, Role, UnknownIdentity, role_satisfies
from core.levers import Registry
from workflows.triage.proposal import utc_now
from workflows.triage.rules import CATEGORIES, PRIORITIES, QUEUES
from workflows.triage.tickets import Labels

DEFAULT_CORRECTIONS_PATH = Path(__file__).resolve().parents[2] / "evals" / "triage" / "corrections.jsonl"

CorrectableField = Literal["category", "priority", "queue", "expected_lever"]
FIELDS: tuple[CorrectableField, ...] = ("category", "priority", "queue", "expected_lever")


_ALLOWED: Mapping[str, tuple[str, ...]] = {"category": CATEGORIES, "priority": PRIORITIES, "queue": QUEUES}


class CorrectionError(ValueError):
    """The correction is not valid and was not written."""


class Correction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: Annotated[str, StringConstraints(pattern=r"^T-[0-9]{4}$")]
    field: CorrectableField
    value: str | None = Field(max_length=64)
    by: str = Field(min_length=1, max_length=64)
    ts: str


def _check_value(field: CorrectableField, value: str | None, registry: Registry) -> None:
    allowed: tuple[str, ...] = _ALLOWED.get(field, ())
    if field == "expected_lever":
        if value is not None and value not in registry:
            raise CorrectionError(f"{value!r} is not a registered lever (use none for no lever)")
    elif value not in allowed:
        raise CorrectionError(f"{value!r} is not a valid {field}; choose one of {', '.join(allowed)}")


def record_correction(
    ticket_id: str,
    field: str,
    value: str | None,
    by: str,
    *,
    path: Path = DEFAULT_CORRECTIONS_PATH,
    identities: IdentityStore | None = None,
    registry: Registry | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> Correction:
    """Validate one correction and append it to ``path``. Returns what was written."""
    if field not in FIELDS:
        raise CorrectionError(f"field must be one of {', '.join(FIELDS)}, got {field!r}")
    checked: CorrectableField = next(f for f in FIELDS if f == field)
    _check_value(checked, value, registry or Registry.load())
    try:
        author = (identities or IdentityStore.load()).get(by)
    except UnknownIdentity:
        raise CorrectionError(f"unknown identity {by!r}") from None
    if not role_satisfies(author.role, Role.TECHNICIAN):
        raise CorrectionError(f"{by} is an {author.role.value}; only technicians and leads record corrections")
    ts = clock().astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        correction = Correction(ticket_id=ticket_id, field=checked, value=value, by=by, ts=ts)
    except ValueError as exc:
        raise CorrectionError(str(exc)) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(correction.model_dump_json() + "\n")
    return correction


def load_corrections(path: Path = DEFAULT_CORRECTIONS_PATH) -> list[Correction]:
    """Every correction in file order; an absent file means none yet."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Correction.model_validate_json(line) for line in lines if line.strip()]


def apply_corrections(ticket_id: str, labels: Labels, corrections: Iterable[Correction]) -> Labels:
    """The labels with this ticket's corrections applied in order, so the latest one per field wins."""
    updates = {c.field: c.value for c in corrections if c.ticket_id == ticket_id}
    return Labels.model_validate(labels.model_dump() | updates) if updates else labels
