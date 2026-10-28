"""B-94 AI incident response runbook, notification templates and tabletop.

Acceptance ids B94-1 to B94-3 are defined in specs/B-94.md. The runbook's own command blocks are filled with synthetic
values and run, in order, against a private state folder in tmp_path (the committed fixtures are never touched), so a
command that does not exist in the repo fails here. The end-to-end test starts `pwsh` (user.disable is a PowerShell
lever and the scope query is a PowerShell filter) and skips when PowerShell 7.4+ is not installed.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/governance
"""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import shutil
import string
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from core.audit import redact
from core.levers.__main__ import _build_parser
from core.levers.models import Verification
from core.queue import open_queue

REPO = Path(__file__).resolve().parents[3]
RUNBOOK = REPO / "docs" / "runbooks" / "ai-incident-response.md"
TEMPLATES = REPO / "governance" / "templates" / "notifications"
TEMPLATE_README = TEMPLATES / "README.md"
TABLETOP = REPO / "docs" / "TABLETOP_2026.md"
GOVERNANCE = REPO / "docs" / "map" / "05-governance.md"
READERS = ("affected-person", "client-contact", "privacy-officer")
MAX_WORDS = {"affected-person": 150, "client-contact": 260, "privacy-officer": 300}
CONTOSO = "contoso-dental"
WRONG = "priya.nair@contosodental.example"  # the person the tabletop disabled by mistake
RIGHT = "jamie.chen@contosodental.example"  # the leaver the ticket was about
FILL = {
    "lever": "user.disable",
    "client": CONTOSO,
    "other-client": "fabrikam-capital",
    "lead": "lead-lee",
    "tech": "tech-ana",
    "upn": RIGHT,
    "reason": "B94 replay wrong user disabled",
}
PLACEHOLDER = re.compile(r"<([a-z][a-z-]*)>")
needs_pwsh = pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh (PowerShell 7.4+) is not installed")


# -- helpers ----------------------------------------------------------------------------------------------------------


def _sections(text: str) -> dict[str, str]:
    """Level-2 heading -> body."""
    parts = re.split(r"(?m)^## (.+)$", text)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _ir_sections() -> dict[str, str]:
    """IR id -> body of that step in the runbook."""
    return {h.split()[0]: body for h, body in _sections(RUNBOOK.read_text(encoding="utf-8")).items() if h[:3] == "IR-"}


def _blocks(body: str) -> list[str]:
    """Command lines of the powershell code blocks in one section."""
    lines: list[str] = []
    for block in re.findall(r"```powershell\n(.*?)```", body, flags=re.S):
        lines += [line.strip() for line in block.splitlines() if line.strip()]
    return lines


def _map_ir_steps() -> list[tuple[str, str]]:
    """(id, step name) of the IR table in docs/map/05-governance.md section 7, in table order."""
    text = GOVERNANCE.read_text(encoding="utf-8")
    section = text.split("## 7.", 1)[1].split("\n## ", 1)[0]
    return [(i, name) for name, i in re.findall(r"(?m)^\| ([^|]+?) \| `(IR-\d)` \|", section)]


def _fill(line: str, extra: dict[str, str] | None = None) -> str:
    values = {**FILL, **(extra or {})}
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], line)


def _syllables(word: str) -> int:
    """The same heuristic as tests/py/notify/test_b04_notify.py."""
    word = word.lower()
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[.!?:]+(?:\s|$)|\n", text) if re.search(r"[A-Za-z0-9]", s)]


