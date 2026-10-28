"""Daily backup job review and failed-backup triage (B-68, specs/B-68.md; W-BDR-01, W-BDR-02; C-27, C-21, C-05).

For one client this reads the client's backup jobs through that client's adapter and lists the ones a person must look
at: failed (including a finished backup whose boot check failed), missed (never started) and long-running, each with the
reason the job record gives. Every job lands in exactly one bucket, so the counts reconcile (B68-3). Failures of the
same protected asset are grouped into ONE ticket draft, however many nights it has failed (B68-2).

Read-only (D6-24). Nothing here writes: a ticket draft is data for a person, and the only backup write is the
``backup.retry-job`` lever, which this module can only dry-run (``propose_retry``); a lead approves the real retry.

Isolation (C-27). The review is built from one client's adapter only, and the adapter already drops every job of another
organization. Review results never carry a job of another client.

Untrusted text (C-12). The reason is the job record's error text, which a system or person wrote. It is checked with the
injection detector; instruction-like text is replaced by a fixed sentence and the job is listed for a person to read.
No model is called: the thresholds are plain configuration (D-022).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from adapters.backup import BackupAdapter
from core.guard import detect_injection
from core.levers import InvokeResult, LeverRunner

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
REVIEW_AGENT = "triage-bot"
RETRY_LEVER = "backup.retry-job"
RETRYABLE_STATUSES = frozenset({"failed", "missed"})
WITHHELD_REASON = "The job record's error text looks like an instruction, so it is not shown. Read the job record."
NO_REASON = "The job record gives no reason."
DRAFT_HEADER = "Draft. A person reviews and creates this ticket."

Bucket = Literal["healthy", "in-progress", "failed", "missed", "long-running"]
BUCKETS: tuple[Bucket, ...] = ("healthy", "in-progress", "failed", "missed", "long-running")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,79}$")


class ReviewError(ValueError):
    """The input is bad (config, as-of time, adapter); nothing was reviewed."""


class ReviewConfig(BaseModel):
    """The workflow's configuration; unknown keys fail the load (STD-CF-3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: Literal[1]
    note: str = Field(default="", alias="_note")
    review_window_hours: float = Field(gt=0, le=72)  # jobs scheduled in this many hours before as_of are reviewed
    long_running_factor: float = Field(gt=1, le=20)  # running longer than expected duration times this is long-running
    missed_grace_minutes: int = Field(ge=0, le=1440)  # a scheduled job with no start this long after its time is missed
    repeat_min_failures: int = Field(ge=2, le=50)  # this many failures of one asset make a repeated failure
    lookback_days: int = Field(ge=1, le=60)  # how far back failures of one asset are grouped


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ReviewConfig:
    try:
        return ReviewConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise ReviewError(f"cannot load backup review config from {path}: {exc}") from exc


def utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` allowed) as UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReviewError(f"{value!r} is not an ISO 8601 timestamp") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Finding:
    """One job a person must look at."""

    job_id: str
    job_type: str
    asset: str
    bucket: Bucket
    reason: str
    scheduled_start: str
    boot_check: str | None  # passed / failed / not-run for an image job, None for a SaaS job
    reason_withheld: bool = False


@dataclass(frozen=True, slots=True)
class Review:
    client: str
    as_of: datetime
    reviewed: int  # jobs scheduled inside the review window
    history: int  # older jobs of this client, kept only to spot repeated failures
    counts: Mapping[str, int]  # bucket -> jobs in the window
    counts_by_type: Mapping[str, Mapping[str, int]]  # job type -> bucket -> jobs
    findings: tuple[Finding, ...]
    flagged: tuple[str, ...]  # job ids whose reason was withheld

    @property
    def reconciles(self) -> bool:
        """Every reviewed job is in exactly one bucket, overall and per job type."""
        per_type_total = sum(sum(b.values()) for b in self.counts_by_type.values())
        return sum(self.counts.values()) == self.reviewed == per_type_total

    def of(self, bucket: Bucket) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.bucket == bucket)


@dataclass(frozen=True, slots=True)
class TicketDraft:
    """One draft ticket for one protected asset. Data for a person; nothing here creates a ticket."""

    client: str
    asset: str
    job_type: str
    job_ids: tuple[str, ...]  # every failed or missed run of this asset in the lookback, oldest first
    failures: int
    repeated: bool
    priority: Literal["normal", "high"]
    title: str
    body: str
    retry_job_id: str | None  # the latest run the lever may retry (failed or missed), if any


@dataclass(frozen=True, slots=True)
class RetryProposal:
    job_id: str
    ok: bool
    reason: str
    result: InvokeResult | None = None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return utc(value)
    except ReviewError:
        return None


def _safe_reason(text: Any) -> tuple[str, bool]:
    if not isinstance(text, str) or not text.strip():
        return NO_REASON, False
    if detect_injection(text).flagged:
        return WITHHELD_REASON, True
    return text.strip()[:300], False


def _safe_asset(name: Any) -> str:
    return name if isinstance(name, str) and _SAFE_NAME.fullmatch(name) else "(asset name withheld)"


def classify(job: Mapping[str, Any], as_of: datetime, config: ReviewConfig) -> tuple[Bucket, str, bool]:
    """Bucket, reason and whether the reason was withheld for one job record."""
    status = job.get("status")
    boot = job.get("bootCheck")
    boot_status = boot.get("status") if isinstance(boot, dict) else None
    if status == "failed":
        reason, withheld = _safe_reason(job.get("errorMessage"))
        return "failed", reason, withheld
    if status == "success":
        if boot_status == "failed":
            detail, withheld = _safe_reason(boot.get("detail") if isinstance(boot, dict) else None)
            return "failed", f"The backup finished but the boot check failed. {detail}", withheld
        return "healthy", "", False
    if status == "missed":
        reason, withheld = _safe_reason(job.get("errorMessage"))
        return "missed", reason, withheld
    scheduled = _when(job.get("scheduledStart"))
    if status == "scheduled":
        grace = timedelta(minutes=config.missed_grace_minutes)
        if scheduled is not None and as_of > scheduled + grace:
            return (
                "missed",
                f"No start was recorded within {config.missed_grace_minutes} minutes of the schedule.",
                False,
            )
        return "in-progress", "", False
    if status == "running":
        started = _when(job.get("startedAt")) or scheduled
        expected = job.get("expectedDurationMinutes")
        if started is not None and isinstance(expected, int) and expected > 0:
            elapsed = (as_of - started).total_seconds() / 60
            if elapsed > expected * config.long_running_factor:
                return (
                    "long-running",
                    f"Running for {int(elapsed)} minutes; the job record expects about {expected}.",
                    False,
                )
        return "in-progress", "", False
    return "failed", "The job status is not one this review knows. Read the job record.", False


def _all_jobs(adapter: BackupAdapter) -> list[dict[str, Any]]:
    result = adapter.list_jobs()
    if not result.ok or result.data is None:
        raise ReviewError(f"cannot list backup jobs for {adapter.client}: {result.reason}")
    return result.data


def review_client(adapter: BackupAdapter, as_of: datetime, config: ReviewConfig) -> Review:
    """The daily review for the one client the adapter is bound to. Read-only."""
    jobs = _all_jobs(adapter)
    start = as_of - timedelta(hours=config.review_window_hours)
    counts: dict[str, int] = dict.fromkeys(BUCKETS, 0)
    by_type: dict[str, dict[str, int]] = {}
    findings: list[Finding] = []
    flagged: list[str] = []
    reviewed = 0
    for job in jobs:
        scheduled = _when(job.get("scheduledStart"))
        if scheduled is None or scheduled < start:
            continue
        reviewed += 1
        bucket, reason, withheld = classify(job, as_of, config)
        counts[bucket] += 1
        job_type = str(job.get("jobType"))
        by_type.setdefault(job_type, dict.fromkeys(BUCKETS, 0))[bucket] += 1
        if bucket in ("healthy", "in-progress"):
            continue
        boot = job.get("bootCheck")
        findings.append(
            Finding(
                job_id=str(job.get("id")),
                job_type=job_type,
                asset=_safe_asset(job.get("assetName")),
                bucket=bucket,
                reason=reason,
                scheduled_start=str(job.get("scheduledStart")),
                boot_check=boot.get("status") if isinstance(boot, dict) else None,
                reason_withheld=withheld,
            )
        )
        if withheld:
            flagged.append(str(job.get("id")))
    return Review(
        client=adapter.client,
        as_of=as_of,
        reviewed=reviewed,
        history=len(jobs) - reviewed,
        counts=counts,
        counts_by_type=by_type,
        findings=tuple(findings),
        flagged=tuple(flagged),
    )


def review_clients(adapters: Mapping[str, BackupAdapter], as_of: datetime, config: ReviewConfig) -> dict[str, Review]:
    """One review per client. A key that is not its adapter's own client is refused before anything is read (TEN-04)."""
    for key, adapter in adapters.items():
        if adapter.client != key:
            raise ReviewError("an adapter is filed under a client that is not its own; nothing was reviewed")
    return {key: review_client(adapter, as_of, config) for key, adapter in sorted(adapters.items())}


def draft_tickets(adapter: BackupAdapter, review: Review, config: ReviewConfig) -> tuple[TicketDraft, ...]:
    """One draft per asset that failed or missed in the review window; repeated failures are one draft, not many."""
    if adapter.client != review.client:
        raise ReviewError("the review belongs to a different client than the adapter; no draft made")
    jobs = _all_jobs(adapter)
    since = review.as_of - timedelta(days=config.lookback_days)
    today = {f.job_id for f in review.findings if f.bucket in ("failed", "missed")}
    groups: dict[tuple[str, str], list[tuple[dict[str, Any], str, bool]]] = defaultdict(list)
    for job in jobs:
        scheduled = _when(job.get("scheduledStart"))
        if scheduled is None or scheduled < since or scheduled > review.as_of:
            continue
        bucket, reason, withheld = classify(job, review.as_of, config)
        if bucket in ("failed", "missed"):
            groups[(_safe_asset(job.get("assetName")), str(job.get("jobType")))].append((job, reason, withheld))
    drafts: list[TicketDraft] = []
    for (asset, job_type), runs in sorted(groups.items()):
        if not any(str(job.get("id")) in today for job, _, _ in runs):
            continue  # failed last week, fine today: not a daily-review item
        runs.sort(key=lambda r: (str(r[0].get("scheduledStart")), str(r[0].get("id"))))
        ids = tuple(str(job.get("id")) for job, _, _ in runs)
        latest_job, latest_reason, _ = runs[-1]
        retryable = [j for j, _, _ in runs if j.get("status") in RETRYABLE_STATUSES]
        repeated = len(runs) >= config.repeat_min_failures
        suffix = f" ({len(runs)} runs in {config.lookback_days} days)" if repeated else ""
        lines = [
            DRAFT_HEADER,
            "",
            f"Client: {review.client}",
            f"Protected item: {asset} ({job_type})",
            f"Failed or missed runs: {', '.join(ids)}",
            f"Latest run: {latest_job.get('scheduledStart')}, {runs[-1][0].get('status')}",
            f"Latest reason from the job record: {latest_reason}",
            "Repeated: " + ("yes, one ticket for all of these runs" if repeated else "no"),
        ]
        drafts.append(
            TicketDraft(
                client=review.client,
                asset=asset,
                job_type=job_type,
                job_ids=ids,
                failures=len(runs),
                repeated=repeated,
                priority="high" if repeated else "normal",
                title=f"Backup failed: {asset}{suffix}",
                body="\n".join(lines),
                retry_job_id=str(retryable[-1].get("id")) if retryable else None,
            )
        )
    return tuple(drafts)


def propose_retry(
    job_id: str, adapter: BackupAdapter, runner: LeverRunner, *, agent: str = REVIEW_AGENT
) -> RetryProposal:
    """Dry-run ``backup.retry-job`` for one job of this client. Nothing is ever executed here.

    The job is looked up in the client's own adapter first (STD-LV-9): another client's job answers like an absent one
    and the lever is not called. Only a failed or missed job may be retried. A person turns an ok dry-run into a
    proposal for a lead; the lever is R2 and a lead's approval is bound to these exact params.
    """
    found = adapter.get_job(job_id)
    if not found.ok or found.data is None:
        return RetryProposal(job_id, False, found.reason)
    status = found.data.get("status")
    if status not in RETRYABLE_STATUSES:
        return RetryProposal(
            job_id, False, f"a job with status {status!r} is not retried; only failed or missed jobs are"
        )
    result = runner.invoke(RETRY_LEVER, {"job_id": job_id}, identity=agent, client=adapter.client, mode="dry-run")
    return RetryProposal(job_id, result.ok, result.reason, result)


def propose_retries(
    adapter: BackupAdapter, drafts: tuple[TicketDraft, ...], runner: LeverRunner, *, agent: str = REVIEW_AGENT
) -> tuple[RetryProposal, ...]:
    """One dry-run retry per draft that has a retryable run: repeated failures are retried once, not once per night."""
    return tuple(
        propose_retry(d.retry_job_id, adapter, runner, agent=agent) for d in drafts if d.retry_job_id is not None
    )


def summary(review: Review, drafts: tuple[TicketDraft, ...] = ()) -> dict[str, Any]:
    """A plain summary for the CLI and reports: ids, assets, reasons and counts, never another client's data."""
    return {
        "client": review.client,
        "as_of": review.as_of.isoformat().replace("+00:00", "Z"),
        "reviewed": review.reviewed,
        "history": review.history,
        "counts": dict(review.counts),
        "counts_by_type": {k: dict(v) for k, v in sorted(review.counts_by_type.items())},
        "reconciles": review.reconciles,
        "findings": [
            {
                "job_id": f.job_id,
                "job_type": f.job_type,
                "asset": f.asset,
                "bucket": f.bucket,
                "reason": f.reason,
                "boot_check": f.boot_check,
            }
            for f in review.findings
        ],
        "needs_a_person_to_read": list(review.flagged),
        "ticket_drafts": [
            {
                "title": d.title,
                "asset": d.asset,
                "jobs": list(d.job_ids),
                "repeated": d.repeated,
                "priority": d.priority,
                "retry_job_id": d.retry_job_id,
            }
            for d in drafts
        ],
    }
