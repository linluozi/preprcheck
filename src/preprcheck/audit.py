"""Decide whether a patch is already present in an upstream repository.

Two independent, local channels are used:

1. **history** -- for each distinctive added line, ``git log -S<line>`` finds
   commits where that exact line was introduced or removed.  Commits are then
   scored by how much of the patch's *added-line set* they also add.  This
   catches the case where upstream implemented the same body inside a
   different function and deleted the original one.
2. **head** -- how many of the patch's added lines already exist verbatim in
   the current HEAD tree.

The verdict is deliberately conservative: ``hit`` requires a commit in the
window that adds at least ``min_ratio`` of the patch's added lines and at
least two of them (one, for single-line patches).  Everything else is
``clear`` (no overlap found) or ``inconclusive`` (nothing distinctive to
search for).  ``clear`` is not a proof of novelty; it is a bounded negative
result over the searched window.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from .diffparse import FilePatch, compact, norm, parse_unified_diff, signature_lines
from .gitprobe import Commit, GitError, commit_added_lines, commits_containing, head_sha, head_text


@dataclass
class BestMatch:
    sha: str
    date: str
    subject: str
    matched: int
    total: int
    ratio: float
    matched_lines: list[str] = field(default_factory=list)


@dataclass
class FileResult:
    path: str
    added_lines: int
    signatures: list[str]
    candidates: int
    best: BestMatch | None
    head_present: int
    head_total: int
    note: str = ""


@dataclass
class AuditResult:
    repo: str
    head: str
    patch_sha256: str
    since: str
    files: list[FileResult]
    verdict: str
    confidence: str
    elapsed_s: float
    searched_commits: int
    min_ratio: float = 0.6

    def to_dict(self) -> dict:
        return {
            "schema": "preprcheck/audit/v1",
            "repo": self.repo,
            "head": self.head,
            "patch_sha256": self.patch_sha256,
            "window": {"since": self.since},
            "min_ratio": self.min_ratio,
            "files": [
                {
                    "path": f.path,
                    "added_lines": f.added_lines,
                    "signatures": f.signatures,
                    "candidates": f.candidates,
                    "best": None
                    if f.best is None
                    else {
                        "sha": f.best.sha,
                        "date": f.best.date,
                        "subject": f.best.subject,
                        "matched": f.best.matched,
                        "total": f.best.total,
                        "ratio": round(f.best.ratio, 4),
                        "matched_lines": f.best.matched_lines,
                    },
                    "head_present": f.head_present,
                    "head_total": f.head_total,
                    "note": f.note,
                }
                for f in self.files
            ],
            "verdict": self.verdict,
            "confidence": self.confidence,
            "searched_commits": self.searched_commits,
            "elapsed_s": round(self.elapsed_s, 3),
        }


def _path_matches(candidate: str, wanted: str) -> bool:
    if candidate == wanted:
        return True
    # Renames: patch path may be the new path, commit path the old one.  Only
    # accept a suffix match when the basename is identical and non-trivial.
    a, b = candidate.rsplit("/", 1)[-1], wanted.rsplit("/", 1)[-1]
    return a == b and len(a) > 3


def _audit_file(
    repo: str,
    fp: FilePatch,
    since: str,
    max_signatures: int,
    min_ratio: float,
    max_commits: int,
) -> tuple[FileResult, int]:
    path = fp.path or "<unknown>"
    added = [norm(line) for line in fp.added if norm(line).strip()]
    keys = {compact(line) for line in added}
    sigs = signature_lines(added, max_signatures=max_signatures)

    if not added:
        return FileResult(path, 0, [], 0, None, 0, 0, "no added lines"), 0
    if not sigs:
        return FileResult(path, len(added), [], 0, None, 0, 0, "no distinctive added lines"), 0

    hits: dict[str, set[str]] = {}
    meta: dict[str, Commit] = {}
    for sig in sigs:
        for commit in commits_containing(repo, sig.raw, path=path, since=since):
            hits.setdefault(commit.sha, set()).add(sig.key)
            meta.setdefault(commit.sha, commit)

    ordered = sorted(hits.items(), key=lambda kv: (-len(kv[1]), meta[kv[0]].date))
    ordered = ordered[:max_commits]

    total = len(keys)
    best: BestMatch | None = None
    searched = 0
    for sha, matched_sigs in ordered:
        if len(matched_sigs) < 2 and total > 1:
            # A single shared line is weak evidence; keep looking for a commit
            # that shares several added lines.
            continue
        added_map = commit_added_lines(repo, sha)
        searched += 1
        commit_paths = [p for p in added_map if _path_matches(p, path)]
        if not commit_paths:
            continue
        commit_added = set().union(*(added_map[p] for p in commit_paths))
        matched = keys & commit_added
        if not matched:
            continue
        ratio = len(matched) / total
        ordered_lines = [line for line in added if compact(line) in matched][:3]
        if best is None or (ratio, len(matched)) > (best.ratio, best.matched):
            best = BestMatch(
                sha=sha,
                date=meta[sha].date,
                subject=meta[sha].subject,
                matched=len(matched),
                total=total,
                ratio=ratio,
                matched_lines=ordered_lines,
            )
        if best.ratio >= 0.999:
            break

    head = head_text(repo, path)
    if head is None:
        head_present, head_total = 0, total
        note = "file absent at HEAD"
    else:
        head_keys = {compact(line) for line in head.splitlines()}
        head_present = len(keys & head_keys)
        head_total = total
        note = ""

    if best is not None and best.ratio >= min_ratio and best.matched >= (2 if total > 1 else 1):
        confidence = "high" if best.ratio >= 0.8 and best.matched >= 3 else "medium"
        return FileResult(path, total, [s.raw for s in sigs], len(ordered), best, head_present, head_total, note), searched
    return FileResult(path, total, [s.raw for s in sigs], len(ordered), best, head_present, head_total, note), searched


def audit(
    repo: str,
    patch_text: str,
    since_days: int = 730,
    max_signatures: int = 8,
    min_ratio: float = 0.6,
    max_commits: int = 200,
    today: date | None = None,
) -> AuditResult:
    started = time.perf_counter()
    files = [fp for fp in parse_unified_diff(patch_text) if fp.path]
    since = (today or date.today()) - timedelta(days=max(0, since_days))
    since_s = since.isoformat()

    results: list[FileResult] = []
    searched = 0
    for fp in files:
        result, n = _audit_file(repo, fp, since_s, max_signatures, min_ratio, max_commits)
        results.append(result)
        searched += n

    def _is_hit(r: FileResult) -> bool:
        if r.best is None or r.best.ratio < min_ratio:
            return False
        return r.best.matched >= (2 if r.best.total > 1 else 1)

    hits = [r for r in results if _is_hit(r)]
    if hits:
        best_hit = max(hits, key=lambda r: r.best.ratio)
        verdict = "hit"
        confidence = "high" if best_hit.best.ratio >= 0.8 else "medium"
    elif not any(r.signatures for r in results):
        verdict = "inconclusive"
        confidence = "low"
    else:
        verdict = "clear"
        confidence = "medium" if searched >= 5 else "low"

    return AuditResult(
        repo=repo,
        head=head_sha(repo),
        patch_sha256=hashlib.sha256(patch_text.encode("utf-8")).hexdigest(),
        since=since_s,
        files=results,
        verdict=verdict,
        confidence=confidence,
        elapsed_s=time.perf_counter() - started,
        searched_commits=searched,
        min_ratio=min_ratio,
    )


__all__ = ["audit", "AuditResult", "FileResult", "BestMatch", "GitError"]