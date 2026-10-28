"""What the QBR draft says and when it says "win", "risk" or "suggestion" (B-72). Words and thresholds, no data access.

Shared by the builder (``qbr.py``) and the validator (``reconcile.py``). It holds no source figure: both sides compute
their own numbers and then apply the same wording, so a change here changes what both of them expect.

Thresholds are the B-71 stand-ins (imported, not copied) and are UNVERIFIED against any real client's risk appetite.
Nothing here claims a saving, a cost, an avoided incident or a guarantee: a win is "this figure went the right way in
the fixtures", a suggestion is a topic to discuss.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from workflows.reporting.health import policy as health_policy
from workflows.reporting.health.sources import HealthError

Metric = int | float | None

SECTIONS: tuple[str, ...] = health_policy.SECTION_KEYS
SECTION_TITLES: Mapping[str, str] = health_policy.SECTION_TITLES
CLICK_ATTENTION_PCT = health_policy.CLICK_ATTENTION_PCT
VAULT_MIN_SCORE = health_policy.VAULT_MIN_SCORE
PATCH_STALE_DAYS = health_policy.PATCH_STALE_DAYS
_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")


# -- the figures a QBR shows -----------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Spec:
    key: str  # a health report metric key (workflows.reporting.health.METRIC_LABELS)
    kind: str  # flow (summed over the months with data) | point (latest month with data) | derived (from two flows)
    label: str
    numerator: str = ""
    denominator: str = ""

    @property
    def section(self) -> str:
        return section_of(self.key)


def section_of(key: str) -> str:
    prefix = key.split(".")[0]
    return "awareness" if prefix in ("phish", "vault") else prefix


SPECS: tuple[Spec, ...] = (
    Spec("tickets.opened", "flow", "Tickets opened"),
    Spec("tickets.resolved", "flow", "Tickets resolved"),
    Spec("tickets.resolved_pct", "derived", "Resolved share (%)", "tickets.resolved", "tickets.opened"),
    Spec("baseline.findings", "point", "Baseline findings at the latest run"),
    Spec("baseline.high", "point", "High-severity baseline findings at the latest run"),
    Spec("patching.devices", "point", "Devices at the latest patch status"),
    Spec("patching.critical_pending_devices", "point", "Devices with a critical update waiting"),
    Spec("patching.not_patched_30d", "point", f"Devices not patched for more than {PATCH_STALE_DAYS} days"),
    Spec("backup.jobs", "flow", "Backup jobs scheduled"),
    Spec("backup.success", "flow", "Backup jobs succeeded"),
    Spec("backup.failed", "flow", "Backup jobs failed"),
    Spec("backup.missed", "flow", "Backup jobs missed"),
    Spec("backup.success_pct", "derived", "Backup jobs succeeded (%)", "backup.success", "backup.jobs"),
    Spec("phish.sent", "flow", "Simulated phishing emails sent"),
    Spec("phish.clicked", "flow", "Simulated phishing emails clicked"),
    Spec("phish.click_pct", "derived", "Clicked (%)", "phish.clicked", "phish.sent"),
    Spec("vault.audit_score", "point", "Password vault audit score at the latest check (0 to 100)"),
)
SPEC_BY_KEY: Mapping[str, Spec] = {s.key: s for s in SPECS}
KEYS: tuple[str, ...] = tuple(s.key for s in SPECS)


def show(value: Metric) -> str:
    """The text a figure has in the page: the one form the builder writes and the validator compares."""
    return health_policy.show(value)


def signed(value: Metric) -> str:
    """A change: ``+3``, ``-2``, ``0``, ``+1.5``, ``0.0`` or ``n/a`` when the two periods cannot be compared."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return "0.0" if value == 0 else f"{value:+.1f}"
    return "0" if value == 0 else f"{value:+d}"


def difference(current: Metric, previous: Metric) -> Metric:
    if current is None or previous is None:
        return None
    if isinstance(current, float) or isinstance(previous, float):
        return float((Decimal(str(current)) - Decimal(str(previous))).quantize(Decimal("0.1")))
    return current - previous


