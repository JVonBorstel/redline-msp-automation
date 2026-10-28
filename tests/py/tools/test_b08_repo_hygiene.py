"""B-08 GitHub organization files (specs/B-08.md: B08-1 to B08-3). Offline: reads the committed files only.

B-08 is an owner item: the owner committed the labels file, the issue form, the PR template and CODEOWNERS. These tests
check that the files exist and contain what docs/map/04-repo-organization.md section 6 promised. Milestones, issues
#3-#29 (B08-4) and the labels as applied on GitHub live on GitHub and cannot be checked offline. Known gap, kept
visible: the `phase:0` .. `phase:11` labels of section 6.1 are not in `.github/labels.json`.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/tools/test_b08_repo_hygiene.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GH = REPO / ".github"
ORG = REPO / "docs" / "map" / "04-repo-organization.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(REPO).as_posix()} is missing"
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n### ", start + len(heading))
    return text[start : end if end > 0 else len(text)]


def test_b08_1_every_listed_label_exists_with_its_description() -> None:
    table = _section(_read(ORG), "### 6.1 Labels")
    promised = dict(re.findall(r"^\| `([a-z]+:[\w-]+)` \| (.+?) \|$", table, flags=re.M))
    promised = {name: desc for name, desc in promised.items() if not name.startswith("phase:")}
    assert len(promised) == 35, sorted(promised)
    labels = {entry["name"]: entry["description"] for entry in json.loads(_read(GH / "labels.json"))}
    missing = sorted(set(promised) - set(labels))
    assert not missing, f"labels in 6.1 but not in .github/labels.json: {missing}"
    wrong = sorted(n for n, d in promised.items() if labels[n] != d)
    assert not wrong, f"labels whose description differs from 6.1: {wrong}"


def test_b08_2_issue_form_requires_every_field_and_blank_issues_are_off() -> None:
    assert re.search(r"^blank_issues_enabled:\s*false\s*$", _read(GH / "ISSUE_TEMPLATE" / "config.yml"), flags=re.M)
    form = _read(GH / "ISSUE_TEMPLATE" / "work-item.yml")
    blocks = re.split(r"\n  - type: ", form)
    required = {
        m.group(1)
        for block in blocks
        if (m := re.search(r"^\w+\n    id: (\w+)", block)) and re.search(r"required: true", block)
    }
    for field in ("roadmap", "inventory", "impact", "controls", "acceptance", "owns", "risk", "size", "synthetic"):
        assert field in required, f"issue form field {field!r} is not required"
    assert "L1 one person at one client" in form and "L4 the community" in form


def test_b08_3_pr_template_carries_the_roadmap_id_and_the_four_trace_lines() -> None:
    text = _read(GH / "pull_request_template.md")
    assert "## Roadmap item" in text and "B-nn" in text
    for line in ("L1 one person at one client:", "L2 the client business:", "L3 the MSP:", "L4 the community:"):
        assert line in text, line
    assert "touches only the paths the roadmap item owns" in text


def test_b08_3_codeowners_names_every_guardrail_and_permission_path() -> None:
    owners = {
        parts[0]
        for line in _read(GH / "CODEOWNERS").splitlines()
        if (parts := line.split()) and not line.startswith("#")
    }
    target = _section(_read(ORG), "### 6.4 CODEOWNERS")
    promised = set(re.findall(r"(?<!\S)(\*|/[\w.-]+(?:/[\w.-]*)*)(?=\s)", target.split("```")[1]))
    # The guardrail paths (C-23: scripts/hooks/pre-commit) and the permission paths need the owner's review.
    assert promised >= {"*", "/scripts/", "/core/audit/", "/governance/", "/.github/"}
    missing = sorted(promised - owners)
    assert not missing, f"paths in 6.4 with no CODEOWNERS line: {missing}"
