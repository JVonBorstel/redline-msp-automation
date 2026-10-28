"""B-71 monthly client health report with reconciliation. Acceptance ids B71-1 to B71-4 are defined in specs/B-71.md.

Offline and deterministic: ``generated_on`` is always passed in, drafts go to tmp_path, committed fixtures are only
read. The reconciliation tests recompute every figure from the raw fixture files with their own small code (C-21);
they call neither the workflow's metric helpers nor its validator to get the expected values.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/reporting/test_b71_health.py
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import statistics
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from core.gateway import Gateway, GatewayConfig
from core.paths import REPO_ROOT
from workflows.reporting import health
from workflows.reporting.health import (
    HealthError,
    HealthReport,
    Sources,
    VerifyError,
    build_report,
    create_draft,
    main,
    reconcile_html,
    render_html,
    verify_draft,
)

CLIENTS = ("contoso-dental", "fabrikam-capital", "litware-legal")
NAMES = {"contoso-dental": "Contoso Dental", "fabrikam-capital": "Fabrikam Capital", "litware-legal": "Litware Legal"}
PERIOD = "2026-10"
GENERATED = "2026-10-31"
TICKETS = REPO_ROOT / "fixtures" / "tickets" / "phase2"
BACKUP = REPO_ROOT / "fixtures" / "backup"
DATA = REPO_ROOT / "workflows" / "reporting" / "health" / "data"
HEALTH_DIR = REPO_ROOT / "workflows" / "reporting" / "health"
# Stand-in thresholds, written out again here on purpose: a changed threshold in the code must show up in this file.
CLICK_ATTENTION_PCT = 10
VAULT_MIN_SCORE = 70
OPEN_SHARE_ATTENTION_PCT = 50
PATCH_STALE_DAYS = 30


# -- raw fixture helpers, separate from the workflow's code ----------------------------------------
def _read(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _in_month(value: str, period: str = PERIOD) -> bool:
    return _utc(value).strftime("%Y-%m") == period


def _pct(n: int, d: int) -> str:
    if d == 0:
        return "n/a"
    tenths = (Fraction(n * 1000, d) + Fraction(1, 2)) // 1  # round half up to one decimal
    return f"{int(tenths) / 10:.1f}"


def _hours(value: Fraction) -> str:
    tenths = (value * 10 + Fraction(1, 2)) // 1
    return f"{int(tenths) / 10:.1f}"


def expect(
    client: str, period: str = PERIOD, *, data: Path = DATA, tickets: Path = TICKETS, backup: Path = BACKUP
) -> dict[str, str]:
    """Every metric the report must show, as the text the report shows, from the raw files."""
    out: dict[str, str] = {}
    tf = _read(tickets / f"{client}.json")
    if _in_month(tf["as_of"], period):
        rows = [t for t in tf["tickets"] if _in_month(t["created"], period)]
        done = [t for t in rows if t["status"] == "resolved"]
        out["tickets.opened"] = str(len(rows))
        out["tickets.resolved"] = str(len(done))
        out["tickets.open"] = str(len(rows) - len(done))
        out["tickets.resolved_pct"] = _pct(len(done), len(rows))
        secs = [int((_utc(t["updated"]) - _utc(t["created"])).total_seconds()) for t in done]
        out["tickets.median_hours_to_resolve"] = _hours(Fraction(statistics.median(secs)) / 3600) if secs else "n/a"
        for channel, n in Counter(t["source"] for t in rows).items():
            out[f"tickets.channel.{channel}"] = str(n)
    bf = _read(data / f"{client}.baseline.json")
    if _in_month(bf["as_of"], period):
        sev = Counter(f["Severity"] for f in bf["findings"])
        d = bf["drift"]
        ca = d["ca"]
        out["baseline.findings"] = str(len(bf["findings"]))
        out["baseline.high"] = str(sev["High"])
        out["baseline.medium"] = str(sev["Medium"])
        out["baseline.low"] = str(sev["Low"])
        out["baseline.new"] = str(len(d["new"]))
        out["baseline.resolved"] = str(len(d["resolved"]))
        out["baseline.unchanged"] = str(len(d["unchanged"]))
        out["baseline.ca_changes"] = str(
            sum(len(ca[k]) for k in ("added", "removed", "state_changed", "assignments_changed"))
        )
    pf = _read(data / f"{client}.patching.json")
    if _in_month(pf["as_of"], period):
        devs = pf["devices"]
        as_of = _utc(pf["as_of"]).date()
        ok = [x for x in devs if x["pending_critical"] == 0 and x["pending_other"] == 0]
        out["patching.devices"] = str(len(devs))
        out["patching.up_to_date"] = str(len(ok))
        out["patching.up_to_date_pct"] = _pct(len(ok), len(devs))
        out["patching.critical_pending_devices"] = str(sum(1 for x in devs if x["pending_critical"] > 0))
        out["patching.critical_pending_updates"] = str(sum(x["pending_critical"] for x in devs))
        out["patching.not_patched_30d"] = str(
            sum(1 for x in devs if (as_of - date.fromisoformat(x["last_patched"])).days > PATCH_STALE_DAYS)
        )
    bpath = backup / f"{client}.json"
    if bpath.is_file():
        bk = _read(bpath)
        if _in_month(bk["asOf"], period):
            jobs = [
                j
                for j in bk["jobs"]
                if j["organizationId"] == bk["organization"]["id"] and _in_month(j["scheduledStart"], period)
            ]
            st = Counter(j["status"] for j in jobs)
            known = st["success"] + st["failed"] + st["missed"]
            out["backup.jobs"] = str(len(jobs))
            out["backup.success"] = str(st["success"])
            out["backup.failed"] = str(st["failed"])
            out["backup.missed"] = str(st["missed"])
            out["backup.other"] = str(len(jobs) - known)
            out["backup.boot_check_failed"] = str(
                sum(
                    1 for j in jobs if isinstance(j.get("bootCheck"), dict) and j["bootCheck"].get("status") == "failed"
                )
            )
            out["backup.success_pct"] = _pct(st["success"], len(jobs))
    af = _read(data / f"{client}.awareness.json")
    if _in_month(af["as_of"], period):
        ps = af["services"]["phishing_simulation"]
        camps = [c for c in ps["campaigns"] if _in_month(c["launched"] + "T00:00:00Z", period)]
        sent = sum(c["sent"] for c in camps)
        clicked = sum(c["clicked"] for c in camps)
        reported = sum(c["reported"] for c in camps)
        v = af["services"]["password_vault"]
        out["phish.campaigns"] = str(len(camps))
        out["phish.sent"] = str(sent)
        out["phish.clicked"] = str(clicked)
        out["phish.reported"] = str(reported)
        out["phish.click_pct"] = _pct(clicked, sent)
        out["phish.report_pct"] = _pct(reported, sent)
        out["vault.audit_score"] = str(v["audit_score"])
        out["vault.users_total"] = str(v["users_total"])
        out["vault.users_enrolled"] = str(v["users_enrolled"])
        out["vault.enrolled_pct"] = _pct(v["users_enrolled"], v["users_total"])
        out["vault.mfa_enforced"] = "yes" if v["mfa_enforced"] else "no"
    return out


def expect_status(m: Mapping[str, str]) -> dict[str, str]:
    """Section status from the expected metrics, with this file's own thresholds."""

    def num(key: str) -> float:
        return float(m[key])

    out: dict[str, str] = {}
    if "tickets.opened" in m:
        out["tickets"] = (
            "attention" if num("tickets.open") * 100 > OPEN_SHARE_ATTENTION_PCT * num("tickets.opened") else "healthy"
        )
    if "baseline.findings" in m:
        out["baseline"] = "attention" if num("baseline.high") > 0 or num("baseline.ca_changes") > 0 else "healthy"
    if "patching.devices" in m:
        bad = num("patching.critical_pending_devices") > 0 or num("patching.not_patched_30d") > 0
        out["patching"] = "attention" if bad else "healthy"
    if "backup.jobs" in m:
        bad = num("backup.failed") > 0 or num("backup.missed") > 0 or num("backup.boot_check_failed") > 0
        out["backup"] = "attention" if bad else "healthy"
    if "vault.audit_score" in m:
        bad = (
            (num("phish.sent") > 0 and num("phish.clicked") * 100 > CLICK_ATTENTION_PCT * num("phish.sent"))
            or num("vault.audit_score") < VAULT_MIN_SCORE
            or m["vault.mfa_enforced"] == "no"
            or num("vault.users_enrolled") < num("vault.users_total")
        )
        out["awareness"] = "attention" if bad else "healthy"
    return {k: out.get(k, "no-data") for k in ("tickets", "baseline", "patching", "backup", "awareness")}