def _fk_grade(text: str) -> float:
    """Flesch-Kincaid grade: 0.39 * words/sentences + 11.8 * syllables/words - 15.59."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text)
    return 0.39 * len(words) / len(_sentences(text)) + 11.8 * sum(_syllables(w) for w in words) / len(words) - 15.59


def _template(name: str) -> str:
    return (TEMPLATES / f"{name}.md").read_text(encoding="utf-8")


SAMPLE = {  # synthetic, plain values a person would type
    "first_name": "Priya",
    "contact_first_name": "Ana",
    "officer_first_name": "Lena",
    "when": "Thursday 23 October at 9:41 am",
    "what_happened": "turned off sign-in for the wrong person",
    "what_we_fixed": "we turned your sign-in back on",
    "what_you_do": "nothing. Sign in as usual.",
    "people_affected": "one person, a hygienist",
    "restored_at": "9:41 am",
    "paused_at": "9:41 am",
    "pause_scope": "for all of our clients",
    "files_note": "Your files and mail are still there.",
    "next_note": "We have stopped this kind of change until we fix the cause.",
    "scope_check": "we searched every change the tool made in the last 30 days and found no other wrong changes",
    "restart_note": "We will tell you before it is turned back on.",
    "data_note": "no patient records were sent anywhere",
    "exposure_note": "We found no sign of it.",
    "availability_note": "Yes, for a few minutes. She could not open patient records.",
    "review_date": "Thursday 30 October",
    "team": "your IT help desk",
    "fast_phone": "555-0190",
    "hours": "8am to 6pm, Monday to Friday",
    "client_name": "Contoso Dental",
    "sender": "Lee",
    "sender_role": "service desk lead",
    "sender_phone": "555-0190",
}
JARGON = re.compile(
    r"\b(lever|levers|audit chain|tenant|rollback|dry-run|idempoten\w*|registry|proposal|runner|payload|API|Graph|"
    r"UPN|hash|JSON|DC-\d|IR-\d|C-\d+|R[0-3]|EU-\d|HO-\d|B-\d+)\b"
)
DEADLINE = re.compile(r"\b(\d+ (?:calendar |business )?days?|deadlines?|no later than|same business day)\b", re.I)


def _run(argv: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv built from the runbook's fixed command lines, no shell
        argv, cwd=REPO, capture_output=True, text=True, timeout=timeout, check=False
    )


def _json_out(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    out = proc.stdout
    return dict(json.loads(out[out.index("{") :]))


def _argv(line: str, state: Path, tmp: Path) -> list[str] | None:
    """The runnable argv of one filled runbook line, pointed at `state`; None for a line this test does not run."""
    line = line.replace(".tmp/demo", state.as_posix()).replace(".tmp/", (tmp / "out").as_posix() + "-")
    if line.startswith("uv run --frozen python -m ui") or re.match(r"uv run --frozen (pytest|ruff)\b", line):
        return None  # the approval page serves forever; pytest and ruff would re-run this suite (checked elsewhere)
    if line.startswith("uv run --frozen python "):
        args = shlex.split(line.removeprefix("uv run --frozen python "))
        if args[:2] == ["-m", "core.levers"]:
            args[2:2] = ["--state", str(state)]
        elif args[:2] in (["-m", "workflows.rollback"], ["-m", "workflows.notify"]):
            args += ["--state", str(state)]
        return [sys.executable, *args]
    return ["pwsh", "-NoProfile", "-NonInteractive", "-Command", line]


# -- B94-1: the runbook follows IR-1 to IR-9 with commands that exist ----------------------------------------------


def test_b94_1_runbook_follows_ir1_to_ir9_in_order_with_the_governance_map_names() -> None:
    expected = _map_ir_steps()
    assert [i for i, _ in expected] == [f"IR-{n}" for n in range(1, 10)]
    headings = re.findall(r"(?m)^## (IR-\d) (.+)$", RUNBOOK.read_text(encoding="utf-8"))
    assert [(i, name.strip()) for i, name in headings] == expected


def test_b94_1_pause_scope_and_rollback_steps_each_carry_commands() -> None:
    ir = _ir_sections()
    assert any("-m core.levers pause <lever>" in line for line in _blocks(ir["IR-2"]))
    assert any("-m workflows.rollback <seq> --client <client>" in line for line in _blocks(ir["IR-3"]))
    scope = _blocks(ir["IR-4"])
    assert any("-m core.levers verify" in line for line in scope)
    assert any(line.startswith("Get-ChildItem .tmp/demo/audit") and "ConvertFrom-Json" in line for line in scope)
    assert any("-m core.levers export --client <client>" in line for line in scope)
    assert any("-m core.levers resume <lever>" in line for line in _blocks(ir["IR-9"]))


def test_b94_1_every_command_names_a_module_flags_and_paths_that_exist() -> None:
    lines = [line for body in _ir_sections().values() for line in _blocks(body)]
    assert len(lines) >= 15
    for line in lines:
        filled = _fill(line, {"seq": "2", "proposal-id": "P-0123456789ab"})
        if filled.startswith("uv run --frozen python -m "):
            args = shlex.split(filled.removeprefix("uv run --frozen python "))
            assert importlib.util.find_spec(args[1]) is not None, line
            if args[1] == "core.levers":
                _build_parser().parse_args(args[2:])  # exits on an unknown subcommand or flag
        elif filled.startswith("uv run --frozen pytest"):
            for target in [a for a in shlex.split(filled) if a.startswith("tests/")]:
                assert (REPO / target).exists(), line
    ui = _run([sys.executable, "-m", "ui", "--help"], timeout=60)
    assert ui.returncode == 0 and "--demo" in ui.stdout


def test_b94_1_runbook_cites_the_real_mechanisms_and_every_cited_path_exists() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for must in (
        "core/levers/pause.py",  # B-02 pause switch
        "core/audit/router.py",  # B-42 per-client audit chains
        "workflows/rollback/rollback.py",  # B-41 rollback
        "core/guard/classify.py",  # B-55 data classes
        "core/guard/redact_prompt.py",  # B-55 redaction gate
        "core/gateway/gateway.py",
        "governance/templates/notifications/",
        "docs/TABLETOP_2026.md",
    ):
        assert f"`{must}" in text, must
    for bid in ("B-02", "B-41", "B-42", "B-55"):
        assert bid in text
    cited = set(
        re.findall(r"`((?:core|workflows|ui|docs|governance|tests|fixtures|evals|levers|config)/[^`\s<]*)`", text)
    )
    assert len(cited) >= 10
    assert [c for c in sorted(cited) if not (REPO / c).exists()] == []


def test_b94_1_every_placeholder_in_a_command_is_explained_in_the_table() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    used = {p for body in _ir_sections().values() for line in _blocks(body) for p in PLACEHOLDER.findall(line)}
    table = set(re.findall(r"(?m)^\| `<([a-z-]+)>` \|", text))
    assert used == table


@needs_pwsh
def test_b94_1_runbook_commands_run_end_to_end_on_a_synthetic_wrong_disable(tmp_path: Path) -> None:
    state = tmp_path / "state"
    levers = [sys.executable, "-m", "core.levers", "--state", str(state)]
    call = [
        "invoke",
        "user.disable",
        "--as",
        "tech-ana",
        "--client",
        CONTOSO,
        "-p",
        f"upn={WRONG}",
        "-p",
        "reason=leaver",
    ]
    assert _run([*levers, *call]).returncode == 0
    wrong = _run([*levers, *call, "--execute", "--approved-by", "lead-lee", "--verified", "callback-on-file"])
    assert wrong.returncode == 0 and _json_out(wrong)["applied"] is True
    extra = {"seq": str(_json_out(wrong)["audit_seq"])}
    ir = _ir_sections()
    outputs: dict[str, list[subprocess.CompletedProcess[str]]] = {}
    for step in [f"IR-{n}" for n in range(1, 10)]:
        outputs[step] = []
        for line in _blocks(ir[step]):
            argv = _argv(_fill(line, extra), state, tmp_path)
            if argv is None:
                continue
            proc = _run(argv)
            assert proc.returncode == 0, (step, line, proc.stdout[-2000:], proc.stderr[-2000:])
            outputs[step].append(proc)
        if step == "IR-2":  # contained: even a dry-run of the lever is refused
            assert "all clients" in outputs[step][-1].stdout
            denied = _run([*levers, *call])
            assert denied.returncode == 1 and "lever paused by lead-lee" in _json_out(denied)["reason"]
        if step == "IR-3":  # the person first: the undo is proposed, then a lead approves it as on the page
            plan = _json_out(outputs[step][0])
            assert plan["outcome"] == "proposed" and plan["undo_lever"] == "user.enable" and plan["executed"] is False
            extra["proposal-id"] = plan["proposal_id"]
            at = datetime.now(UTC)
            check = Verification(method="callback-on-file", by="lead-lee", at=at, ref="CALL-B94")
            decision = open_queue(state).decide(plan["proposal_id"], "lead-lee", True, check)
            assert decision.proposal.status == "executed"
            users = json.loads((state / "tenant" / f"{CONTOSO}.json").read_text(encoding="utf-8"))["users"]
            assert [u["accountEnabled"] for u in users if u["userPrincipalName"] == WRONG] == [True]
        if step == "IR-4":  # scope: the filter finds the wrong execute; the export holds one client only
            assert WRONG in outputs[step][1].stdout and CONTOSO in outputs[step][1].stdout
            exported = sorted(p.name for p in tmp_path.glob(f"out-ir-{CONTOSO}/*"))
            assert exported == [f"{CONTOSO}.jsonl", f"{CONTOSO}.jsonl.head"]
            assert "fabrikam" not in (tmp_path / f"out-ir-{CONTOSO}" / f"{CONTOSO}.jsonl").read_text(encoding="utf-8")
        if step == "IR-5":
            assert "'dental': 'DC-4'" in outputs[step][0].stdout
    assert outputs["IR-9"][-1].stdout.strip() == "no levers are paused"
    pilot = _json_out(outputs["IR-9"][2])
    assert pilot["status"] == "ok" and pilot["mode"] == "dry-run" and pilot["data"]["user"] == RIGHT
    assert _run([*levers, "verify"]).returncode == 0


# -- B94-2: plain-language notification templates, timelines marked 'confirm with counsel' ---------------------------


def test_b94_2_one_template_for_each_reader_and_a_person_sends_it() -> None:
    names = sorted(p.stem for p in TEMPLATES.glob("*.md") if p.name != "README.md")
    assert names == sorted(READERS)
    for name in READERS:
        assert (
            _template(name).splitlines()[0]
            == "Draft. A person reviews and sends this. Do not send it from an automation."
        )


@pytest.mark.parametrize("name", READERS)
def test_b94_2_templates_are_plain_language(name: str) -> None:
    raw = _template(name)
    template = string.Template(raw)
    assert template.is_valid()
    documented = set(re.findall(r"`\$([a-z_]+)`", TEMPLATE_README.read_text(encoding="utf-8")))
    assert set(template.get_identifiers()) <= documented
    text = template.substitute(SAMPLE)  # raises on a placeholder with no plain value
    body = "\n".join(text.splitlines()[1:])
    assert _fk_grade(body) <= 8.0, _fk_grade(body)
    longest = max(len(s.split()) for s in _sentences(body))
    assert longest <= 25, longest
    assert JARGON.findall(raw) == []
    assert len(body.split()) <= MAX_WORDS[name], len(body.split())


@pytest.mark.parametrize("name", READERS)
def test_b94_2_every_timeline_is_listed_as_confirm_with_counsel(name: str) -> None:
    lines = _template(name).splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Timelines"))
    bullets = []
    for line in lines[start + 1 :]:
        if not line.startswith("- "):
            break
        bullets.append(line)
    assert bullets, "a Timelines list with at least one line"
    assert all("confirm with counsel" in b for b in bullets)
    for line in lines:
        if DEADLINE.search(line):
            assert "confirm with counsel" in line, line


def test_b94_2_privacy_officer_timelines_match_the_governance_map() -> None:
    gov = GOVERNANCE.read_text(encoding="utf-8")
    assert "no later than 60 days after discovery" in gov  # BA-5
    assert "within 30 days" in gov and "500 or more consumers" in gov  # GLBA-7
    text = _template("privacy-officer")
    timelines = text.split("Timelines", 1)[1]
    for must in ("HIPAA", "60 days", "FTC", "30 days", "500 or more", "State laws", "contract"):
        assert must in timelines, must


@pytest.mark.parametrize("name", READERS)
def test_b94_2_templates_hold_no_number_address_secret_or_name(name: str) -> None:
    raw = _template(name)
    assert re.search(r"\d{3}[-. ]\d{4}", raw) is None
    assert "@" not in raw and redact(raw) == raw
    for synthetic_person in ("Priya", "Jamie", "Ana", "Lee", "Nair", "Chen"):
        assert synthetic_person not in raw  # names come from placeholders only


# -- B94-3: one tabletop on synthetic tenants, recorded with times and lessons -------------------------------------


def test_b94_3_tabletop_is_a_synthetic_wrong_user_disabled_at_contoso_dental() -> None:
    text = TABLETOP.read_text(encoding="utf-8")
    assert text.splitlines()[1].startswith("Status: **")
    for must in (
        "Contoso Dental",
        "synthetic",
        "wrong user",
        "user.disable",
        WRONG,
        RIGHT,
        "Independently built prototype",
    ):
        assert must in text, must


def test_b94_3_every_ir_step_is_recorded_with_a_time_in_order() -> None:
    text = TABLETOP.read_text(encoding="utf-8")
    rows = re.findall(r"(?m)^\| (IR-\d) \| (\d{2}:\d{2}:\d{2}) \| ", text)
    assert [i for i, _ in rows] == [f"IR-{n}" for n in range(1, 10)]
    times = [t for _, t in rows]
    assert times == sorted(times)
    assert re.search(r"(?m)^Date: 2026-\d{2}-\d{2} \(UTC\)", text)


def test_b94_3_lessons_are_recorded_each_with_a_follow_up() -> None:
    lessons = _sections(TABLETOP.read_text(encoding="utf-8"))["Lessons"]
    items = re.findall(r"(?m)^- \*\*L-(\d+)\*\* (.+)$", lessons)
    assert len(items) >= 3
    assert [int(n) for n, _ in items] == list(range(1, len(items) + 1))
    assert all("Follow-up:" in body for _, body in items)


# -- the checks above can fail: each is run against a spoiled copy and must object ---------------


def _plain_problems(raw: str) -> list[str]:
    """What is wrong, in words, with a template's plain-language rules (empty list: it passes)."""
    body = "\n".join(string.Template(raw).substitute(SAMPLE).splitlines()[1:])
    problems = []
    if _fk_grade(body) > 8.0:
        problems.append("grade")
    if max(len(s.split()) for s in _sentences(body)) > 25:
        problems.append("long sentence")
    if JARGON.findall(raw):
        problems.append("jargon")
    return problems


