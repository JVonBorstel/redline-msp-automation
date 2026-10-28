"""What the client health report says and when it says "needs attention" (B-71). Words and thresholds, no data access.

Shared by the builder (``health.py``) and the validator (``reconcile.py``). It holds no source figure: both sides
compute their own numbers and then apply the same wording, so a change here changes what both of them expect.

Every threshold is a stand-in chosen for the synthetic fixtures (UNVERIFIED against any real client's risk appetite).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass

Metric = int | float | str | None
Metrics = Mapping[str, Metric]

SECTION_KEYS: tuple[str, ...] = ("tickets", "baseline", "patching", "backup", "awareness")
SECTION_TITLES: dict[str, str] = {
    "tickets": "Service desk tickets",
    "baseline": "Tenant baseline",
    "patching": "Device patching",
    "backup": "Backups",
    "awareness": "Security awareness (service-level)",
}

# -- stand-in thresholds (UNVERIFIED) -------------------------------------------------------------------------------
OPEN_SHARE_ATTENTION_PCT = 50  # more than this share of the month's tickets still open
PATCH_STALE_DAYS = 30  # last successful patch run older than this many days before the source date
CLICK_ATTENTION_PCT = 10  # more than this share of simulated phishing emails clicked
VAULT_MIN_SCORE = 70  # vault audit score below this (0 to 100)

METRIC_LABELS: dict[str, str] = {
    "tickets.opened": "Tickets opened this month",
    "tickets.resolved": "Tickets resolved",
    "tickets.open": "Tickets still open",
    "tickets.resolved_pct": "Resolved share (%)",
    "tickets.median_hours_to_resolve": "Median hours from opened to resolved (last update stands in for resolved time)",
    "baseline.findings": "Baseline findings",
    "baseline.high": "High severity",
    "baseline.medium": "Medium severity",
    "baseline.low": "Low severity",
    "baseline.new": "New since last month",
    "baseline.resolved": "Resolved since last month",
    "baseline.unchanged": "Unchanged since last month",
    "baseline.ca_changes": "Conditional Access changes since last month",
    "patching.devices": "Devices",
    "patching.up_to_date": "Devices with nothing waiting",
    "patching.up_to_date_pct": "Devices with nothing waiting (%)",
    "patching.critical_pending_devices": "Devices with a critical update waiting",
    "patching.critical_pending_updates": "Critical updates waiting",
    "patching.not_patched_30d": f"Devices not patched for more than {PATCH_STALE_DAYS} days",
    "backup.jobs": "Backup jobs scheduled this month",
    "backup.success": "Succeeded",
    "backup.failed": "Failed",
    "backup.missed": "Missed",
    "backup.other": "Running or not yet due",
    "backup.boot_check_failed": "Test restores (boot checks) that failed",
    "backup.success_pct": "Succeeded (%)",
    "phish.campaigns": "Phishing simulation campaigns this month",
    "phish.sent": "Simulated emails sent",
    "phish.clicked": "Clicked",
    "phish.reported": "Reported with the report button",
    "phish.click_pct": "Clicked (%)",
    "phish.report_pct": "Reported (%)",
    "vault.audit_score": "Password vault audit score (0 to 100)",
    "vault.users_total": "People who should have a vault",
    "vault.users_enrolled": "People enrolled",
    "vault.enrolled_pct": "Enrolled (%)",
    "vault.mfa_enforced": "Vault MFA enforced",
}
CHANNEL_PREFIX = "tickets.channel."

# Display order of metric keys inside each section; ticket channels are appended in sorted order.
SECTION_METRICS: dict[str, tuple[str, ...]] = {
    s: tuple(k for k in METRIC_LABELS if k.split(".")[0] == p)
    for s, p in (("tickets", "tickets"), ("baseline", "baseline"), ("patching", "patching"), ("backup", "backup"))
} | {"awareness": tuple(k for k in METRIC_LABELS if k.split(".")[0] in ("phish", "vault"))}


def label_for(key: str) -> str:
    if key.startswith(CHANNEL_PREFIX):
        return f"Opened by {key[len(CHANNEL_PREFIX) :]}"
    return METRIC_LABELS[key]


def show(value: Metric) -> str:
    """The text a figure has in the report, the one form the builder writes and the validator compares."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _n(m: Metrics, key: str) -> float:
    value = m.get(key)
    return float(value) if isinstance(value, int | float) else 0.0


