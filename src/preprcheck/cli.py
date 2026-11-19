"""Command line entry point for preprcheck."""

from __future__ import annotations

import argparse
import json
import sys

from .audit import audit
from .gitprobe import GitError, is_git_repo


def _render(result, repo: str) -> str:
    d = result.to_dict()
    lines = [
        f"preprcheck: {d['verdict'].upper()} ({d['confidence']} confidence)",
        f"repo: {repo} @ {d['head'][:12]}",
        f"patch: sha256 {d['patch_sha256'][:16]}...",
        f"window: since {d['window']['since']}",
        f"searched commits: {d['searched_commits']}",
        "",
    ]
    for f in d["files"]:
        lines.append(f"{f['path']}")
        lines.append(
            f"  added lines: {f['added_lines']}, signatures: {len(f['signatures'])}, "
            f"candidates: {f['candidates']}"
        )
        if f["signatures"]:
            lines.append(f"  signature: {f['signatures'][0][:100]}")
        if f["best"]:
            b = f["best"]
            lines.append(f"  closest commit: {b['sha'][:12]} {b['date'][:10]} {b['subject']}")
            lines.append(f"  added-line overlap: {b['matched']}/{b['total']} ({b['ratio']:.1%})")
            for sample in b["matched_lines"]:
                lines.append(f"    = {sample}")
        lines.append(f"  present at HEAD: {f['head_present']}/{f['head_total']}")
        if f["note"]:
            lines.append(f"  note: {f['note']}")
        lines.append("")
    if d["verdict"] == "hit":
        lines.append("This patch body already exists upstream. Do not open a PR.")
    elif d["verdict"] == "clear":
        lines.append("No overlapping commit found in the window. This is a bounded negative result.")
    else:
        lines.append("Not enough distinctive added lines to search; inspect manually.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="preprcheck",
        description="Check whether a patch's body already exists in an upstream git history.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="audit one patch against one repository clone")
    p_audit.add_argument("--patch", required=True, help="path to a unified diff / patch.diff")
    p_audit.add_argument("--repo", required=True, help="path to a *full-history* git clone")
    p_audit.add_argument("--since-days", type=int, default=730, help="history window (default: 730)")
    p_audit.add_argument("--max-signatures", type=int, default=8, help="added lines used as pickaxes")
    p_audit.add_argument("--min-ratio", type=float, default=0.6, help="overlap ratio required for a hit")
    p_audit.add_argument("--max-commits", type=int, default=200, help="candidate commits inspected per file")
    p_audit.add_argument("--format", choices=("text", "json"), default="text")
    p_audit.add_argument("--output", help="write the report to this path instead of stdout")
    p_audit.add_argument("--allow-shallow", action="store_true", help="proceed even if the clone is shallow")

    sub.add_parser("version", help="print the version")

    args = parser.parse_args(argv)

    if args.command == "version":
        from . import __version__

        print(__version__)
        return 0

    try:
        if not is_git_repo(args.repo):
            print(f"error: not a git repository: {args.repo}", file=sys.stderr)
            return 2
        if not args.allow_shallow:
            from .gitprobe import git

            shallow = git(args.repo, "rev-parse", "--is-shallow-repository", check=False).stdout.strip()
            if shallow == "true":
                print(
                    "error: shallow clone cannot answer history questions; "
                    "re-clone with full history or pass --allow-shallow",
                    file=sys.stderr,
                )
                return 2
        with open(args.patch, encoding="utf-8", errors="replace") as fh:
            patch_text = fh.read()
        result = audit(
            args.repo,
            patch_text,
            since_days=args.since_days,
            max_signatures=args.max_signatures,
            min_ratio=args.min_ratio,
            max_commits=args.max_commits,
        )
    except (OSError, GitError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        text = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
    else:
        text = _render(result, args.repo)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)

    if result.verdict == "hit":
        return 1
    if result.verdict == "inconclusive":
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())