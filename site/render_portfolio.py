"""Portfolio, Blueprint, Roadmap, Ideas and Proof pages. Content comes from content/*.json (written for the public);
roadmap and proof numbers come from data/roadmap.json and data/proof.json (read from the repo by stats.py).
Every value goes through esc(); there is no inline script."""

from __future__ import annotations

from typing import Any

from render import esc, pill, table

STATUS_PILL = {"built": "ok", "specced": "info", "planned": ""}
STATUS_LABEL = {"built": "built", "specced": "specced", "planned": "planned"}
PROJECT_PILL = {"live": "ok", "building": "info", "idea": ""}


def _stat(n: object, label: str) -> str:
    return f'<div class="card"><div class="stat">{esc(n)}</div><div class="stat-label">{esc(label)}</div></div>'


def _bar(counts: dict[str, int]) -> str:
    total = sum(counts.values()) or 1
    seg = "".join(
        f'<span class="seg {k}" style="width:{counts[k] / total * 100:.1f}%"></span>'
        for k in ("built", "specced", "planned")
        if counts[k]
    )
    label = f"{counts['built']} built, {counts['specced']} specced, {counts['planned']} planned"
    return f'<span class="bar" role="img" aria-label="{esc(label)}">{seg}</span>'


def page_portfolio(content: dict[str, Any]) -> tuple[str, str, str]:
    cards = []
    for p in content["projects"]:
        proof = "".join(
            f'<li><a href="{esc(x["href"])}">{esc(x["label"])}</a></li>'
            if x.get("href")
            else f"<li>{esc(x['label'])}</li>"
            for x in p.get("proof", [])
        )
        links = "".join(
            f'<li><a href="{esc(x["href"])}" rel="noopener">{esc(x["label"])}</a></li>' for x in p.get("links", [])
        )
        skills = "".join(f"<li>{esc(s)}</li>" for s in p.get("skills", []))
        cards.append(f"""<article class="card project" id="{esc(p["id"])}">
<p class="kicker">{esc(p["kicker"])} {pill(p["status"], PROJECT_PILL.get(p["status"], ""))}</p>
<h2>{esc(p["name"])}</h2><p>{esc(p["summary"])}</p>
<h3>Proof you can open</h3><ul>{proof}</ul>
{f"<h3>Links</h3><ul>{links}</ul>" if links else ""}
<h3>Skills shown</h3><ul class="chips">{skills}</ul></article>""")
    skills = "".join(
        f'<div class="card"><h3>{esc(s["area"])}</h3><p>{esc(s["detail"])}</p></div>' for s in content["skills"]
    )
    body = f"""
<h1>Portfolio</h1>
<p class="lede">{esc(content["intro"])}</p>
<h2 id="projects">Projects</h2>
<div class="grid">{"".join(cards)}</div>
<h2 id="skills">What the work shows</h2>
<div class="grid three">{skills}</div>
<p class="muted">More projects are added as they reach the same standard: a working demo, a list of what is real, and a
list of what is not.</p>
"""
    return ("portfolio", "Portfolio", body)


def page_blueprint(bp: dict[str, Any], proof: dict[str, Any]) -> tuple[str, str, str]:
    principles = "".join(
        f'<li class="card"><h3>{esc(p["title"])}</h3><p>{esc(p["text"])}</p>'
        f'<p class="small muted">Decision log: {esc(p["ref"])}</p></li>'
        for p in bp["principles"]
    )
    layers = table(
        ["Layer", "What it does"],
        [[f"<strong>{esc(x['name'])}</strong>", esc(x["text"])] for x in bp["layers"]],
        "The layers of the system",
    )
    flow = "".join(f"<li>{esc(s)}</li>" for s in bp["flow"])
    risk = table(
        ["Class", "Meaning"],
        [[f"<code>{esc(r['id'])}</code>", esc(r["text"])] for r in bp["risk_classes"]],
        "Risk classes",
    )
    body = f"""
<h1>Blueprint</h1>
<p class="lede">{esc(bp["lede"])}</p>
<p class="muted">{esc(proof["decisions"])} design decisions are written down in the project's decision log, each with the
reason, the alternatives and what would change it.</p>
<h2 id="principles">Ten rules the design will not break</h2>
<ol class="principles">{principles}</ol>
<h2 id="layers">Layers</h2>{layers}
<h2 id="path">The path of one change</h2><ol class="steps-plain">{flow}</ol>
<h2 id="risk">Risk classes</h2>{risk}
<p>See the rules working: <a href="approvals.html">approve, refuse and tamper</a>, <a href="levers.html">every lever</a>,
<a href="roadmap.html">what is built next</a>.</p>
"""
    return ("blueprint", "Blueprint", body)


