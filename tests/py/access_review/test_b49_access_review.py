"""B-49 quarterly access review. Acceptance ids B49-1 to B49-3 are defined in specs/B-49.md.

Offline and deterministic: dates are pinned with as_of, output and audit chains go under tmp_path, committed
fixtures and config are never modified (tests that need other identities or levers write copies under tmp_path).
Run: uv run --frozen pytest -p no:cacheprovider tests/py/access_review
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from core.audit.chain import head_path_for, verify_chain
from core.identity import IdentityStore
from core.levers.registry import Registry
from workflows.access_review import (
    DECISIONS,
    AccessReviewError,
    VerifyError,
    audit_digest,
    build_client_export,
    build_msp_export,
    canonical_bytes,
    decide,
    execute_levers,
    export,
    load_needs,
    quarter_of,
    sidecar_for,
    undecided,
    verify,
)
from workflows.access_review.__main__ import main
from workflows.access_review.review import (
    DEFAULT_IDENTITIES,
    DEFAULT_NEEDS,
    DEFAULT_REGISTRY,
    GRAPH_FOLDER,
    ROW_ID,
)

REPO = Path(__file__).resolve().parents[3]
AS_OF = "2026-10-23"
LEAD = "lead-lee"
CLIENTS = ("contoso-dental", "fabrikam-capital")


def _read(path: Path) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(path.read_bytes())
    return body


def _records(audit: Path, name: str) -> list[dict[str, Any]]:
    chain = audit / f"{name}.jsonl"
    return [json.loads(line) for line in chain.read_text(encoding="utf-8").splitlines()] if chain.is_file() else []


def _chain_ok(audit: Path, name: str) -> bool:
    chain = audit / f"{name}.jsonl"
    return verify_chain(chain, head_path_for(chain)).ok


def _export(tmp_path: Path, client: str | None = "contoso-dental", **kw: Any) -> Path:
    kw.setdefault("by", LEAD)
    written = export(client, as_of=AS_OF, out_dir=tmp_path / "out", audit_dir=tmp_path / "audit", **kw)
    return written.path


def _identities(tmp_path: Path, extra: list[dict[str, Any]]) -> Path:
    raw = json.loads(DEFAULT_IDENTITIES.read_text(encoding="utf-8"))
    raw["identities"].extend(extra)
    path = tmp_path / "identities.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _needs(tmp_path: Path, agents: dict[str, Any]) -> Path:
    path = tmp_path / "needs.json"
    path.write_text(json.dumps({"version": 1, "agents": agents}), encoding="utf-8")
    return path


def _agent_registry(tmp_path: Path, scope: Any = "any", *, write: bool = True, read_scope: Any = None) -> Path:
    """A one-file registry (no registry.d beside it) holding `user.disable` with required_role lowered to agent.

    `write=False` leaves out the write lever; `read_scope` sets `ticket.get`'s client_scope (a read lever)."""
    raw = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    names = ("ticket.get", "kb.search", "user.disable") if write else ("ticket.get", "kb.search")
    levers = [dict(lv) for lv in raw["levers"] if lv["name"] in names]
    for lever in levers:
        if lever["name"] == "user.disable":
            lever["required_role"] = "agent"
            lever["client_scope"] = scope
        if lever["name"] == "ticket.get" and read_scope is not None:
            lever["client_scope"] = read_scope
    folder = tmp_path / "reg"
    folder.mkdir()
    path = folder / "registry.json"
    path.write_text(json.dumps({"version": raw["version"], "levers": levers}), encoding="utf-8")
    return path