def _timeline_problems(raw: str) -> list[str]:
    problems = [line for line in raw.splitlines() if DEADLINE.search(line) and "confirm with counsel" not in line]
    return problems


@pytest.mark.parametrize("name", READERS)
def test_b94_2_plain_language_check_rejects_spoiled_templates(name: str) -> None:
    raw = _template(name)
    assert _plain_problems(raw) == []
    assert "jargon" in _plain_problems(raw + "\nThe lever ran in the tenant, see IR-3.\n")
    assert "long sentence" in _plain_problems(raw + "\n" + " ".join(["word"] * 30) + ".\n")
    hard = "Notwithstanding unavailability, organizational responsibilities necessitate comprehensive documentation. "
    assert "grade" in _plain_problems(raw + "\n" + hard * 12)


@pytest.mark.parametrize("name", READERS)
def test_b94_2_timeline_check_rejects_a_deadline_without_counsel(name: str) -> None:
    raw = _template(name)
    assert _timeline_problems(raw) == []
    spoiled = raw.replace("(confirm with counsel)", "").replace("(each one: confirm with counsel)", "")
    spoiled = spoiled.replace("confirm with counsel and your contract", "check your contract")
    if DEADLINE.search(spoiled):
        assert _timeline_problems(spoiled) != []
    assert _timeline_problems(raw + "\nWe must report within 30 days.\n") != []
    assert "confirm with counsel" in raw  # the spoiling above really removed something


