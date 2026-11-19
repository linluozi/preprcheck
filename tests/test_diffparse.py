from preprcheck.diffparse import compact, parse_unified_diff, signature_lines


MULTI = """diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -1,3 +1,4 @@
 x = 1
-old = 2
+new = 2
+extra = 3
 y = 3
diff --git a/b.py b/b.py
new file mode 100644
--- /dev/null
+++ b/b.py
@@ -0,0 +1,2 @@
+def f():
+    return 1
"""


def test_parse_multiple_files_and_counts():
    files = parse_unified_diff(MULTI)
    assert [f.path for f in files] == ["a.py", "b.py"]
    assert files[0].added == ["new = 2", "extra = 3"]
    assert files[0].removed == ["old = 2"]
    assert files[1].added == ["def f():", "    return 1"]
    assert files[1].old_path is None


def test_added_line_that_looks_like_a_header_is_not_a_header():
    patch = """--- a/c.py
+++ b/c.py
@@ -1,2 +1,3 @@
 line = 1
+++i
+total += 1
"""
    files = parse_unified_diff(patch)
    assert len(files) == 1
    assert files[0].added == ["++i", "total += 1"]


def test_crlf_input():
    files = parse_unified_diff(MULTI.replace("\n", "\r\n"))
    assert files[0].added == ["new = 2", "extra = 3"]


def test_compact_ignores_indent_but_norm_does_not():
    assert compact("    if key in order:") == "ifkeyinorder:"
    assert compact("if key in order:") == "ifkeyinorder:"
    from preprcheck.diffparse import norm

    assert norm("a  b  ") == "a  b"


def test_signatures_skip_trivial_and_short_lines():
    sigs = signature_lines(["pass", "return None", "x = 1", "self._cache = {}", "if key in order:"])
    assert [s.raw for s in sigs] == ["self._cache = {}", "if key in order:"]


def test_signatures_deduplicate_same_body_with_different_indent():
    sigs = signature_lines(["    order[key] = None", "        order[key] = None"])
    assert len(sigs) == 1
    assert sigs[0].key == "order[key]=None"