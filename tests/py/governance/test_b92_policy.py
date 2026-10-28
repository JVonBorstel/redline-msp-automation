"""B-92 AI policy, acceptable use and DLP mapping: three short pages that match the governance map and the code.

Acceptance ids B92-1 to B92-3 are defined in specs/B-92.md. The pages are read as committed; the map table is read
from docs/map/05-governance.md section 1, the never-automate list from governance/never-automate.json and the
floors and the hosted refusal from the B-55 code, so a change on either side fails here until both agree.
Run: uv run --frozen pytest -p no:cacheprovider tests/py/governance -o addopts=
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.gateway.gateway import HOSTED_PROVIDERS, HOSTED_REFUSED_FROM
from core.guard.classify import DEFAULT_FLOOR, INDUSTRY_FLOOR, DataClass
from core.guard.redact_prompt import redact_prompt

ROOT = Path(__file__).resolve().parents[3]
GOV = ROOT / "governance"
POLICY = GOV / "AI_POLICY.md"
AUP = GOV / "ACCEPTABLE_USE.md"
DLP = GOV / "DLP_MAPPING.md"
PAGES = (POLICY, AUP, DLP)
LABELLED = (*PAGES, ROOT / "specs" / "B-92.md", ROOT / "docs" / "changes" / "B-92.md")
MAP = ROOT / "docs" / "map" / "05-governance.md"
NEVER = GOV / "never-automate.json"

MAX_WORDS = 1200
MAX_LINES = 120
CLASSES = tuple(f"DC-{n}" for n in range(7))
MAP_COLUMNS = (
    "May enter a local model prompt?",
    "May enter a hosted model prompt?",
    "May enter the audit log?",
)
INDEX_COLUMN = "May enter a retrieval index?"
SYNTHETIC = "Synthetic data only."
NOT_LEGAL = "Not legal advice."
PATH = re.compile(r"`((?:core|config|governance|levers|docs|tests|specs|map|workflows|evals)/[^`\s*]+)`")


# ---------- parsing (pure functions, tested on a bad page below) ----------


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The body of the '## <heading>' section, up to the next '## ' heading."""
    match = re.search(rf"(?ms)^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text)
    assert match, f"no section '## {heading}'"
    return match.group(1)


def first_table(text: str) -> tuple[list[str], list[list[str]]]:
    """Header cells and body rows of the first Markdown table in ``text``, cells stripped."""
    lines = [ln for ln in text.splitlines() if ln.startswith("|")]
    assert len(lines) >= 2, "no table"
    cells = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    header, body = cells[0], cells[1:]
    body = [row for row in body if not all(re.fullmatch(r":?-{3,}:?", c) for c in row)]
    return header, body


def class_table(text: str) -> dict[str, dict[str, str]]:
    """Class id (``DC-n``, backticks removed) -> {column header: cell}."""
    header, body = first_table(text)
    table: dict[str, dict[str, str]] = {}
    for row in body:
        assert len(row) == len(header), f"row has {len(row)} cells, header has {len(header)}: {row}"
        table[row[0].strip("`")] = dict(zip(header, row, strict=True))
    return table


def map_table() -> dict[str, dict[str, str]]:
    return class_table(section(read(MAP), "1. Data classification for MSP AI work"))


def dlp_table(text: str | None = None) -> dict[str, dict[str, str]]:
    return class_table(section(text if text is not None else read(DLP), "1. The mapping"))


def mismatches(dlp: dict[str, dict[str, str]], gov: dict[str, dict[str, str]]) -> list[str]:
    """Every cell where the DLP page differs from the governance map (classes, names and the three map columns)."""
    problems = []
    if list(dlp) != list(gov):
        problems.append(f"classes differ: {list(dlp)} vs {list(gov)}")
    for dc in gov:
        for column in ("Class", *MAP_COLUMNS):
            mine, theirs = dlp.get(dc, {}).get(column), gov[dc].get(column)
            if mine != theirs:
                problems.append(f"{dc} {column!r}: {mine!r} != map {theirs!r}")
    return problems


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][\w'.-]*", text))


def never_entries() -> list[dict[str, object]]:
    entries = json.loads(read(NEVER))["entries"]
    assert isinstance(entries, list)
    return entries


# ---------- B92-1: two pages each, the seven classes and the never-automate list ----------


@pytest.mark.parametrize("page", [POLICY, AUP], ids=lambda p: p.name)
def test_b92_1_policy_and_acceptable_use_fit_on_two_pages(page: Path) -> None:
    text = read(page)
    assert words(text) <= MAX_WORDS, f"{page.name}: {words(text)} words"
    assert len(text.splitlines()) <= MAX_LINES, f"{page.name}: {len(text.splitlines())} lines"


def too_long(text: str) -> bool:
    return words(text) > MAX_WORDS or len(text.splitlines()) > MAX_LINES


def labelled(text: str) -> bool:
    head = "\n".join(text.splitlines()[:10])
    return SYNTHETIC in head and NOT_LEGAL in head


def test_b92_1_the_length_check_catches_a_long_page() -> None:
    assert too_long("word " * (MAX_WORDS + 1))
    assert too_long("short\n" * (MAX_LINES + 1))
    assert not too_long(read(POLICY)) and not too_long(read(AUP))


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_b92_1_every_page_references_dc0_to_dc6(page: Path) -> None:
    text = read(page)
    assert [dc for dc in CLASSES if not re.search(rf"\b{dc}\b", text)] == []


@pytest.mark.parametrize("page", [POLICY, AUP], ids=lambda p: p.name)
def test_b92_1_policy_and_acceptable_use_name_the_never_automate_list(page: Path) -> None:
    assert "`governance/never-automate.json`" in read(page)


def test_b92_1_acceptable_use_lists_every_never_automate_entry() -> None:
    text = section(read(AUP), "Never ask AI to do these (the never-automate list)")
    listed = re.findall(r"^- `(W-[A-Z0-9]+-\d{2})` ", text, re.M)
    assert listed == [str(e["inventory_id"]) for e in never_entries()]


def test_b92_1_the_policy_entry_count_matches_the_file() -> None:
    pattern = r"`governance/never-automate.json` lists the work that stays with people: (\d+) entries"
    count = re.search(pattern, read(POLICY))
    assert count and int(count.group(1)) == len(never_entries())


def test_b92_1_the_policy_floor_sentence_matches_the_code() -> None:
    text = read(POLICY)
    assert "dental DC-4; financial, RIA, legal, accounting and other DC-5; no client record DC-5" in text
    assert INDUSTRY_FLOOR["dental"] is DataClass.DC4 and DEFAULT_FLOOR is DataClass.DC5
    dc5 = {k for k, v in INDUSTRY_FLOOR.items() if v is DataClass.DC5}
    assert dc5 == {"financial", "ria", "legal", "accounting", "other"}


# ---------- B92-2: the DLP table matches the governance map and the code ----------


def test_b92_2_the_map_table_still_has_the_columns_this_test_compares() -> None:
    gov = map_table()
    assert list(gov) == list(CLASSES)
    assert all(column in gov["DC-0"] for column in MAP_COLUMNS)


def test_b92_2_dlp_mapping_matches_governance_map_section_1_exactly() -> None:
    assert mismatches(dlp_table(), map_table()) == []


def test_b92_2_the_comparison_catches_a_changed_cell() -> None:
    row = "| `DC-4` | PHI (dental and other healthcare clients) | "
    text = read(DLP).replace(row + "only if", row + "yes, if", 1)
    assert text != read(DLP)
    assert any("DC-4" in p and "local" in p for p in mismatches(dlp_table(text), map_table()))


def test_b92_2_every_class_has_an_index_rule_and_dc6_never() -> None:
    dlp = dlp_table()
    assert all(dlp[dc][INDEX_COLUMN] for dc in CLASSES)
    assert dlp["DC-6"][INDEX_COLUMN] == "**never**"
    assert "This column is derived, not copied" in read(DLP)


def test_b92_2_the_floor_table_matches_industry_floor_in_code() -> None:
    _, body = first_table(section(read(DLP), "2. The unknown-text floor per client industry"))
    page = {row[0]: DataClass.parse(row[1]) for row in body}
    expected: dict[str, DataClass] = {**INDUSTRY_FLOOR, "no client record": DEFAULT_FLOOR}
    assert page == expected


def test_b92_2_the_enforced_rows_match_the_code() -> None:
    text = section(read(DLP), "3. What the code enforces today")
    assert "DC-4 and DC-5 text is refused on a hosted route" in text
    assert HOSTED_REFUSED_FROM is DataClass.DC4 and HOSTED_PROVIDERS == frozenset({"azure_openai", "anthropic"})
    models = json.loads(read(ROOT / "config" / "models.json"))["providers"]
    assert [p for p in HOSTED_PROVIDERS if models[p]["enabled"]] == []
    secret = "pass" + "word is Synthetic#2026x"  # split so this file does not itself look like a disclosure
    assert "DC-6 text is blocked" in text and redact_prompt(secret).blocked


# ---------- B92-3: labels on every page ----------


@pytest.mark.parametrize("page", LABELLED, ids=lambda p: p.name if p.parent.name != "changes" else "changes-" + p.name)
def test_b92_3_every_page_carries_the_synthetic_and_not_legal_advice_labels(page: Path) -> None:
    head = "\n".join(read(page).splitlines()[:10])
    assert SYNTHETIC in head and NOT_LEGAL in head


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_b92_3_every_page_starts_with_a_status_line(page: Path) -> None:
    lines = [ln for ln in read(page).splitlines() if ln.strip()]
    assert lines[0].startswith("# ") and lines[1].startswith("Status: **document-only**")


# ---------- STD-DC: cited paths and ids resolve ----------


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_b92_std_dc_cited_paths_exist(page: Path) -> None:
    paths = PATH.findall(read(page))
    assert paths, page.name
    assert [p for p in paths if not (ROOT / p.rstrip("/")).exists()] == []


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_b92_std_dc_cited_controls_and_work_items_exist(page: Path) -> None:
    text = read(page)
    controls_raw = json.loads(read(ROOT / "map" / "controls.json"))
    controls = {c["id"] for c in (controls_raw["controls"] if isinstance(controls_raw, dict) else controls_raw)}
    inventory = {w["id"] for w in json.loads(read(ROOT / "map" / "inventory.json"))}
    assert sorted(set(re.findall(r"\bC-\d{2}\b", text)) - controls) == []
    assert sorted(set(re.findall(r"\bW-[A-Z0-9]+-\d{2}\b", text)) - inventory) == []


# ---------- honesty: unverified items are marked, and bad input is caught ----------


UNVERIFIED_TOPICS = (
    "review cycle",
    "consequence for breaking the policy",
    "notice duties",
    "Colorado AI Act",
    "who holds the owner and approver roles",
)


def missing_topics(text: str) -> list[str]:
    """Topics that are not named in the policy's own Unverified section, or have no UNVERIFIED mark in the page."""
    body = section(text, "7. Unverified")
    return [t for t in UNVERIFIED_TOPICS if t not in body or "UNVERIFIED" not in text]


def test_b92_policy_marks_what_it_cannot_verify() -> None:
    text = read(POLICY)
    assert missing_topics(text) == []
    # the inline marks sit next to the claims they hedge
    assert re.search(r"review cycle is set in the repo", text) and re.search(r"notice duties are UNVERIFIED", text)
    assert re.search(r"consequence is the MSP's own to set \(UNVERIFIED", text)


def test_b92_the_unverified_check_catches_a_dropped_topic() -> None:
    text = read(POLICY).replace("Colorado AI Act", "state AI law")
    assert missing_topics(text) == ["Colorado AI Act"]


def test_b92_cited_symbols_exist() -> None:
    from core.guard.detect import detect_injection
    from core.guard.wrap import wrap_untrusted
    from core.levers.registry import NeverAutomate
    from core.levers.runner import LeverRunner

    assert callable(LeverRunner.pause) and callable(detect_injection) and callable(wrap_untrusted)
    assert callable(NeverAutomate.check)
    models = json.loads(read(ROOT / "config" / "models.json"))["providers"]
    assert {p: models[p]["enabled"] for p in ("azure_openai", "anthropic")} == {
        "azure_openai": False,
        "anthropic": False,
    }
    text = read(POLICY)
    for cited in (
        "LeverRunner.pause",
        "detect_injection",
        "core/guard/wrap.py",
        "core/guard/detect.py",
        "core/levers/registry.py",
    ):
        assert cited in text, cited


def test_b92_the_policy_does_not_overclaim_model_processing() -> None:
    assert "only a schema field" in read(POLICY) and "model_processing" in section(
        read(DLP), "3. What the code enforces today"
    )
    assert "model_processing" in (ROOT / "adapters" / "binding.py").read_text(encoding="utf-8")


def test_b92_dc4_row_keeps_the_maps_covered_host_condition() -> None:
    cond = "only if the model host is covered"
    assert cond in map_table()["DC-4"]["May enter a local model prompt?"]
    assert cond in read(AUP)


def test_b92_labels_use_the_repos_standard_label() -> None:
    standard = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
    for page in PAGES:
        assert standard in read(page), page.name


def test_b92_the_never_automate_check_catches_a_dropped_entry() -> None:
    text = section(read(AUP), "Never ask AI to do these (the never-automate list)")
    dropped = "\n".join(ln for ln in text.splitlines() if not ln.startswith("- `W-IDM-04`"))
    listed = re.findall(r"^- `(W-[A-Z0-9]+-\d{2})` ", dropped, re.M)
    assert listed != [str(e["inventory_id"]) for e in never_entries()]


def test_b92_the_floor_comparison_catches_a_changed_floor() -> None:
    _, body = first_table(section(read(DLP), "2. The unknown-text floor per client industry"))
    page = {row[0]: DataClass.parse(row[1]) for row in body}
    page["dental"] = DataClass.DC5
    assert page != {**INDUSTRY_FLOOR, "no client record": DEFAULT_FLOOR}


def test_b92_the_path_check_catches_a_missing_path() -> None:
    assert PATH.findall("see `core/guard/no_such_file.py`") == ["core/guard/no_such_file.py"]
    assert not (ROOT / "core/guard/no_such_file.py").exists()