def page_roadmap(rm: dict[str, Any]) -> tuple[str, str, str]:
    t = rm["totals"]
    stats = "".join(
        [
            _stat(t["items"], "planned work items"),
            _stat(len(rm["waves"]), "waves"),
            _stat(t["built"], "built (change note on main)"),
            _stat(t["specced"], "specced, not yet built"),
            _stat(t["planned"], "planned, no spec yet"),
        ]
    )
    waves = []
    for w in rm["waves"]:
        rows = [
            [
                f"<code>{esc(i['id'])}</code>",
                esc(i["title"]),
                esc(i["size"]),
                pill(STATUS_LABEL[i["status"]], STATUS_PILL[i["status"]]),
            ]
            for i in w["items"]
        ]
        c = w["counts"]
        open_attr = " open" if c["built"] < len(w["items"]) and c["built"] > 0 else ""
        waves.append(f"""<details class="wave" id="{esc(w["id"].lower())}"{open_attr}>
<summary><strong>{esc(w["id"])}: {esc(w["name"])}</strong>
<span class="small muted"> {c["built"]} of {len(w["items"])} built</span>{_bar(c)}</summary>
<p>{esc(w["goal"])}</p>{table(["Item", "What", "Size", "Status"], rows, w["name"])}</details>""")
    notnow = "".join(f"<li><code>{esc(n['id'])}</code> {esc(n['what'])}</li>" for n in rm["not_now"])
    body = f"""
<h1>Roadmap and upgrades</h1>
<p class="lede">Every piece of planned work, by wave, with its real status. Nothing here is a promise; the point is that the
plan, the specs and the code agree and can be checked.</p>
<p class="banner warn"><strong>How status is decided.</strong> <em>Built</em> means a change note for the item is on the main
branch. <em>Specced</em> means its spec exists but no change note does. <em>Planned</em> means neither. Read from commit
<code>{esc(rm["ref"][:7])}</code>, dated {esc(rm["commit_date"][:10])}.</p>
<div class="stats">{stats}</div>
<h2>Waves</h2>{"".join(waves)}
<h2 id="not-now">Deliberately not planned</h2>
<p class="muted">Work that is kept human, or cannot be done safely with synthetic data.</p><ul>{notnow}</ul>
<p>Next: <a href="ideas.html">ideas ranked by value</a>, or the <a href="proof.html">evidence behind the status</a>.</p>
"""
    return ("roadmap", "Roadmap", body)


def page_ideas(ideas: dict[str, Any]) -> tuple[str, str, str]:
    sections = []
    for g in ideas["groups"]:
        cards = "".join(
            f"""<article class="card"><p class="kicker">{esc(i["id"])} · effort {esc(i["effort"])}</p>
<h3>{esc(i["title"])}</h3><p>{esc(i["why"])}</p>
<p class="small muted">Builds on: {esc(", ".join(i["builds_on"]))}</p></article>"""
            for i in ideas["ideas"]
            if i["group"] == g["id"]
        )
        sections.append(
            f'<h2 id="{esc(g["id"])}">{esc(g["label"])}</h2><p class="muted">{esc(g["text"])}</p>'
            f'<div class="grid two">{cards}</div>'
        )
    body = f"""
<h1>Ideas</h1>
<p class="lede">{esc(ideas["lede"])}</p>
{"".join(sections)}
<p>Where these sit in the plan: <a href="roadmap.html">roadmap and upgrades</a>.</p>
"""
    return ("ideas", "Ideas", body)


def page_proof(pr: dict[str, Any], content: dict[str, Any]) -> tuple[str, str, str]:
    stats = "".join(
        [
            _stat(pr["test_functions"], f"test functions in {pr['test_files']} files"),
            _stat(pr["decisions"], "written design decisions"),
            _stat(pr["specs"], "item specs"),
            _stat(pr["change_notes"], "change notes (built items)"),
            _stat(pr["unverified_claims"], "claims listed as unverified"),
        ]
    )
    runs = table(
        ["Date", "What", "Command", "Result", "Commit"],
        [
            [
                esc(r["date"]),
                esc(r["what"]),
                f"<code>{esc(r['command'])}</code>",
                esc(r["result"]),
                f"<code>{esc(r['commit'])}</code>",
            ]
            for r in content["recorded_runs"]
        ],
        "Recorded runs",
    )
    claims = table(
        ["Claim", "How it is shown", "Where the tests are", "State"],
        [
            [esc(c["claim"]), esc(c["evidence"]), f"<span class='small'>{esc(c['tests'])}</span>", esc(c["state"])]
            for c in content["claims"]
        ],
        "Claims and evidence",
    )
    nope = "".join(f"<li>{esc(x)}</li>" for x in content["not_proven"])
    body = f"""
<h1>Proof and limits</h1>
<p class="lede">{esc(content["lede"])}</p>
<p class="muted">Counts read from commit <code>{esc(pr["ref"][:7])}</code>, dated {esc(pr["commit_date"][:10])}. Test
counts are functions; parameterised cases would add more.</p>
<div class="stats">{stats}</div>
<h2 id="recorded">Recorded runs</h2>{runs}
<h2 id="claims">Claims and where they are checked</h2>{claims}
<h2 id="not-proven">What is not proven</h2><ul>{nope}</ul>
<p>Try it yourself: <a href="approvals.html">tamper with the audit log</a> and watch the verifier name the record.</p>
"""
    return ("proof", "Proof", body)


DESCRIPTIONS = {
    "portfolio": "Projects and the skills they show, each with proof you can open and an honest list of limits.",
    "blueprint": "The design: ten rules, the layers, the path of one change and the risk classes.",
    "roadmap": "Every planned work item by wave, with a status read from the project itself.",
    "ideas": "What to build next, ranked by how much it makes the system more real.",
    "proof": "Counts, dated runs, claims with their tests, and what is not proven.",
}
