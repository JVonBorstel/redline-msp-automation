"""Client AI-use policy draft (B-73, specs/B-73.md; W-RPT-05; C-42, C-45).

Fills ``governance/templates/client-ai-policy-starter.md`` for one client from three places: the MSP's own AI policy
(``governance/AI_POLICY.md``: the five rules and the data-class table, read at build time, so a changed policy changes
the draft), the client's industry (the unknown-text floor from ``core/guard/classify.py``), and the hosted-model
vendor register (``governance/ai-vendor-register.json``: only an entry that is approved, names this client and is
within its review date counts).

A draft, never a policy in force. It says DRAFT, "starter, review with your counsel" and "human review required", has
no reviewer, and nothing here sends it. It reads no other client's record: an approval that names other clients is
never shown. It makes no legal claim and no claim that anyone meets any law or standard.

Hosted models: this starter never lets PHI or NPI (DC-4, DC-5) or credentials (DC-6) go to a hosted tool, whatever a
register entry lists, because the gateway refuses them there (``HOSTED_REFUSED_FROM`` in ``core/gateway/gateway.py``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from core.gateway.vendor_register import VendorEntry, VendorRegister
from core.guard.classify import INDUSTRY_FLOOR
from core.paths import REPO_ROOT
from workflows.reporting.health import HealthError
from workflows.reporting.health.sources import check_client, check_date, digest, display_name
from workflows.reporting.roadmap.model import RoadmapError

DEFAULT_TEMPLATE = REPO_ROOT / "governance" / "templates" / "client-ai-policy-starter.md"
DEFAULT_POLICY = REPO_ROOT / "governance" / "AI_POLICY.md"
DEFAULT_REGISTER = REPO_ROOT / "governance" / "ai-vendor-register.json"
DEFAULT_CLIENTS = Path(__file__).with_name("data") / "clients.json"
DEFAULT_MODELS = REPO_ROOT / "config" / "models.json"
DEFAULT_REGPACKS = REPO_ROOT / "fixtures" / "regpacks" / "clients.json"

NEVER_HOSTED = ("DC-4", "DC-5", "DC-6")
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
INDUSTRY_NOTES = {
    "dental": (
        "Patient information (PHI) is the most sensitive material here: "
        "text that might hold a patient's details is treated as DC-4."
    ),
    "financial": (
        "Customer account and financial information (NPI) is the most sensitive material here: "
        "such text is treated as DC-5."
    ),
    "ria": (
        "Client account and financial information (NPI) is the most sensitive material here: "
        "such text is treated as DC-5."
    ),
    "legal": (
        "Client matter files and confidential client information are the most sensitive material here: "
        "such text is treated as DC-5."
    ),
    "accounting": (
        "Client tax and financial information (NPI) is the most sensitive material here: such text is treated as DC-5."
    ),
    "other": "Unlabelled text is treated as DC-5 until the MSP's compliance owner sets a different starting class.",
}


@dataclass(frozen=True)
class ClassRow:
    data_class: str
    meaning: str
    local: str
    hosted: str


@dataclass(frozen=True)
class Tool:
    name: str
    kind: str  # local | hosted
    note: str


@dataclass(frozen=True)
class HostedStatus:
    status: str  # not approved | approved | expired
    provider: str | None
    allowed_classes: tuple[str, ...]
    purposes: tuple[str, ...]
    review_date: str | None
    retention_terms: str | None
    config_enabled: bool | None


@dataclass(frozen=True)
class AIPolicyDraft:
    client: str
    display_name: str
    industry: str
    floor: str
    generated_on: str
    rules: tuple[str, ...]
    data_classes: tuple[ClassRow, ...]
    approved_tools: tuple[Tool, ...]
    hosted: HostedStatus
    policy_sha256: str
    template_sha256: str
    text: str
    status: str = "draft"
    reviewed_by: str | None = None
    reviewed_on: str | None = None


# -- reading the MSP's policy ---------------------------------------------------------------------------------------
def _read(path: Path, what: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError as exc:
        raise RoadmapError(f"cannot read the {what} {Path(path).name}: {exc}") from None


def _section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        raise RoadmapError(f"the AI policy has no section {heading!r}")
    rest = text[start + len(heading) :]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _first_sentence(body: str) -> str:
    plain = re.sub(r"\s*\([^)]*\)", "", body).replace("`", "").strip()
    match = re.match(r"(.+?[.!?])(\s|$)", plain)
    return match.group(1) if match else plain


def parse_rules(policy_text: str) -> tuple[str, ...]:
    """The five rules as ``**Title.** First sentence.`` lines; refuses a policy that no longer has exactly five."""
    block = _section(policy_text, "## 2. Five rules")
    rules = []
    for match in re.finditer(r"^\d+\. \*\*(.+?)\*\*\s*(.*)$", block, flags=re.M):
        sentence = _first_sentence(match.group(2))
        rules.append(f"**{match.group(1)}** {sentence}".rstrip())
    if len(rules) != 5:
        raise RoadmapError(f"the AI policy section 2 must list five rules, found {len(rules)}")
    return tuple(rules)


def parse_class_meanings(policy_text: str) -> dict[str, str]:
    block = _section(policy_text, "## 3. Data classes")
    meanings = {m.group(1): m.group(2).strip() for m in re.finditer(r"^\| (DC-[0-6]) \| (.+?) \|", block, flags=re.M)}
    if set(meanings) != {f"DC-{i}" for i in range(7)}:
        raise RoadmapError("the AI policy section 3 must define DC-0 to DC-6")
    return meanings


# -- the client's parameters ---------------------------------------------------------------------------------------
def _industry(client: str, clients_file: Path) -> str:
    try:
        raw = json.loads(Path(clients_file).read_text(encoding="utf-8"))
        industry = raw["clients"][client]["industry"]
    except (OSError, ValueError, KeyError, TypeError):
        raise RoadmapError(f"no industry is recorded for client {client!r}") from None
    if industry not in INDUSTRY_FLOOR:
        raise RoadmapError(f"industry {industry!r} is not one of {sorted(INDUSTRY_FLOOR)}")
    return str(industry)


def _regimes(client: str, path: Path) -> tuple[str, ...]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return tuple(str(r) for r in raw["clients"][client]["regimes"])
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _hosted(client: str, register: Path, today: date, models: Path) -> tuple[HostedStatus, list[VendorEntry]]:
    try:
        reg = VendorRegister.load(Path(register))
    except (OSError, ValueError) as exc:
        raise RoadmapError(f"cannot read the vendor register: {type(exc).__name__}") from None
    enabled: dict[str, bool] = {}
    try:
        providers: dict[str, Any] = json.loads(Path(models).read_text(encoding="utf-8"))["providers"]
        enabled = {name: bool(p.get("enabled")) for name, p in providers.items()}
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        enabled = {}
    mine = [v for v in reg.vendors if client in v.clients and v.status == "approved"]
    live = [v for v in mine if v.review_date is not None and today <= v.review_date]
    if live:
        classes = sorted({c for v in live for c in v.allowed_data_classes if c not in NEVER_HOSTED})
        status = HostedStatus(
            "approved",
            ", ".join(v.name for v in live),
            tuple(classes),
            tuple(sorted({p for v in live for p in v.purposes})),
            min(v.review_date for v in live if v.review_date).isoformat(),
            "; ".join(v.retention_terms for v in live if v.retention_terms),
            all(enabled.get(v.provider, False) for v in live),
        )
        return status, live
    if mine:
        late = min(v.review_date for v in mine if v.review_date)
        return HostedStatus("expired", ", ".join(v.name for v in mine), (), (), late.isoformat(), None, None), []
    return HostedStatus("not approved", None, (), (), None, None, None), []


def _rows(meanings: dict[str, str], industry: str, hosted: HostedStatus) -> tuple[ClassRow, ...]:
    own = INDUSTRY_FLOOR[industry].label
    rows = []
    for i in range(7):
        label = f"DC-{i}"
        if i <= 1:
            local = "yes"
        elif i == 2:
            local = "yes, this client only"
        elif i == 3:
            local = "minimum necessary, this client only"
        elif i == 6:
            local = "never"
        elif label == own:
            local = "minimum necessary, MSP local model only, this client only"
        else:
            local = "not expected for this client: ask the MSP compliance owner first"
        if label in NEVER_HOSTED:
            outside = "never" if label == "DC-6" else "no"
        elif label == "DC-0":
            outside = "yes, public material only" if hosted.status != "approved" else "yes"
        elif label in hosted.allowed_classes:
            outside = "yes, with the approved provider only"
        else:
            outside = "no"
        rows.append(ClassRow(label, meanings[label], local, outside))
    return tuple(rows)


def _tools(models: Path, live: list[VendorEntry], hosted: HostedStatus) -> tuple[Tool, ...]:
    tools: list[Tool] = []
    try:
        providers: dict[str, Any] = json.loads(Path(models).read_text(encoding="utf-8"))["providers"]
    except (OSError, ValueError, KeyError, TypeError):
        providers = {}
    local = providers.get("ollama")
    if isinstance(local, dict) and local.get("enabled"):
        tools.append(
            Tool(
                "MSP local model gateway",
                "local",
                "A model that runs on the MSP's own machine, reachable only from that machine. "
                "Information stays there; the MSP's logging rules still apply.",
            )
        )
    for vendor in live:
        switched = "on" if hosted.config_enabled else "off"
        tools.append(
            Tool(
                vendor.name,
                "hosted",
                f"Hosted model, approved for this client only, until {vendor.review_date}. "
                f"It also needs the provider switched on in the MSP's gateway configuration (now: {switched}).",
            )
        )
    return tuple(tools)


def _hosted_text(hosted: HostedStatus, industry: str, name: str) -> str:
    if hosted.status == "approved":
        classes = ", ".join(hosted.allowed_classes)
        purposes = ", ".join(hosted.purposes)
        return (
            f"A hosted model is approved for {name}: {hosted.provider}. Data classes: {classes} (never DC-4, DC-5 or "
            f"DC-6 under this starter). Purposes: {purposes}. Retention terms recorded: {hosted.retention_terms}. "
            f"Review due {hosted.review_date}; after that date it approves nothing until a person renews it."
        )
    if hosted.status == "expired":
        return (
            f"An approval for {hosted.provider} exists, but its review date {hosted.review_date} has passed, so it "
            "approves nothing until a person renews it."
        )
    baa = (
        " Where patient information may be involved, a signed business associate agreement for that exact "
        "service is also needed."
        if industry == "dental"
        else ""
    )
    return (
        f"No hosted AI model is approved for {name}. A hosted model is used only after the MSP's AI change approver "
        "records an approval that names the provider, this client, the data classes, the purposes, how long the "
        "provider keeps data and whether it trains on it, and a review date." + baa
    )


def _table(rows: tuple[ClassRow, ...]) -> str:
    lines = ["| Class | What it is | MSP local model | Hosted or outside AI tool |", "|---|---|---|---|"]
    lines += [f"| {r.data_class} | {r.meaning} | {r.local} | {r.hosted} |" for r in rows]
    return "\n".join(lines)


def _regime_note(regimes: tuple[str, ...], name: str) -> str:
    if not regimes:
        return (
            f"No regulatory regime is recorded for {name} yet. Ask the MSP's compliance owner and counsel which apply."
        )
    return (
        f"The prototype's client fixture lists these regimes for {name}: {', '.join(regimes)}. "
        "UNVERIFIED: whether and how each applies is for the compliance owner and counsel to confirm."
    )


def build_ai_policy(
    client: str,
    *,
    generated_on: str,
    register: Path = DEFAULT_REGISTER,
    ai_policy: Path = DEFAULT_POLICY,
    template: Path = DEFAULT_TEMPLATE,
    clients: Path = DEFAULT_CLIENTS,
    models: Path = DEFAULT_MODELS,
    regpacks: Path = DEFAULT_REGPACKS,
) -> AIPolicyDraft:
    """The draft AI-use policy for one client. Reads that client's parameters only; writes nothing."""
    try:
        check_client(client)
        today = check_date(generated_on, "generated_on")
    except HealthError as exc:
        raise RoadmapError(str(exc)) from None
    industry = _industry(client, clients)
    policy_text = _read(ai_policy, "AI policy")
    template_text = _read(template, "template")
    rules = parse_rules(policy_text)
    meanings = parse_class_meanings(policy_text)
    hosted, live = _hosted(client, register, today, models)
    rows = _rows(meanings, industry, hosted)
    tools = _tools(models, live, hosted)
    name = display_name(client)
    floor = INDUSTRY_FLOOR[industry].label
    values = {
        "CLIENT_NAME": name,
        "INDUSTRY": industry,
        "FLOOR": floor,
        "INDUSTRY_NOTE": INDUSTRY_NOTES[industry],
        "REGIME_NOTE": _regime_note(_regimes(client, regpacks), name),
        "GENERATED_ON": generated_on,
        "POLICY_SHA": digest(ai_policy),
        "TEMPLATE_SHA": digest(template),
        "RULES": "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1)),
        "DATA_CLASS_TABLE": _table(rows),
        "APPROVED_TOOLS": "\n".join(f"- **{t.name}** ({t.kind}): {t.note}" for t in tools) or "- None.",
        "HOSTED_STATUS": _hosted_text(hosted, industry, name),
    }
    unknown = sorted(set(PLACEHOLDER.findall(template_text)) - set(values))
    if unknown:
        raise RoadmapError(f"the template has fields this workflow does not fill: {', '.join(unknown)}")
    text = PLACEHOLDER.sub(lambda m: values[m.group(1)], template_text)
    return AIPolicyDraft(
        client=client,
        display_name=name,
        industry=industry,
        floor=floor,
        generated_on=generated_on,
        rules=rules,
        data_classes=rows,
        approved_tools=tools,
        hosted=hosted,
        policy_sha256=values["POLICY_SHA"],
        template_sha256=values["TEMPLATE_SHA"],
        text=text,
    )
