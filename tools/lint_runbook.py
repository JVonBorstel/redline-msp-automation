"""Runbook linter (B-59): read-only checks on the repo's runbooks, with a proposed fix for every finding.

    uv run --frozen python tools/lint_runbook.py                        # docs/RUNBOOKS.md and docs/runbooks/*.md
    uv run --frozen python tools/lint_runbook.py docs/runbooks/x.md     # named files
    uv run --frozen python tools/lint_runbook.py --as-of 2026-10-23 --json

Rules (each finding names one):
  missing-section       a required section is absent: purpose, prerequisites, steps, rollback, verification
  missing-owner         no `Owner: <role>` line and no Owner section with text
  missing-last-reviewed no `Last reviewed: YYYY-MM-DD` line
  bad-last-reviewed     the date is not a real date, or is after --as-of
  stale-review          the date is more than 365 days before --as-of
  broken-link           a markdown link to a file that does not exist
  missing-file          a backticked repo path (with a folder part, outside code fences) that does not exist
  secret                text that looks like a credential (the patterns of core/guard/classify.py, DC-6); never echoed
  unregistered-lever    a lever name (in a core.levers command or a backticked name in a registered family) that the
                        lever registry does not have

A finding's `proposal` is text for a person. This tool never edits a runbook. Exit codes: 0 clean, 1 findings,
2 bad input. Headings are matched by the words in SECTIONS, so a runbook may use a close synonym.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.guard.classify import DC6_PATTERNS  # noqa: E402

MAX_AGE_DAYS = 365

# section -> heading words that satisfy it (the heading, lower-cased, must start with one of them)
SECTIONS: dict[str, tuple[str, ...]] = {
    "purpose": ("purpose", "when this runbook", "scope"),
    "prerequisites": ("prerequisites", "before you start"),
    "steps": ("steps", "checklist", "procedure", "ir-"),
    "rollback": ("rollback", "roll back", "undo", "back out"),
    "verification": ("verification", "verify", "check"),
}
_PROPOSALS = {
    "purpose": "Add a `## Purpose` section: one or two sentences on when this runbook starts and what it achieves.",
    "prerequisites": "Add a `## Prerequisites` section: access, tools and approvals needed before step 1.",
    "steps": "Add a `## Steps` section: the numbered actions, in order.",
    "rollback": "Add a `## Rollback` section: how to undo the steps, or a sentence saying why they cannot be undone.",
    "verification": "Add a `## Verification` section: how a second person confirms the result.",
}
# the first path segment of things a runbook cites that exist only at run time
_RUNTIME_ROOTS = {".tmp", "build", "audit", ".venv"}
_FILE_EXT = {"md", "json", "jsonl", "py", "ps1", "psm1", "yml", "yaml", "txt", "toml", "sha256"}
_NOT_LEVER_SUFFIX = _FILE_EXT | {"example", "com", "org", "net", "local"}

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_OWNER = re.compile(r"^\s*[*_]*owner[*_]*\s*:\s*[*_]*\s*(\S.*)$", re.IGNORECASE)
_REVIEWED = re.compile(r"^\s*[*_]*last[ -]reviewed[*_]*\s*:\s*[*_]*\s*(\S.*)$", re.IGNORECASE)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_LEVER_CMD = re.compile(r"core\.levers\s+(?:invoke|pause|resume)\s+(\S+)")
_LEVER_NAME = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9][a-z0-9_-]*)+$")


class LintInputError(ValueError):
    """The request itself is unusable (unreadable file, bad date)."""


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str
    proposal: str


def _parse_date(value: str) -> date | None:
    if not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _scan(lines: list[str]) -> list[tuple[int, str, str]]:
    """Every line as (number, text, kind); kind is 'fence' for fence markers and fenced lines, else 'text'."""
    rows: list[tuple[int, str, str]] = []
    inside = False
    for number, text in enumerate(lines, start=1):
        if _FENCE.match(text):
            inside = not inside
            rows.append((number, text, "fence"))
        elif inside:
            rows.append((number, text, "fence"))
        else:
            rows.append((number, text, "text"))
    return rows


def _headings(rows: list[tuple[int, str, str]]) -> list[tuple[int, str, int]]:
    """(line, lower-cased heading text, index of its first body line) outside code fences."""
    found: list[tuple[int, str, int]] = []
    for number, text, kind in rows:
        match = _HEADING.match(text) if kind == "text" else None
        if match:
            found.append((number, match.group(2).strip("*_ ").lower(), number))
    return found


def _owner_given(lines: list[str], rows: list[tuple[int, str, str]], heads: list[tuple[int, str, int]]) -> bool:
    for _number, text, kind in rows:
        match = _OWNER.match(text) if kind == "text" else None
        if match and match.group(1).strip(" *_"):
            return True
    for index, (number, title, _) in enumerate(heads):
        if title.startswith("owner"):
            end = heads[index + 1][0] if index + 1 < len(heads) else len(lines) + 1
            if any(lines[i - 1].strip() for i in range(number + 1, end)):
                return True
    return False


def _path_candidate(token: str) -> str | None:
    """The repo-relative path a backticked token cites, or None when it is not a checkable citation."""
    if not token or any(c in token for c in " <>*{}$~|\"'()\\") or "://" in token or token.startswith(("/", "-")):
        return None
    clean = token.split("#", 1)[0].rstrip(".,;:")
    if not clean or clean.split("/", 1)[0] in _RUNTIME_ROOTS:
        return None
    suffix = clean.rsplit(".", 1)[-1] if "." in clean.rsplit("/", 1)[-1] else ""
    if "/" not in clean:
        return None  # a bare file name is ambiguous (it may sit in a folder the text names), so it is not checked
    return clean if clean.endswith("/") or suffix in _FILE_EXT else None


def _exists(target: str, repo: Path, here: Path) -> bool:
    for base in (repo, here):
        if (base / target).exists():
            return True
    return False


def lint_text(
    text: str,
    rel_path: str,
    *,
    repo: Path,
    levers: frozenset[str] | set[str],
    as_of: str,
    max_age_days: int = MAX_AGE_DAYS,
) -> list[Finding]:
    """Lint one runbook's text. `rel_path` is its repo-relative path (links resolve from its folder)."""
    today = _parse_date(as_of)
    if today is None:
        raise LintInputError("as_of must be a real YYYY-MM-DD date")
    lines = text.splitlines()
    rows = _scan(lines)
    heads = _headings(rows)
    here = (Path(repo) / rel_path).parent
    out: list[Finding] = []

    def add(line: int, rule: str, message: str, proposal: str) -> None:
        out.append(Finding(rel_path, line, rule, message, proposal))

    titles = [title for _, title, _ in heads]
    for section, words in SECTIONS.items():
        if not any(t.startswith(w) for t in titles for w in words):
            add(1, "missing-section", f"required section missing: {section}", _PROPOSALS[section])

    if not _owner_given(lines, rows, heads):
        add(
            1, "missing-owner", "no owner named", "Add a line `Owner: <role>` under the title (a role, never a person)."
        )

    reviewed: tuple[int, str] | None = None
    for number, line, kind in rows:
        match = _REVIEWED.match(line) if kind == "text" else None
        if match:
            reviewed = (number, match.group(1).strip(" *_"))
            break
    if reviewed is None:
        add(
            1,
            "missing-last-reviewed",
            "no last-reviewed date",
            "Add a line `Last reviewed: YYYY-MM-DD` under the title.",
        )
    else:
        number, raw = reviewed
        parsed = _parse_date(raw)
        if parsed is None or parsed > today:
            add(
                number,
                "bad-last-reviewed",
                "last-reviewed is not a real past date",
                "Write the date of the last real review as YYYY-MM-DD.",
            )
        elif (today - parsed).days > max_age_days:
            add(
                number,
                "stale-review",
                f"last reviewed {(today - parsed).days} days before {as_of} (limit {max_age_days})",
                "Re-read the runbook against current practice, fix it, and update the date.",
            )

    for number, line, kind in rows:
        if kind == "fence":
            continue
        for match in _LINK.finditer(line):
            target = match.group(1)
            if target.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            path = target.split("#", 1)[0].split("?", 1)[0]
            if path and not Path(os.path.normpath(here / path)).exists():
                add(number, "broken-link", f"link target does not exist: {path}", "Fix the link or remove it.")
        for match in _CODE_SPAN.finditer(line):
            token = match.group(1).strip()
            cited = _path_candidate(token)
            if cited is not None and not _exists(cited, Path(repo), here):
                add(
                    number,
                    "missing-file",
                    f"cited file does not exist: {cited}",
                    "Correct the path or remove the citation.",
                )
            if _LEVER_NAME.fullmatch(token) and token.rsplit(".", 1)[-1] not in _NOT_LEVER_SUFFIX:
                family = token.split(".", 1)[0]
                if token not in levers and any(name.startswith(family + ".") for name in levers):
                    add(
                        number,
                        "unregistered-lever",
                        f"lever not in the registry: {token}",
                        "Name a registered lever (`python -m core.levers list`) or describe the step in words.",
                    )

    for number, line, _kind in rows:
        for match in _LEVER_CMD.finditer(line):
            name = match.group(1).strip("`'\"")
            if name.startswith("<") or name in levers:
                continue
            add(number, "unregistered-lever", f"lever not in the registry: {name}", "Use a registered lever name.")
        if any(p.search(line) for p in DC6_PATTERNS):
            add(
                number,
                "secret",
                "text that looks like a credential (value not shown)",
                "Remove it and rotate it if it was ever real; refer to the secret by its vault name.",
            )
    return sorted(out, key=lambda f: (f.line, f.rule, f.message))


