"""B-33 MailboxOps and OneDrive transfer levers (specs/B-33.md).

Acceptance ids B33-1 to B33-3. Every test is offline and works in a private folder (tmp_path) with a copy of the
synthetic mock tenant; committed fixtures are never modified. Tests that start `pwsh` skip when PowerShell 7.4+ is
not installed. Run: uv run --frozen pytest -p no:cacheprovider tests/py/mailbox
"""

from __future__ import annotations

import json
import re
import shutil
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.audit import AuditLog
from core.identity import IdentityStore
from core.levers import DEFAULT_TENANT_DIR, Approval, LeverRunner, MockTenant, Registry
from core.levers.bridge import PowerShellBridge

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / "levers" / "powershell" / "MailboxOps"
TEMPLATES = REPO / "workflows" / "notify" / "templates"
SOURCES = MODULE / "SOURCES.md"
CONTOSO, FABRIKAM = "contoso-dental", "fabrikam-capital"
D = "contosodental.example"
ANA, SAM, JAMIE, PRIYA, TOM = (f"{n}@{D}" for n in ("ana.lopez", "sam.patel", "jamie.chen", "priya.nair", "tom.baker"))
INFO = f"info@{D}"
FRONTDESK = f"frontdesk@{D}"
ALEX = "alex.ward@fabrikamcapital.example"
MORGAN = "morgan.reyes@fabrikamcapital.example"
REPLY = "Jamie has left the practice. Please write to Ana Lopez instead."
PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh (PowerShell 7.4+) is not installed")
NO_CHANGE = "no change: already in the desired state"


@dataclass
class Env:
    runner: LeverRunner
    tenant_dir: Path

    def path(self, client: str = CONTOSO) -> Path:
        return self.tenant_dir / client / "mailboxes.json"

    def raw(self, client: str = CONTOSO) -> bytes:
        return self.path(client).read_bytes()

    def state(self, client: str = CONTOSO) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.raw(client))
        return loaded

    def dry(self, lever: str, params: dict[str, Any], client: str = CONTOSO) -> Any:
        return self.runner.invoke(lever, params, "triage-bot", client)

    def run(self, lever: str, params: dict[str, Any], client: str = CONTOSO) -> Any:
        approval = Approval(approver="lead-lee", lever=lever, client=client, params=dict(params))
        return self.runner.invoke(lever, params, "tech-ana", client, mode="execute", approval=approval)


def make_env(tmp_path: Path) -> Env:
    tenant_dir = tmp_path / "tenant"
    shutil.copytree(DEFAULT_TENANT_DIR, tenant_dir)
    bridge = PowerShellBridge(tenant_dir=tenant_dir)
    runner = LeverRunner(
        Registry.load(), IdentityStore.load(), MockTenant(tenant_dir), AuditLog(tmp_path / "audit.jsonl"), bridge=bridge
    )
    return Env(runner, tenant_dir)


def mailbox_levers() -> list[str]:
    return sorted(n for n in Registry.load().names() if n.startswith("mailbox."))


# lever -> (params, steps to run first so the lever has something to change)
GRANT = {"upn": JAMIE, "manager": ANA, "expires_on": "2026-11-15"}
CASES: dict[str, tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]] = {
    "mailbox.add-dl-member": ({"upn": TOM, "list": FRONTDESK}, []),
    "mailbox.remove-dl-member": ({"upn": JAMIE, "list": FRONTDESK}, []),
    "mailbox.grant-full-access": ({"upn": JAMIE, "delegate": ANA}, []),
    "mailbox.revoke-full-access": ({"upn": INFO, "delegate": ANA}, []),
    "mailbox.grant-send-as": ({"upn": JAMIE, "delegate": ANA}, []),
    "mailbox.revoke-send-as": ({"upn": INFO, "delegate": ANA}, []),
    "mailbox.convert-shared": ({"upn": JAMIE}, []),
    "mailbox.set-auto-reply": ({"upn": JAMIE, "message": REPLY}, []),
    "mailbox.clear-auto-reply": ({"upn": JAMIE}, [("mailbox.set-auto-reply", {"upn": JAMIE, "message": REPLY})]),
    "mailbox.enable-archive": ({"upn": TOM}, []),
    "mailbox.grant-onedrive-manager": (GRANT, []),
    "mailbox.revoke-onedrive-manager": ({"upn": JAMIE, "manager": ANA}, [("mailbox.grant-onedrive-manager", GRANT)]),
}