def test_b94_1_heading_check_rejects_a_missing_or_swapped_step() -> None:
    expected = _map_ir_steps()
    text = RUNBOOK.read_text(encoding="utf-8")
    swapped = text.replace("## IR-3 Restore the person first", "## IR-3 Restore the user")
    assert re.findall(r"(?m)^## (IR-\d) (.+)$", swapped) != [(i, n) for i, n in expected]
    dropped = text.replace("## IR-6 Notify", "## Notify")
    assert [i for i, _ in re.findall(r"(?m)^## (IR-\d) (.+)$", dropped)] != [i for i, _ in expected]


def test_b94_1_a_command_with_an_unknown_subcommand_is_rejected_by_the_parser() -> None:
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["pausee", "user.disable", "--as", "lead-lee"])
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["pause", "user.disable", "--as", "lead-lee", "--no-such-flag"])
    assert importlib.util.find_spec("workflows.no_such_module") is None


def test_b94_3_tabletop_lesson_l1_still_describes_the_notify_draft() -> None:
    """L-1 says the rollback draft gives an untrue reason; if B-04 fixes that, update the lesson."""
    notify = (REPO / "workflows" / "notify" / "notify.py").read_text(encoding="utf-8")
    template = (REPO / "workflows" / "notify" / "templates" / "user.enable.md").read_text(encoding="utf-8")
    assert 'return f"a security check flagged it ({proposal.ref})"' in notify
    assert "Why:" in template
    assert "a security check flagged it" in TABLETOP.read_text(encoding="utf-8")