def _sub(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _fixture_members(client: str) -> list[dict[str, Any]]:
    body = json.loads((REPO / "fixtures" / "graph" / GRAPH_FOLDER[client] / "directoryRoles.json").read_text("utf-8"))
    return [m | {"_role": r["roleTemplateId"]} for r in body["value"] for m in r["members"]]


def _all_keep(path: Path) -> dict[str, str]:
    return {r["row_id"]: "keep" for r in _read(path)["rows"]}


# -- B49-1: quarterly per-client export, dated and SHA-256 hashed ---------------------------------------------------
@pytest.mark.parametrize("client", CLIENTS)
def test_b49_1_client_export_lists_every_directory_role_member_from_the_graph_mock(tmp_path: Path, client: str) -> None:
    body = _read(_export(tmp_path, client))
    rows = [r for r in body["rows"] if r["kind"] == "directory-role-member"]
    members = _fixture_members(client)
    assert len(rows) == len(members) > 0
    got = {(r["role_template_id"], r["member_id"], r["user_principal_name"]) for r in rows}
    assert got == {(m["_role"], m["id"], m["userPrincipalName"]) for m in members}
    assert all(r["role"] and r["member_type"] == "user" for r in rows)


@pytest.mark.parametrize("client", CLIENTS)
def test_b49_1_client_export_lists_every_repo_identity_for_the_client_with_its_role(
    tmp_path: Path, client: str
) -> None:
    body = _read(_export(tmp_path, client))
    rows = {r["identity"]: r for r in body["rows"] if r["kind"] == "repo-identity"}
    config = json.loads(DEFAULT_IDENTITIES.read_text(encoding="utf-8"))["identities"]
    scoped = {i["id"]: i for i in config if client in i["clients"]}
    assert set(rows) == set(scoped)
    for ident, row in rows.items():
        assert row["role"] == scoped[ident]["role"]
        assert row["clients"] == [client]
        assert row["other_clients"] == len(scoped[ident]["clients"]) - 1


def test_b49_1_msp_export_lists_every_repo_identity_with_role_and_client_list(tmp_path: Path) -> None:
    body = _read(_export(tmp_path, None))
    config = json.loads(DEFAULT_IDENTITIES.read_text(encoding="utf-8"))["identities"]
    assert body["scope"] == "msp" and body["client"] is None
    got = {r["identity"]: (r["role"], r["clients"]) for r in body["rows"]}
    assert got == {i["id"]: (i["role"], sorted(i["clients"])) for i in config}
    assert body["data_class"] == "DC-1"


@pytest.mark.parametrize("client", [*CLIENTS, None])
def test_b49_1_export_is_dated_and_its_sha256_sidecar_matches_the_file(tmp_path: Path, client: str | None) -> None:
    path = _export(tmp_path, client)
    body = _read(path)
    assert (body["as_of"], body["quarter"], body["exported_by"]) == (AS_OF, "2026-Q4", LEAD)
    assert path.parent.name == "2026-Q4" and path.name == f"{client or '_msp'}.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert sidecar_for(path).read_text(encoding="ascii") == f"{digest}  {path.name}\n"
    assert verify(path) == digest


def test_b49_1_export_names_the_sha256_of_every_source_it_read(tmp_path: Path) -> None:
    body = _read(_export(tmp_path))
    roles = REPO / "fixtures" / "graph" / "contoso" / "directoryRoles.json"
    assert body["sources"]["directory_roles"] == {
        "path": "fixtures/graph/contoso/directoryRoles.json",
        "sha256": hashlib.sha256(roles.read_bytes()).hexdigest(),
    }
    assert body["sources"]["identities"]["sha256"] == hashlib.sha256(DEFAULT_IDENTITIES.read_bytes()).hexdigest()
    assert body["sources"]["needs"]["sha256"] == hashlib.sha256(DEFAULT_NEEDS.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("as_of", "quarter"),
    [("2026-01-01", "2026-Q1"), ("2026-03-31", "2026-Q1"), ("2026-04-01", "2026-Q2"), ("2026-09-30", "2026-Q3"),
     ("2026-10-01", "2026-Q4"), ("2026-12-31", "2026-Q4")],
)  # fmt: skip
def test_b49_1_quarter_comes_from_the_as_of_date(as_of: str, quarter: str) -> None:
    assert quarter_of(as_of) == quarter


def test_b49_1_bad_as_of_is_refused() -> None:
    with pytest.raises(AccessReviewError, match="ISO date"):
        quarter_of("23/10/2026")


def test_b49_1_export_is_deterministic(tmp_path: Path) -> None:
    one = build_client_export("contoso-dental", as_of=AS_OF, by=LEAD)
    two = build_client_export("contoso-dental", as_of=AS_OF, by=LEAD)
    assert canonical_bytes(one) == canonical_bytes(two)
    assert _export(tmp_path).read_bytes() == canonical_bytes(one)


@pytest.mark.parametrize(("client", "other"), [CLIENTS, CLIENTS[::-1]])
def test_b49_1_client_export_names_no_other_client(tmp_path: Path, client: str, other: str) -> None:
    text = _export(tmp_path, client).read_text(encoding="ascii")
    other_domain = "fabrikamcapital" if other == "fabrikam-capital" else "contosodental"
    assert other not in text and other_domain not in text
    assert "lead-lee" in text  # a cross-client identity is listed, its other client is a count only


def test_b49_1_client_without_graph_data_is_refused_and_nothing_written(tmp_path: Path) -> None:
    identities = _identities(
        tmp_path,
        [{"id": "lead-lit", "display_name": "Lit lead (synthetic)", "role": "lead", "clients": ["litware-legal"]}],
    )
    with pytest.raises(AccessReviewError, match="no directory role data"):
        _export(tmp_path, "litware-legal", by="lead-lit", identities_path=identities)
    assert not (tmp_path / "out").exists()
    (record,) = _records(tmp_path / "audit", "litware-legal")  # a refusal after the lead check is audited too
    assert record["result"]["status"] == "denied" and "no directory role data" in record["result"]["reason"]
    assert (record["agent"], record["actor_kind"], record["lever"]) == ("lead-lit", "human", "access-review.export")
    assert _chain_ok(tmp_path / "audit", "litware-legal")


def test_b49_1_bad_needs_or_registry_after_the_lead_check_is_refused_and_audited(tmp_path: Path) -> None:
    bad_needs = tmp_path / "bad-needs.json"
    bad_needs.write_text("{not json", encoding="utf-8")
    with pytest.raises(AccessReviewError, match="cannot read"):
        _export(tmp_path, needs_path=bad_needs)
    bad_registry = tmp_path / "bad-registry.json"
    bad_registry.write_text("{not json", encoding="utf-8")
    with pytest.raises(AccessReviewError):
        _export(tmp_path, None, registry_path=bad_registry)
    assert not (tmp_path / "out").exists()
    (con,) = _records(tmp_path / "audit", "contoso-dental")
    (msp,) = _records(tmp_path / "audit", "_msp")
    assert con["result"]["status"] == msp["result"]["status"] == "denied"
    assert _chain_ok(tmp_path / "audit", "contoso-dental") and _chain_ok(tmp_path / "audit", "_msp")


def _graph_dir(tmp_path: Path, members: list[Any], template: str | None = "tmpl-1") -> Path:
    """A graph folder with one directory role for contoso-dental holding `members` (synthetic)."""
    folder = tmp_path / "graph" / GRAPH_FOLDER["contoso-dental"]
    folder.mkdir(parents=True)
    role: dict[str, Any] = {"id": "r-1", "displayName": "Test Admin", "members": members}
    if template is not None:
        role["roleTemplateId"] = template
    (folder / "directoryRoles.json").write_text(json.dumps({"value": [role]}), encoding="utf-8")
    return tmp_path / "graph"


def _user(ident: str | None, **extra: Any) -> dict[str, Any]:
    user: dict[str, Any] = {"@odata.type": "#microsoft.graph.user", "userPrincipalName": f"{ident}@x.example"}
    if ident is not None:
        user["id"] = ident
    return user | extra


def test_b49_1_member_user_type_and_account_enabled_are_carried_and_flagged(tmp_path: Path) -> None:
    graph = _graph_dir(
        tmp_path,
        [
            _user("guest-1", userType="Guest", accountEnabled=True),
            _user("off-1", userType="Member", accountEnabled=False),
            _user("plain-1"),
        ],
    )
    rows = {r["member_id"]: r for r in _read(_export(tmp_path, graph_dir=graph))["rows"] if "member_id" in r}
    assert (rows["guest-1"]["user_type"], rows["guest-1"]["account_enabled"]) == ("Guest", True)
    assert [f["flag"] for f in rows["guest-1"]["flags"]] == ["guest-holds-role"]
    assert [f["flag"] for f in rows["off-1"]["flags"]] == ["disabled-account-holds-role"]
    assert rows["off-1"]["account_enabled"] is False
    plain = rows["plain-1"]  # the fixtures do not carry these fields: absent, not guessed
    assert (plain["user_type"], plain["account_enabled"], plain["flags"]) == (None, None, [])


def test_b49_1_members_without_an_id_or_role_template_are_skipped_and_counted(tmp_path: Path) -> None:
    graph = _graph_dir(tmp_path, [_user("ok-1"), _user(None), _user("")])
    body = _read(_export(tmp_path, graph_dir=graph))
    members = [r for r in body["rows"] if r["kind"] == "directory-role-member"]
    assert [r["member_id"] for r in members] == ["ok-1"]
    assert body["gaps"]["members_without_id"] == 2
    assert "None" not in json.dumps(body["rows"])
    two = _sub(tmp_path, "two")
    body2 = _read(_export(two, graph_dir=_graph_dir(two, [_user("a"), _user("b")], template=None)))
    assert not [r for r in body2["rows"] if r["kind"] == "directory-role-member"]
    assert body2["gaps"]["members_without_id"] == 2


def test_b49_1_skipped_members_are_counted_in_the_audit_record_not_only_the_file(tmp_path: Path) -> None:
    graph = _graph_dir(tmp_path, [_user("ok-1"), _user(None), _user("")])
    _export(tmp_path, graph_dir=graph)
    last = _records(tmp_path / "audit", "contoso-dental")[-1]
    assert last["result"]["status"] == "ok"
    assert last["result"]["skipped"] == 2


def test_b49_1_duplicate_members_never_make_a_file_the_tool_wrote_fail_verify_or_decide(tmp_path: Path) -> None:
    graph = _graph_dir(tmp_path, [_user("dup-1"), _user("dup-1"), _user("dup-2")])
    path = _export(tmp_path, graph_dir=graph)
    body = _read(path)
    assert body["gaps"]["duplicate_members"] == 1
    ids = [r["row_id"] for r in body["rows"]]
    assert len(ids) == len(set(ids))
    verify(path)
    written = decide(path, _all_keep(path), by=LEAD, decided_on=AS_OF, audit_dir=tmp_path / "audit")
    assert verify(written.path, tmp_path / "audit") == written.sha256


@pytest.mark.parametrize("bad", ['quo"te', "new\nline", "sp ace", "x" * 300, "caf\u00e9"])
def test_b49_1_graph_ids_that_are_not_safe_row_keys_are_skipped_and_counted(tmp_path: Path, bad: str) -> None:
    graph = _graph_dir(tmp_path, [_user("ok-1"), _user(bad)])
    path = _export(tmp_path, graph_dir=graph)
    body = _read(path)
    assert [r["member_id"] for r in body["rows"] if r["kind"] == "directory-role-member"] == ["ok-1"]
    assert body["gaps"]["members_with_invalid_id"] == 1
    assert all(ROW_ID.fullmatch(r["row_id"]) for r in body["rows"])
    assert verify(path)


def test_b49_1_a_role_template_id_with_a_newline_is_skipped_and_counted(tmp_path: Path) -> None:
    graph = _graph_dir(tmp_path, [_user("ok-1")], template="tmpl\n")
    body = _read(_export(tmp_path, graph_dir=graph))
    assert not [r for r in body["rows"] if r["kind"] == "directory-role-member"]
    assert body["gaps"]["members_with_invalid_id"] == 1


def test_b49_1_bad_client_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AccessReviewError, match="not a client id"):
        _export(tmp_path, "../contoso")


