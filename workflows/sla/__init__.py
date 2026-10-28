"""SLA breach watch and backlog grooming report (B-24). A person reads it and sends any draft (HO-9).

report = collect(as_of=parse_time("2026-10-16T23:00:00Z"))   # per client; validate_report(report) == [] reconciles
"""

from workflows.sla.sla import (
    LABEL,
    ClientSource,
    Sla,
    SlaError,
    WatchTicket,
    build_report,
    collect,
    load_client_source,
    load_file_tickets,
    parse_time,
    render_markdown,
    validate_report,
    write_demo_bindings,
    write_report,
)

__all__ = [
    "LABEL",
    "ClientSource",
    "Sla",
    "SlaError",
    "WatchTicket",
    "build_report",
    "collect",
    "load_client_source",
    "load_file_tickets",
    "parse_time",
    "render_markdown",
    "validate_report",
    "write_demo_bindings",
    "write_report",
]