def default_targets(repo: Path) -> list[Path]:
    """docs/RUNBOOKS.md and every docs/runbooks/*.md, sorted."""
    repo = Path(repo)
    found = sorted((repo / "docs" / "runbooks").glob("*.md"))
    index = repo / "docs" / "RUNBOOKS.md"
    return ([index] if index.is_file() else []) + found


def _load_levers() -> frozenset[str]:
    from core.levers.registry import Registry

    return frozenset(Registry.load().names())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lint_runbook", description="Read-only runbook linter (B-59).")
    parser.add_argument(
        "files", nargs="*", type=Path, help="runbooks to lint (default: docs/RUNBOOKS.md and docs/runbooks/*.md)"
    )
    parser.add_argument("--repo", type=Path, default=REPO, help=argparse.SUPPRESS)
    parser.add_argument("--as-of", default=None, help="ISO date for the review-age check (default: today, UTC)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    as_of = args.as_of or date.today().isoformat()
    try:
        if _parse_date(as_of) is None:
            raise LintInputError("--as-of must be a real YYYY-MM-DD date")
        targets = [Path(f).resolve() for f in args.files] or default_targets(repo)
        levers = _load_levers()
        findings: list[Finding] = []
        for path in targets:
            if not path.is_file():
                raise LintInputError(f"not a file: {path.name}")
            try:
                rel = path.relative_to(repo).as_posix()
                text = path.read_text(encoding="utf-8")
            except (ValueError, OSError, UnicodeDecodeError) as exc:
                raise LintInputError(f"cannot read {path.name}: {type(exc).__name__}") from exc
            findings.extend(lint_text(text, rel, repo=repo, levers=levers, as_of=as_of))
    except LintInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"files": len(targets), "as_of": as_of, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        for f in findings:
            print(f"{f.path}:{f.line}: {f.rule}: {f.message}")
            print(f"    proposal: {f.proposal}")
        print(f"{len(targets)} file(s), {len(findings)} finding(s) (read-only; no file was changed)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