@pytest.mark.parametrize(
    ("who", "reason", "kind"),
    [
        ("tech-ana", "needs lead", "human"),
        ("triage-bot", "needs lead", "agent"),
        ("nobody", "unknown identity", "unknown"),
    ],
)
def test_b49_1_only_a_lead_may_export_and_a_refusal_is_audited(
    tmp_path: Path, who: str, reason: str, kind: str
) -> None:
    with pytest.raises(AccessReviewError, match=reason):
        _export(tmp_path, by=who)
    assert not (tmp_path / "out").exists()
    (record,) = _records(tmp_path / "audit", "contoso-dental")
    assert record["result"]["status"] == "denied" and reason in record["result"]["reason"]
    assert (record["agent"], record["actor_kind"], record["event"]) == (who, kind, "job.run")
    assert _chain_ok(tmp_path / "audit", "contoso-dental")


def test_b49_1_a_lead_of_client_a_cannot_export_client_b_and_it_is_audited(tmp_path: Path) -> None:
    identities = _identities(
        tmp_path,
        [{"id": "lead-a", "display_name": "A lead (synthetic)", "role": "lead", "clients": ["contoso-dental"]}],
    )
    with pytest.raises(AccessReviewError, match="not scoped to 'fabrikam-capital'"):
        _export(tmp_path, "fabrikam-capital", by="lead-a", identities_path=identities)
    (record,) = _records(tmp_path / "audit", "fabrikam-capital")
    assert record["result"]["status"] == "denied"
    assert _records(tmp_path / "audit", "contoso-dental") == []
    with pytest.raises(AccessReviewError, match="not scoped to every client"):
        _export(tmp_path, None, by="lead-a", identities_path=identities)
    (msp,) = _records(tmp_path / "audit", "_msp")
    assert msp["client"] is None and msp["result"]["status"] == "denied"