def test_b94_3_tabletop_quotes_the_ticket_and_the_ids_the_replay_uses() -> None:
    text = TABLETOP.read_text(encoding="utf-8")
    fixture = (REPO / "fixtures" / "tenant" / "contoso-dental.json").read_text(encoding="utf-8")
    assert "Jamie Chen left the practice on Friday. Please disable their account." in fixture
    assert "Jamie Chen left the practice on Friday. Please disable their account." in text
    assert WRONG in fixture and RIGHT in fixture
    assert "Fabrikam Capital" in text and "fabrikam-capital" in text


# -- scope-dependent statements are placeholders a person confirms; the HIPAA line is marked UNVERIFIED ---------------

HARD_CODED = ("all of our clients", "all clients", "files and mail are still there", "stopped this kind of change")


def _hard_coded(raw: str) -> list[str]:
    return [s for s in HARD_CODED if s in raw.lower()]


def _readme() -> str:
    return TEMPLATE_README.read_text(encoding="utf-8")


def _hipaa_line_problems(raw: str) -> list[str]:
    lines = [line for line in raw.splitlines() if "HIPAA" in line]
    return [line for line in lines if not line.startswith("- UNVERIFIED:")] or ([] if lines else ["no HIPAA line"])


@pytest.mark.parametrize("name", READERS)
def test_b94_2_scope_dependent_statements_use_the_documented_placeholders(name: str) -> None:
    raw = _template(name)
    assert _hard_coded(raw) == []
    ids = set(string.Template(raw).get_identifiers())
    if name == "affected-person":
        assert {"files_note", "next_note"} <= ids
    else:
        assert "pause_scope" in ids
    if name == "client-contact":
        assert {"restart_note", "scope_check"} <= ids
        assert (
            "We will tell you before it is turned back on." not in raw
        )  # a promise the owner confirms, not fixed text
        assert "we searched our records for every change" not in raw
    if name == "affected-person":
        assert "A person checks every step" not in raw
    assert "stays off until" not in raw