def as_sets(state: dict[str, Any]) -> dict[str, Any]:
    """Membership and permission lists are sets: an undo may put a person back at the end of the list."""
    clone: dict[str, Any] = json.loads(json.dumps(state))
    for dl in clone["distributionLists"]:
        dl["members"].sort()
    for box in clone["mailboxes"]:
        box["fullAccess"].sort()
        box["sendAs"].sort()
    return clone


def without_reply_text(state: dict[str, Any]) -> dict[str, Any]:
    clone: dict[str, Any] = json.loads(json.dumps(state))
    for box in clone["mailboxes"]:
        box["autoReply"]["internalMessage"] = box["autoReply"]["externalMessage"] = None
        box["autoReply"]["externalAudience"] = "None"
    return clone


# -- B33-1: the levers, each with dry-run diff, undo where one exists, and a template -----------------------------


def test_b33_1_the_six_kinds_of_lever_are_registered_as_r2_powershell_writes_with_lead_approval() -> None:
    registry = Registry.load()
    assert set(mailbox_levers()) == set(CASES)
    for name in CASES:
        spec = registry.get(name)
        assert spec is not None
        assert registry.runtime(name) == "powershell"
        assert (spec.lever_class, spec.risk_class, spec.approval, spec.dry_run) == ("write", "R2", "lead", True)
        assert spec.dry_run_role == "agent"
        assert spec.required_role == "technician"
        assert spec.impact is not None
        assert list(spec.idempotency_keys) == list(spec.params)
    families = {n.split(".", 1)[1].split("-", 1)[1] for n in CASES}
    assert {"dl-member", "full-access", "send-as", "shared", "auto-reply", "archive", "onedrive-manager"} <= families


def test_b33_1_every_lever_names_an_exported_function_of_the_module() -> None:
    registry = Registry.load()
    manifest = (MODULE / "MailboxOps.psd1").read_text(encoding="utf-8")
    exported = set(
        re.findall(r"'([A-Z][A-Za-z]+-[A-Za-z]+)'", manifest.split("FunctionsToExport", 1)[1].split(")", 1)[0])
    )
    entries = {registry.powershell_entry(n) for n in CASES}
    assert None not in entries
    assert {e.function for e in entries if e is not None} == exported
    assert {e.module for e in entries if e is not None} == {"MailboxOps"}


def test_b33_1_undo_pairs_are_registered_write_levers_and_the_irreversible_gaps_are_the_two_named_ones() -> None:
    registry = Registry.load()
    without_undo = []
    for name in CASES:
        spec = registry.get(name)
        assert spec is not None
        if spec.undo is None:
            without_undo.append(name)
        else:
            target = registry.get(spec.undo)
            assert target is not None and target.lever_class == "write" and spec.undo in CASES
    # Converting back needs a licence; switching an archive off can delete mail. Both stay with people.
    assert sorted(without_undo) == ["mailbox.convert-shared", "mailbox.enable-archive"]


def test_b33_1_every_lever_has_a_plain_template_with_only_trusted_placeholders() -> None:
    allowed = {"first_name", "request", "approver", "team", "fast_phone", "hours"}
    values = {k: "x" for k in allowed}
    for name in CASES:
        path = TEMPLATES / f"{name}.md"
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        used = {
            m.group("named") or m.group("braced")
            for m in string.Template.pattern.finditer(text)
            if m.group("named") or m.group("braced")
        }
        assert used <= allowed, (name, used - allowed)
        assert {"first_name", "approver", "request"} <= used
        string.Template(text).substitute(values)
        for heading in ("What changed:", "Why:", "Who approved it:", "How to undo it:"):
            assert heading in text, (name, heading)


@needs_pwsh
@pytest.mark.parametrize("lever", sorted(CASES))
def test_b33_1_each_lever_dry_runs_with_a_diff_executes_once_and_is_convergent(tmp_path: Path, lever: str) -> None:
    env = make_env(tmp_path)
    params, prep = CASES[lever]
    for step, step_params in prep:
        assert env.run(step, step_params).status == "ok"
    before = env.raw()
    dry = env.dry(lever, params)
    assert dry.status == "ok", dry.reason
    assert dry.diff and not dry.applied
    assert env.raw() == before, "a dry-run must write nothing"
    done = env.run(lever, params)
    assert (done.status, done.applied) == ("ok", True), done.reason
    assert [c.path for c in done.diff] == [c.path for c in dry.diff]
    assert env.raw() != before
    again = env.run(lever, params)
    assert (again.status, again.reason, again.applied, again.diff) == ("ok", NO_CHANGE, False, ())