@pytest.mark.parametrize("client", [*CLIENTS, None])
def test_b49_1_export_is_audited_in_its_own_chain_with_the_file_hash(tmp_path: Path, client: str | None) -> None:
    path = _export(tmp_path, client)
    name = client or "_msp"
    (record,) = _records(tmp_path / "audit", name)
    assert record["lever"] == "access-review.export" and record["result"]["status"] == "ok"
    assert record["client"] == client and record["actor_kind"] == "human"
    assert "".join(record["result"]["sha256"].split()) == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record["result"]["rows"] == len(_read(path)["rows"])
    assert "user_principal_name" not in json.dumps(record)  # the hash, never the rows
    assert _chain_ok(tmp_path / "audit", name)
    others = {p.stem for p in (tmp_path / "audit").glob("*.jsonl")}
    assert others == {name}


def test_b49_1_audit_digest_survives_redaction_and_rebuilds_the_hash() -> None:
    digest = hashlib.sha256(b"x").hexdigest()
    grouped = audit_digest(digest)
    assert len(grouped.split()) == 8 and "".join(grouped.split()) == digest


def test_b49_1_client_export_is_marked_end_user_pii(tmp_path: Path) -> None:
    assert _read(_export(tmp_path))["data_class"] == "DC-3"


# -- B49-2: a lead decision field on every row; re-verifiable from the hash -----------------------------------------
@pytest.mark.parametrize("client", [*CLIENTS, None])
def test_b49_2_every_row_has_an_empty_lead_decision_field(tmp_path: Path, client: str | None) -> None:
    body = _read(_export(tmp_path, client))
    assert body["decision_options"] == ["keep", "remove", "investigate"] == list(DECISIONS)
    assert body["rows"] and all("decision" in r and r["decision"] is None for r in body["rows"])
    assert len({r["row_id"] for r in body["rows"]}) == len(body["rows"])


