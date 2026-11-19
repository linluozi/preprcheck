# preprcheck

**Before you open a PR, check whether the body of your patch already exists in the upstream history.**

`preprcheck` takes a unified diff and a full-history clone of the upstream
repository. It extracts the patch's added lines, finds commits in which those
exact lines changed (`git log -S`), and scores every candidate by how much of
the patch's added-line set that commit also added. The verdict is `hit`,
`clear` or `inconclusive`, with the matching commit and the matched lines as
evidence.

Upstream: none

This is an original tool. It does not modify or vendor any upstream project.

## Why it exists

On 2026-11-18 a patch published from this account was closed by the upstream
maintainer with *"Already in c128aa5e"*. Our patch kept
`LRUCache.__touch()` and rewrote its body. Upstream had done the opposite: it
inlined the same five lines into `__setitem__()` and **deleted `__touch()`**.

Searching by function name, by changed file, or by commit message misses that
duplicate. Searching by the added-line set does not: the audit reports a 5/5
match. That is the failure mode this tool is built around, and it is the reason
the tool refuses shallow clones: `git log -S` cannot answer the question
without history.

## What it finds on real patches

Eight patches published from this account were audited against full-history
clones, 730-day window (raw data: `evidence/audit.json`, run log:
`evidence/audit.md`).

| published repo | upstream | verdict | added-line overlap | audit time |
|---|---|---|---|---|
| `linluozi/cachetools-lru-opt-lab` | `tkem/cachetools` | **hit** | 5/5 | 0.050 s |
| `linluozi/semver-opt-lab` | `python-semver/python-semver` | clear | — | 0.038 s |
| `linluozi/pyjson5-opt-lab` | `dpranke/pyjson5` | clear | — | 0.040 s |
| `linluozi/inflect-opt-lab` | `jaraco/inflect` | clear | — | 0.071 s |
| `linluozi/jsonpatch-apply-opt-lab` | `stefankoegl/python-json-patch` | clear | — | 0.090 s |
| `linluozi/markdown-opt-lab` | `Python-Markdown/markdown` | clear | — | 0.039 s |
| `linluozi/jsonschema-opt-lab` | `python-jsonschema/jsonschema` | clear | — | 0.072 s |
| `linluozi/glom-opt-lab` | `mahmoud/glom` | clear | — | 0.008 s |

The hit exists twice in the upstream clone, on two branches, with the same
`git patch-id` (`19324221d52295596531a861bdd84300178adc7e`):

```
598aaede07ea  dev/v7.3.x   Improve LRUCache.__setitem__() performance.
c128aa5e538b  master       Improve LRUCache.__setitem__() performance.
```

Because the tool searches `--all` refs, it sees both; a clone of only one
branch may see only one. This is a 1-in-8 sample, not a population estimate.

All seven `clear` rows had zero candidate commits: none of their added lines was introduced anywhere in
the 730-day window. That is expected for newly written code, but it remains a
bounded negative (see Limits).

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
python -m pytest -q          # 15 passed
```

No third-party runtime dependency; Python >= 3.9 and a `git` binary are enough.

## Use

```bash
# human-readable report; exit 1 means "already upstream, do not open a PR"
preprcheck audit --patch patch.diff --repo /path/to/full-history-clone

# machine-readable report
preprcheck audit --patch patch.diff --repo /path/to/full-history-clone \
                 --format json --output report.json

# widen the window (default 730 days)
preprcheck audit --patch patch.diff --repo /path/to/full-history-clone --since-days 3650

# a shallow clone is refused; override only if you accept a blind spot
preprcheck audit --patch patch.diff --repo /tmp/shallow --allow-shallow
```

Exit codes: `0` = clear, `1` = hit, `2` = usage/git error, `3` = inconclusive
(no distinctive added lines to search).

## How the decision is made

1. Parse every file in the unified diff; keep added lines, normalise trailing
   whitespace.
2. Pick up to eight *signatures*: added lines ranked by length and statement
   structure, with trivial lines (`pass`, `return None`, `else:`, ...) removed.
3. For each signature run `git log --all -S<line> -- <path>` and collect the
   commits where the number of occurrences of that line changed.
4. For the most-repeated candidates, parse the commit's own added lines and
   compute `|patch added lines ∩ commit added lines| / |patch added lines|`.
5. A commit is a `hit` when the overlap ratio is >= 0.60 and at least two added
   lines match (one, for a single-line patch). The current `HEAD` tree is
   checked independently and reported as `present at HEAD`.

Thresholds are configurable (`--min-ratio`, `--max-signatures`,
`--max-commits`, `--since-days`).

## Limits (read these before trusting a verdict)

- **`clear` is a bounded negative, not proof of novelty.** It means no commit
  in the searched window adds >= 60% of the patch's added lines. An upstream
  change that was reformatted, landed outside the window, or lives in a file
  path the clone does not have will not be found.
- `git log -S` is a literal pickaxe: changing whitespace *inside* a line
  defeats it, and it only fires when the number of occurrences changes. A pure
  move or reformat is invisible. One audited patch (`markdown-opt-lab`) has
  10 of its 41 added lines already at HEAD yet zero history candidates, which
  is consistent with moved code rather than an introduced body.
- The tool searches git history only. It does **not** query GitHub issues or
  PRs; that remains a manual step (`gh search issues`). This is deliberate:
  the check is local, network-free and deterministic.
- Candidate commits are capped per file (default 200) for predictable runtime.
- Eight real patches is a small sample; the hit rate is reported as 1/8, not as
  a general property of this account's output.

## 本轮创新

新在把「PR 前置查重」从函数名 / 文件名 / commit message 提升到 **added-line 集合**：8 个真实已发布补丁中，1 个（cachetools）补丁与上游 `c128aa5`（同 `patch-id` 的 `598aaed`）有 **5/5 行**重合，而上游是把同一函数体内联到 `__setitem__` 后**删掉** `__touch`——任何按名字或按文件的查重都会漏掉它。与台账里「PR 被关后写教训」不同，本工具在发布前以 exit 1 直接拦下；档位 **B**。

## Reproduce

```bash
# 1. install and test
python3 -m venv .venv && . .venv/bin/activate && pip install -e . pytest && python -m pytest -q

# 2. full-history clones + the eight real patches (commands in evidence/commands.txt)
python evidence/reproduce.py --clones /tmp/pc-up --out evidence/audit.json

# 3. shallow control: the same patch against a --depth=1 clone exits 2
git clone --depth=1 git@github-linluozi:tkem/cachetools.git /tmp/shallow-ct
preprcheck audit --patch evidence/patches/cachetools-lru-opt-lab.diff --repo /tmp/shallow-ct; echo $?
```

## Tests

`python -m pytest -q` -> **15 passed in 0.50 s**. Tests build real temporary git
repositories and cover: body moved to another function (hit), same file but no
line overlap (clear), only trivial lines (inconclusive), commit deletion,
CRLF/multi-file/new-file diffs, signature dedup, CLI JSON exit codes, and the
shallow-clone refusal.

## Environment

AMD EPYC 7K62 (4 vCPU), 3,723 MiB RAM, CPython 3.12.3, git 2.43.0.
Audit date 2026-11-19; window start 2024-11-19; eight upstream clones
(303–3,232 commits each, 1.1–4.8 MB `.git`). Total audit time 0.408 s.

## License

MIT. Original work; no upstream source is copied. See `LICENSE`.