"""Tests for the built site (dist/). Standard library only; run after build.py:

    python -B -m unittest discover -s tests -v

Needs: this repository (read-only, for its own audit verifier and fixtures), Node (chain.js parity), PowerShell 7
(privacy scan), Microsoft Edge (headless page rendering). A missing tool fails the test that needs it; nothing is skipped.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True  # importing the repo's verifier must not write __pycache__ into the repo

SITE = Path(__file__).resolve().parents[1]
DIST = SITE / "dist"
REPO = Path(os.environ.get("REDLINE_REPO", Path(__file__).resolve().parents[2]))


# A headless Chrome (or Edge as the fallback): REDLINE_BROWSER, then the usual install paths, then PATH.
def _find_browser() -> Path:
    candidates = [
        os.environ.get("REDLINE_BROWSER", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    candidates += [
        shutil.which(n) or ""
        for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")
    ]
    return next((Path(c) for c in candidates if c and Path(c).is_file()), Path("chrome-not-found"))


EDGE = _find_browser()
CONFIG = json.loads((SITE / "site.config.json").read_text(encoding="utf-8"))
PAGES = [
    "index",
    "portfolio",
    "blueprint",
    "roadmap",
    "ideas",
    "proof",
    "triage",
    "approvals",
    "injection",
    "baseline",
    "workflows",
    "levers",
    "about",
    "404",
]

sys.path.insert(0, str(SITE))  # stats.py: the banned-word list is shared with the build
sys.path.insert(0, str(REPO))
from core.audit.chain import canonical_json, verify_chain  # noqa: E402


def data(name: str):
    return json.loads((DIST / "data" / f"{name}.json").read_text(encoding="utf-8"))


def chain_for(approvals: dict, node_id: str) -> list[str]:
    by_id = {n["id"]: n for n in approvals["nodes"]}
    path, n = [], by_id[node_id]
    while n:
        path.insert(0, n)
        n = by_id.get(n["parent"]) if n["parent"] else None
    return [line for node in path for line in node["new_lines"]]


def py_verify(lines: list[str], head: dict | None) -> dict:
    """The repo's own verify_chain() over these exact lines (written to a temp file, never into the repo)."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "audit.jsonl"
        log.write_bytes(b"".join(line.encode("utf-8") + b"\n" for line in lines))
        head_path = None
        if head is not None:
            head_path = Path(tmp) / "audit.jsonl.head"
            head_path.write_text(json.dumps(head), encoding="utf-8")
        r = verify_chain(log, head_path)
    return {"ok": r.ok, "broken_seq": r.broken_seq, "reason": r.reason, "records": r.records}


class Server:
    """dist (or a copy of it) on 127.0.0.1, a free port, for the life of a test class."""

    def __init__(self, root: Path) -> None:
        handler = functools.partial(QuietHandler, directory=str(root))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, page: str) -> str:
        return f"http://127.0.0.1:{self.port}/{page}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".json": "application/json",
        ".svg": "image/svg+xml",
    }

    def log_message(self, *args) -> None:  # noqa: D401
        pass