# -- attention rules ------------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    section: str
    template: str  # {metric.key} is replaced by the figure, shown as a metric span
    test: Callable[[Metrics], bool]


RULES: tuple[Rule, ...] = (
    Rule(
        "tickets.open-share",
        "tickets",
        "{tickets.open} of {tickets.opened} tickets opened this month are still open.",
        lambda m: _n(m, "tickets.open") * 100 > OPEN_SHARE_ATTENTION_PCT * _n(m, "tickets.opened"),
    ),
    Rule(
        "baseline.high",
        "baseline",
        "{baseline.high} high-severity baseline findings are open.",
        lambda m: _n(m, "baseline.high") > 0,
    ),
    Rule(
        "baseline.ca-changed",
        "baseline",
        "{baseline.ca_changes} Conditional Access changes since last month; a person confirms they were intended.",
        lambda m: _n(m, "baseline.ca_changes") > 0,
    ),
    Rule(
        "patching.critical",
        "patching",
        "{patching.critical_pending_devices} of {patching.devices} devices have a critical update waiting.",
        lambda m: _n(m, "patching.critical_pending_devices") > 0,
    ),
    Rule(
        "patching.stale",
        "patching",
        f"{{patching.not_patched_30d}} devices have not been patched for more than {PATCH_STALE_DAYS} days.",
        lambda m: _n(m, "patching.not_patched_30d") > 0,
    ),
    Rule(
        "backup.failed",
        "backup",
        "{backup.failed} of {backup.jobs} backup jobs failed.",
        lambda m: _n(m, "backup.failed") > 0,
    ),
    Rule(
        "backup.missed",
        "backup",
        "{backup.missed} of {backup.jobs} backup jobs never started.",
        lambda m: _n(m, "backup.missed") > 0,
    ),
    Rule(
        "backup.boot-check",
        "backup",
        "{backup.boot_check_failed} test restores (boot checks) failed.",
        lambda m: _n(m, "backup.boot_check_failed") > 0,
    ),
    Rule(
        "awareness.clicks",
        "awareness",
        f"{{phish.clicked}} of {{phish.sent}} simulated phishing emails were clicked "
        f"(more than {CLICK_ATTENTION_PCT}%).",
        lambda m: _n(m, "phish.sent") > 0 and _n(m, "phish.clicked") * 100 > CLICK_ATTENTION_PCT * _n(m, "phish.sent"),
    ),
    Rule(
        "awareness.vault-score",
        "awareness",
        f"The password vault audit score is {{vault.audit_score}} out of 100 (below {VAULT_MIN_SCORE}).",
        lambda m: m.get("vault.audit_score") is not None and _n(m, "vault.audit_score") < VAULT_MIN_SCORE,
    ),
    Rule(
        "awareness.vault-mfa",
        "awareness",
        "Vault MFA is not enforced.",
        lambda m: m.get("vault.mfa_enforced") == "no",
    ),
    Rule(
        "awareness.vault-enrolment",
        "awareness",
        "{vault.users_enrolled} of {vault.users_total} people are enrolled in the password vault.",
        lambda m: m.get("vault.users_total") is not None and _n(m, "vault.users_enrolled") < _n(m, "vault.users_total"),
    ),
)
RULES_BY_ID: dict[str, Rule] = {r.id: r for r in RULES}


def firing(section: str, metrics: Metrics) -> tuple[str, ...]:
    return tuple(r.id for r in RULES if r.section == section and r.test(metrics))


def status_of(section: str, metrics: Metrics) -> str:
    return "attention" if firing(section, metrics) else "healthy"


