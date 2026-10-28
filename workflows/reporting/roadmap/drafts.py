"""Render, write, verify and the command line for the B-73 drafts. Nothing here sends, posts or queues anything."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.paths import REPO_ROOT
from workflows.reporting.health.sources import digest, period_label
from workflows.reporting.roadmap.ai_policy import AIPolicyDraft, build_ai_policy
from workflows.reporting.roadmap.model import Roadmap, RoadmapError, VerifyError
from workflows.reporting.roadmap.recommend import DEFAULT_PRICE_LIST, build_roadmap

DEFAULT_OUT_DIR = REPO_ROOT / "build" / "client-roadmap"
CLIENTS = ("contoso-dental", "fabrikam-capital", "litware-legal")
BANNER = "DRAFT. Not sent. A person reviews this roadmap before it goes anywhere."
PROTOTYPE = "Independently built prototype. Not affiliated with any vendor's or real company's systems."
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Drafts:
    roadmap_md: Path
    roadmap_json: Path
    policy_md: Path
    sha256: str  # of the JSON record


def roadmap_to_dict(road: Roadmap) -> dict[str, Any]:
    data = asdict(road)
    data["kind"] = "technology-roadmap-draft"
    data["version"] = SCHEMA_VERSION
    return data


def _canonical(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def _num(value: int | float) -> str:
    return f"{value:,.0f}"


def render_roadmap(road: Roadmap) -> str:
    t = road.totals
    lines = [
        f"# DRAFT: technology roadmap for {road.display_name}, {period_label(road.period)}",
        "",
        f"**{BANNER}**",
        "",
        f"> {PROTOTYPE} Synthetic data only. Not legal advice. Every figure is {road.label}.",
        "",
        f"Generated on {road.generated_on}. Reviewed by: nobody yet. Amounts are in {road.currency}, from the "
        "prototype's invented price list and the client's licensing fixture; they are ranges, not quotes.",
        "",
        "## Summary",
        "",
        f"- Items: {t['items']}.",
        f"- One-time budget range: {_num(t['one_time_low'])} to {_num(t['one_time_high'])} {road.currency}.",
        f"- Yearly renewal range: {_num(t['per_year_low'])} to {_num(t['per_year_high'])} {road.currency} per year.",
        "- Effort is the work to do the item. Risk is what leaving the finding alone could cost. Both are stand-ins.",
    ]
    for gap in road.gaps:
        lines.append(f"- Not covered: {gap}.")
    category = ""
    for r in road.recommendations:
        if r.category != category:
            category = r.category
            lines += ["", f"## {category.capitalize()}"]
        b = r.budget
        lines += [
            "",
            f"### {r.title}",
            "",
            f"- Id: `{r.id}` (rule `{r.rule}`). Effort: **{r.effort}**. Risk: **{r.risk}**.",
            f"- Action: {r.action}",
            f"- Budget: {_num(b.low)} to {_num(b.high)} {road.currency} ({b.unit}). {b.basis}.",
            "- Findings this rests on:",
        ]
        for e in r.evidence:
            files = ", ".join(f"`{f.path}` (sha256 {f.sha256[:12]})" for f in e.files)
            lines.append(f"  - {e.source}: `{e.field}` = {e.value}; from {files}")
    lines += ["", f"*{road.label}. A person reviews, edits and decides what goes to the client.*", ""]
    return "\n".join(lines)


def render_policy(policy: AIPolicyDraft) -> str:
    return policy.text if policy.text.endswith("\n") else policy.text + "\n"


def verify_roadmap(road: Roadmap) -> None:
    """Every item cites a finding and every cited file still has the hash the draft recorded."""
    root = REPO_ROOT.resolve()
    for r in road.recommendations:
        if not r.evidence:
            raise VerifyError(f"{r.id}: no cited finding")
        for e in r.evidence:
            if not e.files:
                raise VerifyError(f"{r.id}: finding {e.field} cites no source file")
            for f in e.files:
                path = (REPO_ROOT / f.path).resolve()
                if root not in path.parents or not path.is_file():
                    raise VerifyError(f"{r.id}: cited file {f.path} is not in the repository")
                if digest(path) != f.sha256:
                    raise VerifyError(f"{r.id}: {f.path} has changed since the draft was made")


def create_drafts(
    client: str,
    period: str,
    *,
    generated_on: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    price_list: Path = DEFAULT_PRICE_LIST,
) -> Drafts:
    """Build everything first, then write three files under ``<out_dir>/<period>/``; a refused run writes nothing."""
    road = build_roadmap(client, period, generated_on=generated_on, price_list=price_list)
    verify_roadmap(road)
    policy = build_ai_policy(client, generated_on=generated_on)
    record = _canonical(roadmap_to_dict(road))
    folder = Path(out_dir) / period
    folder.mkdir(parents=True, exist_ok=True)
    paths = Drafts(
        folder / f"{client}.roadmap.draft.md",
        folder / f"{client}.roadmap.draft.json",
        folder / f"{client}.ai-policy.draft.md",
        hashlib.sha256(record).hexdigest(),
    )
    paths.roadmap_md.write_bytes(render_roadmap(road).encode("utf-8"))
    paths.roadmap_json.write_bytes(record)
    paths.policy_md.write_bytes(render_policy(policy).encode("utf-8"))
    return paths


def verify_draft(json_path: Path, *, price_list: Path = DEFAULT_PRICE_LIST) -> None:
    """Rebuild the roadmap from the sources and compare it, byte for byte, with the record and its Markdown."""
    path = Path(json_path)
    try:
        raw = path.read_bytes()
        meta = json.loads(raw)
        client, period, generated_on = meta["client"], meta["period"], meta["generated_on"]
        road = build_roadmap(client, period, generated_on=generated_on, price_list=price_list)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise VerifyError(f"cannot read the draft record: {type(exc).__name__}") from None
    except RoadmapError as exc:
        raise VerifyError(str(exc)) from None
    verify_roadmap(road)
    if _canonical(roadmap_to_dict(road)) != raw.replace(b"\r\n", b"\n"):
        raise VerifyError(f"{path.name} does not match what the sources give today")
    md = path.with_name(path.name.removesuffix(".json") + ".md")
    if md.exists() and md.read_bytes().replace(b"\r\n", b"\n") != render_roadmap(road).encode("utf-8"):
        raise VerifyError(f"{md.name} does not match its record")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m workflows.reporting.roadmap", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build", help="write the roadmap and AI-use policy drafts for a client")
    build.add_argument("client", nargs="?")
    build.add_argument("--all", action="store_true", help="every client with a roadmap fixture")
    build.add_argument("--period", required=True, help="YYYY-MM")
    build.add_argument("--generated-on", required=True, help="YYYY-MM-DD (never the clock)")
    build.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    check = sub.add_parser("verify", help="rebuild a draft record from its sources and compare")
    check.add_argument("draft", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "verify":
            verify_draft(args.draft)
            print(f"{args.draft.name}: matches its sources")
            return 0
        clients = CLIENTS if args.all else (args.client,)
        if clients == (None,):
            raise RoadmapError("give a client id or --all")
        for client in clients:
            made = create_drafts(client, args.period, generated_on=args.generated_on, out_dir=args.out_dir)
            print(f"{client}: DRAFT written, nothing sent: {made.roadmap_md.parent}")
        return 0
    except VerifyError as exc:
        print(f"MISMATCH: {exc}", file=sys.stderr)
        return 1
    except RoadmapError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