def dump_dom(url: str) -> str:
    with tempfile.TemporaryDirectory() as profile:
        proc = subprocess.run(
            [
                str(EDGE),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=10000",
                "--dump-dom",
                *(["--no-sandbox"] if os.environ.get("CI") else []),
                url,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
    return proc.stdout


# ---------------------------------------------------------------------------------------------------------------


class TestBuildProvenance(unittest.TestCase):
    """The data was generated by real runs of the repo's code, and says so."""

    def test_every_build_step_succeeded(self) -> None:
        b = data("build")
        self.assertRegex(b["source"]["commit"], r"^[0-9a-f]{12}$")
        self.assertGreaterEqual(len(b["steps"]), 10)
        failed = [s["name"] for s in b["steps"] if not s.get("ok")]
        self.assertEqual(failed, [], "every build step must have succeeded")
        cli = [s for s in b["steps"] if s["name"] == "export:cli"]
        self.assertGreater(len(cli), 30, "the exporter must have run the repo's command lines")
        self.assertTrue(all(s.get("exit_code") is not None for s in cli))

    def test_commit_exists_in_repo(self) -> None:
        sha = data("build")["source"]["commit"]
        proc = subprocess.run(["git", "-C", str(REPO), "cat-file", "-t", sha], capture_output=True, text=True)
        self.assertEqual(proc.stdout.strip(), "commit")

    def test_triage_covers_every_fixture_ticket(self) -> None:
        ids = set()
        for f in (REPO / "fixtures" / "tickets").glob("*.json"):
            ids |= {t["id"] for t in json.loads(f.read_text(encoding="utf-8"))["tickets"]}
        self.assertEqual({t["id"] for t in data("triage")["tickets"]}, ids)

    def test_proposal_ids_follow_the_repo_contract(self) -> None:
        # "P-" + first 12 hex of SHA-256 over lever + client + canonical JSON params (core/queue/store.py)
        n = 0
        for t in data("triage")["tickets"]:
            p = t["triage"]["proposal"]
            if not p:
                continue
            digest = hashlib.sha256(
                p["lever"].encode() + p["client"].encode() + canonical_json(p["params"])
            ).hexdigest()
            self.assertEqual(p["id"], "P-" + digest[:12], t["id"])
            n += 1
        self.assertEqual(n, 13)

    def test_flagged_tickets_never_get_a_lever(self) -> None:
        for t in data("triage")["tickets"]:
            if t["triage"]["injection"]["flagged"]:
                self.assertIsNone(t["triage"]["proposal"], t["id"])

    def test_triage_audit_lines_verify_with_the_repo_verifier(self) -> None:
        tri = data("triage")
        self.assertTrue(tri["audit_verify"]["ok"])
        for t in tri["tickets"]:
            if t["audit_line"]:
                rec = json.loads(t["audit_line"])
                self.assertEqual(rec["seq"], t["triage"]["dry_run"]["audit_seq"])
                self.assertEqual(canonical_json(rec).decode("utf-8"), t["audit_line"])

    def test_every_approval_state_chain_verifies(self) -> None:
        a = data("approvals")
        self.assertEqual(len(a["nodes"]), 21)
        for node in a["nodes"]:
            lines = chain_for(a, node["id"])
            r = py_verify(lines, node["verify"]["head"])
            self.assertTrue(r["ok"], node["id"])
            self.assertEqual(r["records"], node["verify"]["records"])

    def test_approval_outcomes_match_the_demo_script(self) -> None:
        demo = (REPO / "docs" / "DEMO.md").read_text(encoding="utf-8")
        by_id = {n["id"]: n for n in data("approvals")["nodes"]}
        self.assertIn(
            "needs the requester verified out of band first; choose how (C-30)", by_id["sN"]["response"]["message"]
        )
        self.assertIn("needs the requester verified out of band first; choose how (C-30)", demo)
        self.assertTrue(by_id["sA"]["response"]["message"].startswith("Executed P-d01c53bdf1dc"))
        self.assertIn("P-d01c53bdf1dc", demo)
        self.assertEqual(by_id["sT"]["response"]["http_status"], 403)
        self.assertEqual(
            by_id["sJ"]["queue"][0]["status"]
            if by_id["sJ"]["queue"][0]["id"] == "P-d01c53bdf1dc"
            else next(q["status"] for q in by_id["sJ"]["queue"] if q["id"] == "P-d01c53bdf1dc"),
            "rejected",
        )

    def test_runner_denials_match_the_demo_script(self) -> None:
        demo = (REPO / "docs" / "DEMO.md").read_text(encoding="utf-8")
        calls = {c["key"]: c["result"] for c in data("controls")["calls"]}
        for key in (
            "agent-cannot-execute",
            "client-scope",
            "needs-approval",
            "needs-verification",
            "four-eyes",
            "paused-denies",
        ):
            self.assertEqual(calls[key]["status"], "denied", key)
            self.assertIn(calls[key]["reason"], demo, f"{key}: the reason the runner gave is the one DEMO.md documents")
        self.assertEqual(calls["all-checks-pass"]["status"], "ok")
        self.assertTrue(calls["all-checks-pass"]["applied"])

    def test_tamper_matches_the_python_verifier(self) -> None:
        t = data("approvals")["tamper"]
        self.assertTrue(
            t["python_verifier_output"].startswith("BROKEN at seq 4: hash does not match the record content")
        )
        self.assertTrue(t["python_verifier_ok_output"].startswith("OK: 4 records"))

    def test_baseline_matches_the_demo_script(self) -> None:
        b = data("baseline")["tenants"]
        c = b["contoso-dental"]["findings"]["counts"]
        self.assertEqual((c["total"], c["bySeverity"]["High"], c["bySeverity"]["Medium"]), (14, 10, 4))
        demo = (REPO / "docs" / "DEMO.md").read_text(encoding="utf-8")
        self.assertIn("14 findings (10 high, 4 medium; fixture-based)", demo)
        for tid, t in b.items():
            self.assertTrue(t["reconcile"].startswith("OK: every number in summary.txt reconciles"), tid)
            self.assertEqual(t["findings"]["source"], "fixture")
            for f in ("report.html", "findings.csv", "findings.json", "summary.txt"):
                self.assertTrue((DIST / "baseline" / tid / f).is_file(), f"{tid}/{f}")

    def test_injection_score_is_what_the_cli_printed(self) -> None:
        inj = data("injection")
        s = inj["score"]
        self.assertEqual(s["tp"] + s["fn"] + s["tn"] + s["fp"], len(inj["cases"]))
        self.assertIn(f"Corpus: {len(inj['cases'])} cases", inj["cli_report"])
        self.assertEqual(inj["report_text"].strip(), inj["cli_report"].strip())


class TestHtml(unittest.TestCase):
    """Structure, accessibility basics and links, from the HTML files."""

    class Collector(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.tags: list[tuple[str, dict]] = []
            self.ids: set[str] = set()
            self.text: list[str] = []

        def handle_starttag(self, tag, attrs):  # noqa: ANN001
            a = dict(attrs)
            self.tags.append((tag, a))
            if "id" in a:
                self.ids.add(a["id"])

        def handle_data(self, d):  # noqa: ANN001
            self.text.append(d)

    def parse(self, path: Path) -> Collector:
        c = self.Collector()
        c.feed(path.read_text(encoding="utf-8"))
        return c

    def test_every_page_has_the_basics(self) -> None:
        for page in PAGES:
            c = self.parse(DIST / f"{page}.html")
            tags = [t for t, _ in c.tags]
            html_tag = next(a for t, a in c.tags if t == "html")
            self.assertEqual(html_tag.get("lang"), "en", page)
            self.assertEqual(tags.count("h1"), 1, f"{page}: exactly one h1")
            self.assertEqual(tags.count("main"), 1, page)
            self.assertIn("title", tags, page)
            metas = [a for t, a in c.tags if t == "meta"]
            self.assertTrue(any(a.get("name") == "viewport" for a in metas), page)
            self.assertTrue(any(a.get("http-equiv") == "Content-Security-Policy" for a in metas), page)
            self.assertTrue(
                any(a.get("class") == "skip" and a.get("href") == "#main" for t, a in c.tags if t == "a"), page
            )
            text = " ".join(c.text)
            self.assertIn("Synthetic data only", text, f"{page}: the prototype label is on every page")
            self.assertIn("Independently built prototype", text, page)
            for t, a in c.tags:
                if t == "script":
                    self.assertTrue(a.get("src"), f"{page}: no inline scripts (CSP script-src 'self')")
                if t == "img":
                    self.assertIn("alt", a, page)
                if t == "button":
                    self.assertTrue(a.get("type"), f"{page}: every button has a type")

    def test_no_inline_style_attributes(self) -> None:
        # The CSP (style-src 'self') makes browsers drop style="" attributes, so anything drawn with one silently
        # disappears (the roadmap bars once did). Sizes go in SVG attributes or classes instead.
        for page in PAGES:
            for t, a in self.parse(DIST / f"{page}.html").tags:
                self.assertNotIn("style", a, f"{page}: <{t}> has an inline style the CSP would block")

    def test_hero_scene_and_mascot(self) -> None:
        c = self.parse(DIST / "index.html")
        scene = [a for t, a in c.tags if t == "svg" and "scene" in (a.get("class") or "").split()]
        self.assertEqual(len(scene), 1, "the overview has one hero scene")
        self.assertEqual(scene[0].get("role"), "img")
        self.assertIn("scene-title", c.ids, "the scene is described for screen readers")
        self.assertIn('class="mascot', (DIST / "404.html").read_text(encoding="utf-8"))
        for page in PAGES:
            text = (DIST / f"{page}.html").read_text(encoding="utf-8")
            self.assertIn('id="menu-btn"', text, page)
            self.assertIn('id="motion-btn"', text, f"{page}: the motion switch (WCAG 2.3.3)")

    def test_pipeline_steps_link_to_their_pages(self) -> None:
        c = self.parse(DIST / "index.html")
        hrefs, inside = [], False
        for t, a in c.tags:
            if t == "ol" and a.get("class") == "flow":
                inside = True
            elif t == "ol":
                inside = False
            elif inside and t == "a":
                hrefs.append(a["href"])
        self.assertEqual(len(hrefs), 8, "every pipeline step is a link")

    def test_nav_marks_the_current_page(self) -> None:
        for page in PAGES[:-1]:
            c = self.parse(DIST / f"{page}.html")
            current = [a["href"] for t, a in c.tags if t == "a" and a.get("aria-current") == "page"]
            self.assertEqual(current, [f"{page}.html"], page)

    def test_no_broken_or_external_links(self) -> None:
        files = [p for p in DIST.rglob("*.html")]
        ids = {p: self.parse(p).ids for p in files}
        checked = 0
        for p in files:
            for tag, a in self.parse(p).tags:
                for attr in ("href", "src"):
                    ref = a.get(attr)
                    if not ref:
                        continue
                    u = urlsplit(ref)
                    # the one allowed outside link is the author's configured profile, as a plain link (not a request)
                    if tag == "a" and attr == "href" and CONFIG.get("contact_url") and ref == CONFIG["contact_url"]:
                        continue
                    self.assertFalse(
                        u.scheme in ("http", "https") or ref.startswith("//"),
                        f"{p.name}: external reference {ref} (the site makes no third-party requests)",
                    )
                    if u.scheme:
                        continue
                    target = (p.parent / u.path).resolve() if u.path else p
                    self.assertTrue(target.is_file(), f"{p.relative_to(DIST)}: broken link {ref}")
                    if u.fragment and target.suffix == ".html" and target in ids:
                        js_built = u.fragment.startswith("t=") or u.fragment.startswith("path=")
                        if not js_built:
                            self.assertIn(u.fragment, ids[target], f"{p.name}: missing anchor {ref}")
                    checked += 1
        self.assertGreater(checked, 50)

    def test_site_name_and_byline(self) -> None:
        for page in PAGES:
            text = (DIST / f"{page}.html").read_text(encoding="utf-8")
            self.assertIn(CONFIG["site_name"], text, page)
            if CONFIG.get("author_line"):
                link = f'<a href="{CONFIG["contact_url"]}" rel="author">{CONFIG["author_line"]}</a>'
                self.assertIn(link, text, f"{page}: the byline links to the configured profile")
            self.assertNotIn("Button Pushers", text, f"{page}: the old name is gone")

    def test_data_files_named_in_scripts_exist(self) -> None:
        for js in (DIST / "assets" / "js").glob("*.js"):
            for ref in re.findall(r"data/[a-z]+\.json", js.read_text(encoding="utf-8")):
                self.assertTrue((DIST / ref).is_file(), f"{js.name} loads {ref}")

    def test_no_external_urls_in_scripts_or_css(self) -> None:
        for f in list((DIST / "assets").rglob("*.js")) + list((DIST / "assets").rglob("*.css")):
            self.assertNotRegex(f.read_text(encoding="utf-8"), r"https?://", f.name)


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TestContrast(unittest.TestCase):
    """WCAG AA (4.5:1) for every text colour on every background it is used on, light and dark."""

    PAIRS = [
        ("text", "bg"),
        ("text", "surface"),
        ("text", "surface-2"),
        ("muted", "bg"),
        ("muted", "surface"),
        ("muted", "surface-2"),
        ("accent", "surface"),
        ("accent", "bg"),
        ("accent", "accent-soft"),
        ("accent-text", "accent"),
        ("ok", "ok-soft"),
        ("ok", "surface"),
        ("bad", "bad-soft"),
        ("bad", "surface"),
        ("warn", "warn-soft"),
        ("warn", "surface"),
        ("text", "code-bg"),
        ("text", "warn-soft"),
        ("surface", "bad"),
    ]

    def tokens(self) -> dict[str, dict[str, str]]:
        css = (DIST / "assets" / "site.css").read_text(encoding="utf-8")
        light = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-f]{6})", css.split("@media")[0]))
        dark_block = css.split(':root[data-theme="dark"]')[1].split("}")[0]
        dark = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-f]{6})", dark_block))
        media_block = css.split("@media (prefers-color-scheme: dark)")[1].split("}\n}")[0]
        self.assertEqual(
            dark,
            dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-f]{6})", media_block)),
            "the two dark definitions must agree",
        )
        return {"light": light, "dark": {**light, **dark}}

    def test_text_pairs_meet_aa(self) -> None:
        for theme, t in self.tokens().items():
            for fg, bg in self.PAIRS:
                ratio = contrast(t[fg], t[bg])
                self.assertGreaterEqual(ratio, 4.5, f"{theme}: --{fg} on --{bg} is {ratio:.2f}:1")