def comparable(spec: Spec, current_months: int, previous_months: int) -> bool:
    """Two quarters are compared only when both have data for the section, and, for a sum, the same number of months
    (a quarter with one month of tickets is not set against a quarter with three)."""
    if current_months == 0 or previous_months == 0:
        return False
    return spec.kind == "point" or current_months == previous_months


# -- quarters --------------------------------------------------------------------------------------------------------
class QbrError(HealthError):
    """The input is bad (client, quarter, dates, a source of another client) or the draft did not reconcile."""


def parse_quarter(quarter: str) -> tuple[int, int]:
    match = _QUARTER.fullmatch(quarter) if isinstance(quarter, str) else None
    if match is None:
        raise QbrError(f"quarter must look like 2026-Q4, got {quarter!r}")
    return int(match.group(1)), int(match.group(2))


def months_of(quarter: str) -> tuple[str, ...]:
    year, q = parse_quarter(quarter)
    return tuple(f"{year}-{m:02d}" for m in range(3 * q - 2, 3 * q + 1))


def previous_quarter(quarter: str) -> str:
    year, q = parse_quarter(quarter)
    return f"{year}-Q{q - 1}" if q > 1 else f"{year - 1}-Q4"


# -- keys of the figures in the page ---------------------------------------------------------------------------------
def q_key(quarter: str, key: str) -> str:
    return f"q.{quarter}.{key}"


def m_key(month: str, key: str) -> str:
    return f"m.{month}.{key}"


def d_key(key: str) -> str:
    return f"d.{key}"


def cov_key(quarter: str, section: str) -> str:
    return f"cov.{quarter}.{section}"


# -- wins, risks, suggestions ----------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Context:
    """What a rule may look at: the current quarter, the change since the previous one, and how many months had data."""

    current: Mapping[str, Metric]
    delta: Mapping[str, Metric]
    months: Mapping[str, int]  # section -> months with data in the current quarter


def _num(value: Metric) -> float:
    return float(value) if value is not None else 0.0


def _down(key: str) -> Callable[[Context], bool]:
    return lambda c: c.delta.get(key) is not None and _num(c.delta[key]) < 0


def _up(key: str) -> Callable[[Context], bool]:
    return lambda c: c.delta.get(key) is not None and _num(c.delta[key]) > 0


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    kind: str  # win | risk
    template: str  # {cur:key} {prev:key} {delta:key} are figures (shown as metric spans); {quarter} is plain text
    test: Callable[[Context], bool]