def test_b49_2_a_changed_byte_fails_verification(tmp_path: Path) -> None:
    path = _export(tmp_path)
    path.write_bytes(path.read_bytes().replace(b"grace.kim", b"grace.kin"))
    with pytest.raises(VerifyError, match="does not match the sidecar"):
        verify(path)


def test_b49_2_a_file_that_matches_its_sidecar_but_is_not_json_is_a_clean_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "junk.json"
    for data, reason in ((b"{not json\n", "not valid JSON"), (b"[1]\n", "not an access review file")):
        path.write_bytes(data)
        sidecar_for(path).write_text(f"{hashlib.sha256(data).hexdigest()}  {path.name}\n", encoding="ascii")
        with pytest.raises(VerifyError, match=reason):
            verify(path)
        assert main(["verify", str(path)]) == 1
        assert "MISMATCH" in capsys.readouterr().err


def test_b49_2_a_missing_sidecar_fails_verification(tmp_path: Path) -> None:
    path = _export(tmp_path)
    sidecar_for(path).unlink()
    with pytest.raises(VerifyError, match="cannot read"):
        verify(path)


def test_b49_2_an_export_with_a_decision_filled_in_place_fails_verification(tmp_path: Path) -> None:
    path = _export(tmp_path)
    body = _read(path)
    body["rows"][0]["decision"] = "keep"
    data = canonical_bytes(body)
    path.write_bytes(data)
    sidecar_for(path).write_text(f"{hashlib.sha256(data).hexdigest()}  {path.name}\n", encoding="ascii")
    with pytest.raises(VerifyError, match="carries no decisions"):
        verify(path)


