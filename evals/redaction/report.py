"""Redaction gate eval (B-55, B55-3): leak rate on the synthetic Phase 2 PHI/NPI set, with the miss list. Fixture-based.

Run from the repo root:  uv run --frozen python -m evals.redaction.report   (writes evals/redaction/report.md)

- Leak: a labelled ``sensitive`` span of ``fixtures/tickets/phase2`` (B-21) whose exact text is still in the prompt
  text the gate produces (``core.guard.redact_prompt``, the function the gateway calls). The primary number is
  PHI and NPI spans; PII spans (phone, client name, matter number) are reported beside it.
- Typed: a span counts as typed when one finding covers exactly that span with the labelled kind.
- Unlabelled: redactions that overlap no labelled span (over-redaction), listed by ticket and kind.
- Blocked: how many tickets the gate blocks as DC-6 (the set holds no secrets, so this should be 0).
- Hosted refusal: every ticket goes through a ``Gateway`` whose summarize route is an *enabled* hosted stub, with
  its client record from ``evals/redaction/clients/``; every ticket must be refused there (DC-4/DC-5), while the
  classify route (the local mock) must answer every ticket.

The tickets, labels and shape rules share one author and the rules were written with the set in view (D-022), so
these numbers show the gate working on this set, not redaction quality on real tickets.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adapters.binding import load_client
from core.gateway import Gateway, GatewayConfig
from core.guard.classify import Finding
from core.guard.normalise import normalise
from core.guard.redact_prompt import redact_prompt
from core.paths import REPO_ROOT

HERE = Path(__file__).parent
CLIENTS = HERE / "clients"
REPORT = HERE / "report.md"
TICKETS = REPO_ROOT / "fixtures" / "tickets" / "phase2"
LABEL_KIND = {"ssn-shaped": "ssn"}
"""Label kinds the gate names differently; every other label kind is also the gate's kind."""
HOSTED_REFUSAL = "may not go to hosted provider"


@dataclass
class ClientResult:
    floor: str = "-"
    tickets: int = 0
    spans: dict[str, int] = field(default_factory=lambda: {"phi-npi": 0, "pii": 0})
    leaked: dict[str, int] = field(default_factory=lambda: {"phi-npi": 0, "pii": 0})
    typed: int = 0
    blocked: int = 0
    hosted_refused: int = 0
    local_ok: int = 0

    def add(self, other: ClientResult) -> None:
        self.tickets += other.tickets
        for bucket in self.spans:
            self.spans[bucket] += other.spans[bucket]
            self.leaked[bucket] += other.leaked[bucket]
        self.typed += other.typed
        self.blocked += other.blocked
        self.hosted_refused += other.hosted_refused
        self.local_ok += other.local_ok


@dataclass
class Result:
    per_client: dict[str, ClientResult]
    misses: list[str]
    untyped: list[str]
    unlabelled: list[str]

    @property
    def total(self) -> ClientResult:
        total = ClientResult()
        for r in self.per_client.values():
            total.add(r)
        return total