RULES: tuple[Rule, ...] = (
    Rule(
        "win.high-findings-down",
        "win",
        "High-severity baseline findings went from {prev:baseline.high} to {cur:baseline.high}.",
        _down("baseline.high"),
    ),
    Rule(
        "win.critical-patch-down",
        "win",
        "Devices with a critical update waiting went from {prev:patching.critical_pending_devices} to "
        "{cur:patching.critical_pending_devices}.",
        _down("patching.critical_pending_devices"),
    ),
    Rule(
        "win.stale-patch-down",
        "win",
        f"Devices not patched for more than {PATCH_STALE_DAYS} days went from "
        "{prev:patching.not_patched_30d} to {cur:patching.not_patched_30d}.",
        _down("patching.not_patched_30d"),
    ),
    Rule(
        "win.backup-failed-down",
        "win",
        "Failed backup jobs went from {prev:backup.failed} to {cur:backup.failed}.",
        _down("backup.failed"),
    ),
    Rule(
        "win.click-down",
        "win",
        "The share of simulated phishing emails clicked went from {prev:phish.click_pct}% to {cur:phish.click_pct}%.",
        _down("phish.click_pct"),
    ),
    Rule(
        "win.vault-up",
        "win",
        "The password vault audit score went from {prev:vault.audit_score} to {cur:vault.audit_score}.",
        _up("vault.audit_score"),
    ),
    Rule(
        "win.resolved-share-up",
        "win",
        "The share of tickets resolved went from {prev:tickets.resolved_pct}% to {cur:tickets.resolved_pct}%.",
        _up("tickets.resolved_pct"),
    ),
    Rule(
        "win.no-failed-backups",
        "win",
        "None of the {cur:backup.jobs} backup jobs scheduled in {quarter} failed or were missed.",
        lambda c: (
            _num(c.current.get("backup.jobs")) > 0
            and c.current.get("backup.failed") == 0
            and c.current.get("backup.missed") == 0
        ),
    ),
    Rule(
        "risk.high-findings",
        "risk",
        "{cur:baseline.high} high-severity baseline findings were open at the latest baseline run in {quarter}.",
        lambda c: _num(c.current.get("baseline.high")) > 0,
    ),
    Rule(
        "risk.high-findings-up",
        "risk",
        "High-severity baseline findings went from {prev:baseline.high} to {cur:baseline.high}.",
        _up("baseline.high"),
    ),
    Rule(
        "risk.critical-patch",
        "risk",
        "{cur:patching.critical_pending_devices} of {cur:patching.devices} devices have a critical update waiting.",
        lambda c: _num(c.current.get("patching.critical_pending_devices")) > 0,
    ),
    Rule(
        "risk.critical-patch-up",
        "risk",
        "Devices with a critical update waiting went from {prev:patching.critical_pending_devices} to "
        "{cur:patching.critical_pending_devices}.",
        _up("patching.critical_pending_devices"),
    ),
    Rule(
        "risk.stale-patch",
        "risk",
        f"{{cur:patching.not_patched_30d}} devices have not been patched for more than {PATCH_STALE_DAYS} days.",
        lambda c: _num(c.current.get("patching.not_patched_30d")) > 0,
    ),
    Rule(
        "risk.backup-failed",
        "risk",
        "{cur:backup.failed} failed and {cur:backup.missed} missed of {cur:backup.jobs} backup jobs scheduled in "
        "{quarter}.",
        lambda c: _num(c.current.get("backup.failed")) > 0 or _num(c.current.get("backup.missed")) > 0,
    ),
    Rule(
        "risk.backup-failed-up",
        "risk",
        "Failed backup jobs went from {prev:backup.failed} to {cur:backup.failed}.",
        _up("backup.failed"),
    ),
    Rule(
        "risk.click-rate",
        "risk",
        f"{{cur:phish.clicked}} of {{cur:phish.sent}} simulated phishing emails were clicked "
        f"(more than {CLICK_ATTENTION_PCT}%).",
        lambda c: (
            _num(c.current.get("phish.sent")) > 0
            and _num(c.current.get("phish.clicked")) * 100 > CLICK_ATTENTION_PCT * _num(c.current.get("phish.sent"))
        ),
    ),
    Rule(
        "risk.click-up",
        "risk",
        "The share of simulated phishing emails clicked went from {prev:phish.click_pct}% to {cur:phish.click_pct}%.",
        _up("phish.click_pct"),
    ),
    Rule(
        "risk.vault-score",
        "risk",
        f"The password vault audit score is {{cur:vault.audit_score}} out of 100 (below {VAULT_MIN_SCORE}).",
        lambda c: (
            c.current.get("vault.audit_score") is not None and _num(c.current["vault.audit_score"]) < VAULT_MIN_SCORE
        ),
    ),
    Rule(
        "risk.vault-down",
        "risk",
        "The password vault audit score went from {prev:vault.audit_score} to {cur:vault.audit_score}.",
        _down("vault.audit_score"),
    ),
    Rule(
        "risk.resolved-share-down",
        "risk",
        "The share of tickets resolved went from {prev:tickets.resolved_pct}% to {cur:tickets.resolved_pct}%.",
        _down("tickets.resolved_pct"),
    ),
)
RULES_BY_ID: Mapping[str, Rule] = {r.id: r for r in RULES}
GAP_PREFIX = "risk.gap."
GAP_TEMPLATE = "There is no {title} data for {quarter}, so nothing is reported for it. This is a gap, not a zero."

