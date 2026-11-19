#!/usr/bin/env python3
"""Re-run the published audit table against full-history upstream clones.

Usage:
    python evidence/reproduce.py --clones /tmp/pc-up --patches evidence/patches \
        --out evidence/audit.json

Each clone must be a *full-history* clone; the tool refuses shallow ones.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preprcheck import __version__
from preprcheck.audit import audit  # noqa: E402

TABLE = [
    ("linluozi/cachetools-lru-opt-lab", "tkem/cachetools", "cachetools", "cachetools-lru-opt-lab.diff"),
    ("linluozi/semver-opt-lab", "python-semver/python-semver", "semver", "semver-opt-lab.diff"),
    ("linluozi/pyjson5-opt-lab", "dpranke/pyjson5", "pyjson5", "pyjson5-opt-lab.diff"),
    ("linluozi/inflect-opt-lab", "jaraco/inflect", "inflect", "inflect-opt-lab.diff"),
    ("linluozi/jsonpatch-apply-opt-lab", "stefankoegl/python-json-patch", "jsonpatch", "jsonpatch-apply-opt-lab.diff"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clones", required=True)
    ap.add_argument("--patches", default=str(Path(__file__).parent / "patches"))
    ap.add_argument("--out", default=str(Path(__file__).parent / "audit.json"))
    args = ap.parse_args()

    rows = []
    for repo, upstream, clone_name, patch_name in TABLE:
        clone = Path(args.clones) / clone_name
        patch_path = Path(args.patches) / patch_name
        patch_text = patch_path.read_text()
        result = audit(str(clone), patch_text)
        d = result.to_dict()
        head = subprocess.run(
            ["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        rows.append(
            {
                "repo": repo,
                "upstream": upstream,
                "clone_head": head,
                "patch": patch_name,
                "patch_sha256": d["patch_sha256"],
                "verdict": d["verdict"],
                "confidence": d["confidence"],
                "searched_commits": d["searched_commits"],
                "elapsed_s": d["elapsed_s"],
                "files": d["files"],
                "window_since": d["window"]["since"],
            }
        )
        best = d["files"][0]["best"]
        print(
            f"{repo:38s} {d['verdict']:12s} "
            + (f"{best['sha'][:12]} {best['matched']}/{best['total']}" if best else "-")
        )

    payload = {
        "schema": "preprcheck/evidence/v1",
        "tool_version": __version__,
        "window_days": 730,
        "python": sys.version.split()[0],
        "rows": rows,
        "summary": {
            "audited": len(rows),
            "hits": sum(r["verdict"] == "hit" for r in rows),
            "clear": sum(r["verdict"] == "clear" for r in rows),
        },
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())