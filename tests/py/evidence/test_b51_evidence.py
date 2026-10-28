"""B-51 SOC 2 evidence bundle and change records. Acceptance ids B51-1 to B51-6 are defined in specs/B-51.md.

Offline and deterministic: audit chains are written under tmp_path with a pinned clock, the git history is a tiny
synthetic repo built under tmp_path with pinned dates, and committed fixtures and config are never modified.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/evidence
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from core.audit.chain import head_path_for, verify_chain
from core.audit.router import AuditRouter
from workflows.access_review import export as ar_export
from workflows.evidence import (
    EvidenceError,
    VerifyError,
    build_bundle,
    change_records,
    verify_bundle,
)
from workflows.evidence.__main__ import main
from workflows.evidence.bundle import DEFAULT_IDENTITIES, DEFAULT_REGISTRY

REPO = Path(__file__).resolve().parents[3]
PERIOD = "2026-10"
AS_OF = "2026-11-02"
LEAD = "lead-lee"
CLIENTS = ("contoso-dental", "fabrikam-capital")
GIT = shutil.which("git")


def _read(path: Path) -> Any:
    return json.loads(path.read_bytes())


def _seed(audit: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Chains with pinned timestamps: records inside October 2026 and one either side of it."""
    router = AuditRouter(audit)
    rows: list[tuple[str, str, str, str, str, str | None, str, str]] = [
        # ts, client, lever, mode, status, approver, agent, actor_kind
        (
            "2026-09-30T23:59:59.000Z",
            "contoso-dental",
            "user.disable",
            "execute",
            "ok",
            "lead-lee",
            "tech-ana",
            "human",
        ),
        ("2026-10-05T09:00:00.000Z", "contoso-dental", "user.disable", "dry-run", "ok", None, "triage-bot", "agent"),
        (
            "2026-10-06T09:00:00.000Z",
            "contoso-dental",
            "user.disable",
            "approve",
            "ok",
            "lead-lee",
            "lead-lee",
            "human",
        ),
        (
            "2026-10-07T09:00:00.000Z",
            "contoso-dental",
            "user.disable",
            "execute",
            "ok",
            "lead-lee",
            "tech-ana",
            "human",
        ),
        (
            "2026-10-08T09:00:00.000Z",
            "contoso-dental",
            "user.reset-mfa",
            "execute",
            "denied",
            None,
            "tech-ana",
            "human",
        ),
        ("2026-10-09T09:00:00.000Z", "contoso-dental", "user.disable", "reject", "ok", "lead-lee", "lead-lee", "human"),
        (
            "2026-11-01T00:00:00.000Z",
            "contoso-dental",
            "user.disable",
            "execute",
            "ok",
            "lead-lee",
            "tech-ana",
            "human",
        ),
        ("2026-10-10T09:00:00.000Z", "fabrikam-capital", "ticket.get", "execute", "ok", None, "tech-ben", "human"),
        (
            "2026-10-11T09:00:00.000Z",
            "fabrikam-capital",
            "user.disable",
            "execute",
            "denied",
            None,
            "tech-ben",
            "human",
        ),
        ("2026-10-12T09:00:00.000Z", "_msp", "lever.pause", "pause", "ok", "lead-lee", "lead-lee", "human"),
    ]
    for ts, client, lever, mode, status, approver, agent, kind in rows:
        monkeypatch.setattr("core.audit.chain._utc_now", lambda ts=ts: ts)
        router.append(
            agent=agent,
            client=None if client == "_msp" else client,
            lever=lever,
            params={"note": f"secret-param-{client}"},
            mode=mode,  # type: ignore[arg-type]
            result={"status": status, "reason": f"reason for {client}"},
            approver=approver,
            actor_kind=kind,  # type: ignore[arg-type]
            lever_version=1,
        )
    monkeypatch.undo()


@pytest.fixture
def audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "audit"
    _seed(folder, monkeypatch)
    return folder


