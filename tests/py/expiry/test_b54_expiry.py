"""B-54 expiry watch. Acceptance ids B54-1 to B54-4 are defined in specs/B-54.md.

Offline and deterministic: dates are pinned with as_of, nothing touches the network, committed fixtures are never
modified (tests that change a fixture work on a copy under tmp_path).
Run: uv run --frozen pytest -p no:cacheprovider tests/py/expiry
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import workflows.expiry.expiry as expiry_module
from workflows.expiry import (
    DEFAULT_DNS_DIR,
    DEFAULT_PARTNER_DIR,
    ExpiryError,
    build_report,
    check_domain,
    parse_dmarc_aggregate,
    render_markdown,
)
from workflows.expiry.__main__ import main

AS_OF = "2026-10-21"
REPO = Path(__file__).resolve().parents[3]


def _rows(client: str, **kw: Any) -> list[dict[str, Any]]:
    return build_report(client, as_of=AS_OF, **kw).rows()


def _find(rows: list[dict[str, Any]], kind: str, text: str, status: str | None = None) -> dict[str, Any]:
    hits = [r for r in rows if r["kind"] == kind and text in r["subject"] and (status is None or r["status"] == status)]
    assert len(hits) == 1, (kind, text, status, hits)
    return hits[0]


@pytest.fixture()
def copies(tmp_path: Path) -> tuple[Path, Path]:
    dns, partner = tmp_path / "dns", tmp_path / "partner"
    shutil.copytree(DEFAULT_DNS_DIR, dns)
    shutil.copytree(DEFAULT_PARTNER_DIR, partner)
    return dns, partner


# ------------------------------------------------------------------------------------------------ B54-1


def test_b54_1_spf_dkim_dmarc_are_checked_per_domain() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    by = {d.domain: d for d in report.domains}
    assert len(by) == 3
    assert (by["contosodental.example"].spf, by["contosodental.example"].dkim, by["contosodental.example"].dmarc) == (
        "warn",
        "pass",
        "warn",
    )
    assert (by["smile.contosodental.example"].spf, by["smile.contosodental.example"].dkim) == ("fail", "fail")
    assert by["smile.contosodental.example"].dmarc == "fail"
    assert by["appointments.contosodental.example"].overall == "pass"


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"spf": "v=spf1 -all"}, ("pass", "fail", "fail")),
        ({"spf": "v=spf1 +all"}, ("fail", "fail", "fail")),
        ({"spf": "v=spf1 ?all"}, ("fail", "fail", "fail")),
        ({"spf": ["v=spf1 -all", "v=spf1 ~all"]}, ("fail", "fail", "fail")),
        ({"spf": "v=spf1 " + " ".join(f"include:s{i}.example" for i in range(11)) + " -all"}, ("fail", "fail", "fail")),
        ({"spf": "v=spf1 include:a.example"}, ("fail", "fail", "fail")),
        ({"dkim": [{"selector": "s1", "published": False}]}, ("fail", "fail", "fail")),
        (
            {"dkim": [{"selector": "s1", "published": True}, {"selector": "s2", "published": False}]},
            ("fail", "warn", "fail"),
        ),
        ({"dmarc": "v=DMARC1; p=reject"}, ("fail", "fail", "warn")),
        ({"dmarc": "v=DMARC1; p=reject; rua=mailto:a@x.example; pct=50"}, ("fail", "fail", "warn")),
        ({"dmarc": "v=DMARC1; p=quarantine; rua=mailto:a@x.example"}, ("fail", "fail", "pass")),
        ({"dmarc": "v=DMARC1; p=bogus"}, ("fail", "fail", "fail")),
        ({"dmarc": "p=reject"}, ("fail", "fail", "fail")),
    ],
)
def test_b54_1_policy_rules(entry: dict[str, Any], expected: tuple[str, str, str]) -> None:
    chk = check_domain({"domain": "x.example", **entry})
    assert (chk.spf, chk.dkim, chk.dmarc) == expected


def test_b54_1_bad_domain_name_is_refused() -> None:
    with pytest.raises(ExpiryError):
        check_domain({"domain": "bad domain;"})


def test_b54_1_secrets_certificates_and_gdap_within_n_days_are_listed_per_client() -> None:
    rows = _rows("contoso-dental")
    secret = _find(rows, "app-secret", "backup secret")
    assert (secret["status"], secret["due"], secret["days_left"]) == ("expiring", "2026-11-02", 12)
    assert _find(rows, "app-certificate", "backup cert")["status"] == "expired"
    assert _find(rows, "tls", "vpn.")["days_left"] == 15
    assert _find(rows, "gdap", "helpdesk (synthetic)", "expiring")["days_left"] == 22
    assert _find(rows, "gdap", "old support")["status"] == "expired"
    assert not [r for r in rows if "Intake portal" in r["subject"] or "portal." in r["subject"]]  # far away: not listed
    assert not [r for r in rows if "2027" in r["due"]]


def test_b54_1_n_changes_the_result() -> None:
    narrow = _rows("contoso-dental", within_days=10)
    wide = _rows("contoso-dental", within_days=366)
    assert not [r for r in narrow if r["kind"] == "tls"]
    assert [r for r in wide if r["kind"] == "tls" and "portal" in r["subject"]]
    assert [r for r in wide if r["kind"] == "app-secret" and "Intake" in r["subject"]]
    with pytest.raises(ExpiryError):
        build_report("contoso-dental", as_of=AS_OF, within_days=0)


def test_b54_1_gdap_global_administrator_is_listed() -> None:
    row = _find(_rows("contoso-dental"), "gdap", "full admin", "global-admin")
    assert "Global Administrator" in row["detail"]


def test_b54_1_global_administrator_is_listed_even_when_far_from_expiry(copies: tuple[Path, Path]) -> None:
    dns, partner = copies
    path = partner / "contoso-dental.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["gdapRelationships"][0]["endDateTime"] = "2028-01-01T00:00:00Z"
    path.write_text(json.dumps(data), encoding="utf-8")
    rows = build_report("contoso-dental", as_of=AS_OF, dns_dir=dns, partner_dir=partner).rows()
    assert _find(rows, "gdap", "full admin")["status"] == "global-admin"


def test_b54_1_clean_twin_has_no_reminders() -> None:
    report = build_report("fabrikam-capital", as_of=AS_OF)
    assert report.reminders == ()
    assert all(d.overall == "pass" for d in report.domains)
    assert all(s.dmarc_fail == 0 for s in report.dmarc)


def test_b54_1_one_client_never_sees_the_other() -> None:
    contoso = json.dumps(_rows("contoso-dental")) + render_markdown(build_report("contoso-dental", as_of=AS_OF))
    fabrikam = json.dumps(_rows("fabrikam-capital")) + render_markdown(build_report("fabrikam-capital", as_of=AS_OF))
    assert "fabrikam" not in contoso.lower()
    assert "contoso" not in fabrikam.lower()


def test_b54_1_a_fixture_filed_under_another_client_is_refused(copies: tuple[Path, Path]) -> None:
    dns, partner = copies
    shutil.copy(dns / "fabrikam-capital.json", dns / "contoso-dental.json")
    with pytest.raises(ExpiryError, match="client"):
        build_report("contoso-dental", as_of=AS_OF, dns_dir=dns, partner_dir=partner)


def test_b54_1_a_report_for_a_domain_the_client_does_not_own_is_refused(copies: tuple[Path, Path]) -> None:
    dns, partner = copies
    foreign = (dns / "fabrikam-capital-dmarc-fabrikamcapital.example.xml").read_text(encoding="utf-8")
    (dns / "contoso-dental-dmarc-fabrikamcapital.example.xml").write_text(foreign, encoding="utf-8")
    with pytest.raises(ExpiryError, match="not one of"):
        build_report("contoso-dental", as_of=AS_OF, dns_dir=dns, partner_dir=partner)


@pytest.mark.parametrize("client", ["../etc", "Contoso", "", "a/b", "nobody-here"])
def test_b54_1_bad_or_unknown_client_is_refused(client: str) -> None:
    with pytest.raises(ExpiryError):
        build_report(client, as_of=AS_OF)


def test_b54_1_a_secret_value_field_is_refused_at_load(copies: tuple[Path, Path]) -> None:
    dns, partner = copies
    path = partner / "contoso-dental.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["appRegistrations"][0]["passwordCredentials"][0]["secretText"] = "x" * 8
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ExpiryError, match="secret"):
        build_report("contoso-dental", as_of=AS_OF, dns_dir=dns, partner_dir=partner)


def test_b54_1_committed_fixtures_hold_no_secret_looking_value() -> None:
    forbidden = ("secrettext", "password", "privatekey", "begin private", "client_secret")
    for path in [*DEFAULT_DNS_DIR.glob("*.json"), *DEFAULT_PARTNER_DIR.glob("*.json")]:
        text = path.read_text(encoding="utf-8").lower()
        assert not [w for w in forbidden if w in text.replace("passwordcredentials", "")], path.name


# ------------------------------------------------------------------------------------------------ B54-2


def _field_names(node: object) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            names.add(key)
            names |= _field_names(value)
    elif isinstance(node, list):
        for item in node:
            names |= _field_names(item)
    return names


def test_b54_2_every_gdap_and_app_fixture_field_is_marked_unverified() -> None:
    sources = (DEFAULT_PARTNER_DIR / "SOURCES.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip(" `"): line for line in sources.splitlines() if line.startswith("| `")}
    names: set[str] = set()
    for path in DEFAULT_PARTNER_DIR.glob("*.json"):
        names |= _field_names(json.loads(path.read_text(encoding="utf-8")))
    names -= {"gdapRelationships", "appRegistrations", "client", "as_of", "_note"}  # envelope and section names
    envelope_ok = ("`client`, `as_of`, `_note`" in sources) and "gdapRelationships" in sources
    assert envelope_ok
    missing = sorted(n for n in names if n not in rows)
    assert not missing, f"fields not documented in SOURCES.md: {missing}"
    for name in names:
        assert "UNVERIFIED" in rows[name] or "invented" in rows[name], name
    gdap = {n for n in ("id", "displayName", "status", "endDateTime", "roles")}
    assert all("UNVERIFIED" in rows[n] for n in gdap)
    assert "Verified (" not in sources.replace("UNVERIFIED", "")  # nothing is claimed verified


# ------------------------------------------------------------------------------------------------ B54-3


def test_b54_3_every_reminder_is_a_row_with_a_date_and_an_owner() -> None:
    rows = _rows("contoso-dental")
    assert len(rows) == 11
    for row in rows:
        assert set(row) == {"client", "kind", "subject", "status", "due", "owner", "detail", "days_left", "action"}
        assert row["client"] == "contoso-dental"
        assert row["owner"] and row["due"][:2] == "20" and len(row["due"]) == 10
        assert row["action"] == "reminder-only"
    assert _find(rows, "app-secret", "printer secret")["owner"] == "unassigned"
    assert _find(rows, "tls", "vpn.")["owner"] == "tech-ana"
    assert _find(rows, "gdap", "full admin", "global-admin")["owner"] == "lead-lee"
    assert _find(rows, "dns", "smile.")["due"] == AS_OF  # a policy gap is due for review at the as-of date


def test_b54_3_rows_are_sorted_with_the_most_urgent_first() -> None:
    statuses = [r["status"] for r in _rows("contoso-dental")]
    order = ["expired", "global-admin", "fail", "expiring", "warn"]
    assert statuses == sorted(statuses, key=order.index)


def test_b54_3_dates_come_from_as_of_not_the_clock() -> None:
    later = build_report("contoso-dental", as_of="2026-11-04").rows()
    assert _find(later, "app-secret", "backup secret")["status"] == "expired"
    assert _find(later, "tls", "vpn.")["days_left"] == 1
    assert build_report("contoso-dental").as_of == AS_OF  # default: the fixture's pinned date


def test_b54_3_nothing_is_renewed_by_automation() -> None:
    tree = ast.parse(Path(expiry_module.__file__).read_text(encoding="utf-8"))
    imported = {
        n.module if isinstance(n, ast.ImportFrom) else a.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [None])
    }
    assert not [m for m in imported if m and (m.startswith("core") or m.startswith("socket") or "requests" in m)]
    assert not [m for m in imported if m and m.startswith("urllib")]
    source = Path(expiry_module.__file__).read_text(encoding="utf-8")
    assert "write_text" not in source and "open(" not in source  # reads only
    assert "Reminders only" in render_markdown(build_report("contoso-dental", as_of=AS_OF))


def test_b54_3_running_the_report_changes_no_fixture() -> None:
    before = {p: p.read_bytes() for p in [*DEFAULT_DNS_DIR.glob("*"), *DEFAULT_PARTNER_DIR.glob("*")]}
    build_report("contoso-dental", as_of=AS_OF)
    build_report("fabrikam-capital", as_of=AS_OF)
    assert before == {p: p.read_bytes() for p in before}


def test_b54_3_cli_prints_rows_and_exits_two_on_bad_input(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["contoso-dental", "--as-of", AS_OF]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["client"] == "contoso-dental" and len(out["reminders"]) == 11
    assert main(["fabrikam-capital", "--markdown"]) == 0
    assert "nothing expiring or weak" in capsys.readouterr().out
    assert main(["no such client"]) == 2
    assert "error:" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------ B54-4


def test_b54_4_aggregate_report_is_summarised_per_domain() -> None:
    xml = (DEFAULT_DNS_DIR / "contoso-dental-dmarc-contosodental.example.xml").read_text(encoding="utf-8")
    s = parse_dmarc_aggregate(xml)
    assert (s.domain, s.policy, s.adkim, s.aspf) == ("contosodental.example", "none", "r", "r")
    assert (s.messages, s.dmarc_pass, s.dmarc_fail) == (164, 150, 14)
    assert (s.dkim_aligned_pass, s.spf_aligned_pass) == (120, 150)
    assert s.failing_sources == (("198.51.100.77", 14, "none"),)


def test_b54_4_report_shows_pass_fail_policy_and_alignment_per_domain() -> None:
    report = build_report("contoso-dental", as_of=AS_OF)
    assert [s.domain for s in report.dmarc] == ["contosodental.example"]
    text = render_markdown(report)
    assert "| contosodental.example | none | r/r | 164 | 150 | 14 |" in text
    row = _find(report.rows(), "dmarc", "contosodental.example")
    assert "14 of 164" in row["detail"] and row["owner"] == "tech-ana"
    clean = build_report("fabrikam-capital", as_of=AS_OF)
    assert (clean.dmarc[0].policy, clean.dmarc[0].messages, clean.dmarc[0].dmarc_fail) == ("reject", 200, 0)


def test_b54_4_dmarc_passes_when_either_aligned_mechanism_passes() -> None:
    xml = """<feedback><policy_published><domain>x.example</domain><p>reject</p></policy_published>
    <record><row><source_ip>192.0.2.1</source_ip><count>5</count><policy_evaluated><disposition>none</disposition>
    <dkim>fail</dkim><spf>pass</spf></policy_evaluated></row></record></feedback>"""
    s = parse_dmarc_aggregate(xml)
    assert (s.dmarc_pass, s.dmarc_fail, s.dkim_aligned_pass, s.spf_aligned_pass) == (5, 0, 0, 5)


@pytest.mark.parametrize(
    "xml",
    [
        "not xml",
        "<other/>",
        "<feedback></feedback>",
        '<!DOCTYPE feedback [<!ENTITY a "aaaa">]><feedback><policy_published><domain>x.example</domain>'
        "</policy_published></feedback>",
        "<feedback><policy_published><domain>bad domain</domain></policy_published></feedback>",
        "<feedback><policy_published><domain>x.example</domain></policy_published><record><row><count>x</count>"
        "<policy_evaluated/></row></record></feedback>",
        "<feedback><policy_published><domain>x.example</domain></policy_published><record><row><count>-1</count>"
        "<policy_evaluated/></row></record></feedback>",
        "<feedback><policy_published><domain>x.example</domain></policy_published><record/></feedback>",
    ],
)
def test_b54_4_malformed_or_hostile_aggregate_xml_is_refused(xml: str) -> None:
    with pytest.raises(ExpiryError):
        parse_dmarc_aggregate(xml)


def test_b54_4_fixtures_cite_rfc_7489_and_label_themselves_synthetic() -> None:
    sources = (DEFAULT_DNS_DIR / "SOURCES.md").read_text(encoding="utf-8")
    assert "RFC 7489" in sources and "EasyDMARC" in sources and "UNVERIFIED" in sources
    for path in DEFAULT_DNS_DIR.glob("*.xml"):
        assert "Synthetic" in path.read_text(encoding="utf-8")
    for path in [*DEFAULT_DNS_DIR.glob("*.json"), *DEFAULT_PARTNER_DIR.glob("*.json")]:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "Synthetic" in data["_note"] and data["client"] == path.stem and data["as_of"] == AS_OF
