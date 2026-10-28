"""Vulnerability, advisory and emergency-patch relevance (B-47). Report only; nothing is deployed.

report = report_for(["contoso-dental"])   # KEV matched to the client's inventory, joined to scan findings by CVE
"""

from workflows.advisories.advisories import (
    DEFAULT_FIXTURES_DIR,
    AdvisoriesError,
    ClientMatch,
    Exposed,
    KevFeed,
    Proposal,
    build_report,
    list_clients,
    load_inventory,
    load_kev,
    load_nessus,
    load_pentest,
    match_client,
    match_one,
    propose_window,
    report_for,
    utc,
)

__all__ = [
    "AdvisoriesError",
    "ClientMatch",
    "DEFAULT_FIXTURES_DIR",
    "Exposed",
    "KevFeed",
    "Proposal",
    "build_report",
    "list_clients",
    "load_inventory",
    "load_kev",
    "load_nessus",
    "load_pentest",
    "match_client",
    "match_one",
    "propose_window",
    "report_for",
    "utc",
]