def _git(repo: Path, *args: str, when: str = "2026-10-15T12:00:00+00:00", who: str = "Pat Synthetic") -> str:
    assert GIT is not None
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": who,
        "GIT_COMMITTER_NAME": who,
        "GIT_AUTHOR_EMAIL": "pat@example.invalid",
        "GIT_COMMITTER_EMAIL": "pat@example.invalid",
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
    }
    done = subprocess.run(  # noqa: S603
        [GIT, "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _commit(repo: Path, name: str, message: str, when: str) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(message, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message, when=when)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """main with: a base commit (September), a merged PR #7 in October touching a guardrail path, a squash-style
    commit '(#8)' in October, a plain commit in October (not a PR), and a merged PR #9 in November."""
    if GIT is None:
        pytest.skip("git is not installed")
    root = tmp_path / "gitrepo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _commit(root, "README.md", "base", "2026-09-01T10:00:00+00:00")
    _git(root, "checkout", "-q", "-b", "feat-b99", when="2026-10-03T10:00:00+00:00")
    _commit(root, "scripts/guard.ps1", "add guard (B-99)", "2026-10-03T10:00:00+00:00")
    _commit(root, "docs/a.md", "docs", "2026-10-04T10:00:00+00:00")
    _git(root, "checkout", "-q", "main")
    _git(
        root,
        "merge",
        "--no-ff",
        "-m",
        "Merge pull request #7 from synth/feat-b99",
        "feat-b99",
        when="2026-10-05T10:00:00+00:00",
        who="Quinn Merge",
    )
    _commit(root, "workflows/x.py", "B-12: squash style change (#8)", "2026-10-20T10:00:00+00:00")
    _commit(root, "notes.txt", "direct commit, no PR", "2026-10-21T10:00:00+00:00")
    _git(root, "checkout", "-q", "-b", "feat-nov", when="2026-11-01T10:00:00+00:00")
    _commit(root, "nov.txt", "november work", "2026-11-01T10:00:00+00:00")
    _git(root, "checkout", "-q", "main")
    _git(
        root,
        "merge",
        "--no-ff",
        "-m",
        "Merge pull request #9 from synth/feat-nov",
        "feat-nov",
        when="2026-11-03T10:00:00+00:00",
    )
    return root


def _reviews(tmp_path: Path, audit: Path) -> Path:
    """B-49 exports for 2026-Q4 for every client and the MSP, written by the real workflow."""
    out = tmp_path / "ar"
    for scope in (*CLIENTS, None):
        ar_export(scope, as_of="2026-10-23", by=LEAD, out_dir=out, audit_dir=tmp_path / "ar-audit")
    return out


def _build(tmp_path: Path, audit: Path, client: str | None = "contoso-dental", **kw: Any) -> Any:
    kw.setdefault("by", LEAD)
    kw.setdefault("period", PERIOD)
    kw.setdefault("as_of", AS_OF)
    kw.setdefault("out_dir", tmp_path / "out")
    kw.setdefault("audit_dir", audit)
    kw.setdefault("access_review_dir", tmp_path / "ar")
    kw.setdefault("git_repo", None)
    return build_bundle(client, **kw)


def _files(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["path"]: f for f in manifest["files"]}


def _records(audit: Path, name: str) -> list[dict[str, Any]]:
    chain = audit / f"{name}.jsonl"
    return [json.loads(x) for x in chain.read_text(encoding="utf-8").splitlines()] if chain.is_file() else []


# -- B51-1: a monthly bundle with every evidence item, hashed into a manifest ---------------------------------------
def test_b51_1_bundle_holds_audit_approvals_registry_and_access_review_hashed_in_the_manifest(
    tmp_path: Path, audit: Path
) -> None:
    _reviews(tmp_path, audit)
    bundle = _build(tmp_path, audit, write=True)
    manifest = _read(bundle.root / "manifest.json")
    files = _files(manifest)
    assert {"audit-verify.json", "approvals.json", "registry.json"} <= set(files)
    assert "access-review/contoso-dental.json" in files and "access-review/contoso-dental.json.sha256" in files
    for path, entry in files.items():
        data = (bundle.root / path).read_bytes()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest() and entry["bytes"] == len(data)
    assert list(files) == sorted(files)
    assert "manifest.json" not in files
    side = (bundle.root / "manifest.json.sha256").read_text(encoding="ascii")
    assert side == f"{hashlib.sha256((bundle.root / 'manifest.json').read_bytes()).hexdigest()}  manifest.json\n"
    assert bundle.manifest_sha256 == side.split()[0]


def test_b51_1_audit_verify_output_reports_the_chain_and_the_period_window(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    out = _read(bundle.root / "audit-verify.json")
    chain = audit / "contoso-dental.jsonl"
    assert verify_chain(chain, head_path_for(chain)).ok
    assert out["chain"] == "contoso-dental.jsonl" and out["present"] is True
    assert out["ok"] is True and out["broken_seq"] is None and out["head_pin_present"] is True
    records = _records(audit, "contoso-dental")
    inside = [r for r in records if r["ts"].startswith(PERIOD) and r["lever"] != "evidence.bundle"]
    assert out["period"]["records"] == len(inside) == 5
    assert (out["period"]["first_seq"], out["period"]["last_seq"]) == (inside[0]["seq"], inside[-1]["seq"])
    assert out["period"]["last_hash"] == inside[-1]["hash"]


def test_b51_1_a_broken_chain_is_still_written_as_a_failure(tmp_path: Path, audit: Path) -> None:
    chain = audit / "contoso-dental.jsonl"
    lines = chain.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace('"ok"', '"OK"', 1)
    chain.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bundle = _build(tmp_path, audit, write=True)
    out = _read(bundle.root / "audit-verify.json")
    assert out["ok"] is False and out["broken_seq"] == 3 and out["reason"]
    assert _read(bundle.root / "manifest.json")["checks"]["audit_chain_ok"] is False


def test_b51_1_a_missing_chain_is_a_listed_gap_not_an_ok(tmp_path: Path, audit: Path) -> None:
    (audit / "contoso-dental.jsonl").unlink()
    (audit / "contoso-dental.jsonl.head").unlink()
    bundle = _build(tmp_path, audit, write=True)
    out = _read(bundle.root / "audit-verify.json")
    assert out["present"] is False and out["ok"] is None
    manifest = _read(bundle.root / "manifest.json")
    assert manifest["checks"]["audit_chain_ok"] is None
    assert "audit chain missing" in manifest["gaps"]


def test_b51_1_approvals_and_denials_summary_counts_the_period_only_and_no_free_text(
    tmp_path: Path, audit: Path
) -> None:
    bundle = _build(tmp_path, audit, write=True)
    raw = (bundle.root / "approvals.json").read_text(encoding="utf-8")
    out = json.loads(raw)
    assert out["totals"] == {"approved": 1, "dry_run": 1, "executed": 1, "denied": 1, "rejected": 1, "other": 0}
    assert out["approvers"] == ["lead-lee"]
    assert out["by_actor_kind"] == {"agent": 1, "human": 4, "unknown": 0}
    assert out["by_lever"]["user.disable"]["executed"] == 1
    assert out["by_lever"]["user.reset-mfa"]["denied"] == 1
    assert "secret-param" not in raw and "reason for" not in raw


def test_b51_1_registry_snapshot_lists_lever_versions_that_can_act_for_the_client(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    out = _read(bundle.root / "registry.json")
    registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    by_name = {lv["name"]: lv for lv in registry["levers"]}
    got = {lv["name"]: lv for lv in out["levers"]}
    assert "user.disable" in got and got["user.disable"]["lever_version"] == by_name["user.disable"]["lever_version"]
    assert {"name", "lever_version", "class", "risk_class", "required_role", "approval"} <= set(got["user.disable"])
    assert [lv["name"] for lv in out["levers"]] == sorted(got)
    assert out["registry_sha256"] == hashlib.sha256(DEFAULT_REGISTRY.read_bytes()).hexdigest()


def test_b51_1_access_review_files_are_copied_and_reverified(tmp_path: Path, audit: Path) -> None:
    _reviews(tmp_path, audit)
    bundle = _build(tmp_path, audit, write=True)
    copied = bundle.root / "access-review" / "contoso-dental.json"
    assert copied.read_bytes() == (tmp_path / "ar" / "2026-Q4" / "contoso-dental.json").read_bytes()
    manifest = _read(bundle.root / "manifest.json")
    assert manifest["checks"]["access_reviews_verified"] is True
    assert _files(manifest)["access-review/contoso-dental.json"]["verified"] is True


def test_b51_1_a_tampered_access_review_is_copied_but_marked_unverified(tmp_path: Path, audit: Path) -> None:
    _reviews(tmp_path, audit)
    victim = tmp_path / "ar" / "2026-Q4" / "contoso-dental.json"
    victim.write_bytes(victim.read_bytes().replace(b"keep", b"kept", 1) + b" ")
    bundle = _build(tmp_path, audit, write=True)
    manifest = _read(bundle.root / "manifest.json")
    assert manifest["checks"]["access_reviews_verified"] is False
    assert _files(manifest)["access-review/contoso-dental.json"]["verified"] is False


def test_b51_1_missing_access_review_is_a_listed_gap(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    manifest = _read(bundle.root / "manifest.json")
    assert "access review missing for 2026-Q4" in manifest["gaps"]
    assert manifest["checks"]["access_reviews_verified"] is None
    assert not (bundle.root / "access-review").exists()


def test_b51_1_msp_bundle_has_the_full_registry_msp_review_and_merged_prs(
    tmp_path: Path, audit: Path, repo: Path
) -> None:
    _reviews(tmp_path, audit)
    bundle = _build(tmp_path, audit, None, git_repo=repo, write=True)
    assert bundle.root.name == "_msp"
    files = _files(_read(bundle.root / "manifest.json"))
    assert {
        "audit-verify.json",
        "approvals.json",
        "registry.json",
        "merged-prs.json",
        "access-review/_msp.json",
    } <= set(files)
    registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    assert len(_read(bundle.root / "registry.json")["levers"]) >= len(registry["levers"])
    assert _read(bundle.root / "audit-verify.json")["chain"] == "_msp.jsonl"
    assert _read(bundle.root / "approvals.json")["totals"]["other"] == 1  # the pause record


def test_b51_1_merged_pr_list_comes_from_the_local_git_log(tmp_path: Path, audit: Path, repo: Path) -> None:
    bundle = _build(tmp_path, audit, None, git_repo=repo, write=True)
    prs = _read(bundle.root / "merged-prs.json")
    assert prs["available"] is True
    assert [p["pr"] for p in prs["merged"]] == [7, 8]  # October only; #9 is November; the direct commit is no PR
    assert prs["merged"][0]["title"] == "Merge pull request #7 from synth/feat-b99"
    assert prs["merged"][0]["merged_on"] == "2026-10-05"


# -- B51-2: deterministic ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("client", [*CLIENTS, None])
def test_b51_2_rerunning_for_the_same_period_gives_the_same_manifest_hash(
    tmp_path: Path, audit: Path, repo: Path, client: str | None
) -> None:
    _reviews(tmp_path, audit)
    first = _build(tmp_path, audit, client, git_repo=repo, write=True)
    before = (first.root / "manifest.json").read_bytes()
    second = _build(tmp_path, audit, client, git_repo=repo, write=True)
    assert second.manifest_sha256 == first.manifest_sha256
    assert (second.root / "manifest.json").read_bytes() == before


def test_b51_2_a_dry_run_gives_the_same_hash_as_the_write(tmp_path: Path, audit: Path) -> None:
    planned = _build(tmp_path, audit)
    written = _build(tmp_path, audit, write=True)
    assert planned.manifest_sha256 == written.manifest_sha256
    assert planned.manifest == _read(written.root / "manifest.json")


def test_b51_2_no_wall_clock_time_is_in_any_bundle_file(tmp_path: Path, audit: Path) -> None:
    _reviews(tmp_path, audit)
    bundle = _build(tmp_path, audit, write=True)
    manifest = _read(bundle.root / "manifest.json")
    assert (manifest["period"], manifest["as_of"], manifest["generated_by"]) == (PERIOD, AS_OF, LEAD)
    assert not any(k in manifest for k in ("generated_at", "created", "timestamp", "ts"))


def test_b51_2_the_bundles_own_audit_records_do_not_change_the_next_runs_counts(
    tmp_path: Path, audit: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.audit.chain._utc_now", lambda: "2026-10-20T08:00:00.000Z")  # inside the period
    first = _build(tmp_path, audit, write=True)
    audit_out = (first.root / "audit-verify.json").read_bytes()
    approvals = (first.root / "approvals.json").read_bytes()
    # A bundle for the current month would see its own earlier records: they must not count.
    now_period = _build(tmp_path, audit, write=True, period="2026-10", as_of="2026-10-31")
    assert (now_period.root / "audit-verify.json").read_bytes() == audit_out
    assert (now_period.root / "approvals.json").read_bytes() == approvals


def test_b51_2_a_different_as_of_changes_the_manifest(tmp_path: Path, audit: Path) -> None:
    a = _build(tmp_path, audit, write=True)
    b = _build(tmp_path, audit, write=True, as_of="2026-11-03")
    assert a.manifest_sha256 != b.manifest_sha256


# -- B51-3: supports a human's management assertion; never asserts -----------------------------------------------------
def test_b51_3_manifest_says_the_bundle_supports_a_human_assertion_and_makes_none(tmp_path: Path, audit: Path) -> None:
    manifest = _build(tmp_path, audit).manifest
    assertion = manifest["management_assertion"]
    assert assertion["status"] == "not made"
    assert "supports" in assertion["note"] and "human" in assertion["note"]
    assert not any("sign" in k for k in assertion) and "signature" not in manifest
    assert manifest["labels"] == ["fixture-based", "not a certification", "not an attestation"]


def test_b51_3_no_bundle_file_claims_compliance_or_certification(tmp_path: Path, audit: Path, repo: Path) -> None:
    _reviews(tmp_path, audit)
    bundle = _build(tmp_path, audit, None, git_repo=repo, write=True)
    for path in bundle.root.rglob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        for banned in ("is compliant", "are compliant", "soc 2 compliant", "certified", "attested by", "passed audit"):
            # the manifest names these words only inside its own denial ("not a certification")
            assert banned not in text.replace("not a certification", "").replace("not an attestation", ""), path


def test_b51_3_the_manifest_never_names_a_reviewer_or_signer(tmp_path: Path, audit: Path) -> None:
    manifest = _build(tmp_path, audit).manifest
    assert manifest["management_assertion"].get("asserted_by") is None
    assert "asserted_by" not in json.dumps({k: v for k, v in manifest.items() if k != "management_assertion"})


# -- B51-4: change records from the local git log ---------------------------------------------------------------------
def test_b51_4_change_records_are_generated_for_merged_changes_in_the_period(repo: Path) -> None:
    records = change_records(repo, PERIOD)
    assert [r["pr"] for r in records] == [7, 8]
    first = records[0]
    assert first["record_id"] == f"CR-{first['commit'][:12]}"
    assert first["merged_on"] == "2026-10-05" and first["author"] == "Quinn Merge"
    assert first["changed_paths"] == ["docs/a.md", "scripts/guard.ps1"]
    assert first["roadmap_ids"] == [] and records[1]["roadmap_ids"] == ["B-12"]
    assert first["touches_guardrails"] is True and records[1]["touches_guardrails"] is False
    assert len(first["parents"]) == 2 and len(records[1]["parents"]) == 1


def test_b51_4_unknown_review_fields_are_null_never_invented(repo: Path) -> None:
    for record in change_records(repo, PERIOD):
        assert record["reviewer"] is None and record["ci_result"] is None and record["approval"] is None
        assert record["evidence"] == "not in local git"


def test_b51_4_change_records_are_files_in_the_msp_bundle_and_hashed(tmp_path: Path, audit: Path, repo: Path) -> None:
    bundle = _build(tmp_path, audit, None, git_repo=repo, write=True)
    files = _files(_read(bundle.root / "manifest.json"))
    names = sorted(p for p in files if p.startswith("change-records/"))
    assert len(names) == 2 and all(n.endswith(".json") for n in names)
    one = _read(bundle.root / names[0])
    assert one["record_id"] == Path(names[0]).stem


def test_b51_4_client_bundles_hold_no_change_records(tmp_path: Path, audit: Path, repo: Path) -> None:
    bundle = _build(tmp_path, audit, git_repo=repo, write=True)
    assert not any(p.startswith(("change-records", "merged-prs")) for p in _files(_read(bundle.root / "manifest.json")))


def test_b51_4_no_git_repo_gives_an_honest_empty_list(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, None, git_repo=tmp_path / "not-a-repo", write=True)
    prs = _read(bundle.root / "merged-prs.json")
    assert prs["available"] is False and prs["merged"] == [] and prs["reason"]
    assert "merged PR list unavailable" in _read(bundle.root / "manifest.json")["gaps"]


def test_b51_4_a_period_with_no_merges_is_an_empty_available_list(repo: Path) -> None:
    assert change_records(repo, "2026-08") == []


# -- B51-5: one client only, scoped lead, audited refusals, dry run by default ------------------------
@pytest.mark.parametrize(
    "client,other", [("contoso-dental", "fabrikam-capital"), ("fabrikam-capital", "contoso-dental")]
)
def test_b51_5_a_client_bundle_names_no_other_client(tmp_path: Path, audit: Path, client: str, other: str) -> None:
    _reviews(tmp_path, audit)
    bundle = _build(tmp_path, audit, client, write=True)
    for path in bundle.root.rglob("*"):
        if path.is_file():
            assert other.encode() not in path.read_bytes(), path
    registry = _read(bundle.root / "registry.json")
    assert all("client_scope" not in lv for lv in registry["levers"])


def test_b51_5_client_bundle_counts_come_from_that_clients_chain_only(tmp_path: Path, audit: Path) -> None:
    out = _read(_build(tmp_path, audit, "fabrikam-capital", write=True).root / "approvals.json")
    assert out["totals"]["executed"] == 1 and out["totals"]["denied"] == 1 and out["approvers"] == []


def test_b51_5_dry_run_is_the_default_and_writes_no_bundle(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit)
    assert bundle.written is False and bundle.root is None
    assert not (tmp_path / "out").exists()
    assert bundle.manifest["files"]


def test_b51_5_write_puts_files_under_period_and_scope(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    assert bundle.written is True and bundle.root == tmp_path / "out" / PERIOD / "contoso-dental"


@pytest.mark.parametrize("who", ["tech-ana", "triage-bot", "nobody"])
def test_b51_5_only_a_lead_may_build_and_the_refusal_is_audited(tmp_path: Path, audit: Path, who: str) -> None:
    before = len(_records(audit, "contoso-dental"))
    with pytest.raises(EvidenceError):
        _build(tmp_path, audit, by=who, write=True)
    assert not (tmp_path / "out").exists()
    records = _records(audit, "contoso-dental")
    assert len(records) == before + 1
    assert records[-1]["lever"] == "evidence.bundle" and records[-1]["result"]["status"] == "denied"
    assert verify_chain(audit / "contoso-dental.jsonl", head_path_for(audit / "contoso-dental.jsonl")).ok


def test_b51_5_a_lead_not_scoped_to_the_client_is_refused(tmp_path: Path, audit: Path) -> None:
    raw = json.loads(DEFAULT_IDENTITIES.read_text(encoding="utf-8"))
    raw["identities"].append(
        {"id": "lead-solo", "display_name": "Solo lead", "role": "lead", "clients": ["contoso-dental"]}
    )
    ids = tmp_path / "identities.json"
    ids.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(EvidenceError):
        _build(tmp_path, audit, "fabrikam-capital", by="lead-solo", identities_path=ids)
    with pytest.raises(EvidenceError):
        _build(tmp_path, audit, None, by="lead-solo", identities_path=ids)
    assert (
        _build(tmp_path, audit, "contoso-dental", by="lead-solo", identities_path=ids).manifest["generated_by"]
        == "lead-solo"
    )


@pytest.mark.parametrize("period", ["2026-13", "2026-1", "26-10", "2026-10-01", "", "../x"])
def test_b51_5_a_bad_period_is_refused_before_anything_is_written(tmp_path: Path, audit: Path, period: str) -> None:
    with pytest.raises(EvidenceError):
        _build(tmp_path, audit, period=period, write=True)
    assert not (tmp_path / "out").exists()


def test_b51_5_as_of_must_be_a_date_not_before_the_period(tmp_path: Path, audit: Path) -> None:
    for bad in ("tomorrow", "2026-09-30"):
        with pytest.raises(EvidenceError):
            _build(tmp_path, audit, as_of=bad)


@pytest.mark.parametrize("client", ["../x", "Contoso", "a/b", ""])
def test_b51_5_a_malformed_client_id_is_refused(tmp_path: Path, audit: Path, client: str) -> None:
    with pytest.raises(EvidenceError):
        _build(tmp_path, audit, client)


def test_b51_5_every_call_writes_one_audit_record_in_the_scopes_chain(tmp_path: Path, audit: Path) -> None:
    before = {n: len(_records(audit, n)) for n in ("contoso-dental", "fabrikam-capital", "_msp")}
    _build(tmp_path, audit)  # dry run
    bundle = _build(tmp_path, audit, write=True)
    after = {n: len(_records(audit, n)) for n in before}
    assert after["contoso-dental"] == before["contoso-dental"] + 2
    assert after["fabrikam-capital"] == before["fabrikam-capital"] and after["_msp"] == before["_msp"]
    dry, real = _records(audit, "contoso-dental")[-2:]
    assert (dry["mode"], dry["result"]["status"]) == ("dry-run", "ok")
    assert (real["mode"], real["event"], real["actor_kind"]) == ("execute", "job.run", "human")
    assert "".join(real["result"]["sha256"].split()) == bundle.manifest_sha256
    assert "secret-param" not in json.dumps(real)


def test_b51_5_the_audit_record_carries_no_bundle_rows(tmp_path: Path, audit: Path) -> None:
    _reviews(tmp_path, audit)
    _build(tmp_path, audit, write=True)
    record = _records(audit, "contoso-dental")[-1]
    assert set(record["result"]) <= {"status", "sha256", "files", "gaps", "audit_chain_ok"}
    assert record["params"] == {"scope": "client", "period": PERIOD, "as_of": AS_OF}


def test_b51_5_committed_config_and_fixtures_are_not_modified(tmp_path: Path, audit: Path) -> None:
    watched = [DEFAULT_IDENTITIES, DEFAULT_REGISTRY]
    before = [p.read_bytes() for p in watched]
    _build(tmp_path, audit, write=True)
    assert [p.read_bytes() for p in watched] == before


# -- B51-6: verify catches edits, removals, additions, and an unpinned manifest ---------------------------------------
def test_b51_6_a_fresh_bundle_verifies(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    assert verify_bundle(bundle.root) == bundle.manifest_sha256


def test_b51_6_an_edited_file_fails(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    target = bundle.root / "approvals.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(VerifyError, match="approvals.json"):
        verify_bundle(bundle.root)


def test_b51_6_a_removed_file_fails(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    (bundle.root / "registry.json").unlink()
    with pytest.raises(VerifyError, match="registry.json"):
        verify_bundle(bundle.root)


def test_b51_6_an_added_file_fails(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    (bundle.root / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(VerifyError, match="extra.json"):
        verify_bundle(bundle.root)


def test_b51_6_an_edited_manifest_fails_against_its_sidecar(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    manifest = bundle.root / "manifest.json"
    manifest.write_bytes(manifest.read_bytes().replace(b"not made", b"made", 1))
    with pytest.raises(VerifyError, match="manifest"):
        verify_bundle(bundle.root)


def test_b51_6_manifest_edited_with_a_fresh_sidecar_is_caught_by_the_audit_pin(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    assert verify_bundle(bundle.root, audit) == bundle.manifest_sha256
    manifest = bundle.root / "manifest.json"
    body = json.loads(manifest.read_bytes())
    body["management_assertion"]["status"] = "made"
    data = (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")
    manifest.write_bytes(data)
    (bundle.root / "manifest.json.sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  manifest.json\n", encoding="ascii"
    )
    verify_bundle(bundle.root)  # internally consistent
    with pytest.raises(VerifyError, match="not pinned"):
        verify_bundle(bundle.root, audit)


def test_b51_6_verify_fails_when_the_audit_chain_is_broken(tmp_path: Path, audit: Path) -> None:
    bundle = _build(tmp_path, audit, write=True)
    chain = audit / "contoso-dental.jsonl"
    lines = chain.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"ok"', '"OK"', 1)
    chain.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(VerifyError, match="does not verify"):
        verify_bundle(bundle.root, audit)


def test_b51_6_a_folder_without_a_manifest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(VerifyError):
        verify_bundle(tmp_path)


# -- CLI --------------------------------------------------------------------------------------------------------------
def _cli(tmp_path: Path, audit: Path, *extra: str) -> list[str]:
    return [
        "bundle",
        "contoso-dental",
        "--period",
        PERIOD,
        "--as",
        LEAD,
        "--as-of",
        AS_OF,
        "--out",
        str(tmp_path / "out"),
        "--audit-dir",
        str(audit),
        "--access-review-dir",
        str(tmp_path / "ar"),
        "--no-git",
        *extra,
    ]


def test_b51_cli_dry_run_prints_the_manifest_and_writes_nothing(
    tmp_path: Path, audit: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_cli(tmp_path, audit)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["written"] is False and printed["files"] > 0 and len(printed["sha256"]) == 64
    assert not (tmp_path / "out").exists()


def test_b51_cli_write_then_verify(tmp_path: Path, audit: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_cli(tmp_path, audit, "--write")) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["written"] is True
    assert main(["verify", printed["path"], "--audit-dir", str(audit)]) == 0
    assert main(["verify", printed["path"]]) == 0
    Path(printed["path"], "approvals.json").write_text("{}", encoding="utf-8")
    assert main(["verify", printed["path"]]) == 1


def test_b51_cli_refusal_exits_2(tmp_path: Path, audit: Path) -> None:
    args = _cli(tmp_path, audit)
    args[args.index(LEAD)] = "tech-ana"
    assert main(args) == 2


def test_b51_cli_needs_a_client_or_msp_but_not_both(tmp_path: Path, audit: Path) -> None:
    args = _cli(tmp_path, audit)
    assert main([*args, "--msp"]) == 2
    del args[1]
    assert main(args) == 2
