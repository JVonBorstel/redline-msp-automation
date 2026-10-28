"""B-10 demo smoke test: every typed command in docs/DEMO.md, run end to end, offline, in a temp state folder.

The test reads the script itself, so a change to a command, an output line or a denial reason that would break the
live demo fails here first. Main blocks run in document order in one temp root; fallback blocks run in a second,
fresh root (a fallback replaces the live step). Each block runs as one `pwsh` script from the repo root with `.tmp/`
replaced by the temp root. The approval page is started as typed (plus `--port 0`) and driven over 127.0.0.1 only.
Synthetic data only; the committed fixtures and the repo's own .tmp demo folders are never touched.

Run: pwsh -NoProfile -File tests/demo/Test-Demo.ps1   (prints "Demo tests: N passed, M failed")
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

import pytest

from core.queue.__main__ import demo_proposals

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "docs" / "DEMO.md"
RUNNER = REPO / "tests" / "demo" / "Test-Demo.ps1"
PWSH = shutil.which("pwsh")
T3101 = "P-d01c53bdf1dc"  # deterministic: P- + sha256(lever + client + canonical params)[:12]
SEEDED_STALE = demo_proposals()[1]  # user.disable for contoso-dental, rejected on the page in step 6a
BLOCK_TIMEOUT = 60
TIME_BUDGET_S = 120  # B10-3

# Lines the smoke test does not run, each with the reason. Each must still be in DEMO.md (test_b10_1_skipped_lines_...).
SKIPPED = {
    "pwsh -File scripts/clean.ps1": "would delete the repo's .tmp; the smoke test starts from an empty temp folder",
    "pwsh -NoProfile -File tests/phase1/Test-Phase1.ps1": "separate suite (CI run it)",
    "pwsh -NoProfile -File tests/sliceb/Test-SliceB.ps1": "separate suite (CI run it)",
    "pwsh -NoProfile -File tests/demo/Test-Demo.ps1": "this suite (no recursion)",
}
PRELUDE = """$ErrorActionPreference = 'Continue'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
# The demo opens report.html in a browser; the smoke test only checks the file is there.
function Invoke-Item { param([Parameter(Mandatory)][string]$Path)
    if (Test-Path -LiteralPath $Path) { "smoke: would open $Path" } else { "smoke: missing $Path"; exit 3 } }
