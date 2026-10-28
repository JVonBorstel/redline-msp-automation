"""B-39 sign-in failure and lockout investigation: the signins.list lever and workflows/lockout.

Acceptance ids B39-1 to B39-3 are defined in specs/B-39.md. Every test is offline and works in a private folder
(tmp_path); committed fixtures are never modified. Run: uv run --frozen pytest -p no:cacheprovider tests/py/lockout
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, LeverRunner, MockTenant, Registry
from workflows.lockout import (
    DEFAULT_CODES_PATH,
    LockoutError,
    investigate,
    load_codes,
    prompt_text,
    summary,
)
from workflows.lockout.__main__ import main

CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
PRIYA = "priya.nair@contosodental.example"
ANA = "ana.lopez@contosodental.example"
SAM = "sam.patel@contosodental.example"
TOM = "tom.baker@contosodental.example"
LENA = "lena.fischer@contosodental.example"
RILEY = "riley.brooks@fabrikamcapital.example"
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Any]:
    shutil.copytree(DEFAULT_TENANT_DIR, tmp_path / "tenant")
    audit = tmp_path / "audit.jsonl"
    runner = LeverRunner(Registry.load(), IdentityStore.load(), MockTenant(tmp_path / "tenant"), AuditLog(audit))
    return {"runner": runner, "audit": audit, "tenant": tmp_path / "tenant", "tmp": tmp_path}


def _tree(path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def _records(audit: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]


def _events(runner: LeverRunner, upn: str, client: str = CONTOSO, **extra: Any) -> Any:
    who = "tech-ben" if client == FABRIKAM else "tech-ana"
    return runner.invoke("signins.list", {"upn": upn, **extra}, identity=who, client=client, mode="execute")


# -- B39-1 signins.list ------------------------------------------------------------------------------------------


def test_b39_1_the_lever_is_a_registered_r0_read_lever() -> None:
    lever = Registry.load().get("signins.list")
    assert lever.lever_class == "read" and lever.risk_class == "R0" and lever.approval == "none"
    assert lever.required_role == "technician"  # IP addresses and places are DC-3 personal data


def test_b39_1_returns_one_users_signins_newest_first(env: dict[str, Any]) -> None:
    result = _events(env["runner"], PRIYA)
    assert result.ok and not result.applied and result.diff == ()
    rows = result.data
    assert len(rows) == 7 and {r["userPrincipalName"] for r in rows} == {PRIYA}
    times = [r["createdDateTime"] for r in rows]
    assert times == sorted(times, reverse=True)
    assert {"id", "createdDateTime", "ipAddress", "status", "location", "appDisplayName"} <= set(rows[0])


def test_b39_1_limit_caps_the_result(env: dict[str, Any]) -> None:
    assert len(_events(env["runner"], PRIYA, limit=2).data) == 2
    assert _events(env["runner"], PRIYA, limit=0).status == "denied"
    assert _events(env["runner"], PRIYA, limit=51).status == "denied"


def test_b39_1_read_results_are_never_written_to_the_audit(env: dict[str, Any]) -> None:
    result = _events(env["runner"], PRIYA)
    text = env["audit"].read_text(encoding="utf-8")
    for event in result.data:
        assert event["ipAddress"] not in text and event["id"] not in text
        assert event["location"]["city"] not in text
    record = _records(env["audit"])[-1]
    assert record["lever"] == "signins.list" and record["client"] == CONTOSO and record["agent"] == "tech-ana"
    assert record["params"] == {"upn": PRIYA} and record["result"]["changes"] == []


def test_b39_1_a_read_changes_no_file(env: dict[str, Any]) -> None:
    before = _tree(env["tenant"])
    _events(env["runner"], PRIYA)
    _events(env["runner"], RILEY, client=FABRIKAM)
    assert _tree(env["tenant"]) == before


def test_b39_1_an_agent_cannot_read_sign_ins(env: dict[str, Any]) -> None:
    result = env["runner"].invoke("signins.list", {"upn": PRIYA}, identity="triage-bot", client=CONTOSO, mode="execute")
    assert result.status == "denied" and result.data is None


def test_b39_1_another_clients_user_answers_like_an_absent_one(env: dict[str, Any]) -> None:
    other = _events(env["runner"], RILEY, client=CONTOSO)
    absent = _events(env["runner"], "nobody@contosodental.example", client=CONTOSO)
    assert other.status == absent.status == "error" and other.reason == absent.reason
    assert other.data is None
    assert _events(env["runner"], RILEY, client=FABRIKAM).ok  # the same user under the right client works


def test_b39_1_a_family_file_naming_another_client_is_refused(env: dict[str, Any]) -> None:
    wrong = env["tenant"] / CONTOSO / "signins.json"
    data = json.loads(wrong.read_text(encoding="utf-8"))
    data["_meta"]["client"] = FABRIKAM
    wrong.write_text(json.dumps(data), encoding="utf-8")
    result = _events(env["runner"], PRIYA)
    assert result.status == "error" and result.data is None


def test_b39_1_fixture_fields_are_the_verified_graph_signin_names() -> None:
    allowed = {
        "id", "createdDateTime", "userDisplayName", "userPrincipalName", "userId", "appDisplayName", "ipAddress",
        "clientAppUsed", "conditionalAccessStatus", "isInteractive", "status", "location",
    }  # fmt: skip
    for client in (CONTOSO, FABRIKAM):
        doc = json.loads((DEFAULT_TENANT_DIR / client / "signins.json").read_text(encoding="utf-8"))
        assert doc["_meta"]["client"] == client and "VERIFIED" in doc["_meta"]["note"]
        users = {
            u["userPrincipalName"]
            for u in json.loads((DEFAULT_TENANT_DIR / f"{client}.json").read_text("utf-8"))["users"]
        }
        for event in doc["value"]:
            assert set(event) <= allowed and event["userPrincipalName"] in users
            assert set(event["status"]) == {"errorCode", "failureReason", "additionalDetails"}
            assert set(event["location"]) == {"city", "state", "countryOrRegion"}


# -- B39-2 plain causes from a cited table, suggestions, never executes ------------------------------------------


def test_b39_2_every_code_is_cited_and_unchecked_ones_say_so() -> None:
    table = load_codes()
    raw = json.loads(DEFAULT_CODES_PATH.read_text(encoding="utf-8"))
    assert table.source.startswith("https://learn.microsoft.com/") and raw["codes"]
    for row in table.rows.values():
        assert row.status in ("verified", "UNVERIFIED") and row.cause and row.next
        if row.status == "UNVERIFIED":
            assert "UNVERIFIED" in row.cause
    assert table.rows[500121].status == "UNVERIFIED"
    assert table.rows[50126].status == "verified"


def test_b39_2_failure_codes_become_plain_causes(env: dict[str, Any]) -> None:
    inv = investigate(env["runner"], CONTOSO, ANA, "tech-ana")
    [cause] = inv.prompt_view["causes"]
    assert cause["code"] == 50079 and cause["status"] == "verified" and "not registered" in cause["cause"]
    assert cause["source"].startswith("https://learn.microsoft.com/")
    tom = investigate(env["runner"], CONTOSO, TOM, "tech-ana")
    statuses = {c["code"]: c["status"] for c in tom.prompt_view["causes"]}
    assert statuses == {50055: "verified", 500121: "UNVERIFIED"}


def test_b39_2_a_code_not_in_the_table_is_unverified_not_guessed(env: dict[str, Any]) -> None:
    [cause] = investigate(env["runner"], CONTOSO, LENA, "tech-ana").prompt_view["causes"]
    assert cause["code"] == 70999 and cause["name"] == "unknown" and cause["status"] == "UNVERIFIED"


def test_b39_2_suggests_the_right_lever_and_it_is_registered(env: dict[str, Any]) -> None:
    registry = Registry.load()
    inv = investigate(env["runner"], CONTOSO, ANA, "tech-ana")
    [suggestion] = inv.prompt_view["suggestions"]
    assert suggestion == {**suggestion, "lever": "user.reset-mfa", "params": {"upn": ANA}, "executed": False}
    assert registry.get("user.reset-mfa").lever_class == "write"
    for row in load_codes().rows.values():
        if row.lever is not None:
            assert row.lever in registry.names()
    # a Conditional Access block suggests no lever: that stays with a human
    assert investigate(env["runner"], CONTOSO, SAM, "tech-ana").prompt_view["suggestions"] == []


def test_b39_2_many_wrong_passwords_from_several_places_are_flagged_as_guessing(env: dict[str, Any]) -> None:
    priya = investigate(env["runner"], CONTOSO, PRIYA, "tech-ana")
    assert priya.prompt_view["possible_password_guessing"] is True
    assert priya.prompt_view["suggestions"][-1]["lever"] is None  # escalate, no lever
    riley = investigate(env["runner"], FABRIKAM, RILEY, "tech-ben")  # two typos from one place
    assert riley.prompt_view["possible_password_guessing"] is False


def test_b39_2_it_never_executes_anything(env: dict[str, Any]) -> None:
    before = _tree(env["tenant"])
    for upn in (PRIYA, ANA, SAM, TOM, LENA):
        inv = investigate(env["runner"], CONTOSO, upn, "tech-ana")
        assert inv.executed is False and all(s["executed"] is False for s in inv.prompt_view["suggestions"])
    assert _tree(env["tenant"]) == before
    records = _records(env["audit"])
    assert records and {r["lever"] for r in records} == {"signins.list"}
    assert all(not r["result"]["applied"] for r in records)


def test_b39_2_a_refused_read_is_an_error_not_a_conclusion(env: dict[str, Any]) -> None:
    with pytest.raises(LockoutError):
        investigate(env["runner"], CONTOSO, RILEY, "tech-ana")  # another client's user
    with pytest.raises(LockoutError):
        investigate(env["runner"], CONTOSO, PRIYA, "triage-bot")  # an agent may not read sign-ins


def test_b39_2_a_bad_table_fails_closed(tmp_path: Path) -> None:
    bad = tmp_path / "codes.json"
    bad.write_text(json.dumps({"version": 1, "source": "x", "codes": [{"code": 1}]}), encoding="utf-8")
    with pytest.raises(LockoutError):
        load_codes(bad)


# -- B39-3 IP addresses and locations only in the technician's view ----------------------------------------------


def test_b39_3_the_technician_view_has_ip_and_place(env: dict[str, Any]) -> None:
    view = summary(investigate(env["runner"], CONTOSO, PRIYA, "tech-ana"))
    assert any(IPV4.fullmatch(e["ip_address"]) for e in view["events"])
    assert any(e["location"]["city"] == "Lagos" for e in view["events"])
    assert view["distinct_ips_in_password_failures"] >= 2


@pytest.mark.parametrize(
    ("client", "upn", "identity"),
    [(CONTOSO, u, "tech-ana") for u in (PRIYA, ANA, SAM, TOM, LENA)] + [(FABRIKAM, RILEY, "tech-ben")],
)
def test_b39_3_the_prompt_view_and_text_hold_no_ip_place_time_or_log_text(
    env: dict[str, Any], client: str, upn: str, identity: str
) -> None:
    inv = investigate(env["runner"], client, upn, identity)
    raw = _events(env["runner"], upn, client).data
    blob = json.dumps(inv.prompt_view) + "\n" + prompt_text(inv)
    assert not IPV4.search(blob) and not TIMESTAMP.search(blob)
    for event in raw:
        for secret in (
            event["ipAddress"],
            event["location"]["city"],
            event["location"]["countryOrRegion"],
            event["status"]["failureReason"],
        ):
            if secret:
                assert secret not in blob


def test_b39_3_untrusted_log_text_is_flagged_and_never_copied(env: dict[str, Any]) -> None:
    inv = investigate(env["runner"], CONTOSO, TOM, "tech-ana")
    assert inv.prompt_view["log_text_flagged_as_instructions"] == 1
    everything = json.dumps(inv.technician_view) + prompt_text(inv)
    assert "Ignore previous instructions" not in everything and "reset every password" not in everything
    assert investigate(env["runner"], CONTOSO, ANA, "tech-ana").prompt_view["log_text_flagged_as_instructions"] == 0


def test_b39_3_the_cli_prompt_flag_prints_only_the_safe_text(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    audit = str(tmp_path / "a.jsonl")
    assert main([CONTOSO, PRIYA, "--prompt", "--audit", audit]) == 0
    out = capsys.readouterr().out
    assert "possible password guessing" in out and not IPV4.search(out)
    assert main([CONTOSO, RILEY, "--audit", audit]) == 2
    full = main([CONTOSO, PRIYA, "--audit", audit])
    assert full == 0 and IPV4.search(capsys.readouterr().out)