class Page:
    """What the HTML says, read with a small regex (not the workflow's parser)."""

    def __init__(self, html: str) -> None:
        self.html = html
        self.metrics: dict[str, list[str]] = {}
        for key, val in re.findall(r'<span data-metric="([^"]+)">([^<]*)</span>', html):
            self.metrics.setdefault(key, []).append(val)
        self.status = dict(re.findall(r'<section data-section="([a-z]+)" data-status="([a-z-]+)"', html))

    def shown(self) -> dict[str, str]:
        assert all(len(set(v)) == 1 for v in self.metrics.values()), "a metric is shown with two different values"
        return {k: v[0] for k, v in self.metrics.items()}

    def summary(self) -> str:
        m = re.search(r'<p data-summary="([a-z]+)">([^<]*)</p>', self.html)
        assert m
        return m.group(2)


def _cfg_gateway(provider: Any) -> Gateway:
    cfg = GatewayConfig.load(REPO_ROOT).model_dump()
    cfg["routes"]["summarize"] = {"provider": "mock", "model": "small"}
    return Gateway(GatewayConfig.model_validate(cfg), providers={"mock": provider})


class Echo:
    """A model double: returns what ``reply`` makes of the prompt text, and remembers every prompt it saw."""

    name = "mock"

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.seen: list[str] = []

    def complete(self, *, task: str, model: str, text: str) -> str:
        self.seen.append(text)
        out: str = self.reply(text)
        return out