# Suggestions: a topic for the account manager to raise, tied to the risks above. No figures, no promises.
SUGGESTIONS: Mapping[str, str] = {
    "high-findings": (
        "Go through the open high-severity baseline findings together and agree who owns each one and by when."
    ),
    "critical-patch": (
        "Agree a window to install the waiting critical updates, and confirm which devices cannot be patched."
    ),
    "stale-patch": (
        "Look at why some devices have not patched recently (offline, retired, excluded) and decide what to do."
    ),
    "backup-failed": "Review the failed and missed backup jobs and confirm the next test restore.",
    "click-rate": "Talk through the latest phishing simulation and whether more awareness training fits.",
    "vault-score": "Review the password vault audit findings and who is not yet enrolled.",
    "resolved-share": "Look at which kinds of requests stay open longest and whether priorities need agreeing.",
    "gap": "Decide how to get the missing data into the next review, or agree that it is not needed.",
}
RISK_TO_SUGGESTION: Mapping[str, str] = {
    "risk.high-findings": "high-findings",
    "risk.high-findings-up": "high-findings",
    "risk.critical-patch": "critical-patch",
    "risk.critical-patch-up": "critical-patch",
    "risk.stale-patch": "stale-patch",
    "risk.backup-failed": "backup-failed",
    "risk.backup-failed-up": "backup-failed",
    "risk.click-rate": "click-rate",
    "risk.click-up": "click-rate",
    "risk.vault-score": "vault-score",
    "risk.vault-down": "vault-score",
    "risk.resolved-share-down": "resolved-share",
}
SUGGESTION_PREFIX = "rec."


def suggestion_id(risk_id: str) -> str:
    if risk_id.startswith(GAP_PREFIX):
        return SUGGESTION_PREFIX + "gap"
    return SUGGESTION_PREFIX + RISK_TO_SUGGESTION[risk_id]


def suggestion_text(rec_id: str) -> str:
    return SUGGESTIONS[rec_id.removeprefix(SUGGESTION_PREFIX)]


def evaluate(context: Context) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """(win ids, risk ids, suggestion ids) in a fixed order. A section with no data in the quarter is a gap risk."""
    wins = tuple(r.id for r in RULES if r.kind == "win" and r.test(context))
    risks = [r.id for r in RULES if r.kind == "risk" and r.test(context)]
    risks += [GAP_PREFIX + s for s in SECTIONS if context.months.get(s, 0) == 0]
    recs: list[str] = []
    for rid in risks:
        sid = suggestion_id(rid)
        if sid not in recs:
            recs.append(sid)
    return wins, tuple(risks), tuple(recs)


_TOKEN = re.compile(r"\{(cur|prev|delta):([a-z_0-9.]+)\}|\{quarter\}|\{title\}")


def tokens(template: str) -> tuple[tuple[str, str], ...]:
    """The (which, metric key) figure placeholders in a template."""
    return tuple((m.group(1), m.group(2)) for m in _TOKEN.finditer(template) if m.group(1))


# -- text of an item ---------------------------------------------------------------------------------------------------
Render = Callable[[str | None, Metric | str], str]


def item_template(item_id: str) -> str:
    if item_id.startswith(GAP_PREFIX):
        return GAP_TEMPLATE.replace("{title}", SECTION_TITLES[item_id.removeprefix(GAP_PREFIX)].lower())
    if item_id.startswith(SUGGESTION_PREFIX):
        return suggestion_text(item_id)
    return RULES_BY_ID[item_id].template


def fill_item(item_id: str, quarter: str, values: Mapping[str, Metric], render: Render) -> str:
    """The item's sentence. ``render(None, text)`` writes plain text, ``render(key, value)`` a figure keyed ``key``."""
    template = item_template(item_id)
    previous = previous_quarter(quarter)
    out: list[str] = []
    last = 0
    for match in _TOKEN.finditer(template):
        out.append(render(None, template[last : match.start()]))
        if match.group(1) is None:
            out.append(render(None, quarter))
        else:
            which, key = match.group(1), match.group(2)
            span = {"cur": q_key(quarter, key), "prev": q_key(previous, key), "delta": d_key(key)}[which]
            out.append(render(span, values[span]))
        last = match.end()
    out.append(render(None, template[last:]))
    return "".join(out)


def plain(key: str | None, value: Metric | str) -> str:
    if key is None:
        return str(value)
    assert not isinstance(value, str)
    return signed(value) if key.startswith("d.") else show(value)
