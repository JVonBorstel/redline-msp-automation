"""Packaged demo (B-98): the whole end-to-end path in one command, offline, on synthetic data.

    uv run --frozen python tools/packaged_demo.py                 # fresh temp state folder, prints a short transcript
    uv run --frozen python tools/packaged_demo.py --state DIR     # DIR must be missing or empty
    uv run --frozen python tools/packaged_demo.py --list-steps

The story is one person at one client: Priya Nair (synthetic) at Contoso Dental, ticket T-3101. A ticket is triaged and
one registered lever is proposed; an injection ticket is flagged and gets no lever; the runner refuses the change with
no approval and with an approval that lacks the requester check; a lead approves with a recorded callback and the
change runs against the mock tenant; the affected person's notice is drafted (a person sends it); a lead pauses the
lever and the next call is denied; the audit chain verifies; one changed letter in a copy of the log is caught.

It drives the same commands as docs/DEMO.md (which also covers the PowerShell baseline check and the approval web
page, not run here) and writes only under the state folder. No network, no model download, no install, no cloud call:
the model is the deterministic mock. Every number printed is fixture-based. Exit 0 = every step passed, 1 = a step
failed, 2 = bad arguments.

Independently built prototype. Not affiliated with any vendor's or real company's systems.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LABEL = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
CLIENT = "contoso-dental"
PRIYA = "priya.nair@contosodental.example"
SAM = "sam.patel@contosodental.example"
PROPOSAL = re.compile(r"\bP-[0-9a-f]{12}\b")
MAX_LINE = 150

Result = tuple[bool, list[str]]


@dataclass
class Context:
    state: Path
    proposal: str = ""

    @property
    def audit_log(self) -> Path:
        return self.state / "audit" / f"{CLIENT}.jsonl"


def run(*args: str) -> tuple[int, str]:
    """One repo command as `python -m ...` from the repo root; (exit code, stdout + stderr). No shell."""
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    done = subprocess.run(  # noqa: S603 - fixed argv built from this file, local interpreter, no shell
        [sys.executable, "-m", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=100,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def pick(text: str, *needles: str) -> list[str]:
    """The first line containing each needle (stripped); a needle that is absent is reported as missing."""
    lines = [line.strip() for line in text.splitlines()]
    return [next((line for line in lines if n in line), f"(missing: {n})") for n in needles]


def reason(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")  # the audit path line precedes the JSON object
    try:
        return str(json.loads(text[start : end + 1]).get("reason", ""))
    except ValueError:
        return "(output was not JSON)"


# -- steps ---------------------------------------------------------------------------------------------------------


def step_registry(ctx: Context) -> Result:
    code, out = run("core.levers", "list")
    names = [line.split()[0] for line in out.splitlines() if line.strip() and not line.startswith(" ")]
    ok = code == 0 and len(names) >= 10 and "user.reset-mfa" in names
    return ok, [f"{len(names)} levers are registered; permissions, approval and dry-run live on each one.",
                *pick(out, "user.reset-mfa")]  # fmt: skip


def step_triage(ctx: Context) -> Result:
    code, out = run("workflows.triage", "T-3101", "--enqueue", "--state", str(ctx.state))
    found = PROPOSAL.search(out)
    ctx.proposal = found.group(0) if found else ""
    queued = next((line for line in out.splitlines() if line.startswith("queued:")), "")
    shown = pick(out, "Injection check:", "L1 one person:", "Before approval:")
    ok = code == 0 and bool(ctx.proposal) and "(pending)" in queued and not any(s.startswith("(missing") for s in shown)
    return ok, [queued.split(" in ")[0], *shown]


def step_injection(ctx: Context) -> Result:
    code, out = run("workflows.triage", "T-3129", "--state", str(ctx.state))
    shown = pick(out, "Injection check: FLAGGED", "Proposal: none")
    ok = code == 0 and not any(s.startswith("(missing") for s in shown)
    return ok, [*shown, "The detector is a tripwire; the control is that no lever exists for what the ticket asks."]


def _invoke(ctx: Context, *extra: str) -> tuple[int, str]:
    return run("core.levers", "--state", str(ctx.state), "invoke", "user.reset-mfa", "--as", "tech-ana", "--client",
               CLIENT, "-p", f"upn={PRIYA}", *extra)  # fmt: skip


def step_denials(ctx: Context) -> Result:
    code1, out1 = _invoke(ctx, "--execute")
    code2, out2 = _invoke(ctx, "--execute", "--approved-by", "lead-lee")
    r1, r2 = reason(out1), reason(out2)
    ok = code1 == 1 and code2 == 1 and "needs a lead approval record" in r1 and "(C-30)" in r2
    return ok, [
        f"no approval: denied, {r1}",
        f"approved but requester not verified: denied, {r2}",
        "Both denials are audited.",
    ]


def step_approve(ctx: Context) -> Result:
    from core.levers.models import Verification
    from core.queue.store import QueueError, open_queue

    verification = Verification.model_validate(
        {"method": "callback-on-file", "by": "lead-lee", "at": datetime.now(UTC), "ref": "number-on-file:psa-contact"}
    )
    try:
        decision = open_queue(ctx.state).decide(ctx.proposal, "lead-lee", True, verification)
    except QueueError as exc:
        return False, [f"refused: {exc}"]
    proposal = decision.proposal
    ok = proposal.status == "executed" and proposal.requested_by == "tech-ana"
    return ok, [
        f"{proposal.id} {proposal.status}: run as {proposal.requested_by}, approved by {proposal.decided_by},",
        "requester verified by callback on the number on file (the number itself is never recorded).",
        f"Applied to the mock tenant only (audit seq {decision.audit_seq}).",
    ]


def step_notice(ctx: Context) -> Result:
    code, out = run("workflows.notify", ctx.proposal, "--state", str(ctx.state))
    lines = [line for line in out.splitlines() if line.strip() and not line.startswith("draft:")]
    ok = code == 0 and bool(lines) and lines[0].startswith("Draft. A person reviews and sends this.")
    return ok, [*lines[:3], "(a person reads, edits and sends it; nothing is sent by software)"]


def step_pause(ctx: Context) -> Result:
    base = ("core.levers", "--state", str(ctx.state))
    c1, o1 = run(
        *base,
        "pause",
        "user.reset-mfa",
        "--client",
        CLIENT,
        "--as",
        "lead-lee",
        "--reason",
        "drill: suspected social engineering",
    )
    c2, o2 = run(*base, "invoke", "user.reset-mfa", "--as", "tech-ana", "--client", CLIENT, "-p", f"upn={SAM}")
    c3, o3 = run(*base, "resume", "user.reset-mfa", "--client", CLIENT, "--as", "lead-lee")
    denied = reason(o2)
    ok = c1 == 0 and c2 == 1 and c3 == 0 and "lever paused by lead-lee" in denied
    return ok, [
        "a lead pauses the lever for this client; no approval is needed to stop things.",
        f"next call: denied, {denied}",
        "resumed by the same lead; pause and resume are audited too.",
    ]


def step_verify(ctx: Context) -> Result:
    code, out = run("core.audit.verify", str(ctx.audit_log))
    shown = pick(out, "OK:")
    return code == 0 and shown[0].startswith("OK:"), [
        *shown,
        "Every call above, allowed or denied, wrote one hash-chained record.",
    ]


def step_tamper(ctx: Context) -> Result:
    copy_dir = ctx.state / "tamper-copy"
    copy_dir.mkdir()
    log = copy_dir / ctx.audit_log.name
    shutil.copy(ctx.audit_log, log)
    shutil.copy(ctx.audit_log.with_name(ctx.audit_log.name + ".head"), log.with_name(log.name + ".head"))
    text = log.read_text(encoding="utf-8")
    if '"approver":"lead-lee"' not in text:
        return False, ["the copy has no lead-lee approval to change"]
    log.write_text(text.replace('"approver":"lead-lee"', '"approver":"lead-leo"', 1), encoding="utf-8", newline="")
    code, out = run("core.audit.verify", str(log))
    shown = pick(out, "BROKEN at seq")
    return code == 1 and shown[0].startswith("BROKEN at seq"), [
        "one letter of the approver changed in a COPY of the log:",
        *shown,
    ]


def step_eval(ctx: Context) -> Result:
    code, out = run("evals.injection.report")
    shown = pick(out, "fixture-based", "Corpus:", "Precision:")
    ok = code == 0 and not any(s.startswith("(missing") for s in shown)
    return ok, [*shown, "Not a real-world number: the corpus was written alongside the rules (D-019)."]


STEPS: list[tuple[str, Callable[[Context], Result]]] = [
    ("The lever registry", step_registry),
    ("A ticket arrives and triage proposes one lever (T-3101)", step_triage),
    ("An injection ticket is flagged and gets no lever (T-3129)", step_injection),
    ("The runner refuses the change without approval and without the requester check", step_denials),
    ("A lead verifies by callback, approves, and the change runs on the mock tenant", step_approve),
    ("The affected person's notice is drafted", step_notice),
    ("A lead pauses the lever; the next call is denied; resume", step_pause),
    ("The audit chain verifies", step_verify),
    ("One changed letter is caught (on a copy)", step_tamper),
    ("Injection detector eval (fixture-based)", step_eval),
]

NOT_RUN = (
    "Not run here: the PowerShell baseline check (needs pwsh; docs/DEMO.md step 4), the approval web page",
    "(docs/DEMO.md step 6a) and anything against a real tenant, ticket or user. Nothing here is a production result.",
)


def _clip(line: str) -> str:
    return line if len(line) <= MAX_LINE else line[: MAX_LINE - 3] + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/packaged_demo.py", description="Run the packaged demo (offline, synthetic)."
    )
    parser.add_argument(
        "--state", type=Path, help="state folder; must be missing or empty (default: a new temp folder)"
    )
    parser.add_argument("--list-steps", action="store_true", help="print the step titles and exit")
    args = parser.parse_args(argv)
    if args.list_steps:
        for number, (title, _) in enumerate(STEPS, 1):
            print(f"{number}. {title}")
        return 0
    if args.state is None:
        state = Path(tempfile.mkdtemp(prefix="packaged-demo-"))
    else:
        state = args.state.resolve()
        if state.exists() and (not state.is_dir() or any(state.iterdir())):
            print(f"error: state folder {state} is not empty; give a new or empty folder", file=sys.stderr)
            return 2
        state.mkdir(parents=True, exist_ok=True)
    ctx = Context(state=state)
    started = time.monotonic()
    print("Packaged demo: offline, synthetic data, mock model, mock tenant.")
    print(LABEL)
    print(f"State folder: {state}")
    passed = 0
    for number, (title, step) in enumerate(STEPS, 1):
        print(_clip(f"[{number}/{len(STEPS)}] {title}"))
        try:
            ok, lines = step(ctx)
        except Exception as exc:  # noqa: BLE001 - a step failure is reported, then the run stops
            ok, lines = False, [f"{type(exc).__name__}: {exc}"]
        for line in lines:
            print(_clip(f"  {line}"))
        print("  PASS" if ok else "  FAILED")
        passed += ok
        if not ok:
            break
    seconds = time.monotonic() - started
    print(f"Packaged demo: {passed} of {len(STEPS)} steps passed in {seconds:.1f} s (every number is fixture-based).")
    for line in NOT_RUN:
        print(_clip(line))
    return 0 if passed == len(STEPS) else 1


if __name__ == "__main__":
    sys.exit(main())