class TestChainParity(unittest.TestCase):
    """chain.js (the browser verifier) must agree with the repo's Python verify_chain() on real and tampered chains."""

    def cases(self) -> list[dict]:
        a = data("approvals")
        out = []
        for node in a["nodes"]:
            lines, head = chain_for(a, node["id"]), node["verify"]["head"]
            out.append({"name": f"{node['id']} intact", "lines": lines, "head": head})
            out.append({"name": f"{node['id']} no head", "lines": lines, "head": None})
        lines, head = chain_for(a, "sNA"), next(n for n in a["nodes"] if n["id"] == "sNA")["verify"]["head"]
        for i, line in enumerate(lines):
            out.append(
                {
                    "name": f"letter edit seq {i + 1}",
                    "lines": lines[:i] + [line.replace('"agent":"', '"agent":"x', 1)] + lines[i + 1 :],
                    "head": head,
                }
            )
            out.append(
                {
                    "name": f"hash edit seq {i + 1}",
                    "lines": lines[:i]
                    + [
                        re.sub(
                            r'"hash":"(.)', lambda m: '"hash":"' + ("0" if m.group(1) != "0" else "1"), line, count=1
                        )
                    ]
                    + lines[i + 1 :],
                    "head": head,
                }
            )
            out.append(
                {
                    "name": f"spaces seq {i + 1}",
                    "lines": lines[:i] + [line.replace('","', '", "', 1)] + lines[i + 1 :],
                    "head": head,
                }
            )
        out += [
            {
                "name": "approver tamper",
                "lines": [ln.replace('"approver":"lead-lee"', '"approver":"lead-leo"') for ln in lines],
                "head": head,
            },
            {"name": "delete middle", "lines": lines[:2] + lines[3:], "head": head},
            {"name": "truncate end", "lines": lines[:-1], "head": head},
            {
                "name": "extra after head",
                "lines": lines,
                "head": {"seq": len(lines) - 1, "hash": json.loads(lines[-2])["hash"]},
            },
            {"name": "swap", "lines": [lines[1], lines[0]] + lines[2:], "head": head},
            {"name": "blank line", "lines": lines[:1] + [""] + lines[1:], "head": head},
            {"name": "not json", "lines": lines[:1] + ["{oops"] + lines[2:], "head": head},
            {"name": "wrong head hash", "lines": lines, "head": {"seq": head["seq"], "hash": "0" * 64}},
            {"name": "empty", "lines": [], "head": None},
        ]
        for c in out:
            c["python"] = py_verify(c["lines"], c["head"])
        return out

    def test_node_verifier_agrees(self) -> None:
        cases = self.cases()
        self.assertGreater(sum(1 for c in cases if not c["python"]["ok"]), 19, "enough broken cases to mean something")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.json"
            path.write_text(json.dumps(cases), encoding="utf-8")
            proc = subprocess.run(
                ["node", str(SITE / "tests" / "chain.test.mjs"), str(DIST / "assets" / "js" / "chain.js"), str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["pass"], len(cases))


class TestPrivacy(unittest.TestCase):
    def run_scan(self, *args: str) -> dict:
        proc = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(SITE / "scan" / "privacy-scan.ps1"), *args, "-Json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return {"code": proc.returncode, **json.loads(proc.stdout.strip().splitlines()[-1])}

    ALLOW = ("-AllowConfig", str(SITE / "site.config.json"))

    def test_scan_finds_nothing_in_dist(self) -> None:
        r = self.run_scan("-Root", str(DIST), *self.ALLOW)
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["hits"], 0, f"privacy hits by class: {r['by_class']}")
        self.assertEqual(r["code"], 0)
        self.assertTrue(r["owner_name_checked"])

    def test_byline_is_the_only_exemption(self) -> None:
        if not CONFIG.get("author_line"):
            self.skipTest("no author line configured")
        r = self.run_scan("-Root", str(DIST))  # without the allowance, the byline (and only it) must be reported
        self.assertGreater(r["hits"], 0)
        self.assertEqual(
            set(r["by_class"]) - {"owner-name"},
            set(),
            f"only the byline may differ between the two scans: {r['by_class']}",
        )

    def test_scan_catches_every_planted_class(self) -> None:
        for args in ((), self.ALLOW):
            r = self.run_scan("-SelfTest", *args)
            self.assertEqual(r["missed"], [], "the scan must catch every class it claims to check")
            self.assertEqual(r["caught"], r["planted"])


