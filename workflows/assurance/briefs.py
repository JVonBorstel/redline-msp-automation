"""B-97 checker for the tech radar, leadership brief, 30/60/90 plan and automation framework review.

The four pages are written by a person. What a script can hold them to:

* every claim line (a table row or a list item) cites at least one real file, or a real test as ``path::test_name``,
  and no citation is broken (B97-1, and the Q-07 rule of B97-3 that the pages rest on this repo, not on outside facts);
* a radar ring is one of adopt, trial, assess, hold, every row names its evidence, and an ``adopt`` row names an eval
  report or a test of this repo (B97-1);
* the ranking table in the leadership brief is the one generated from the intake scores (B97-2);
* the framework review has its five questions and makes no claim about any real script (B97-3);
* no page promises a result, quotes a price, or leaves out the honest labels.

A citation proves the file or test exists and a test is defined there. It does not prove the cited text says what
the sentence says; a person reads the pages.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.paths import REPO_ROOT
from workflows.assurance.intake import load_intakes, rank
from workflows.assurance.render import INTAKE_DIR, ordered, score_examples
from workflows.assurance.roi import load_roi

PAGES = {
    "radar": "governance/TECH_RADAR.md",
    "brief": "docs/LEADERSHIP_BRIEF.md",
    "plan": "docs/PLAN_30_60_90.md",
    "review": "docs/AUTOMATION_FRAMEWORK_REVIEW.md",
}
RINGS = ("adopt", "trial", "assess", "hold")
LABEL = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
RANK_BEGIN = "<!-- ranking:begin -->"
RANK_END = "<!-- ranking:end -->"
REVIEW_QUESTIONS = ("Rights", "Secrets", "Idempotency", "Logging", "Owner")
WINDOWS = ("## Days 1 to 30", "## Days 31 to 60", "## Days 61 to 90")
_PATH_EXT = {"md", "json", "py", "ps1", "yml", "yaml", "jsonl", "txt", "toml", "lock", "csv"}
_TOKEN = re.compile(r"`([^`\n]+)`")
_PROMISES = (
    (re.compile(r"\$"), "a money figure"),
    (re.compile(r"\bguarantee[sd]?\b", re.I), "the word guarantee"),
    (re.compile(r"\bwill (save|reduce|cut|deliver|increase|improve|eliminate|pay)\b", re.I), "a promised result"),
    (
        re.compile(r"\b\d+(\.\d+)?\s?% (saving|savings|reduction|improvement|fewer|faster)", re.I),
        "a promised percentage",
    ),
    (re.compile(r"\b(proven|production-ready)\b", re.I), "a claim of proof or production use"),
)


@dataclass(frozen=True)
class Cite:
    path: str
    test: str | None


@dataclass(frozen=True)
class RadarRow:
    area: str
    candidate: str
    ring: str
    evidence: str
    not_shown: str


def _resolve(token: str, root: Path) -> Cite | str | None:
    """A Cite when the backticked token names a real file or folder (or a test defined in one), an error string when it
    looks like a citation but is not one, None when it is not a path at all (a lever name, a rule id)."""
    base, _, test = token.partition("::")
    if not re.fullmatch(r"[\w./\\:-]+", base):
        return None
    ext = base.rsplit(".", 1)[-1].lower() if "." in base.rsplit("/", 1)[-1] else ""
    if "/" not in base and "\\" not in base and ext not in _PATH_EXT:
        return None
    parts = base.replace("\\", "/").split("/")
    if base.startswith(("/", "\\")) or ":" in base or ".." in parts:
        return f"{token}: not a path inside the repo"
    target = (root / base).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        return f"{token}: not a path inside the repo"
    if not target.exists():
        return f"{token}: no such file or folder"
    if test:
        if not target.is_file() or not re.search(
            rf"^\s*(async\s+)?def {re.escape(test)}\(", target.read_text(encoding="utf-8"), re.M
        ):
            return f"{token}: no test of that name is defined in that file"
    return Cite(base.replace("\\", "/"), test or None)


def cited(text: str, root: Path = REPO_ROOT) -> list[Cite]:
    """Every valid citation in the text."""
    found = (_resolve(m.group(1), root) for m in _TOKEN.finditer(text))
    return [c for c in found if isinstance(c, Cite)]


def broken(text: str, root: Path = REPO_ROOT) -> list[str]:
    found = (_resolve(m.group(1), root) for m in _TOKEN.finditer(text))
    return [c for c in found if isinstance(c, str)]


def claim_lines(text: str) -> list[tuple[int, str]]:
    """Table rows (not the header or separator) and list items outside code fences, with 1-based line numbers."""
    lines = text.split("\n")
    out: list[tuple[int, str]] = []
    fenced = False
    for n, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        stripped = line.strip()
        if stripped.startswith("|"):
            if re.fullmatch(r"\|[\s:|-]+\|", stripped):
                continue
            nxt = lines[n].strip() if n < len(lines) else ""
            if re.fullmatch(r"\|[\s:|-]+\|", nxt):
                continue  # header row
            out.append((n, line))
        elif re.match(r"\s*([-*]|\d+\.)\s+\S", line):
            out.append((n, line))
    return out


def check_citations(key: str, text: str, root: Path = REPO_ROOT) -> list[str]:
    problems: list[str] = []
    for n, line in claim_lines(text):
        bad = broken(line, root)
        problems += [f"{PAGES.get(key, key)}:{n}: broken citation {b}" for b in bad]
        if not bad and not cited(line, root):
            problems.append(f"{PAGES.get(key, key)}:{n}: claim line cites no file or test")
    return problems


def check_promises(key: str, text: str) -> list[str]:
    plain = re.sub(r"```.*?```", "", text, flags=re.S)
    out: list[str] = []
    for n, line in enumerate(plain.split("\n"), start=1):
        out += [f"{PAGES.get(key, key)}: line {n} has {what}" for rx, what in _PROMISES if rx.search(line)]
    return out


def check_labels(key: str, text: str) -> list[str]:
    name = PAGES.get(key, key)
    problems = [
        f"{name}: missing {what}"
        for ok, what in (
            (LABEL in text, "the prototype label"),
            ("fixture-based" in text, "the word fixture-based"),
            ("UNVERIFIED" in text, "an UNVERIFIED marker"),
            (
                bool(re.search(r"^## (Not shown|Unverified|Limits)", text, re.M)),
                "a Not shown, Unverified or Limits section",
            ),
        )
        if not ok
    ]
    return problems


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_radar(text: str) -> list[RadarRow]:
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.startswith("| Area")), None)
    if start is None:
        return []
    rows: list[RadarRow] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = _cells(line)
        if len(cells) == 5:
            rows.append(RadarRow(*cells))
        else:
            rows.append(RadarRow(cells[0], "", "malformed", "", ""))
    return rows


def check_radar(text: str, root: Path = REPO_ROOT) -> list[str]:
    rows = parse_radar(text)
    if not rows:
        return ["radar: no table with an Area column"]
    problems: list[str] = []
    for row in rows:
        who = f"radar row {row.candidate or row.area!r}"
        if row.ring not in RINGS:
            problems.append(f"{who}: ring {row.ring!r} is not one of {', '.join(RINGS)}")
        cites = cited(row.evidence, root)
        if not cites:
            problems.append(f"{who}: no evidence cited")
        elif row.ring == "adopt" and not any(c.path.startswith(("evals/", "tests/py/")) for c in cites):
            problems.append(f"{who}: adopt needs an eval report or a test of this repo as evidence")
        if not row.not_shown.strip():
            problems.append(f"{who}: the Not shown cell is empty")
    return problems


def ranking_block(text: str) -> str:
    """The generated block as found in the page (markers included), or an empty string."""
    start, end = text.find(RANK_BEGIN), text.find(RANK_END)
    if start < 0 or end < start:
        return ""
    return text[start : end + len(RANK_END)]


def render_ranking(root: Path = REPO_ROOT) -> str:
    scored = score_examples(root)
    position = {s.id: n for n, s in enumerate(rank(scored), start=1)}
    reports = {r.id: r.report for r in load_roi(root / "governance" / "roi_fixtures.json")}
    intakes = {i.id: i for i in load_intakes(root / INTAKE_DIR)}
    lines = [
        RANK_BEGIN,
        "| Rank | Intake | Idea | Risk class | Hours per month (assumed) | Acceptance (fixture) | Priority | Verdict "
        "| Source |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in ordered(scored):
        acc = "-" if s.acceptance is None else f"{s.acceptance * 100:.1f}%"
        pri = "-" if s.priority is None else f"{s.priority:.2f}"
        source = f"`{INTAKE_DIR}/{s.id}.json`"
        report = reports.get(intakes[s.id].roi_row or "")
        if report:
            source += f", `{report}`"
        lines.append(
            f"| {position.get(s.id, '-')} | {s.id} | {s.title.replace('|', '/')} | {s.risk_class} "
            f"| {s.hours_per_month:.2f} | {acc} | {pri} | {s.verdict} | {source} |"
        )
    lines.append(RANK_END)
    return "\n".join(lines)


def check_brief(text: str, root: Path = REPO_ROOT) -> list[str]:
    block = ranking_block(text)
    if not block:
        return ["brief: the ranking block (between the ranking markers) is missing"]
    if block != render_ranking(root):
        return ["brief: the ranking table differs from the intake scores; run: briefs ranking --write"]
    return []


def write_ranking(root: Path = REPO_ROOT) -> bool:
    """Replace the ranking block in the leadership brief; True when the file changed."""
    path = root / PAGES["brief"]
    text = path.read_text(encoding="utf-8")
    block = ranking_block(text)
    if not block:
        raise ValueError("the leadership brief has no ranking markers")
    new = text.replace(block, render_ranking(root))
    if new == text:
        return False
    path.write_bytes(new.encode("utf-8"))
    return True


def check_review(text: str, root: Path = REPO_ROOT) -> list[str]:
    problems = [
        f"review: the checklist question {q!r} is missing"
        for q in REVIEW_QUESTIONS
        if not re.search(rf"^### \d\. {q}\b", text, re.M)
    ]
    for needle in ("Q-07", "D6-26"):
        if needle not in text:
            problems.append(f"review: does not cite {needle}")
    if "no claim about any real script" not in text.lower():
        problems.append("review: must say it makes no claim about any real script")
    if re.search(r"\.(ps1|bat|cmd|vbs|sh)\b", re.sub(r"`[^`]*`", "", text)):
        problems.append("review: names something that looks like a script file")
    if "Review record" not in text or not re.search(r"\|\s*Script\s*\|", text):
        problems.append("review: the blank review record is missing")
    return problems


def _roadmap_ids(root: Path) -> set[str]:
    data = json.loads((root / "map" / "roadmap.json").read_text(encoding="utf-8"))
    return {item["id"] for wave in data["waves"] for item in wave.get("items", [])}


def check_plan(text: str, root: Path = REPO_ROOT) -> list[str]:
    problems: list[str] = []
    for heading in WINDOWS:
        match = re.search(rf"^{re.escape(heading)}\b.*?(?=^## |\Z)", text, re.M | re.S)
        if not match:
            problems.append(f"plan: missing section {heading!r}")
        elif "Exit check" not in match.group(0):
            problems.append(f"plan: {heading!r} has no Exit check")
    known = _roadmap_ids(root)
    problems += [f"plan: {i} is not a roadmap item" for i in sorted(set(re.findall(r"\bB-\d{2}\b", text)) - known)]
    if "proposal" not in text.lower():
        problems.append("plan: must say it is a proposal")
    return problems


def check_all(root: Path = REPO_ROOT) -> list[str]:
    problems: list[str] = []
    specific = {
        "radar": check_radar,
        "brief": check_brief,
        "plan": check_plan,
        "review": check_review,
    }
    for key, rel in PAGES.items():
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}: page is missing")
            continue
        text = path.read_text(encoding="utf-8")
        problems += check_labels(key, text)
        problems += check_promises(key, text)
        problems += check_citations(key, text, root)
        problems += specific[key](text, root)
    return problems