def _draft_of(prompt: str) -> str:
    return prompt.split("DRAFT:\n", 1)[1].strip()


@pytest.fixture(scope="module")
def reports() -> dict[str, HealthReport]:
    return {c: build_report(c, PERIOD, generated_on=GENERATED) for c in CLIENTS}


@pytest.fixture(scope="module")
def pages(reports: dict[str, HealthReport]) -> dict[str, str]:
    return {c: render_html(r) for c, r in reports.items()}


def _world(tmp_path: Path) -> Sources:
    """A private copy of every input, for tests that plant a defect."""
    tickets, data, backup = tmp_path / "tickets", tmp_path / "data", tmp_path / "backup"
    shutil.copytree(TICKETS, tickets)
    shutil.copytree(DATA, data)
    shutil.copytree(BACKUP, backup)
    return Sources(data_dir=data, tickets_dir=tickets, backup_dir=backup)


# -- B71-1: one HTML report per client, every number reconciled ------------------------------------
@pytest.mark.parametrize("client", CLIENTS)
def test_b71_1_every_number_in_the_report_equals_its_recomputed_source_figure(
    client: str, pages: dict[str, str]
) -> None:
    page = Page(pages[client])
    want = expect(client)
    assert page.shown() == want
    assert len(want) >= 25  # five sections really produced figures, not an empty pass


@pytest.mark.parametrize("client", CLIENTS)
def test_b71_1_section_status_follows_the_numbers(client: str, pages: dict[str, str]) -> None:
    assert Page(pages[client]).status == expect_status(expect(client))


def test_b71_1_the_fixtures_exercise_healthy_attention_and_not_available_cases(pages: dict[str, str]) -> None:
    statuses = {c: Page(pages[c]).status for c in CLIENTS}
    flat = {s for v in statuses.values() for s in v.values()}
    assert {"healthy", "attention"} <= flat
    assert statuses["litware-legal"]["backup"] == "no-data"  # no backup fixture: a gap, not a zero
    assert Page(pages["litware-legal"]).shown()["phish.click_pct"] == "n/a"  # no campaign this month