@needs_pwsh
@pytest.mark.parametrize("lever", sorted(CASES))
def test_b33_1_the_undo_lever_puts_the_state_back(tmp_path: Path, lever: str) -> None:
    spec = Registry.load().get(lever)
    assert spec is not None
    if spec.undo is None:
        pytest.skip(f"{lever} has no undo lever by design")
    env = make_env(tmp_path)
    params, prep = CASES[lever]
    for step, step_params in prep:
        assert env.run(step, step_params).status == "ok"
    before = env.state()
    assert env.run(lever, params).applied
    undo_spec = Registry.load().get(spec.undo)
    assert undo_spec is not None
    extras = {"message": REPLY, "expires_on": GRANT["expires_on"]}
    undo_params = {k: params[k] if k in params else extras[k] for k in undo_spec.params}
    undone = env.run(spec.undo, undo_params)
    assert (undone.status, undone.applied) == ("ok", True), undone.reason
    if lever == "mailbox.set-auto-reply":
        assert env.state()["mailboxes"] != before["mailboxes"]  # the text stays on file, the reply is off
        assert without_reply_text(env.state()) == without_reply_text(before)
    else:
        assert as_sets(env.state()) == as_sets(before)


@needs_pwsh
def test_b33_1_a_failed_dry_run_or_a_refused_execute_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    # no approval: the Python runner refuses before PowerShell starts
    assert env.runner.invoke("mailbox.enable-archive", {"upn": TOM}, "tech-ana", CONTOSO, mode="execute").status != "ok"
    # an agent may not execute
    approval = Approval(approver="lead-lee", lever="mailbox.enable-archive", client=CONTOSO, params={"upn": TOM})
    assert (
        env.runner.invoke(
            "mailbox.enable-archive", {"upn": TOM}, "triage-bot", CONTOSO, mode="execute", approval=approval
        ).status
        != "ok"
    )
    assert env.raw() == before