class TestPortfolioContent(unittest.TestCase):
    """The data-driven pages: content files are well formed, the roadmap agrees with itself, nothing private ships."""

    from stats import BANNED  # one list, shared with the build, so the two cannot drift apart

    def content(self, name: str):
        return json.loads((SITE / "content" / f"{name}.json").read_text(encoding="utf-8"))

    def test_portfolio_entries_have_the_required_fields(self) -> None:
        required = {"id", "name", "status", "kicker", "summary", "skills", "proof", "links"}
        ids = set()
        for p in self.content("portfolio")["projects"]:
            self.assertFalse(required - set(p), p.get("id"))
            self.assertRegex(p["id"], r"^[a-z0-9-]+$")
            self.assertIn(p["status"], {"live", "building", "idea"})
            self.assertNotIn(p["id"], ids)
            ids.add(p["id"])
            for x in p["links"]:
                self.assertTrue(x["href"].startswith("https://"), "outside links must be https")
            for x in p["proof"]:
                if x.get("href"):
                    self.assertTrue((DIST / x["href"].split("#")[0]).is_file(), x["href"])

    def test_roadmap_totals_agree(self) -> None:
        rm = data("roadmap")
        items = [i for w in rm["waves"] for i in w["items"]]
        self.assertEqual(len(items), rm["totals"]["items"])
        self.assertEqual(len({i["id"] for i in items}), len(items), "item ids are unique")
        for status in ("built", "specced", "planned"):
            self.assertEqual(sum(1 for i in items if i["status"] == status), rm["totals"][status])
        for w in rm["waves"]:
            self.assertEqual(sum(w["counts"].values()), len(w["items"]), w["id"])

    def test_roadmap_matches_the_repo(self) -> None:
        rm = data("roadmap")
        raw = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{rm['ref']}:map/roadmap.json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        repo_ids = {i["id"] for w in json.loads(raw)["waves"] for i in w["items"]}
        self.assertEqual(repo_ids, {i["id"] for w in rm["waves"] for i in w["items"]})

    def test_ideas_point_at_real_roadmap_items(self) -> None:
        ids = {i["id"] for w in data("roadmap")["waves"] for i in w["items"]}
        for idea in self.content("ideas")["ideas"]:
            self.assertIn(idea["group"], {g["id"] for g in self.content("ideas")["groups"]})
            for ref in idea["builds_on"]:
                if ref.startswith("B-"):
                    self.assertIn(ref, ids, idea["id"])

    def test_proof_counts_are_plausible(self) -> None:
        pr = data("proof")
        self.assertGreater(pr["test_functions"], 500)
        self.assertGreaterEqual(pr["decisions"], 60)
        built = sum(w["counts"]["built"] for w in data("roadmap")["waves"])
        self.assertEqual(
            pr["change_notes"], built, "built items on the roadmap page = change notes counted for the proof page"
        )

    def test_blueprint_decision_refs_exist_in_the_repo(self) -> None:
        ref = data("roadmap")["ref"]
        text = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{ref}:docs/DECISIONS.md"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        have = set(re.findall(r"^## (D-\d+)", text, re.MULTILINE))
        for pr in self.content("blueprint")["principles"]:
            for d in re.findall(r"D-\d+", pr["ref"]):
                self.assertIn(d, have, pr["title"])

    def test_proof_test_paths_exist_in_the_repo(self) -> None:
        ref = data("roadmap")["ref"]
        listing = set(
            subprocess.run(
                ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", ref],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            ).stdout.splitlines()
        )
        for c in self.content("proof")["claims"]:
            for path in re.findall(r"[\w./-]+\.(?:py|ps1)|tests/py/[\w/]+/", c["tests"]):
                found = path in listing or any(x.startswith(path) for x in listing)
                self.assertTrue(found, f"{c['claim']}: {path} is not in the repo at {ref}")

    def test_no_private_words_in_content_or_pages(self) -> None:
        for f in (SITE / "content").glob("*.json"):
            self.assertIsNone(self.BANNED.search(f.read_text(encoding="utf-8")), f.name)
        for page in ("portfolio", "blueprint", "roadmap", "ideas", "proof"):
            self.assertIsNone(self.BANNED.search((DIST / f"{page}.html").read_text(encoding="utf-8")), page)
        for f in list((DIST / "data").glob("*.json")) + [DIST / "index.html", DIST / "about.html"]:
            self.assertIsNone(self.BANNED.search(f.read_text(encoding="utf-8")), f.name)


class TestRendering(unittest.TestCase):
    """Every page rendered by headless Edge: scripts ran, data loaded, no error state; plus error and empty states."""

    @classmethod
    def setUpClass(cls) -> None:
        if not EDGE.is_file():
            raise AssertionError(f"Microsoft Edge not found at {EDGE}")
        cls.server = Server(DIST)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.close()

    EXPECT = {
        "index": ["Agents are button-pushers.", "The 2-minute story"],
        "portfolio": ["What the work shows", "Proof you can open"],
        "blueprint": ["Ten rules the design will not break", "The path of one change"],
        "roadmap": ["Roadmap and upgrades", "How status is decided", "Deliberately not planned"],
        "ideas": ["Parked on purpose", "Wire two signed-in approvers"],
        "proof": ["Recorded runs", "What is not proven"],
        "triage": ["The ticket arrives", "Who this affects", "P-d01c53bdf1dc", "OK: 13 records"],
        "approvals": ["Verify chain: ", "OK: 3 records, chain intact and matches the head pin", "Record the callback"],
        "injection": ["Flagged: ", "Showing 50 of 50 synthetic cases."],
        "baseline": ["Contoso Dental", "reconciles with findings.json (14 findings)"],
        "workflows": ["Intake proposal for T-5301", "SLA breach watch"],
        "levers": ["user.reset-mfa", "What stays human"],
        "about": ["How this site was built", "Privacy"],
        "404": ["Page not found"],
    }

    def test_every_page_renders(self) -> None:
        for page in PAGES:
            with self.subTest(page=page):
                dom = dump_dom(self.server.url(f"{page}.html"))
                self.assertIn('data-ready="1"', dom, f"{page}: the page script did not finish")
                self.assertNotIn("data-error=", dom, page)
                for text in self.EXPECT[page]:
                    self.assertIn(text, dom, f"{page}: expected {text!r}")

    def test_deep_links_restore_state(self) -> None:
        dom = dump_dom(self.server.url("approvals.html#path=sNA&pause=3"))
        self.assertIn("OK: 9 records, chain intact and matches the head pin", dom)
        self.assertIn("All three steps are in the audit log.", dom)
        dom = dump_dom(self.server.url("triage.html#t=T-3129"))
        self.assertIn("instruction-override", dom)

    def test_error_and_empty_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "dist"
            shutil.copytree(DIST, broken)
            (broken / "data" / "approvals.json").unlink()
            tri = json.loads((broken / "data" / "triage.json").read_text(encoding="utf-8"))
            tri["tickets"] = []
            (broken / "data" / "triage.json").write_text(json.dumps(tri), encoding="utf-8")
            srv = Server(broken)
            try:
                dom = dump_dom(srv.url("approvals.html"))
                self.assertIn("This demo could not load its data.", dom)
                self.assertIn("data-error=", dom)
                dom = dump_dom(srv.url("triage.html"))
                self.assertIn("The build produced no tickets", dom)
            finally:
                srv.close()


class TestRepoUntouched(unittest.TestCase):
    def test_repo_working_tree_is_clean(self) -> None:
        proc = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"], capture_output=True, text=True)
        self.assertEqual(
            proc.stdout.strip(), "", "the build reads the repo read-only; its working tree must stay clean"
        )


if __name__ == "__main__":
    unittest.main()