def test_b71_1_one_html_file_per_client_written_as_a_draft(tmp_path: Path) -> None:
    for client in CLIENTS:
        d = create_draft(client, PERIOD, generated_on=GENERATED, out_dir=tmp_path)
        assert d.html_path == tmp_path / PERIOD / f"{client}.draft.html"
        assert d.html_path.is_file() and d.json_path.is_file()
        assert hashlib.sha256(d.html_path.read_bytes()).hexdigest() == d.sha256
    assert sorted(p.name for p in (tmp_path / PERIOD).iterdir()) == sorted(
        f"{c}.draft.{e}" for c in CLIENTS for e in ("html", "json")
    )


def test_b71_1_the_validator_fails_when_a_number_in_the_report_is_changed(reports: dict[str, HealthReport]) -> None:
    html = render_html(reports["contoso-dental"])
    assert reconcile_html(html) == ()
    bad = html.replace('<span data-metric="backup.failed">', '<span data-metric="backup.failed">9', 1)
    found = reconcile_html(bad)
    assert [m.key for m in found] == ["backup.failed"] and found[0].expected != found[0].shown
    gone = re.sub(r'<span data-metric="patching\.devices">\d+</span>', "", html)
    assert any(m.key == "patching.devices" for m in reconcile_html(gone))
    extra = html.replace("</main>", '<span data-metric="tickets.invented">3</span></main>')
    assert any(m.key == "tickets.invented" for m in reconcile_html(extra))