@needs_pwsh
def test_b33_1_the_onedrive_grant_is_time_bound_and_names_its_end_date(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    for bad in (
        "2026-10-21",  # not after the as-of date
        "2026-10-01",
        "2026-11-21",  # 31 days after 2026-10-21
        "2027-01-01",
        "2026-13-45",
        "2026-11-3",
    ):
        before = env.raw()
        result = env.dry("mailbox.grant-onedrive-manager", {**GRANT, "expires_on": bad})
        assert result.status != "ok" and not result.diff, bad
        assert env.raw() == before
        assert (
            "crashed" in result.reason or "invalid params" in result.reason
        )  # the host reports a refusal by type only (STD-ER-5); text is in the PS tests
    last_day = env.run("mailbox.grant-onedrive-manager", {**GRANT, "expires_on": "2026-11-20"})  # exactly 30 days
    assert last_day.status == "ok" and last_day.applied
    drive = next(d for d in env.state()["oneDrive"] if d["owner"] == JAMIE)
    assert drive["access"] == [
        {"grantee": ANA, "grantedOn": "2026-10-21", "expiresOn": "2026-11-20", "accessLevel": "SiteCollectionAdmin"}
    ]
    # Asking again with a shorter end date changes only the end date; the approval is bound to the exact date.
    shorter = env.run("mailbox.grant-onedrive-manager", GRANT)
    assert [(c.op, c.path.rsplit("/", 1)[1]) for c in shorter.diff] == [("replace", "expiresOn")]
    ended = env.run("mailbox.revoke-onedrive-manager", {"upn": JAMIE, "manager": ANA})
    assert ended.applied
    assert next(d for d in env.state()["oneDrive"] if d["owner"] == JAMIE)["access"] == []


@needs_pwsh
def test_b33_1_a_grant_names_a_user_of_the_same_client_and_never_the_owner_or_an_outside_address(
    tmp_path: Path,
) -> None:
    env = make_env(tmp_path)
    before = env.raw()
    refused = [
        ("mailbox.grant-full-access", {"upn": JAMIE, "delegate": JAMIE}),
        ("mailbox.grant-full-access", {"upn": JAMIE, "delegate": INFO}),  # a shared mailbox is not a person
        ("mailbox.grant-full-access", {"upn": JAMIE, "delegate": "someone@outside.example"}),
        ("mailbox.grant-send-as", {"upn": JAMIE, "delegate": MORGAN}),  # another client's person
        ("mailbox.add-dl-member", {"upn": TOM, "list": "all@fabrikamcapital.example"}),  # another client's list
        ("mailbox.add-dl-member", {"upn": MORGAN, "list": FRONTDESK}),
        ("mailbox.grant-onedrive-manager", {**GRANT, "manager": JAMIE}),
        ("mailbox.grant-onedrive-manager", {**GRANT, "manager": "boss@outside.example"}),
    ]
    for lever, params in refused:
        result = env.dry(lever, params)
        assert result.status != "ok" and not result.diff, (lever, params)
    assert env.raw() == before


@needs_pwsh
def test_b33_1_another_clients_mailbox_answers_exactly_like_an_absent_one(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    other = env.dry("mailbox.enable-archive", {"upn": ALEX})
    absent = env.dry("mailbox.enable-archive", {"upn": f"nobody@{D}"})
    assert other.status == absent.status != "ok"
    assert other.reason == absent.reason
    assert ALEX not in other.reason and ALEX not in str(other)
    assert env.state(FABRIKAM)["mailboxes"][3]["archiveStatus"] == "None"


@needs_pwsh
def test_b33_1_a_mailbox_over_the_unlicensed_shared_limit_is_refused_and_a_small_one_converts(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    big = env.dry("mailbox.convert-shared", {"upn": ALEX}, FABRIKAM)
    assert big.status != "ok" and "crashed" in big.reason
    small = env.run("mailbox.convert-shared", {"upn": JAMIE})
    assert small.applied
    box = next(b for b in env.state()["mailboxes"] if b["userPrincipalName"] == JAMIE)
    assert box["recipientTypeDetails"] == "SharedMailbox"


@needs_pwsh
def test_b33_1_a_write_to_one_clients_file_never_touches_the_other(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    fabrikam, contoso_tenant = env.raw(FABRIKAM), (env.tenant_dir / f"{CONTOSO}.json").read_bytes()
    assert env.run("mailbox.enable-archive", {"upn": TOM}).applied
    assert env.raw(FABRIKAM) == fabrikam
    assert (env.tenant_dir / f"{CONTOSO}.json").read_bytes() == contoso_tenant


def test_b33_1_the_auto_reply_text_pattern_refuses_markup_links_and_newlines(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    for text in (
        "<b>Hello there</b>",
        "See https://x.example/a?b=c now",
        "Line one\nline two",
        "ab",
        "x" * 401,
        "Hi {0}",
    ):
        result = env.dry("mailbox.set-auto-reply", {"upn": JAMIE, "message": text})
        assert result.status != "ok", text
        assert not result.diff


# -- B33-2: external forwarding is not a lever --------------------------------------------------------------------


def test_b33_2_no_registered_lever_sets_forwarding_to_an_external_domain() -> None:
    registry = Registry.load()
    for name in registry.names():
        spec = registry.get(name)
        assert spec is not None
        words = " ".join([name, spec.description, *spec.params, *(p.description for p in spec.params.values())]).lower()
        assert "forward" not in words, name
        assert "redirect" not in words, name
        # no parameter that could carry an outside destination address
        assert not ({"to", "target", "destination", "recipient", "address", "smtp", "email"} & set(spec.params)), name
    assert not [n for n in mailbox_levers() if re.search(r"forward|redirect|inbox-rule|transport", n)]


def test_b33_2_the_module_never_writes_a_forwarding_address_or_a_mail_flow_rule() -> None:
    source = (MODULE / "MailboxOps.psm1").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    code = re.sub(r"<#.*?#>", "", code, flags=re.S)
    for banned in (
        "forwardingSmtpAddress",
        "ForwardingAddress",
        "DeliverToMailboxAndForward",
        "InboxRule",
        "TransportRule",
        "RedirectTo",
    ):
        assert banned.lower() not in code.lower(), banned


@needs_pwsh
def test_b33_2_running_every_lever_leaves_forwarding_empty_and_touches_no_forwarding_path(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    paths: list[str] = []
    for lever in CASES:
        params, prep = CASES[lever]
        for step, step_params in prep:
            env.run(step, step_params)
        result = env.run(lever, params)
        assert result.status == "ok", (lever, result.reason)
        paths += [c.path for c in result.diff]
    assert paths
    assert not [p for p in paths if "forward" in p.lower()]
    for client in (CONTOSO, FABRIKAM):
        assert all(box["forwardingSmtpAddress"] is None for box in env.state(client)["mailboxes"])


def test_b33_2_the_fixtures_start_with_no_forwarding_and_the_inventory_says_who_flags_it() -> None:
    for client in (CONTOSO, FABRIKAM):
        state = json.loads((DEFAULT_TENANT_DIR / client / "mailboxes.json").read_text(encoding="utf-8"))
        assert all(box["forwardingSmtpAddress"] is None for box in state["mailboxes"])
    sources = SOURCES.read_text(encoding="utf-8")
    assert "W-M365-05" in sources and "not offered" in sources.lower()


# -- B33-3: SOURCES.md marks Exchange Online PowerShell versus Graph and what is UNVERIFIED ----------------------


def _rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in SOURCES.read_text(encoding="utf-8").splitlines():
        if line.startswith("| `mailbox."):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[cells[0].strip("`")] = cells
    return rows


def test_b33_3_sources_has_a_row_for_every_lever_naming_the_api_family_and_its_status() -> None:
    rows = _rows()
    assert set(rows) == set(CASES)
    families = {cells[2] for cells in rows.values()}
    assert families <= {"Exchange Online PowerShell", "SharePoint Online (PowerShell or Graph)"}
    assert "Exchange Online PowerShell" in families
    for name, cells in rows.items():
        assert len(cells) == 5, name
        assert "UNVERIFIED" in cells[4], name
        assert "Verified" not in cells[4].replace("UNVERIFIED", ""), name


def test_b33_3_sources_says_no_vendor_documentation_was_read_and_graph_is_not_the_shape() -> None:
    text = SOURCES.read_text(encoding="utf-8")
    assert "Exchange Online PowerShell" in text and "not Graph" in text
    assert "no vendor documentation was read" in text.lower()
    assert "no call was made to a real" in text.lower()


def test_b33_3_every_fixture_field_appears_in_sources() -> None:
    text = SOURCES.read_text(encoding="utf-8")
    keys: set[str] = set()
    for client in (CONTOSO, FABRIKAM):
        state = json.loads((DEFAULT_TENANT_DIR / client / "mailboxes.json").read_text(encoding="utf-8"))
        for group in ("mailboxes", "distributionLists", "oneDrive"):
            for item in state[group]:
                keys |= set(item)
                if "autoReply" in item:
                    keys |= set(item["autoReply"])
    keys |= {"accessLevel", "grantee", "grantedOn", "expiresOn"}
    missing = sorted(k for k in keys if not re.search(rf"`(?:[a-zA-Z]+\[\]\.)?{k}`", text))
    assert not missing, missing


def test_b33_3_the_fixtures_are_synthetic_self_labelled_and_internally_consistent() -> None:
    for client in (CONTOSO, FABRIKAM):
        path = DEFAULT_TENANT_DIR / client / "mailboxes.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        meta = state["_meta"]
        assert meta["client"] == client and meta["as_of"].startswith("2026-10-21")
        assert "Synthetic" in meta["note"] and "UNVERIFIED" in meta["note"]
        upns = [b["userPrincipalName"] for b in state["mailboxes"]]
        assert len(upns) == len(set(upns))
        assert all(u.endswith(".example") for u in upns)
        tenant = json.loads((DEFAULT_TENANT_DIR / f"{client}.json").read_text(encoding="utf-8"))
        people = {u["userPrincipalName"] for u in tenant["users"]}
        assert people <= set(upns), "every person of the tenant has a mailbox"
        domain = upns[0].split("@")[1]
        assert all(u.endswith("@" + domain) for u in upns), "no mailbox of another organization in the file"
        for dl in state["distributionLists"]:
            assert set(dl["members"]) <= set(upns) and dl["primarySmtpAddress"].endswith("@" + domain)
        assert {d["owner"] for d in state["oneDrive"]} <= set(upns)
        for box in state["mailboxes"]:
            assert set(box["fullAccess"]) | set(box["sendAs"]) <= set(upns)
        # the same ids never appear in both clients
    ids = [
        item["id"]
        for client in (CONTOSO, FABRIKAM)
        for group in ("mailboxes", "distributionLists", "oneDrive")
        for item in json.loads((DEFAULT_TENANT_DIR / client / "mailboxes.json").read_text(encoding="utf-8"))[group]
    ]
    assert len(ids) == len(set(ids))


def test_b33_3_the_family_loader_accepts_the_mailbox_files_for_reads() -> None:
    state = MockTenant().load_for_read(CONTOSO)
    assert "mailboxes" in state["_families"]