def test_b49_2_lead_decides_every_row_and_the_decided_file_rebuilds_the_export_hash(tmp_path: Path) -> None:
    path = _export(tmp_path)
    choices = _all_keep(path)
    first, second = sorted(choices)[:2]
    choices[first], choices[second] = "remove", "investigate"
    written = decide(
        path,
        choices,
        by=LEAD,
        decided_on="2026-10-24",
        notes={first: "left the practice"},
        audit_dir=tmp_path / "audit",
    )
    decided = _read(written.path)
    assert written.path.name == "contoso-dental.decided.json"
    assert decided["export_sha256"] == verify(path)
    assert (decided["decided_by"], decided["decided_on"]) == (LEAD, "2026-10-24")
    assert {r["row_id"]: r["decision"] for r in decided["rows"]} == choices
    assert verify(written.path) == written.sha256
    assert canonical_bytes(undecided(decided)) == path.read_bytes()
    records = _records(tmp_path / "audit", "contoso-dental")
    assert [r["lever"] for r in records] == ["access-review.export", "access-review.decide"]
    res = records[1]["result"]
    assert (res["keep"], res["remove"], res["investigate"]) == (len(choices) - 2, 1, 1)
    assert "".join(res["sha256"].split()) == written.sha256
    assert "".join(records[1]["params"]["export_sha256"].split()) == decided["export_sha256"]
    assert verify(path, tmp_path / "audit") and verify(written.path, tmp_path / "audit")


def test_b49_2_a_decided_file_with_a_changed_row_does_not_rebuild_the_export(tmp_path: Path) -> None:
    path = _export(tmp_path)
    decided_path = decide(path, _all_keep(path), by=LEAD, decided_on=AS_OF, audit_dir=tmp_path / "audit").path
    body = _read(decided_path)
    body["rows"] = body["rows"][1:]  # a row dropped from the review, sidecar rewritten to match
    data = canonical_bytes(body)
    decided_path.write_bytes(data)
    sidecar_for(decided_path).write_text(f"{hashlib.sha256(data).hexdigest()}  {decided_path.name}\n", "ascii")
    with pytest.raises(VerifyError, match="do not rebuild the export"):
        verify(decided_path)


def test_b49_2_a_decision_changed_after_the_fact_is_caught_by_the_audit_chain(tmp_path: Path) -> None:
    path = _export(tmp_path)
    decided_path = decide(path, _all_keep(path), by=LEAD, decided_on=AS_OF, audit_dir=tmp_path / "audit").path
    body = _read(decided_path)
    body["rows"][0]["decision"] = "remove"
    data = canonical_bytes(body)
    decided_path.write_bytes(data)
    sidecar_for(decided_path).write_text(f"{hashlib.sha256(data).hexdigest()}  {decided_path.name}\n", "ascii")
    verify(decided_path)  # self-consistent on its own ...
    with pytest.raises(VerifyError, match="not pinned"):
        verify(decided_path, tmp_path / "audit")  # ... but no audited decision has this hash


def test_b49_2_a_broken_audit_chain_fails_pinned_verification(tmp_path: Path) -> None:
    path = _export(tmp_path)
    chain = tmp_path / "audit" / "contoso-dental.jsonl"
    chain.write_text(chain.read_text(encoding="utf-8").replace('"rows":', '"rowz":'), encoding="utf-8")
    with pytest.raises(VerifyError, match="does not verify"):
        verify(path, tmp_path / "audit")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("bad-value", "must be one of"),
        ("missing", "every row needs a decision"),
        ("unknown", "not in the export"),
    ],
)
def test_b49_2_bad_decisions_are_refused_and_audited(tmp_path: Path, change: str, reason: str) -> None:
    path = _export(tmp_path)
    choices = _all_keep(path)
    first = sorted(choices)[0]
    if change == "bad-value":
        choices[first] = "approve"
    elif change == "missing":
        del choices[first]
    else:
        choices["identity:ghost"] = "keep"
    with pytest.raises(AccessReviewError, match=reason):
        decide(path, choices, by=LEAD, decided_on=AS_OF, audit_dir=tmp_path / "audit")
    assert not path.with_name("contoso-dental.decided.json").exists()
    last = _records(tmp_path / "audit", "contoso-dental")[-1]
    assert last["lever"] == "access-review.decide" and last["result"]["status"] == "denied"
    assert _chain_ok(tmp_path / "audit", "contoso-dental")


@pytest.mark.parametrize("who", ["tech-ana", "triage-bot", "nobody"])
def test_b49_2_only_a_lead_may_decide_and_a_refusal_is_audited(tmp_path: Path, who: str) -> None:
    path = _export(tmp_path)
    with pytest.raises(AccessReviewError):
        decide(path, _all_keep(path), by=who, decided_on=AS_OF, audit_dir=tmp_path / "audit")
    last = _records(tmp_path / "audit", "contoso-dental")[-1]
    assert (last["agent"], last["result"]["status"]) == (who, "denied")