def test_b71_1_a_run_that_does_not_reconcile_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = health.health.render_html

    def lying(report: HealthReport) -> str:
        return real(report).replace('<span data-metric="tickets.opened">', '<span data-metric="tickets.opened">1', 1)

    monkeypatch.setattr(health.health, "render_html", lying)
    with pytest.raises(HealthError, match="tickets.opened"):
        create_draft("contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path)
    assert not any(tmp_path.rglob("*.html")) and not any(tmp_path.rglob("*.json"))


def test_b71_1_the_validator_catches_a_source_that_changed_after_the_draft(tmp_path: Path) -> None:
    src = _world(tmp_path / "w")
    d = create_draft("fabrikam-capital", PERIOD, generated_on=GENERATED, out_dir=tmp_path / "out", sources=src)
    verify_draft(d.html_path, sources=src)  # untouched: fine
    path = src.data_dir / "fabrikam-capital.patching.json"
    raw = _read(path)
    raw["devices"][0]["pending_critical"] = 4
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(VerifyError, match="patching"):
        verify_draft(d.html_path, sources=src)


def test_b71_1_verify_catches_an_edited_draft_and_a_hash_mismatch(tmp_path: Path) -> None:
    d = create_draft("contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path)
    verify_draft(d.html_path)
    original = d.html_path.read_text("utf-8")
    d.html_path.write_text(original.replace('data-metric="tickets.open">', 'data-metric="tickets.open">1', 1), "utf-8")
    with pytest.raises(VerifyError):
        verify_draft(d.html_path)
    d.html_path.write_text(original + "\n<!-- edited -->\n", "utf-8")  # numbers fine, bytes not
    with pytest.raises(VerifyError, match="hash"):
        verify_draft(d.html_path)


def test_b71_1_the_report_states_its_period_and_every_source_with_hash_and_date(
    reports: dict[str, HealthReport], pages: dict[str, str]
) -> None:
    for client in CLIENTS:
        html = pages[client]
        assert f'data-period="{PERIOD}"' in html and "October 2026" in html
        files = [DATA / f"{client}.{k}.json" for k in ("baseline", "patching", "awareness")] + [
            TICKETS / f"{client}.json"
        ]
        if (BACKUP / f"{client}.json").is_file():
            files.append(BACKUP / f"{client}.json")
        for f in files:
            digest = hashlib.sha256(f.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            assert digest in html, f.name
            assert f.name in html
        assert len(re.findall(r'<tr data-source="', html)) == len(files)
        assert "fixture-based" in html and "synthetic" in html.lower()
    contoso = _read(HEALTH_DIR / "data" / "contoso-dental.baseline.json")["as_of"]
    assert contoso in pages["contoso-dental"]


def test_b71_1_sources_dated_outside_the_period_are_not_reported(tmp_path: Path) -> None:
    r = build_report("contoso-dental", "2026-09", generated_on="2026-09-30")
    assert expect("contoso-dental", "2026-09") == {}
    assert all(not s.available for s in r.sections)
    page = Page(render_html(r))
    assert page.shown() == {}
    assert "outside the period" in render_html(r)


def test_b71_1_ticket_labels_and_technicians_are_never_read(tmp_path: Path) -> None:
    src = _world(tmp_path)
    path = src.tickets_dir / "contoso-dental.json"
    raw = _read(path)
    for t in raw["tickets"]:
        t.pop("labels", None)
        t.pop("technician", None)
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = Page(render_html(build_report("contoso-dental", PERIOD, generated_on=GENERATED))).shown()
    after = Page(render_html(build_report("contoso-dental", PERIOD, generated_on=GENERATED, sources=src))).shown()
    assert before == after
    html = render_html(build_report("contoso-dental", PERIOD, generated_on=GENERATED))
    assert not re.search(r"tech-|technician|T-5\d{3}|@contosodental", html)


# -- B71-2: summary from counts, optional rephrase, validator after the rephrase -------------------
def test_b71_2_the_summary_is_built_from_computed_counts(pages: dict[str, str]) -> None:
    for client in CLIENTS:
        page = Page(pages[client])
        text = page.summary()
        assert 'data-summary="computed"' in pages[client]
        m = page.shown()
        body = re.sub(r"October 2026|\d{4}-\d{2}-\d{2}", "", text)
        numbers = re.findall(r"\d+(?:\.\d+)?", body)
        assert numbers, "a summary with no numbers is not computed from counts"
        assert set(numbers) <= set(m.values())
    contoso = Page(pages["contoso-dental"]).summary()
    want = expect("contoso-dental")
    assert f"{want['tickets.opened']} tickets opened" in contoso
    assert f"{want['tickets.resolved']} tickets resolved" in contoso


def _facts_kept(prompt: str) -> str:
    """A believable rephrase: new wording around the same fact phrases (the prompt quotes them one per line)."""
    facts = re.findall(r'^- "(.+)"$', prompt, re.M)
    return "In plain terms: " + "; ".join(facts) + ". Please call us with questions."


def test_b71_2_a_rephrase_that_keeps_every_figure_is_used_and_revalidated() -> None:
    model = Echo(_facts_kept)
    r = build_report("contoso-dental", PERIOD, generated_on=GENERATED, gateway=_cfg_gateway(model))
    assert r.summary.origin == "rephrased" and r.summary.text.startswith("In plain terms:")
    html = render_html(r)
    assert 'data-summary="rephrased"' in html and reconcile_html(html) == ()
    assert len(model.seen) == 1


@pytest.mark.parametrize(
    ("label", "reply"),
    [
        ("changed number", lambda p: _draft_of(p).replace("tickets opened", "tickets opened (about 99)")),
        ("dropped fact", lambda p: "Things are mostly fine this month."),
        ("invented number", lambda p: _draft_of(p) + " Uptime was 100 percent."),
        ("spelled-out number", lambda p: _draft_of(p) + " Three more items are pending."),
        ("markup", lambda p: _draft_of(p) + " <script>alert(1)</script>"),
        ("link", lambda p: _draft_of(p) + " See https://example.invalid/x"),
    ],
)
def test_b71_2_a_rephrase_that_changes_a_figure_is_rejected_and_the_computed_text_stays(label: str, reply: Any) -> None:
    plain = build_report("contoso-dental", PERIOD, generated_on=GENERATED)
    r = build_report("contoso-dental", PERIOD, generated_on=GENERATED, gateway=_cfg_gateway(Echo(reply)))
    assert r.summary.origin == "computed", label
    assert r.summary.text == plain.summary.text
    assert "rephrase rejected" in r.summary.note
    html = render_html(r)
    assert "rephrase rejected" in html and reconcile_html(html) == ()


def test_b71_2_a_model_failure_or_the_default_mock_leaves_the_computed_text() -> None:
    def boom(prompt: str) -> str:
        raise RuntimeError("down")

    for gateway in (_cfg_gateway(Echo(boom)), Gateway(GatewayConfig.load(REPO_ROOT))):
        r = build_report("fabrikam-capital", PERIOD, generated_on=GENERATED, gateway=gateway)
        assert r.summary.origin == "computed" and "rephrase" in r.summary.note


def test_b71_2_the_validator_runs_on_the_final_html_after_the_rephrase() -> None:
    r = build_report("contoso-dental", PERIOD, generated_on=GENERATED, gateway=_cfg_gateway(Echo(_facts_kept)))
    html = render_html(r)
    swapped = html.replace("tickets opened", "tickets opened and 7 more", 1)
    assert any(m.key == "summary" for m in reconcile_html(swapped))
    assert any(m.key == "summary" for m in reconcile_html(html.replace("tickets resolved", "items closed", 1)))


def test_b71_2_the_model_sees_counts_only_for_this_client() -> None:
    model = Echo(_facts_kept)
    build_report("fabrikam-capital", PERIOD, generated_on=GENERATED, gateway=_cfg_gateway(model))
    sent = model.seen[0]
    assert "Fabrikam Capital" in sent
    for other in ("Contoso", "Litware", "contoso", "litware", "@", "T-5", "BJ-"):
        assert other not in sent
    assert not re.search(r"fabrikamcapital\.example|FC-", sent)


# -- B71-3: isolation ------------------------------------------------------------------------------
@pytest.mark.parametrize("client", CLIENTS)
def test_b71_3_no_other_clients_data_appears(
    client: str, reports: dict[str, HealthReport], pages: dict[str, str]
) -> None:
    html = pages[client] + json.dumps(health.report_to_dict(reports[client]))
    for other in CLIENTS:
        if other == client:
            continue
        stem = other.split("-")[0]
        assert stem not in html.lower(), (client, other)
        assert NAMES[other] not in html
    # ticket ids of the other clients
    others_ids = {t["id"] for o in CLIENTS if o != client for t in _read(TICKETS / f"{o}.json")["tickets"]} - {
        t["id"] for t in _read(TICKETS / f"{client}.json")["tickets"]
    }
    assert not any(i in html for i in others_ids)


def test_b71_3_the_backup_decoy_row_of_another_client_is_not_counted() -> None:
    bk = _read(BACKUP / "fabrikam-capital.json")
    decoys = [j for j in bk["jobs"] if j["organizationId"] != bk["organization"]["id"]]
    assert decoys, "fixture lost its decoy row; the isolation test would pass for nothing"
    m = Page(render_html(build_report("fabrikam-capital", PERIOD, generated_on=GENERATED))).shown()
    assert m["backup.jobs"] == str(len(bk["jobs"]) - len(decoys))


def test_b71_3_a_source_file_of_another_client_is_refused(tmp_path: Path) -> None:
    src = _world(tmp_path)
    shutil.copy(src.data_dir / "litware-legal.patching.json", src.data_dir / "contoso-dental.patching.json")
    with pytest.raises(HealthError, match="client"):
        build_report("contoso-dental", PERIOD, generated_on=GENERATED, sources=src)


def test_b71_3_a_ticket_of_another_client_in_the_ticket_file_is_refused(tmp_path: Path) -> None:
    src = _world(tmp_path)
    path = src.tickets_dir / "contoso-dental.json"
    raw = _read(path)
    raw["tickets"][3]["client"] = "fabrikam-capital"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(HealthError, match="another client"):
        build_report("contoso-dental", PERIOD, generated_on=GENERATED, sources=src)


def test_b71_3_a_client_id_is_checked_and_there_is_no_msp_wide_report(tmp_path: Path) -> None:
    for bad in ("../contoso-dental", "Contoso", "", "a/b", "contoso-dental.json"):
        with pytest.raises(HealthError):
            build_report(bad, PERIOD, generated_on=GENERATED)
    with pytest.raises(HealthError, match="no source data"):
        build_report("adatum-unknown", PERIOD, generated_on=GENERATED)
    assert not hasattr(health, "build_msp_report")


# -- B71-4: security-awareness lines ---------------------------------------------------------------
@pytest.mark.parametrize("client", CLIENTS)
def test_b71_4_awareness_lines_come_from_the_per_client_fixture_and_say_what_they_are(
    client: str, reports: dict[str, HealthReport], pages: dict[str, str]
) -> None:
    html = pages[client]
    sec = next(s for s in reports[client].sections if s.key == "awareness")
    assert sec.available
    assert "service-level" in html.lower() and "UNVERIFIED" in html
    assert "MP-23" in html and "MP-24" in html
    af = _read(DATA / f"{client}.awareness.json")
    assert af["client"] == client and af["level"] == "service"
    assert af["services"]["phishing_simulation"]["vendor"] == "UNVERIFIED"
    assert af["services"]["password_vault"]["vendor"] == "UNVERIFIED"
    assert "vault.audit_score" in Page(html).shown() and "phish.click_pct" in Page(html).shown()


def test_b71_4_an_awareness_fixture_that_is_not_service_level_or_names_a_known_vendor_is_refused(
    tmp_path: Path,
) -> None:
    src = _world(tmp_path)
    path = src.data_dir / "contoso-dental.awareness.json"
    raw = _read(path)
    raw["level"] = "per-user"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(HealthError, match="service-level"):
        build_report("contoso-dental", PERIOD, generated_on=GENERATED, sources=src)
    raw["level"] = "service"
    raw["services"]["password_vault"]["vendor"] = "SomeVendor"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(HealthError, match="UNVERIFIED"):
        build_report("contoso-dental", PERIOD, generated_on=GENERATED, sources=src)


# -- draft only: a person reviews before it goes anywhere ------------------------------------------
def test_b71_the_report_is_a_draft_that_nothing_sends(
    reports: dict[str, HealthReport], pages: dict[str, str], tmp_path: Path
) -> None:
    for client in CLIENTS:
        html = pages[client]
        assert 'data-report-status="draft"' in html and "DRAFT" in html
        assert "Not sent" in html and "person reviews" in html
        assert not re.search(r"<script|<iframe|<form|<img|<link|src=|href=|http://|https://|@import|url\(", html, re.I)
        data = health.report_to_dict(reports[client])
        assert data["status"] == "draft" and data["reviewed_by"] is None and data["reviewed_on"] is None
    d = create_draft("contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path)
    body = _read(d.json_path)
    assert body["status"] == "draft" and body["html_sha256"] == d.sha256
    assert "this draft" in body["note"].lower()


def test_b71_the_module_has_no_way_to_send_or_reach_the_network() -> None:
    text = "".join(p.read_text("utf-8") for p in HEALTH_DIR.glob("*.py"))
    assert not re.search(
        r"^\s*(?:import|from)\s+(?:socket|smtplib|urllib|http|requests|httpx|subprocess|ftplib)\b", text, re.M
    )
    assert not re.search(r"\bdef\s+(?:send|post|deliver|publish|email|notify)\w*\(", text)
    assert not re.search(r"core\.(?:notify|levers|queue)|workflows\.notify", text)


def test_b71_output_is_deterministic_and_dates_never_come_from_the_clock(tmp_path: Path) -> None:
    a = create_draft("contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path / "a")
    b = create_draft("contoso-dental", PERIOD, generated_on=GENERATED, out_dir=tmp_path / "b")
    assert a.html_path.read_bytes() == b.html_path.read_bytes()
    assert a.json_path.read_bytes() == b.json_path.read_bytes()
    assert GENERATED in a.html_path.read_text("utf-8")


# -- public interface other workflows (QBR, digest) build on ---------------------------------------
def test_b71_public_interface_is_small_and_typed_for_reuse() -> None:
    for name in (
        "build_report",
        "create_draft",
        "render_html",
        "report_to_dict",
        "reconcile_html",
        "verify_draft",
        "HealthReport",
        "Section",
        "Summary",
        "SourceRef",
        "Sources",
        "Mismatch",
        "HealthError",
        "VerifyError",
        "SECTION_KEYS",
        "METRIC_LABELS",
        "main",
    ):
        assert name in health.__all__ and hasattr(health, name), name
    assert health.SECTION_KEYS == ("tickets", "baseline", "patching", "backup", "awareness")
    r = build_report("contoso-dental", PERIOD, generated_on=GENERATED)
    assert (r.client, r.period, r.generated_on, r.status) == ("contoso-dental", PERIOD, GENERATED, "draft")
    assert tuple(s.key for s in r.sections) == health.SECTION_KEYS
    m = {k: v for s in r.sections for k, v in s.metrics.items()}
    assert set(m) <= set(health.METRIC_LABELS) | {k for k in m if k.startswith("tickets.channel.")}
    assert m["tickets.opened"] == int(expect("contoso-dental")["tickets.opened"])  # typed values, not text
    assert isinstance(m["tickets.resolved_pct"], float) and isinstance(m["vault.mfa_enforced"], str)
    section = r.sections[0]
    with pytest.raises(AttributeError):
        section.key = "x"  # type: ignore[misc]
    assert all(s.sources and s.sources[0].sha256 for s in r.sections if s.available)


def test_b71_bad_period_or_dates_are_refused() -> None:
    for bad in ("2026-13", "2026-1", "October", "2026-10-01", ""):
        with pytest.raises(HealthError, match="period"):
            build_report("contoso-dental", bad, generated_on=GENERATED)
    for bad in ("31/10/2026", "2026-10-99", ""):
        with pytest.raises(HealthError, match="generated_on"):
            build_report("contoso-dental", PERIOD, generated_on=bad)
    with pytest.raises(HealthError, match="before the period"):
        build_report("contoso-dental", PERIOD, generated_on="2026-09-30")


# -- CLI -------------------------------------------------------------------------------------------
def test_b71_cli_build_all_and_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert main(["build", "--all", "--period", PERIOD, "--generated-on", GENERATED, "--out", str(out)]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    assert sorted(x["client"] for x in lines) == sorted(CLIENTS)
    assert all(x["status"] == "draft" for x in lines)
    html = out / PERIOD / "contoso-dental.draft.html"
    assert main(["verify", str(html)]) == 0
    html.write_text(
        html.read_text("utf-8").replace('data-metric="tickets.open">', 'data-metric="tickets.open">1', 1), "utf-8"
    )
    assert main(["verify", str(html)]) == 1
    assert "MISMATCH" in capsys.readouterr().err


def test_b71_cli_bad_input_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["build", "nobody", "--period", PERIOD, "--generated-on", GENERATED, "--out", str(tmp_path)]) == 2
    assert main(["build", "--period", PERIOD, "--generated-on", GENERATED, "--out", str(tmp_path)]) == 2
    assert (
        main(["build", "contoso-dental", "--period", "2026-99", "--generated-on", GENERATED, "--out", str(tmp_path)])
        == 2
    )
    assert main(["verify", str(tmp_path / "missing.html")]) == 2
    assert not list(tmp_path.rglob("*.html"))
    capsys.readouterr()


# -- fixtures are honest ---------------------------------------------------------------------------
@pytest.mark.parametrize("client", CLIENTS)
def test_b71_fixtures_carry_a_synthetic_note_and_a_consistent_drift_block(client: str) -> None:
    for kind in ("baseline", "patching", "awareness"):
        raw = _read(DATA / f"{client}.{kind}.json")
        assert "ynthetic" in raw["_note"] and raw["client"] == client and raw["as_of"].endswith("Z")
    b = _read(DATA / f"{client}.baseline.json")
    keys = {(f["CheckId"], f["Subject"]) for f in b["findings"]}
    drift = b["drift"]
    now = {(x["CheckId"], x["Subject"]) for x in drift["new"] + drift["unchanged"]}
    assert keys == now, "drift new + unchanged must be exactly the current findings"
    assert not {(x["CheckId"], x["Subject"]) for x in drift["resolved"]} & keys
    ids = [d["id"] for d in _read(DATA / f"{client}.patching.json")["devices"]]
    assert len(ids) == len(set(ids))
