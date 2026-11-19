"""Unified-diff parsing with just enough structure for history matching.

The parser does not try to be a patch *applier*.  It only needs the set of
added lines per file, because those are the lines a duplicate upstream commit
would also have had to add.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


@dataclass
class FilePatch:
    old_path: str | None = None
    new_path: str | None = None
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def path(self) -> str | None:
        return self.new_path or self.old_path


def _strip_prefix(path: str) -> str | None:
    path = path.strip()
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        path = path[1:-1]
        if path.startswith(("a/", "b/")):
            path = path[2:]
    return path


def parse_unified_diff(text: str) -> list[FilePatch]:
    """Return one FilePatch per file in a unified/git diff.

    Handles multiple files, new/deleted files (``/dev/null``), CRLF input and
    ``diff --git`` preambles.  Hunk bodies are parsed literally: a line is
    added iff it starts with ``+`` and we are inside a hunk.
    """

    files: list[FilePatch] = []
    cur: FilePatch | None = None
    in_hunk = False
    pending_old: str | None = None
    have_old = False

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("diff --git "):
            cur = None
            in_hunk = False
            have_old = False
            continue
        if line.startswith("--- ") and not in_hunk:
            pending_old = _strip_prefix(line[4:])
            have_old = True
            continue
        if line.startswith("+++ ") and have_old:
            cur = FilePatch(old_path=pending_old, new_path=_strip_prefix(line[4:]))
            files.append(cur)
            have_old = False
            in_hunk = False
            continue
        if cur is not None and _HUNK_RE.match(line):
            in_hunk = True
            continue
        if cur is None or not in_hunk:
            continue
        if line.startswith("+"):
            cur.added.append(line[1:])
        elif line.startswith("-"):
            cur.removed.append(line[1:])
        elif line.startswith("\\"):
            # "\ No newline at end of file"
            continue
    return files


def norm(line: str) -> str:
    """Strip trailing whitespace only; internal spacing is meaningful for -S."""
    return line.rstrip()


def compact(line: str) -> str:
    """Whitespace-free form used for equality across indentation styles."""
    return "".join(line.split())


@dataclass(frozen=True)
class Signature:
    raw: str   # exactly as it appears in the patch (used with git log -S)
    key: str   # compact form (used for commit-body overlap)
    score: int


# Lines that say nothing about *which* change was made.
_TRIVIAL = {
    "pass",
    "break",
    "continue",
    "return",
    "returnNone",
    "returnTrue",
    "returnFalse",
    "else:",
    "try:",
    "finally:",
    "except:",
    "exceptException:",
    "exceptKeyError:",
    ")",
    "}",
    "]",
    "):",
}


def _specificity(line: str) -> int:
    key = compact(line)
    if len(key) < 10 or key in _TRIVIAL:
        return 0
    alnum = sum(ch.isalnum() or ch == "_" for ch in key)
    if alnum < 4:
        return 0
    # Prefer lines that look like statements/expressions over prose comments.
    structural = sum(ch in "=().[]{}:" for ch in key)
    return len(key) + 12 * structural


def signature_lines(added: list[str], max_signatures: int = 8) -> list[Signature]:
    """Pick the most distinctive added lines, deduplicated by compact form."""

    seen: set[str] = set()
    scored: list[Signature] = []
    for line in added:
        raw = norm(line)
        key = compact(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        score = _specificity(raw)
        if score <= 0:
            continue
        scored.append(Signature(raw=raw, key=key, score=score))
    scored.sort(key=lambda s: (-s.score, -len(s.key)))
    return scored[:max_signatures]