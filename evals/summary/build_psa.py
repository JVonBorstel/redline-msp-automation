"""Build the PSA-shaped synthetic data the summary workflow reads (B-22).

Run: uv run --frozen python -m evals.summary.build_psa

Output: workflows/summary/data/psa/<client>.json, shaped like fixtures/psa/<client>.json (Autotask-like Companies,
Contacts, Tickets, TicketNotes, Resources). Contacts come from the client's tenant users (keeping the ids already used
in fixtures/psa/); tickets come from the ticket files with every gold label dropped; notes come from notes.json.
A test checks the committed files equal a fresh build. Synthetic data only; status values are placeholders.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "workflows" / "summary" / "data" / "psa"
TICKETS_DIR = REPO / "fixtures" / "tickets" / "phase2"
TENANT_DIR = REPO / "fixtures" / "tenant"
PSA_DIR = REPO / "fixtures" / "psa"
NOTES = Path(__file__).with_name("notes.json")

COMPANY_IDS = {"contoso-dental": 30001, "fabrikam-capital": 30002, "litware-legal": 30003}
CONTACT_BASE = {"contoso-dental": 41000, "fabrikam-capital": 42000, "litware-legal": 43000}
TICKET_BASE = {"contoso-dental": 71000, "fabrikam-capital": 72000, "litware-legal": 73000}
NOTE_BASE = {"contoso-dental": 91000, "fabrikam-capital": 92000, "litware-legal": 93000}
RESOURCE_ID = {"tech-ana": 50001, "tech-ben": 50002, "tech-cara": 50003}
STATUS = {"new": 1, "in-progress": 2, "waiting-client": 3, "waiting-vendor": 4, "resolved": 5}  # placeholders


HONORIFICS = frozenset({"Dr.", "Mr.", "Ms.", "Mrs."})


def person_name(display: str) -> str:
    """A tenant display name without the "(synthetic)" marker and without a leading title."""
    words = [w for w in display.replace("(synthetic)", "").split() if w not in HONORIFICS]
    return " ".join(words)


def _names(display: str) -> tuple[str, str]:
    words = person_name(display).split()
    return words[0], " ".join(words[1:])


def build(client: str) -> dict[str, Any]:
    tenant = json.loads((TENANT_DIR / f"{client}.json").read_text(encoding="utf-8"))
    company_id = COMPANY_IDS[client]
    committed = PSA_DIR / f"{client}.json"
    known: dict[str, int] = {}
    company: dict[str, Any] = {
        "id": company_id,
        "companyName": tenant["_meta"]["displayName"] + " (synthetic)",
        "companyType": 1,
        "isActive": True,
    }
    if committed.is_file():
        data = json.loads(committed.read_text(encoding="utf-8"))
        company = data["company"]
        known = {c["emailAddress"]: c["id"] for c in data["contacts"]}
    contacts: list[dict[str, Any]] = []
    by_email: dict[str, int] = {}
    for index, user in enumerate(tenant["users"], start=1):
        email = user["userPrincipalName"]
        first, last = _names(user["displayName"])
        contact_id = known.get(email, CONTACT_BASE[client] + index)
        by_email[email] = contact_id
        contacts.append(
            {
                "id": contact_id,
                "companyID": company_id,
                "firstName": first,
                "lastName": last,
                "title": user.get("jobTitle", ""),
                "emailAddress": email,
                "isActive": 1 if user.get("accountEnabled", True) else 0,
            }
        )
    raw = json.loads((TICKETS_DIR / f"{client}.json").read_text(encoding="utf-8"))
    tickets: list[dict[str, Any]] = []
    ids: dict[str, int] = {}
    technicians: set[str] = set()
    for offset, ticket in enumerate(raw["tickets"], start=1):
        ids[ticket["id"]] = TICKET_BASE[client] + offset
        technicians.add(ticket["technician"])
        tickets.append(
            {
                "id": ids[ticket["id"]],
                "ticketNumber": ticket["id"],
                "companyID": company_id,
                "contactID": by_email.get(ticket["requester"]),
                "affectedUserEmail": ticket["affected_user"],
                "title": ticket["subject"],
                "description": ticket["body"],
                "status": STATUS[ticket["status"]],
                "assignedResourceID": RESOURCE_ID[ticket["technician"]],
                "source": ticket["source"],
                "createDate": ticket["created"],
                "lastActivityDate": ticket["updated"],
            }
        )
    updated = {t["id"]: t["updated"] for t in raw["tickets"]}
    tech_of = {t["id"]: t["technician"] for t in raw["tickets"]}
    spec = json.loads(NOTES.read_text(encoding="utf-8"))["notes"]
    notes: list[dict[str, Any]] = []
    for number, note in enumerate((n for n in spec if n["client"] == client), start=1):
        notes.append(
            {
                "id": NOTE_BASE[client] + number,
                "ticketID": ids[note["ticket"]],
                "title": "Technician note (synthetic)",
                "description": note["description"],
                "noteType": 1,
                "publish": 2,
                "creatorResourceID": RESOURCE_ID[tech_of[note["ticket"]]],
                "createDateTime": updated[note["ticket"]],
            }
        )
    resources = [
        {
            "id": RESOURCE_ID[name],
            "firstName": name.split("-")[1].title(),
            "lastName": "(technician, synthetic)",
            "userName": name,
            "isActive": True,
        }
        for name in sorted(technicians)
    ]
    return {
        "_note": (
            "Synthetic PSA-shaped data for the B-22 summary workflow (invented client, people and tickets). "
            "Generated by evals/summary/build_psa.py from the tenant users and the ticket files; no labels. "
            "Field names follow fixtures/psa/SOURCES.md; status values are placeholders (UNVERIFIED); "
            "affectedUserEmail is a local field, not an Autotask field (UNVERIFIED). Fixture-based, not a real PSA."
        ),
        "client": client,
        "company": company,
        "contacts": contacts,
        "resources": resources,
        "tickets": tickets,
        "ticketNotes": notes,
    }


def render(client: str) -> str:
    """One record per line so a reviewer can read a diff."""
    data = build(client)
    lines = ["{"]
    keys = list(data)
    for i, key in enumerate(keys):
        value = data[key]
        comma = "," if i < len(keys) - 1 else ""
        if isinstance(value, list):
            lines.append(f"  {json.dumps(key)}: [")
            for j, item in enumerate(value):
                tail = "," if j < len(value) - 1 else ""
                lines.append(f"    {json.dumps(item, ensure_ascii=False)}{tail}")
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for client in COMPANY_IDS:
        target = OUT_DIR / f"{client}.json"
        target.write_text(render(client), encoding="utf-8", newline="\n")
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