_PLACEHOLDER = re.compile(r"\{([a-z_0-9.]+)\}")


def fill(template: str, metrics: Metrics) -> str:
    return _PLACEHOLDER.sub(lambda m: show(metrics.get(m.group(1))), template)


def placeholders(template: str) -> tuple[str, ...]:
    return tuple(_PLACEHOLDER.findall(template))


# -- summary --------------------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Fact:
    section: str
    template: str  # one phrase; a figure that is n/a drops the fact


FACTS: tuple[Fact, ...] = (
    Fact("tickets", "{tickets.opened} tickets opened"),
    Fact("tickets", "{tickets.resolved} tickets resolved"),
    Fact("baseline", "{baseline.high} high-severity baseline findings"),
    Fact(
        "patching", "{patching.critical_pending_devices} of {patching.devices} devices with a critical update waiting"
    ),
    Fact("backup", "{backup.failed} failed and {backup.missed} missed of {backup.jobs} backup jobs"),
    Fact("awareness", "{phish.click_pct}% of simulated phishing emails clicked"),
    Fact("awareness", "a password vault audit score of {vault.audit_score}"),
)


def facts_for(available: Mapping[str, Metrics]) -> tuple[str, ...]:
    """The fact phrases for the sections that have data, in a fixed order; a phrase with an n/a figure is dropped."""
    out: list[str] = []
    for fact in FACTS:
        metrics = available.get(fact.section)
        if metrics is None:
            continue
        keys = placeholders(fact.template)
        if any(metrics.get(k) is None for k in keys):
            continue
        out.append(fill(fact.template, metrics))
    return tuple(out)


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def computed_summary(
    name: str,
    period_label: str,
    facts: tuple[str, ...],
    attention: tuple[str, ...],
    healthy: tuple[str, ...],
    missing: tuple[str, ...],
) -> str:
    """The plain-English summary built only from computed figures and section names."""
    parts = [f"{name}, {period_label}."]
    if facts:
        parts.append(f"This month: {_join(list(facts))}.")
    if attention:
        parts.append(f"Needs attention: {_join([SECTION_TITLES[s].lower() for s in attention])}.")
    if healthy:
        parts.append(f"No concerns in: {_join([SECTION_TITLES[s].lower() for s in healthy])}.")
    if missing:
        parts.append(f"No data for this period: {_join([SECTION_TITLES[s].lower() for s in missing])}.")
    return " ".join(parts)


_ISO = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_NUMBER_WORDS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|dozen|half|double|triple|twice)\b",
    re.I,
)
MAX_SUMMARY_CHARS = 1500


def number_tokens(text: str, period_label: str) -> Counter[str]:
    """Figures in a text, not counting the period label or ISO dates."""
    return Counter(_NUMBER.findall(_ISO.sub(" ", text.replace(period_label, " "))))


def check_rephrase(candidate: str, computed: str, facts: tuple[str, ...], period_label: str) -> str | None:
    """None when the rephrase is safe to show; otherwise the reason it is not.

    It must keep every fact phrase word for word, carry exactly the figures of the computed summary (no more, no fewer),
    spell no figure out in words, and contain no markup or link. Anything else falls back to the computed text.
    """
    text = candidate.strip()
    if not text:
        return "empty"
    if len(text) > MAX_SUMMARY_CHARS:
        return "too long"
    if re.search(r"[<>]|https?:|www\.|\bftp:", text, re.I):
        return "markup or link"
    if "\n" in text or "\r" in text:
        return "not a single paragraph"
    missing = [f for f in facts if f not in text]
    if missing:
        return f"dropped or reworded a fact: {missing[0]!r}"
    if number_tokens(text, period_label) != number_tokens(computed, period_label):
        return "figures differ from the computed summary"
    if _NUMBER_WORDS.search(text.replace(period_label, " ")) and not _NUMBER_WORDS.search(computed):
        return "a figure spelled out in words"
    return None