def load_set() -> dict[str, list[dict[str, Any]]]:
    """Phase 2 tickets per client, in file order."""
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(TICKETS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        out[document["client"]] = document["tickets"]
    return out


def eval_gateway() -> Gateway:
    """Shipped models config, with summarize on an ENABLED Anthropic stub and classify on the local mock.

    The stub has no client, key or endpoint; it can only fail. The point is that the gate refuses before it.
    """
    providers = json.loads((REPO_ROOT / "config" / "models.json").read_text(encoding="utf-8"))["providers"]
    providers["anthropic"] = {"enabled": True, "models": {"strong": "hosted-example"}}
    routes = {
        "summarize": {"provider": "anthropic", "model": "strong"},
        "classify": {"provider": "mock", "model": "small"},
    }
    return Gateway(GatewayConfig.model_validate({"providers": providers, "routes": routes, "root": REPO_ROOT}))


def ticket_text(ticket: dict[str, Any]) -> str:
    return f"{ticket['subject']}\n{ticket['body']}"


def _occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    return [(i, i + len(needle)) for i in range(len(text)) if text.startswith(needle, i)]


def _overlaps(finding: Finding, spans: list[tuple[int, int]]) -> bool:
    return any(finding.start < end and finding.end > start for start, end in spans)


def evaluate() -> Result:
    gateway = eval_gateway()
    result = Result(per_client={}, misses=[], untyped=[], unlabelled=[])
    for client_id, tickets in load_set().items():
        record = load_client(client_id, CLIENTS)
        r = result.per_client.setdefault(client_id, ClientResult())
        for ticket in tickets:
            r.tickets += 1
            raw = ticket_text(ticket)
            gated = redact_prompt(raw, client=record)
            r.floor = gated.classification.base.label
            r.blocked += gated.blocked
            text = normalise(raw)  # the gate's findings index into the normalised text
            findings = gated.classification.findings
            labelled: list[tuple[int, int]] = []
            for span in ticket["labels"]["sensitive"]:
                bucket = "phi-npi" if span["class"] in ("phi", "npi") else "pii"
                r.spans[bucket] += 1
                where = _occurrences(text, span["text"])
                labelled += where
                kind = LABEL_KIND.get(span["kind"], span["kind"])
                if span["text"] in gated.text:
                    r.leaked[bucket] += 1
                    result.misses.append(f"{ticket['id']} {span['kind']} ({span['class']}): `{span['text']}`")
                elif any((f.start, f.end) in where and f.kind == kind for f in findings):
                    r.typed += 1
                else:
                    got = sorted({f.kind for f in findings if _overlaps(f, where)})
                    result.untyped.append(f"{ticket['id']} {span['kind']} redacted as {', '.join(got)}")
            result.unlabelled += [f"{ticket['id']} {f.kind}" for f in findings if not _overlaps(f, labelled)]
            hosted = gateway.complete("summarize", raw, client=record)
            r.hosted_refused += not hosted.ok and HOSTED_REFUSAL in (hosted.error or "")
            r.local_ok += gateway.complete("classify", raw, client=record).ok
    return result


def _pct(a: int, b: int) -> str:
    return "n/a" if b == 0 else f"{100 * a / b:.1f}%"


def render(result: Result) -> str:
    def row(name: str, r: ClientResult) -> str:
        spans = r.spans["phi-npi"] + r.spans["pii"]
        return (
            f"| {name} | {r.floor} | {r.tickets} | {r.spans['phi-npi']} | {r.leaked['phi-npi']} | "
            f"{_pct(r.leaked['phi-npi'], r.spans['phi-npi'])} | {r.spans['pii']} | {r.leaked['pii']} | "
            f"{r.typed} of {spans} | {r.blocked} | {r.hosted_refused} | {r.local_ok} |"
        )

    def listing(items: list[str]) -> list[str]:
        return [f"- {item}" for item in items] if items else ["- none"]

    lines = [
        "# Pre-prompt redaction gate: fixture-based eval (B-55)",
        "",
        "> Fixture-based and synthetic. The Phase 2 tickets, their `sensitive` labels and the gate's shape rules were "
        "written by one author, and the rules were written with this set in view (D-022). This shows the gate working "
        "on this set, not redaction quality on real tickets. Regenerate with "
        "`uv run --frozen python -m evals.redaction.report`.",
        "",
        "A labelled span **leaks** when its exact text is still in the prompt text the gate produces. Each client's "
        "floor comes from its record in `evals/redaction/clients/` (industry, D6-12). Hosted route: summarize on an "
        "enabled Anthropic stub; local route: classify on the offline mock.",
        "",
        "| Client | Floor | Tickets | PHI/NPI spans | PHI/NPI leaked | PHI/NPI leak rate | PII spans | PII leaked | "
        "Typed as labelled | Blocked as DC-6 | Hosted route refused | Local route ok |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
        *(row(client, r) for client, r in sorted(result.per_client.items())),
        row("**all**", result.total),
        "",
        "## Miss list (labelled spans still in the prompt)",
        "",
        *listing(result.misses),
        "",
        "## Redacted under another placeholder type than the label",
        "",
        *listing(result.untyped),
        "",
        "## Redactions that overlap no labelled span (over-redaction)",
        "",
        *listing(result.unlabelled),
        "",
        "## Limits",
        "",
        "- Names are found only after a cue: patient, investor, limited partner, client, named, the name, an "
        "honorific, `the <Name> matter`, `<Name> Family Trust`. A bare name with no cue is not found; the industry "
        "floor (DC-4 or DC-5) is what keeps such text off hosted models.",
        "- Dates of birth are found only next to `DOB`, `date of birth` or `born`.",
        "- Personal email addresses and street addresses are not redacted (UPNs are identifiers the tickets need).",
        "- The hosted provider is a stub: the refusal happens before any provider is called, so no hosted model "
        "was reached.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    result = evaluate()
    text = render(result)
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    total = result.total
    refused_all = all(r.hosted_refused == r.tickets for r in result.per_client.values())
    ok = total.leaked["phi-npi"] == 0 and total.blocked == 0 and refused_all and total.local_ok == total.tickets
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