def test_b49_2_a_tampered_export_cannot_be_decided(tmp_path: Path) -> None:
    path = _export(tmp_path)
    choices = _all_keep(path)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AccessReviewError, match="does not verify"):
        decide(path, choices, by=LEAD, decided_on=AS_OF, audit_dir=tmp_path / "audit")


def test_b49_2_msp_export_is_decided_by_a_lead_over_every_client(tmp_path: Path) -> None:
    path = _export(tmp_path, None)
    written = decide(path, _all_keep(path), by=LEAD, decided_on=AS_OF, audit_dir=tmp_path / "audit")
    assert verify(written.path, tmp_path / "audit") == written.sha256
    assert [r["lever"] for r in _records(tmp_path / "audit", "_msp")] == [
        "access-review.export",
        "access-review.decide",
    ]


def test_b49_2_cli_export_decide_verify_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out, audit = tmp_path / "out", tmp_path / "audit"
    common = ["--as", LEAD, "--audit-dir", str(audit)]
    assert main(["export", "fabrikam-capital", "--as-of", AS_OF, "--out", str(out), *common]) == 0
    path = Path(json.loads(capsys.readouterr().out)["path"])
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps(_all_keep(path)), encoding="utf-8")
    assert main(["decide", str(path), "--on", AS_OF, "--decisions", str(decisions), *common]) == 0
    decided = Path(json.loads(capsys.readouterr().out)["path"])
    assert main(["verify", str(decided), "--audit-dir", str(audit)]) == 0
    assert capsys.readouterr().out.startswith("OK ")
    decided.write_bytes(decided.read_bytes().replace(b'"keep"', b'"remove"', 1))
    assert main(["verify", str(decided)]) == 1
    assert "MISMATCH" in capsys.readouterr().err


def test_b49_2_cli_refuses_a_client_and_msp_together_and_a_non_lead(tmp_path: Path) -> None:
    base = ["--as-of", AS_OF, "--out", str(tmp_path / "out"), "--audit-dir", str(tmp_path / "audit")]
    assert main(["export", "contoso-dental", "--msp", "--as", LEAD, *base]) == 2
    assert main(["export", "--as", LEAD, *base]) == 2
    assert main(["export", "contoso-dental", "--as", "tech-ana", *base]) == 2


# -- B49-3: agents with execute capability or more clients than their workflow needs are flagged --------------------
def test_b49_3_registered_agent_has_no_execute_capability_and_no_excess_clients(tmp_path: Path) -> None:
    rows = {r["identity"]: r for r in _read(_export(tmp_path, None))["rows"]}
    assert rows["triage-bot"]["role"] == "agent" and rows["triage-bot"]["flags"] == []
    registry = Registry.load()

    bot = IdentityStore.load().get("triage-bot")
    assert execute_levers(bot, registry) == []  # every write lever in the registry needs a technician or above


def test_b49_3_agent_that_can_execute_a_write_lever_is_flagged(tmp_path: Path) -> None:
    registry = _agent_registry(tmp_path)
    msp = build_msp_export(as_of=AS_OF, by=LEAD, registry_path=registry)
    bot = next(r for r in msp["rows"] if r["identity"] == "triage-bot")
    assert bot["flags"] == [{"flag": "execute-capability", "levers": ["user.disable"]}]
    client = build_client_export("contoso-dental", as_of=AS_OF, by=LEAD, registry_path=registry)
    bot = next(r for r in client["rows"] if r.get("identity") == "triage-bot")
    assert bot["flags"] == [{"flag": "execute-capability", "levers": ["user.disable"]}]
    humans = [r for r in msp["rows"] if r["role"] != "agent"]
    assert humans and all(r["flags"] == [] for r in humans)  # only agents are flagged


def test_b49_3_execute_capability_is_per_client_in_the_client_export(tmp_path: Path) -> None:
    registry = _agent_registry(tmp_path, scope=["fabrikam-capital"])
    contoso = build_client_export("contoso-dental", as_of=AS_OF, by=LEAD, registry_path=registry)
    fabrikam = build_client_export("fabrikam-capital", as_of=AS_OF, by=LEAD, registry_path=registry)
    assert next(r for r in contoso["rows"] if r.get("identity") == "triage-bot")["flags"] == []
    assert next(r for r in fabrikam["rows"] if r.get("identity") == "triage-bot")["flags"][0]["levers"] == [
        "user.disable"
    ]


