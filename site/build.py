"""Build the static showcase site from REAL runs of this repository's code. Standard library only.

    python site/build.py                  # builds the repository that contains this file, ref HEAD, writes site/dist
    python site/build.py --offline        # forbid network access for the uv sync step (needs a warm uv cache)
    python site/build.py --worktree       # snapshot the working tree (tracked and untracked, not ignored) instead of a commit
    python site/build.py --ref v1 --keep-work

What it does, in order:
1. Reads the repository READ-ONLY: `git archive <ref>` (or the working tree) into a scratch folder under the temp directory.
   Nothing is written inside the repository (no venv, no bytecode, no state folder).
2. `uv sync --frozen` in the snapshot: the repository's own locked environment.
3. Runs exporter/export_data.py inside the snapshot: it calls the repository's own functions and command lines
   over the synthetic fixtures and writes JSON (data/*.json) plus captures of the real local approval page.
4. Runs the PowerShell TenantBaseline module (Slice B) on both synthetic tenants, then its own
   Test-SummaryReconciles.ps1 check.
5. Reads the roadmap and proof numbers from the same snapshot (stats.py), renders the pages (render.py), copies assets, and
   swaps the result into dist/ atomically.

Needs: git, uv, PowerShell 7 (pwsh). Exit 0 on success; any failing step stops the build and leaves the previous dist/ untouched.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import render  # noqa: E402

BASELINE_TENANTS = (("contoso-dental", "Contoso Dental"), ("fabrikam-capital", "Fabrikam Capital"))
SOURCE_NAME = "redline-msp-automation"


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8")  # noqa: S603


def must(proc: subprocess.CompletedProcess[str], what: str) -> str:
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-4000:])
        raise SystemExit(f"build failed at: {what} (exit {proc.returncode})")
    return proc.stdout


def strip_paths(text: str, *roots: Path) -> str:
    return "".join(line for line in text.splitlines(keepends=True) if not any(str(r) in line for r in roots))


def repo_root() -> Path:
    """The repository that contains this file (site/ lives inside it)."""
    proc = run(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"])
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return HERE.parent


def snapshot_worktree(repo: Path, dest: Path) -> None:
    """Copy tracked and untracked (not ignored) files of the working tree; used before the first commit."""
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S603
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    for rel in filter(None, listing.split("\0")):
        src = repo / rel
        if src.is_file():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--repo", type=Path, default=None, help="repository to build (default: the one containing this file)"
    )
    ap.add_argument("--ref", default="HEAD", help="git ref the site is built from (default: HEAD)")
    ap.add_argument("--worktree", action="store_true", help="snapshot the working tree instead of a commit")
    ap.add_argument("--offline", action="store_true", help="pass --offline to uv sync (needs a warm cache)")
    ap.add_argument("--out", type=Path, default=HERE / "dist")
    ap.add_argument("--keep-work", action="store_true", help="keep the scratch folder for inspection")
    args = ap.parse_args()
    repo = (args.repo or repo_root()).resolve()
    started = time.perf_counter()
    steps: list[dict[str, object]] = []

    def timed(name: str, what: str, t0: float, **extra: object) -> None:
        steps.append({"name": name, "what": what, "ok": True, "seconds": round(time.perf_counter() - t0, 3), **extra})

    config = json.loads((HERE / "site.config.json").read_text(encoding="utf-8"))
    work = Path(tempfile.mkdtemp(prefix="rlweb-"))  # short path under the temp directory (Windows path length)
    snap = work / "snap"
    try:
        # 1. snapshot, read-only
        t0 = time.perf_counter()
        sha = must(run(["git", "-C", str(repo), "rev-parse", args.ref]), "git rev-parse").strip()
        commit_date = must(run(["git", "-C", str(repo), "show", "-s", "--format=%cI", sha]), "git show").strip()
        if args.worktree:
            snap.mkdir(parents=True)
            snapshot_worktree(repo, snap)
            what = f"working tree copy (based on {sha[:7]})"
        else:
            archive = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "core.autocrlf=false",
                    "-c",
                    "core.eol=lf",  # noqa: S603
                    "archive",
                    "--format=tar",
                    sha,
                ],
                capture_output=True,
                check=True,
            ).stdout
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(snap, filter="data")
            what = f"git archive {sha[:7]} (read-only copy of the repository)"
        timed("snapshot", what, t0)

        # 2. the repository's own locked environment
        t0 = time.perf_counter()
        env = {**os.environ, "UV_PYTHON_PREFERENCE": "only-managed", "PYTHONDONTWRITEBYTECODE": "1"}
        sync = ["uv", "sync", "--frozen"] + (["--offline"] if args.offline else [])
        must(run(sync, cwd=snap, env=env), " ".join(sync))
        py = snap / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        uv_version = must(run(["uv", "--version"]), "uv --version").split()[1]
        timed("environment", f"{' '.join(sync)} (uv.lock as committed)", t0)

        # 3. real runs -> JSON
        t0 = time.perf_counter()
        stage = work / "stage"
        data_dir = stage / "data"
        exporter = HERE / "exporter" / "export_data.py"
        out = must(
            run(
                [
                    str(py),
                    "-B",
                    str(exporter),
                    "--snap",
                    str(snap),
                    "--work",
                    str(work / "state"),
                    "--out",
                    str(data_dir),
                ],
                cwd=snap,
                env=env,
            ),
            "exporter",
        )
        timed(
            "export", "exporter/export_data.py inside the snapshot", t0, counts=json.loads(out.strip().splitlines()[-1])
        )

        # 4. Slice B, PowerShell
        baseline = {}
        pwsh_version = must(
            run(["pwsh", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"]), "pwsh version"
        ).strip()
        module = snap / "levers" / "powershell" / "TenantBaseline"
        for tenant, display in BASELINE_TENANTS:
            t0 = time.perf_counter()
            dest = stage / "baseline" / tenant
            cmd = (
                f"Import-Module '{module / 'TenantBaseline.psd1'}'; "
                f"Invoke-TenantBaseline -Tenant {tenant} -OutDir '{dest}' | Out-Null"
            )
            must(run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", cmd], cwd=snap), f"baseline {tenant}")
            check = run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(module / "Test-SummaryReconciles.ps1"),
                    "-OutDir",
                    str(dest),
                ],
                cwd=snap,
            )
            must(check, f"reconcile {tenant}")
            baseline[tenant] = {
                "display": display,
                "findings": json.loads((dest / "findings.json").read_text(encoding="utf-8-sig")),
                "summary": (dest / "summary.txt").read_text(encoding="utf-8-sig").strip(),
                "reconcile": strip_paths(check.stdout, work, snap).strip(),
                "files": sorted(p.name for p in dest.iterdir()),
            }
            timed(f"baseline-{tenant}", f"Invoke-TenantBaseline -Tenant {tenant}, then Test-SummaryReconciles.ps1", t0)
        graph_cfg = json.loads((module / "TenantBaseline.config.json").read_text(encoding="utf-8"))["graph"]
        (data_dir / "baseline.json").write_text(
            json.dumps(
                {
                    "tenants": baseline,
                    "graph_scopes": {"required": graph_cfg["requiredScopes"], "optional": graph_cfg["optionalScopes"]},
                },
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )

        # 4b. roadmap and proof numbers from the same snapshot (read-only file reads, no checkout)
        t0 = time.perf_counter()
        import stats  # noqa: E402

        blueprint = json.loads((HERE / "content" / "blueprint.json").read_text(encoding="utf-8"))
        roadmap_out, proof_out = stats.collect(snap, blueprint, sha, commit_date)
        (data_dir / "roadmap.json").write_text(json.dumps(roadmap_out, indent=1) + "\n", encoding="utf-8")
        (data_dir / "proof.json").write_text(json.dumps(proof_out, indent=1) + "\n", encoding="utf-8")
        timed("stats", f"roadmap and proof counts read from the snapshot of {roadmap_out['ref'][:7]}", t0)

        # 5. pages
        t0 = time.perf_counter()
        provenance = json.loads((data_dir / "provenance.json").read_text(encoding="utf-8"))
        export_steps = [{**s, "name": "export:" + s["name"]} for s in provenance["steps"]]
        build_info = {
            "source": {
                "repo": SOURCE_NAME,
                "commit": sha[:12],
                "commit_date": commit_date,
                "ref": "working tree" if args.worktree else args.ref,
            },
            "built_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "tools": {
                "python": provenance["python"],
                "pydantic": provenance["pydantic"],
                "uv": uv_version,
                "powershell": pwsh_version,
            },
            "steps": steps + export_steps,
        }
        render.build_site(HERE / "src", stage, data_dir, config, build_info)
        timed("render", "render.py: pages, assets", t0)
        build_info["steps"] = steps + export_steps
        build_info["seconds"] = round(time.perf_counter() - started, 1)
        (data_dir / "build.json").write_text(json.dumps(build_info, indent=1) + "\n", encoding="utf-8")

        # no scratch path may reach the output
        for f in stage.rglob("*"):
            if f.is_file() and f.suffix in {".html", ".json", ".js", ".css", ".txt", ".csv", ".svg"}:
                text = f.read_text(encoding="utf-8-sig", errors="replace")
                for root in (work, snap, repo, Path.home()):
                    if str(root) in text or str(root).replace("\\", "\\\\") in text:
                        raise SystemExit(f"build failed: a local path leaked into {f.relative_to(stage)}")

        # swap into place only when everything succeeded
        out_dir = args.out.resolve()
        if out_dir.exists():
            old = out_dir.with_name(out_dir.name + ".old")
            if old.exists():
                shutil.rmtree(old)
            out_dir.rename(old)
            shutil.move(str(stage), str(out_dir))
            shutil.rmtree(old)
        else:
            shutil.move(str(stage), str(out_dir))
        files = [p for p in out_dir.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        print(
            f"built {out_dir.name}/: {len(files)} files, {size / 1024:.0f} KiB, from {sha[:7]} "
            f"in {time.perf_counter() - started:.1f}s"
        )
        return 0
    finally:
        if args.keep_work:
            print(f"scratch kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
