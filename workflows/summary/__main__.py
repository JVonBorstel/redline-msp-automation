"""Intake proposal and escalation package for one synthetic ticket (B-22). Read-only; nothing is saved or sent.

    uv run --frozen python -m workflows.summary T-5301 --state .tmp/demo

Writes <state>/summary/<ticket>.md (proposal, then package) and prints it. A person confirms the proposal (HO-9).
Exit 0 = proposal and package written, 1 = proposal only (no client matched, or ticket not in the PSA), 2 = bad input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.levers import DEFAULT_TENANT_DIR, MockTenant
from workflows.summary.common import DEFAULT_PSA_DIR, DEFAULT_TICKETS_DIR, SummaryError, get_ticket, load_adapters
from workflows.summary.intake import IntakeProposal, propose
from workflows.summary.package import DeviceFacts, build_package

DEFAULT_STATE = Path(__file__).resolve().parents[2] / ".tmp" / "demo"


def render_proposal(proposal: IntakeProposal) -> str:
    match, summary = proposal.match, proposal.summary
    contact = (
        f"{match.contact_name} (PSA contact {match.contact_id})" if match.contact_id is not None else "none proposed"
    )
    lines = [
        f"# Intake proposal for {proposal.ticket_id}",
        "",
        "Draft for the dispatcher to confirm before the ticket is saved. Client and contact were looked up in the "
        "PSA contact lists, not chosen by a model.",
        "",
        f"- Client: {match.client or 'none proposed'} (matched by {match.how})",
        f"- Contact: {contact}",
        f"- Affected user: {match.affected.state}"
        + (f" ({match.affected.contact_name})" if match.affected.contact_name else ""),
        f"- Summary: {summary.text}",
    ]
    lines += [f"- Note: {note}" for note in (*match.notes, *summary.notes)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.summary",
        description="Propose client, contact and summary, and build an escalation package (synthetic data; read-only).",
    )
    parser.add_argument("ticket_id", help="ticket id from fixtures/tickets, e.g. T-5301")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="state folder (default .tmp/demo)")
    parser.add_argument("--tickets", type=Path, default=DEFAULT_TICKETS_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--psa", type=Path, default=DEFAULT_PSA_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        ticket = get_ticket(args.ticket_id, args.tickets)
        adapters = load_adapters(args.psa)
        proposal = propose(ticket, adapters)
        text = render_proposal(proposal)
        code = 1
        client = proposal.match.client
        if client is not None:
            tenant_dir = args.state / "tenant"
            tenant = MockTenant(tenant_dir if tenant_dir.is_dir() else DEFAULT_TENANT_DIR)
            result = build_package(ticket.id, adapters[client], DeviceFacts(tenant))
            if result.package is not None:
                text += "\n" + result.package.render()
                code = 0
            else:
                text += f"\n{result.reason}\n"
        out_dir = args.state / "summary"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{ticket.id}.md"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(text.encode("utf-8"))
        tmp.replace(target)
    except SummaryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(text.rstrip("\n"))
    print(f"{'package' if code == 0 else 'proposal only'}: {target}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