def test_b49_3_read_levers_are_not_an_execute_capability(tmp_path: Path) -> None:
    bot = IdentityStore.load().get("triage-bot")
    # A read lever whose required role is the agent role and whose scope is any client, and no write lever.
    reads = Registry.load(_agent_registry(_sub(tmp_path, "r"), write=False, read_scope="any"))
    read = reads.get("ticket.get")
    assert read is not None and (read.lever_class, read.required_role, read.client_scope) == ("read", "agent", "any")
    assert execute_levers(bot, reads) == []
    # The same registry plus a write lever with the same role and scope: only the write lever is listed.
    both = Registry.load(_agent_registry(_sub(tmp_path, "w"), scope="any", read_scope="any"))
    write = both.get("user.disable")
    assert write is not None and (write.lever_class, write.client_scope) == ("write", "any")
    assert execute_levers(bot, both) == ["user.disable"]


def test_b49_3_agent_with_more_clients_than_its_workflow_needs_is_flagged(tmp_path: Path) -> None:
    needs = _needs(tmp_path, {"triage-bot": {"workflow": "triage", "clients": ["contoso-dental"]}})
    msp = build_msp_export(as_of=AS_OF, by=LEAD, needs_path=needs)
    bot = next(r for r in msp["rows"] if r["identity"] == "triage-bot")
    assert bot["flags"] == [
        {"flag": "excess-clients", "workflow": "triage", "clients": ["fabrikam-capital"], "needed": ["contoso-dental"]}
    ]
    fab = build_client_export("fabrikam-capital", as_of=AS_OF, by=LEAD, needs_path=needs)
    flags = next(r for r in fab["rows"] if r.get("identity") == "triage-bot")["flags"]
    assert [f["flag"] for f in flags] == ["excess-clients"]
    assert "contoso" not in json.dumps(fab)  # the flag does not name the other client
    assert flags[0]["excess_other_clients"] == 0
    con = build_client_export("contoso-dental", as_of=AS_OF, by=LEAD, needs_path=needs)
    flags = next(r for r in con["rows"] if r.get("identity") == "triage-bot")["flags"]
    # The needed client's export carries a count of the unneeded clients, never their names.
    assert flags == [{"flag": "excess-other-clients", "workflow": "triage", "count": 1}]
    assert "fabrikam" not in json.dumps(con)


def test_b49_3_agent_with_no_declared_need_is_flagged(tmp_path: Path) -> None:
    identities = _identities(
        tmp_path,
        [
            {
                "id": "notify-bot",
                "display_name": "Notify agent (synthetic)",
                "role": "agent",
                "clients": ["contoso-dental"],
            }
        ],
    )
    msp = build_msp_export(as_of=AS_OF, by=LEAD, identities_path=identities)
    bot = next(r for r in msp["rows"] if r["identity"] == "notify-bot")
    assert [f["flag"] for f in bot["flags"]] == ["no-declared-need"]


def test_b49_3_flags_are_counted_in_the_export_audit_record(tmp_path: Path) -> None:
    needs = _needs(tmp_path, {"triage-bot": {"workflow": "triage", "clients": ["contoso-dental"]}})
    _export(tmp_path, None, needs_path=needs, registry_path=_agent_registry(tmp_path))
    (record,) = _records(tmp_path / "audit", "_msp")
    assert record["result"]["flagged"] == 1


def test_b49_3_needs_file_naming_an_unknown_identity_is_refused(tmp_path: Path) -> None:
    needs = _needs(tmp_path, {"ghost-bot": {"workflow": "triage", "clients": ["contoso-dental"]}})
    with pytest.raises(AccessReviewError, match="do not exist"):
        build_msp_export(as_of=AS_OF, by=LEAD, needs_path=needs)


def test_b49_3_committed_needs_file_loads_and_covers_every_agent() -> None:
    needs = load_needs()
    config = json.loads(DEFAULT_IDENTITIES.read_text(encoding="utf-8"))["identities"]
    agents = {i["id"] for i in config if i["role"] == "agent"}
    assert agents <= set(needs)