"""
EXIT_LINE = re.compile(r"^\[exit (-?\d+)\]$", re.M)
STATEFUL = re.compile(
    r"python -m (core\.levers (?!list)|core\.queue|workflows\.notify|ui\b|core\.audit\.verify)|--enqueue|-OutDir"
)


@dataclass(frozen=True)
class Block:
    step: str  # "before" or "1".."8"
    kind: str  # "main" or "fallback"
    index: int  # order within (step, kind)
    lines: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.step}/{self.kind}/{self.index}"

    @property
    def is_server(self) -> bool:
        return any(" -m ui " in f"{line} " for line in self.lines)


@dataclass(frozen=True)
class Expect:
    exits: tuple[int, ...]  # exit code of each `uv` / `pwsh` line that is run, in order
    markers: tuple[str, ...] = ()  # literal substrings, or "re:<pattern>"


# What each block must print. Keys are <step>/<main|fallback>/<n>; a block without an entry fails (B10-1).
EXPECT: dict[str, Expect] = {
    # B-42: one chain per client, so the third demo proposal (Fabrikam) starts its own chain at seq 1.
    "before/main/0": Expect((0, 0), ("user.reset-mfa", "verify=requester", "[dry-run seq 1]", "[dry-run seq 2]")),
    "1/main/0": Expect(
        (0,),
        (
            f"queued: {T3101} (pending)",
            f"Proposal {T3101} (pending, needs a lead's approval to execute)",
            "priya.nair@contosodental.example",
            "Injection check: nothing flagged",
            "Who this affects (user.reset-mfa, risk class R3",
            "L1 one person:",
            "L4 the community:",
            "Before approval: call back on the number on file",
        ),
    ),
    "2/fallback/0": Expect(
        (0, 0), ('"provider":"mock"', '"ok":true', '"status": "ok"', '"mode": "dry-run"', '"applied": false')
    ),
    "3/main/0": Expect(
        (0,), ("Injection check: FLAGGED", "instruction-override", "invisible-characters", "Proposal: none")
    ),
    "3/fallback/0": Expect(
        (0, 1, 1),
        (
            "True ['instruction-override']",
            '"status": "denied"',
            "role 'agent' cannot execute user.disable (needs technician)",
            "tech-ana is not scoped to client 'fabrikam-capital'",
        ),
    ),
    "3/main/1": Expect((0,), ("fixture-based", "Corpus: 50 cases", "Precision: 100.0%", "re:Recall:\\s+100\\.0%")),
    "4/main/0": Expect(
        (0,), ("re:Findings\\s*:\\s*14", "re:High\\s*:\\s*10", "re:Medium\\s*:\\s*4", "smoke: would open")
    ),
    "5/main/0": Expect(
        (0,), ("fixture-based", "OK: every number in summary.txt reconciles with findings.json (14 findings).")
    ),
    "6/main/0": Expect((), ("Approval queue on http://127.0.0.1:",)),  # the page; checked in PAGE_CHECKS
    "6/main/1": Expect(
        (0,),
        (
            "Draft. A person reviews and sends this.",
            "Hi Priya,",
            "you asked for it in ticket T-3101",
            "Who approved it: Lee, a service desk lead.",
            "555-0190",
            f"notices/{T3101}.md".replace("/", os.sep),
        ),
    ),
    "6/main/2": Expect(
        (0, 1, 0),
        (
            "user.reset-mfa paused for client contoso-dental",
            '"status": "denied"',
            "lever paused by lead-lee: drill: suspected social engineering",
            "user.reset-mfa resumed for client contoso-dental",
        ),
    ),
    "6/fallback/0": Expect(
        (1, 1, 0, 1),
        (
            "user.reset-mfa in execute mode needs a lead approval record",
            "user.reset-mfa needs a recorded requester verification (C-30)",
            '"status": "ok"',
            '"approver": "lead-lee"',
            '"applied": true',
            "requester cannot approve their own action (four-eyes rule)",
        ),
    ),
    "6/fallback/1": Expect((), ("What changed:", "How to undo it:", "$fast_phone")),
    "7/main/0": Expect((0,), (r"re:OK: \d+ records, chain intact and matches the head pin",)),
    "8/main/0": Expect((1,), (r"re:BROKEN at seq \d+: hash does not match the record content",)),
    "8/main/1": Expect((0,), (r"re:OK: \d+ records, chain intact and matches the head pin",)),
}


# -- parsing DEMO.md ---------------------------------------------------------------------------------------------


def demo_text() -> str:
    return DEMO.read_text(encoding="utf-8").replace("\r\n", "\n")


def parse_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    step: str | None = None
    counts: dict[tuple[str, str], int] = {}
    previous = ""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            step = "before" if line.startswith("## Before the room") else None
        elif m := re.match(r"### (\d+)\. ", line):
            step = m.group(1)
        elif line.startswith("### "):
            step = None
        if line.startswith("```powershell"):
            body: list[str] = []
            i += 1
            while not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            if step is not None:
                kind = "fallback" if previous.startswith("Fallback") else "main"
                n = counts.get((step, kind), 0)
                counts[(step, kind)] = n + 1
                blocks.append(Block(step, kind, n, tuple(x for x in body if x.strip())))
        elif line.strip():
            previous = line
        i += 1
    return blocks


def command_of(line: str) -> str:
    return re.sub(r"\s+#.*$", "", line).strip()


def is_native(line: str) -> bool:
    return line.startswith(("uv ", "pwsh "))


# -- running blocks ---------------------------------------------------------------------------------------------


@dataclass
class Outcome:
    output: str = ""
    exits: list[int] = field(default_factory=list)
    page: list[tuple[str, bool, str]] = field(default_factory=list)  # (check, ok, detail)


@dataclass
class Run:
    root: Path
    outcomes: dict[str, Outcome]
    seconds: float


def substitute(line: str, root: Path) -> str:
    return line.replace(".tmp/", f"{root.as_posix()}/")


def script_for(block: Block, root: Path) -> str:
    parts = [PRELUDE]
    for line in block.lines:
        if command_of(line) in SKIPPED:
            parts.append(f'"smoke: skipped {command_of(line)}"')
            continue
        parts.append(substitute(line, root))
        if is_native(line):
            parts.append('"[exit $LASTEXITCODE]"')
    return "\n".join(parts) + "\n"


def run_block(block: Block, root: Path, scripts: Path) -> Outcome:
    assert PWSH is not None
    path = scripts / f"{block.key.replace('/', '-')}.ps1"
    path.write_text(script_for(block, root), encoding="utf-8")
    done = subprocess.run(  # noqa: S603 - fixed pwsh, script text from the committed DEMO.md
        [PWSH, "-NoProfile", "-NonInteractive", "-File", str(path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=BLOCK_TIMEOUT,
        env={**os.environ, "NO_COLOR": "1"},
    )
    output = done.stdout + done.stderr
    return Outcome(output=output, exits=[int(x) for x in EXIT_LINE.findall(output)])


class Page:
    """The approval page started exactly as DEMO.md types it (plus --port 0), driven over 127.0.0.1 only."""

    def __init__(self, block: Block, root: Path) -> None:
        assert PWSH is not None
        (line,) = block.lines
        command = PRELUDE + substitute(line, root) + " --port 0\n"
        self.proc = subprocess.Popen(  # noqa: S603 - fixed pwsh, command from the committed DEMO.md
            [PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"},
        )
        assert self.proc.stdout is not None
        self.banner = self.proc.stdout.readline()
        m = re.search(r"http://127\.0\.0\.1:(\d+)/", self.banner)
        self.port = int(m.group(1)) if m else 0

    def request(self, method: str, target: str, form: dict[str, str] | None = None) -> tuple[int, str, str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            body = urlencode(form).encode() if form is not None else None
            headers = {"Content-Type": "application/x-www-form-urlencoded"} if form is not None else {}
            conn.request(method, target, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.getheader("Location") or "", response.read().decode("utf-8")
        finally:
            conn.close()

    def stop(self) -> None:
        if self.proc.poll() is None:
            if sys.platform == "win32":  # uv starts python as a child: stop the whole tree
                taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
                subprocess.run(  # noqa: S603 - Windows built-in, fixed arguments
                    [str(taskkill), "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True, check=False
                )
            else:
                self.proc.kill()
        self.proc.wait(timeout=20)
        if self.proc.stdout is not None:
            self.proc.stdout.close()


def verify_button(page: Page, out: Outcome, expect: str) -> None:
    status, _, body = page.request("GET", "/audit?verify=1")
    out.page.append((f"Verify chain says {expect}", status == 200 and expect in body, f"status {status}"))


def drive_step_6a(page: Page, out: Outcome) -> None:
    status, _, body = page.request("GET", "/?as=lead-lee")
    csrf = re.search(r'name="csrf" value="([^"]+)"', body)
    card = body[body.find(f"approve:{T3101}") - 4000 : body.find(f"approve:{T3101}")]
    out.page.append(("page lists Priya's proposal", status == 200 and f"approve:{T3101}" in body, f"status {status}"))
    out.page.append(("card shows the person", "priya.nair@contosodental.example" in card, ""))
    out.page.append(("card shows the undo", "no undo lever: manual undo" in card, ""))
    out.page.append(("card asks for the verification", "Requester verified out of band" in card, ""))
    token = csrf.group(1) if csrf else ""
    base = {"csrf": token, "actor": "lead-lee"}
    status, _, body = page.request("POST", "/decide", {**base, "act": f"approve:{T3101}"})
    refused = "Refused: user.reset-mfa needs the requester verified out of band first; choose how (C-30)"
    out.page.append(("approve without a verification is refused", status == 400 and refused in body, f"{status}"))
    _, _, body = page.request("GET", "/?as=lead-lee")
    out.page.append(("the proposal is still pending", f"approve:{T3101}" in body, ""))
    form = {**base, "act": f"approve:{T3101}", "verified": "callback-on-file", "number_source": "psa-contact"}
    status, location, _ = page.request("POST", "/decide", form)
    out.page.append(("approve with a callback is accepted", status == 303, f"{status}"))
    _, _, body = page.request("GET", location or "/")
    banner = f"Executed {T3101}: user.reset-mfa for contoso-dental as tech-ana, approved by lead-lee."
    out.page.append(("banner names the execute and the approver", banner in body, ""))
    out.page.append(("banner names the verification", "called back on the number on file" in body, ""))
    status, location, _ = page.request("POST", "/decide", {**base, "act": f"reject:{SEEDED_STALE.id}"})
    _, _, body = page.request("GET", location or "/")
    out.page.append(("reject of a seeded proposal", status == 303 and f"Rejected {SEEDED_STALE.id}" in body, ""))


def run_path(kind: str, root: Path) -> Run:
    if " " in str(root):
        pytest.fail(f"temp root has a space, which the unquoted demo paths cannot take: {root}")
    scripts = root / "_scripts"
    scripts.mkdir(parents=True)
    outcomes: dict[str, Outcome] = {}
    page: Page | None = None
    started = time.monotonic()
    try:
        for block in (b for b in parse_blocks(demo_text()) if b.kind == kind):
            if block.is_server:
                page = Page(block, root)
                out = Outcome(output=page.banner)
                if page.port:
                    drive_step_6a(page, out)
            else:
                out = run_block(block, root, scripts)
                if page is not None and block.step in ("7", "8"):
                    verify_button(page, out, "BROKEN at seq" if block.key == "8/main/0" else "OK: ")
            outcomes[block.key] = out
    finally:
        if page is not None:
            page.stop()
    return Run(root, outcomes, time.monotonic() - started)


def snapshot() -> dict[str, str]:
    """What the smoke test must not touch: the repo's own demo state folders and the committed fixtures."""
    seen: dict[str, str] = {}
    for rel in (".tmp/demo", ".tmp/triage", ".tmp/baseline-contoso", "fixtures/tenant", "fixtures/notify"):
        base = REPO / rel
        for path in sorted(base.rglob("*")) if base.exists() else []:
            if path.is_file():
                seen[path.relative_to(REPO).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return seen


needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh (PowerShell 7) is not on PATH")


@pytest.fixture(scope="module")
def before() -> dict[str, str]:
    return snapshot()


@pytest.fixture(scope="module")
def main_run(before: dict[str, str], tmp_path_factory: pytest.TempPathFactory) -> Iterator[Run]:
    yield run_path("main", tmp_path_factory.mktemp("demo-main"))


@pytest.fixture(scope="module")
def fallback_run(main_run: Run, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Run]:
    yield run_path("fallback", tmp_path_factory.mktemp("demo-fallback"))


def check(outcome: Outcome, expect: Expect) -> list[str]:
    problems = []
    if tuple(outcome.exits) != expect.exits:
        problems.append(f"exit codes {outcome.exits}, expected {list(expect.exits)}")
    for marker in expect.markers:
        found = re.search(marker[3:], outcome.output) if marker.startswith("re:") else marker in outcome.output
        if not found:
            problems.append(f"missing marker {marker!r}")
    problems += [f"page: {name} failed ({detail})" for name, ok, detail in outcome.page if not ok]
    return problems


def chain_files(root: Path) -> list[Path]:
    """B-42: the demo's audit chains, one `<client>.jsonl` each plus `_msp.jsonl`."""
    return sorted((root / "demo" / "audit").glob("*.jsonl"))


def audit_records(root: Path, client: str | None = None) -> list[dict[str, object]]:
    """Every record of one client's chain, or of all chains when no client is named."""
    paths = [root / "demo" / "audit" / f"{client}.jsonl"] if client else chain_files(root)
    return [
        json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


BLOCKS = parse_blocks(demo_text())
MAIN_KEYS = [b.key for b in BLOCKS if b.kind == "main"]
FALLBACK_KEYS = [b.key for b in BLOCKS if b.kind == "fallback"]


# -- B10-1: every typed command runs and prints what the presenter points at --------------------------------------


def test_b10_1_every_block_in_demo_md_has_an_expectation_and_back() -> None:
    keys = {b.key for b in BLOCKS}
    assert keys == set(EXPECT), f"blocks without expectations: {keys - set(EXPECT)}; stale: {set(EXPECT) - keys}"
    assert {b.step for b in BLOCKS} == {"before", *map(str, range(1, 9))}, "steps 1-8 each have a typed block"
    assert sum(1 for b in BLOCKS if b.kind == "fallback") >= 4


def test_b10_1_stateful_commands_name_a_temp_substitutable_state_folder() -> None:
    for block in BLOCKS:
        for line in block.lines:
            if STATEFUL.search(line) and command_of(line) not in SKIPPED:
                assert ".tmp/" in line, f"{block.key}: {line!r} uses a default state folder the test cannot move"


def test_b10_1_skipped_lines_are_still_in_the_script_and_are_the_only_ones() -> None:
    lines = {command_of(line) for b in BLOCKS for line in b.lines}
    assert set(SKIPPED) <= lines
    assert all(b.step == "before" for b in BLOCKS for line in b.lines if command_of(line) in SKIPPED)


def test_b10_1_inline_commands_in_the_prose_are_also_in_a_tested_block() -> None:
    run = {command_of(line) for b in BLOCKS for line in b.lines}
    inline = set(re.findall(r"`(uv run [^`]+)`", demo_text()))
    assert inline <= run, f"inline commands not in a block: {inline - run}"


def test_b10_1_the_proposal_id_named_in_the_script_is_the_deterministic_t3101_id() -> None:
    from core.queue import Proposal

    pid = Proposal.new(
        source="triage",
        ref="T-3101",
        lever="user.reset-mfa",
        client="contoso-dental",
        params={"upn": "priya.nair@contosodental.example"},
        requested_by="tech-ana",
        reason="x",
    ).id
    assert pid == T3101 and demo_text().count(T3101) >= 3


@needs_pwsh
@pytest.mark.parametrize("key", MAIN_KEYS)
def test_b10_1_main_block_runs_and_prints_its_markers(main_run: Run, key: str) -> None:
    assert key in main_run.outcomes, f"{key} did not run"
    problems = check(main_run.outcomes[key], EXPECT[key])
    assert not problems, f"{key}: {problems}\n--- output ---\n{main_run.outcomes[key].output[-3000:]}"


@needs_pwsh
@pytest.mark.parametrize("key", FALLBACK_KEYS)
def test_b10_1_fallback_block_runs_and_prints_its_markers(fallback_run: Run, key: str) -> None:
    assert key in fallback_run.outcomes, f"{key} did not run"
    problems = check(fallback_run.outcomes[key], EXPECT[key])
    assert not problems, f"{key}: {problems}\n--- output ---\n{fallback_run.outcomes[key].output[-3000:]}"


@needs_pwsh
def test_b10_1_both_paths_leave_an_intact_audit_chain_with_every_denial_recorded(
    main_run: Run, fallback_run: Run
) -> None:
    from core.audit import head_path_for, verify_chain

    for run, denials in ((main_run, 2), (fallback_run, 5)):
        assert chain_files(run.root), "no audit chain was written"
        for log in chain_files(run.root):
            head = head_path_for(log)
            assert verify_chain(log, head if head.exists() else None).ok, log.name
        denied = [r for r in audit_records(run.root) if r["result"]["status"] == "denied"]  # type: ignore[index]
        assert len(denied) == denials, [r["result"] for r in denied]


@needs_pwsh
def test_b10_1_the_repo_demo_state_and_committed_fixtures_are_untouched(
    before: dict[str, str], main_run: Run, fallback_run: Run
) -> None:
    assert snapshot() == before


# -- B10-2: callback before approve, notice after execute, pause/deny/resume, all inside five minutes -------------


def _seconds(stamp: str) -> int:
    minutes, seconds = stamp.split(":")
    return int(minutes) * 60 + int(seconds)


def test_b10_2_timing_table_is_contiguous_and_sums_to_five_minutes_or_less() -> None:
    rows = re.findall(r"^\| (\d+:\d\d)-(\d+:\d\d) \| ([^|]+?) \|", demo_text(), re.M)
    assert rows[0][0] == "0:00"
    for (_, end, _), (start, _, _) in zip(rows, rows[1:], strict=False):
        assert end == start, "rows are contiguous"
    assert _seconds(rows[-1][1]) <= 300
    labels = [label for _, _, label in rows]
    assert [label.split(".")[0] for label in labels[:8]] == [str(n) for n in range(1, 9)] and labels[8] == "Close"
    step6 = labels[5].lower()
    assert "verifies" in step6 and "tells priya" in step6 and "switch" in step6


def test_b10_2_step_6_orders_callback_approve_notice_then_pause_deny_resume() -> None:
    text = demo_text()
    s6 = text[text.index("### 6. ") : text.index("### 7. ")]
    order = [
        s6.index("with no verification chosen"),
        s6.index("called back on the number on file"),
        s6.index("Press **Approve**. The banner says"),
        s6.index(f"python -m workflows.notify {T3101}"),
        s6.index(" pause user.reset-mfa"),
        s6.index("invoke user.reset-mfa --as tech-ana --client contoso-dental -p upn=sam.patel"),
        s6.index(" resume user.reset-mfa"),
    ]
    assert order == sorted(order)
    assert text.index("### 6. ") < text.index("### 7. ") < text.index("### Close")


@needs_pwsh
def test_b10_2_the_audit_log_shows_refusal_verified_execute_pause_denied_resume_in_order(main_run: Run) -> None:
    records = audit_records(main_run.root, "contoso-dental")  # the whole step 6 story is Contoso's chain

    def first(pred: object) -> int:
        return next(i for i, r in enumerate(records) if pred(r))  # type: ignore[operator]

    refused = first(lambda r: r["mode"] == "approve" and r["result"]["status"] == "denied")
    execute = first(lambda r: r["mode"] == "execute" and r["params"] == {"upn": "priya.nair@contosodental.example"})
    paused = first(lambda r: r["mode"] == "pause")
    denied = first(lambda r: r["mode"] == "dry-run" and "lever paused" in (r["result"].get("reason") or ""))
    resumed = first(lambda r: r["mode"] == "resume")
    assert refused < execute < paused < denied < resumed
    exe = records[execute]
    assert exe["approver"] == "lead-lee" and exe["result"]["status"] == "ok"  # type: ignore[index]
    verification = exe["result"]["verification"]  # type: ignore[index]
    assert verification["method"] == "callback-on-file" and verification["ref"] == "number-on-file:psa-contact"
    notice = main_run.root / "demo" / "notices" / f"{T3101}.md"
    assert notice.exists() and notice.read_text(encoding="utf-8").startswith("Draft. A person reviews and sends this.")


# -- B10-3: under 120 seconds, one summary line ------------------------------------------------------------------


@needs_pwsh
def test_b10_3_both_paths_finish_inside_the_time_budget(main_run: Run, fallback_run: Run) -> None:
    total = main_run.seconds + fallback_run.seconds
    assert total < TIME_BUDGET_S, f"{total:.1f}s"


def test_b10_3_the_runner_prints_the_summary_line_and_enforces_the_budget() -> None:
    src = RUNNER.read_text(encoding="utf-8")
    assert 'Write-Host "Demo tests: $pass passed, $fail failed"' in src
    assert "120" in src and "uv run --frozen pytest" in src and "tests/demo" in src


# -- B10-4: honesty lines and week-one plan unchanged; numbers labelled fixture-based ------------------------------

# sha256 of each section (from its heading to the next "## ", stripped, LF line ends) as it stood before B-10.
# A deliberate edit (e.g. The owner's ramp-plan wording) updates the pin in the same PR, with his yes.
PINNED = {
    "## Honesty lines": "bab9334c10e545c7cd764836f728a23295a44f5608487bd913ce2fa291c79e93",
    "## Adapting this to a real MSP": "4edc6889489698bd79e0e8c0872f1b4734b086fa20a0e2e09a9b6183e04b1170",
}


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + 1)
    return text[start : end if end > 0 else None].strip()


@pytest.mark.parametrize("heading", sorted(PINNED))
def test_b10_4_honesty_lines_and_week_one_plan_are_unchanged(heading: str) -> None:
    assert hashlib.sha256(_section(demo_text(), heading).encode()).hexdigest() == PINNED[heading]


def test_b10_4_every_number_shown_is_labelled_fixture_based() -> None:
    text = demo_text()
    assert "Independently built prototype. Not affiliated with any vendor's or real company's systems." in text
    assert "every number shown is fixture-based" in text
    assert "Synthetic tenants, offline, every number is from fixtures." in text
    shown = [line for line in text.split("\n") if line.startswith(("You'll see", "Precision"))]
    numbered = [line for line in shown if re.search(r"\d+%|\b\d+ findings\b|\d+-case", line)]
    assert numbered, "the numbered claims are found"
    for line in numbered:
        assert "fixture-based" in line, line
