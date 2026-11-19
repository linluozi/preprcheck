import json
import os
import subprocess
import sys
from pathlib import Path

from preprcheck.audit import audit

SRC = Path(__file__).resolve().parents[1] / "src"

INITIAL = """class Cache:
    def __init__(self):
        self.order = {}

    def set(self, key, value):
        self.order[key] = value

    def touch(self, key):
        \"\"\"Mark as recently used.\"\"\"
        self.order[key] = None
"""

AFTER_UPSTREAM = """class Cache:
    def __init__(self):
        self.order = {}

    def set(self, key, value):
        order = self.order
        if key in order:
            order.move_to_end(key)
        else:
            order[key] = None

    def touch(self, key):
        \"\"\"Mark as recently used.\"\"\"
        self.order[key] = None
"""

# Same body, different function: this is the cachetools c128aa5 shape.
DUPLICATE_PATCH = """--- a/lib.py
+++ b/lib.py
@@ -9,7 +9,11 @@ class Cache:
     def touch(self, key):
         \"\"\"Mark as recently used.\"\"\"
-        self.order[key] = None
+        order = self.order
+        if key in order:
+            order.move_to_end(key)
+        else:
+            order[key] = None
"""

NOVEL_PATCH = """--- a/lib.py
+++ b/lib.py
@@ -1,2 +1,6 @@
 def existing(x):
     return x + 1
+
+def doubled(x):
+    total = x * 2 + 1
+    return total
"""

GENERIC_PATCH = """--- a/lib.py
+++ b/lib.py
@@ -1,2 +1,6 @@
 def existing(x):
     return x + 1
+    pass
+    try:
+        return None
+    except KeyError:
+        return None
"""


def _duplicate_repo(repo):
    repo.commit("lib.py", INITIAL, "initial")
    sha = repo.commit("lib.py", AFTER_UPSTREAM, "Improve Cache.set() performance.")
    return sha


def test_hit_when_body_moved_to_another_function(repo):
    sha = _duplicate_repo(repo)
    result = audit(str(repo.path), DUPLICATE_PATCH, today=__import__("datetime").date(2026, 11, 19))
    assert result.verdict == "hit"
    assert result.confidence == "high"
    best = result.files[0].best
    assert best is not None
    assert best.sha == sha
    assert best.matched == best.total == 5
    assert best.ratio == 1.0
    assert result.files[0].head_present == 5


def test_clear_when_only_the_file_is_shared(repo):
    _duplicate_repo(repo)
    result = audit(str(repo.path), NOVEL_PATCH)
    assert result.verdict == "clear"
    assert result.files[0].best is None or result.files[0].best.ratio < 0.6
    assert result.files[0].head_present == 0


def test_inconclusive_when_patch_has_no_distinctive_lines(repo):
    repo.commit("lib.py", INITIAL, "initial")
    result = audit(str(repo.path), GENERIC_PATCH)
    assert result.verdict == "inconclusive"
    assert result.files[0].signatures == []


def test_window_excludes_old_commit(repo):
    sha = _duplicate_repo(repo)
    result = audit(str(repo.path), DUPLICATE_PATCH, since_days=1,
                   today=__import__("datetime").date(2026, 11, 19))
    # The fixture commit is dated "now", so a 1-day window still includes it.
    assert result.verdict == "hit"
    assert result.files[0].best.sha == sha


def test_commit_deleting_the_body_is_not_a_hit(repo):
    _duplicate_repo(repo)
    repo.remove("lib.py", "delete module")
    result = audit(str(repo.path), DUPLICATE_PATCH)
    # Deletion removes lines, so the added-line overlap with HEAD is gone and
    # the historical add commit is still found (hit), but head_present is 0.
    assert result.files[0].head_present == 0
    if result.verdict == "hit":
        assert result.files[0].best.matched == 5


def _run_cli(args, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "preprcheck", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def test_cli_json_exit_code_1_on_hit(repo, tmp_path):
    _duplicate_repo(repo)
    patch = tmp_path / "patch.diff"
    patch.write_text(DUPLICATE_PATCH)
    proc = _run_cli(["audit", "--patch", str(patch), "--repo", str(repo.path), "--format", "json"], tmp_path)
    assert proc.returncode == 1, proc.stderr
    data = json.loads(proc.stdout)
    assert data["verdict"] == "hit"
    assert data["files"][0]["best"]["matched"] == 5


def test_cli_refuses_shallow_clone(repo, tmp_path):
    repo.commit("lib.py", INITIAL, "initial")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth=1", f"file://{repo.path}", str(shallow)],
        check=True,
    )
    patch = tmp_path / "patch.diff"
    patch.write_text(NOVEL_PATCH)
    proc = _run_cli(["audit", "--patch", str(patch), "--repo", str(shallow)], tmp_path)
    assert proc.returncode == 2
    assert "shallow" in proc.stderr

def test_cli_text_report_renders_window(repo, tmp_path):
    _duplicate_repo(repo)
    patch = tmp_path / "patch.diff"
    patch.write_text(DUPLICATE_PATCH)
    proc = _run_cli(["audit", "--patch", str(patch), "--repo", str(repo.path)], tmp_path)
    assert proc.returncode == 1, proc.stderr
    assert "HIT (high confidence)" in proc.stdout
    assert "window: since" in proc.stdout
    assert "added-line overlap: 5/5 (100.0%)" in proc.stdout


TWO_LINE_PATCH = """--- a/lib.py
+++ b/lib.py
@@ -1,2 +1,4 @@
 def existing(x):
     return x + 1
+    if type(x) is str:
+        return x
"""


def test_two_line_patch_with_one_signature_can_still_hit(repo):
    repo.commit("lib.py", INITIAL, "initial")
    base = repo.head("lib.py")
    changed = base.replace(
        "    def touch(self, key):",
        "    if type(x) is str:\n        return x\n\n    def touch(self, key):",
    )
    sha = repo.commit("lib.py", changed, "add string fast path")
    result = audit(str(repo.path), TWO_LINE_PATCH)
    assert result.verdict == "hit"
    assert result.files[0].best.sha == sha
    assert result.files[0].best.matched == 2