def test_b94_2_hard_coded_scope_check_rejects_the_old_wording() -> None:
    old = "we paused that tool for all of our clients at $paused_at. Your files and mail are still there."
    assert _hard_coded(old) == ["all of our clients", "files and mail are still there"]
    assert _hard_coded(_template("client-contact")) == []


def test_b94_2_hipaa_line_starts_with_unverified() -> None:
    assert _hipaa_line_problems(_template("privacy-officer")) == []
    old = "- Health data (HIPAA): we, as your business associate, must tell you in 60 days (confirm with counsel)."
    assert _hipaa_line_problems(old) == [old]
    assert "UNVERIFIED: counsel to confirm whether we are your business associate" in _template("privacy-officer")


def test_b94_2_readme_documents_every_placeholder_and_the_person_confirms_marker() -> None:
    readme = _readme()
    table_ids = set(re.findall(r"`\$([a-z_]+)`", readme.split("## Placeholders", 1)[1].split("## Timelines", 1)[0]))
    used: set[str] = set()
    for name in READERS:
        used |= set(string.Template(_template(name)).get_identifiers())
    assert used <= table_ids, sorted(used - table_ids)
    assert "person confirms before sending" in readme
    for confirmed in ("files_note", "next_note", "pause_scope"):
        assert confirmed in readme.split("### Person confirms before sending", 1)[1].split("## Timelines", 1)[0]
    assert "paraphrased by the reviewing person" in readme and "never pasted" in readme
    assert "BA-5" in readme and "GLBA-7" in readme
