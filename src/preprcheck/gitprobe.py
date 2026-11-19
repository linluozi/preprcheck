"""Thin, deterministic wrapper around the git CLI.

Only read-only plumbing is used: ``git log -S``, ``git show`` and
``git rev-parse``.  Nothing in this module writes to the repository.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .diffparse import compact, parse_unified_diff


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str
    subject: str


def git(repo: str, *args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()[:300]}"
        )
    return proc


def is_git_repo(path: str) -> bool:
    try:
        return git(path, "rev-parse", "--git-dir", check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def head_sha(repo: str) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def commits_containing(
    repo: str, signature: str, path: str | None = None, since: str | None = None, timeout: int = 120
) -> list[Commit]:
    """Commits where the number of occurrences of ``signature`` changed.

    ``git log -S`` is a literal (non-regex) pickaxe; it is the only channel
    that catches a body line moved to a different function.
    """

    args = ["log", "--all", "--format=%H%x1f%aI%x1f%s"]
    if since:
        args.append(f"--since={since}")
    args.append(f"-S{signature}")
    if path:
        args.extend(["--", path])
    proc = git(repo, *args, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise GitError(f"git log -S failed: {proc.stderr.strip()[:300]}")
    commits: list[Commit] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            commits.append(Commit(sha=parts[0], date=parts[1], subject=parts[2]))
    return commits


def commit_added_lines(repo: str, sha: str, timeout: int = 120) -> dict[str, set[str]]:
    """Map path -> set of compact added lines for one commit."""

    proc = git(
        repo,
        "show",
        "--format=",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        sha,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        return {}
    out: dict[str, set[str]] = {}
    for fp in parse_unified_diff(proc.stdout):
        path = fp.path
        if not path:
            continue
        out.setdefault(path, set()).update(compact(line) for line in fp.added)
    return out


def head_text(repo: str, path: str, timeout: int = 60) -> str | None:
    proc = git(repo, "show", f"HEAD:{path}", timeout=timeout, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout