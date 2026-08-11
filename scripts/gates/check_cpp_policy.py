#!/usr/bin/env python3
"""C++ policy ratchet gate (M5  S1 / ) — the enforce-now, no-new-violations guardrail.

This is NOT the cleanup campaign: it pins the current C++ error-handling / RTTI / ownership
surface so it can only shrink, never grow. Three policies, all discovered STRUCTURALLY by walking
the source tree (no hand-maintained file list):

  - dynamic_cast        BANNED in include/ + lib/ + tools/ (hard zero; RTTI has no place in the
                        typed value/AST model — a `dynamic_cast` means a missing dialect/visitor).
  - throw_runtime_error per-file ceiling in lib/ (the throw / std::runtime_error error-handling
                        debt that D-lane wants migrated to Expected/diagnostics; may not increase).
  - shared_ptr          per-file ceiling in include/ + lib/ (compiler-model ownership; the
                        ProcedureView/AST ownership rework is deferred, so pin what exists).

Ratchet semantics (by EQUALITY, not an allowlist):
  - current > baseline  -> FAIL: a new violation (the file + delta is printed).
  - current < baseline  -> FAIL: an UNRECORDED REDUCTION — regenerate the baseline so the ceiling
                           moves DOWN (a win must be banked; the gate never silently forgives).
  - dynamic_cast is the degenerate hard-zero case (any occurrence fails).

Fail-closed (non-vacuous):
  - a scan that discovers fewer than FLOOR C++ files (wrong root / renamed tree) FAILS rather than
    passing empty;
  - a missing or malformed baseline FAILS.

Counting is over comment-stripped source (a `// throw` in a comment does not count), by MATCHING
LINES per file (grep -c semantics). Baseline is authored by this script — regenerate with
`--write-baseline` — so the committed counts always match what the checker computes.

    check_cpp_policy.py [--root DIR] [--baseline FILE] [--write-baseline]

Exit: 0 = clean; 1 = policy violation; 2 = fail-closed (floor / baseline missing or malformed).
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_BASELINE = os.path.join(HERE, "cpp_policy_baseline.json")

CPP_EXTS = (".cpp", ".h", ".cc", ".hpp", ".cxx", ".hh")
# Non-source subdirs that must never be scanned even if they appear under a policy dir.
SKIP_DIRS = {"build", "out", "CMakeFiles", ".git", "third_party", "external"}

# The minimum number of distinct C++ files the union scan must discover; a smaller result means the
# tree was not found (wrong --root, renamed dirs) and the gate fails closed rather than vacuously.
FLOOR_FILES = 20

# The policies. `dirs` are repo-relative roots to walk; `pattern` counts matching (comment-stripped)
# lines per file. Order is the report order.
POLICIES = [
    {
        "name": "dynamic_cast",
        "dirs": ["include", "lib", "tools"],
        "pattern": r"\bdynamic_cast\b",
        "hard_zero": True,
    },
    {
        "name": "throw_runtime_error",
        "dirs": ["lib"],
        "pattern": r"\bthrow\b|\bstd::runtime_error\b",
        "hard_zero": False,
    },
    {
        "name": "shared_ptr",
        "dirs": ["include", "lib"],
        "pattern": r"\bstd::shared_ptr\b",
        "hard_zero": False,
    },
    {
        # Raw `new` (M5  S4 / ). BANNED in compiler code: MLIR ops/attributes/types are
        # built through OpBuilder / the MLIRContext (context-owned, uniqued), never `new`; other heap
        # objects use std::make_unique / value ownership / arenas. The tree is at zero — the only
        # grep hits are inside string literals (rendered Solidity `new` in a generated test harness,
        # and the English word in a diagnostic), which the comment/string-aware scanner ignores — so
        # this is a hard-zero block, not a ratchet. `\bnew\b` matches the keyword only (not
        # `newFoo`/`renew`).
        "name": "raw_new",
        "dirs": ["include", "lib", "tools"],
        "pattern": r"\bnew\b",
        "hard_zero": True,
    },
]


def strip_comments(text: str, keep_string_content: bool = False) -> str:
    """Blank out C/C++ comments (and char / raw-string / string literal CONTENT), preserving line
    structure, so a token only counts when it is real code. This must be string-aware, not a naive
    regex: a `//` inside a string literal (`"http://x"`) does NOT start a comment, and a token after
    such a string must still be seen — otherwise the gate fails OPEN (a real `dynamic_cast` could be
    hidden behind a string containing `//`). Handles `//`, `/* */`, `"..."` (with escapes), `'...'`
    (char literals — critical: `'"'` must NOT be read as a string start), and C++ raw strings
    `R"delim( ... )delim"` (which appear in this tree, e.g. embedded schemas). Everything blanked is
    replaced space-for-space, newlines kept, so per-line counts stay aligned.

    keep_string_content: when True, the CONTENT of ordinary/raw string literals is preserved (comments
    and char literals are still blanked). The architecture scanner () needs this — a backend/domain
    NAME inside a string literal (`"solidity"`) in core IS coupling and must be seen — whereas the C++
    policy gate keeps the default (False), where a `dynamic_cast` inside a string is not real code."""
    def blank(seg: str) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in seg)

    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        # C++ raw string: R"delim( ... )delim" — the `R` immediately precedes the quote (possibly
        # after an encoding prefix like u8/L, which does not change detection).
        if c == '"' and i > 0 and text[i - 1] == "R":
            j = i + 1
            while j < n and text[j] != "(":
                j += 1
            delim = text[i + 1:j]
            close = ")" + delim + '"'
            end = text.find(close, j)
            end = n if end == -1 else end + len(close)
            seg = text[i:end]
            out.append(seg if keep_string_content else blank(seg))
            i = end
            continue
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(blank(text[i:j]))
            i = j
            continue
        if c == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append(blank(text[i:end]))
            i = end
            continue
        if c == '"' or c == "'":
            quote = c
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote or text[j] == "\n":
                    j += 1 if text[j] == quote else 0
                    break
                j += 1
            seg = text[i:j]
            # char literals ('...') are always blanked; ordinary strings ("...") are kept only when
            # keep_string_content is set (else blanked, the policy-gate default).
            out.append(seg if (keep_string_content and quote == '"') else blank(seg))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def cpp_files(root: str, rel_dir: str):
    base = os.path.join(root, rel_dir)
    if not os.path.isdir(base):
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(CPP_EXTS):
                full = os.path.join(dirpath, fn)
                yield os.path.relpath(full, root).replace(os.sep, "/")


def count_lines(path: str, rx: "re.Pattern") -> int:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return 0
    body = strip_comments(text)
    return sum(1 for line in body.splitlines() if rx.search(line))


def scan(root: str):
    """Return (per_policy_counts, total_distinct_files). per_policy_counts[name] = {relpath: n>0}."""
    counts = {}
    seen = set()
    for pol in POLICIES:
        rx = re.compile(pol["pattern"])
        files = {}
        for rel_dir in pol["dirs"]:
            for rel in cpp_files(root, rel_dir):
                seen.add(rel)
                n = count_lines(os.path.join(root, rel), rx)
                if n > 0:
                    files[rel] = n
        counts[pol["name"]] = files
    return counts, len(seen)


def load_baseline(path: str):
    if not os.path.isfile(path):
        return None, f"baseline not found: {path}"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, f"baseline is not valid JSON ({path}): {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("policies"), dict):
        return None, f"baseline is malformed (missing 'policies' object): {path}"
    for pol in POLICIES:
        p = data["policies"].get(pol["name"])
        if not isinstance(p, dict) or not isinstance(p.get("files"), dict):
            return None, f"baseline is malformed (policy '{pol['name']}' missing 'files'): {path}"
        for f, n in p["files"].items():
            if not isinstance(n, int) or n < 0:
                return None, f"baseline is malformed (bad count for '{f}' in '{pol['name']}')"
    return data, None


def build_baseline(counts: dict) -> dict:
    return {
        "_note": (
            "C++ policy ratchet baseline ( / ). AUTHORED BY scripts/gates/check_cpp_policy.py -- "
            "regenerate with `python3 scripts/gates/check_cpp_policy.py --write-baseline`. Ceilings may "
            "only move DOWN: a reduction must be banked by regenerating this file. dynamic_cast and "
            "raw_new are hard-zero. Do not hand-edit."
        ),
        "floor_files": FLOOR_FILES,
        "policies": {
            pol["name"]: {
                "dirs": pol["dirs"],
                "hard_zero": pol["hard_zero"],
                "files": dict(sorted(counts[pol["name"]].items())),
            }
            for pol in POLICIES
        },
    }


def diff_policy(name, hard_zero, current, baseline):
    """Return a list of (severity, message) for one policy."""
    problems = []
    files = sorted(set(current) | set(baseline))
    for f in files:
        cur = current.get(f, 0)
        base = baseline.get(f, 0)
        if cur == base:
            continue
        if cur > base:
            problems.append((
                "increase",
                f"[{name}] {f}: {cur} (baseline {base}, +{cur - base}) — new violation; "
                f"reduce it, do not raise the ceiling"
                + (f" — {name} is BANNED (hard zero)" if hard_zero else ""),
            ))
        else:
            problems.append((
                "reduction",
                f"[{name}] {f}: {cur} (baseline {base}, {cur - base}) — unrecorded reduction; "
                f"bank the win: regenerate scripts/gates/cpp_policy_baseline.json (--write-baseline)",
            ))
    return problems


def selftest(root: str, baseline: str) -> int:
    """Prove the ratchet is non-vacuous / fail-closed (): the clean tree passes the committed
    baseline, and an empty tree, a missing baseline, a malformed baseline, and each introduced
    violation (throw, a dynamic_cast hidden after a string containing '//', a raw new) all fail
    closed. Ported from the retired test/checks/cpp_policy.sh ( /  S5d); registered as the
    `cpp-policy` CTest test. Re-invokes this checker as a subprocess against temp trees, so it
    exercises the real gate exactly as a caller would."""
    import shutil
    import subprocess
    import tempfile

    me = [sys.executable, os.path.abspath(__file__)]

    def gate(root_arg: str, baseline_arg: str) -> int:
        return subprocess.run(
            me + ["--root", root_arg, "--baseline", baseline_arg],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode

    if not os.path.isfile(baseline):
        print(f"    FAIL: committed baseline not found: {baseline}", file=sys.stderr)
        return 1

    fails = []
    # 1. Clean tree passes against the committed baseline (the real acceptance).
    if gate(root, baseline) != 0:
        fails.append("clean tree does not pass the committed C++ policy baseline")

    tmp = tempfile.mkdtemp(prefix="cpp_policy_selftest.")
    try:
        # 2. An empty tree fails closed on the file floor (a zero-file scan cannot pass).
        empty = os.path.join(tmp, "empty")
        for d in ("include", "lib", "tools"):
            os.makedirs(os.path.join(empty, d))
        if gate(empty, baseline) == 0:
            fails.append("an empty tree passed the gate (vacuous scan not rejected)")

        # 3. A missing baseline fails closed.
        if gate(root, os.path.join(tmp, "nope.json")) == 0:
            fails.append("a missing baseline passed the gate")

        # 4. A malformed baseline fails closed.
        bad = os.path.join(tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{ not: json")
        if gate(root, bad) == 0:
            fails.append("a malformed baseline passed the gate")

        # 5-7. An INTRODUCED violation on an otherwise-clean copy is caught (copy the real dirs so the
        #      file floor is met, then append one probe to lib/targets/TestRealizationTarget.cpp).
        def inject_and_expect_caught(name: str, probe: str, label: str) -> None:
            dst = os.path.join(tmp, name)
            os.makedirs(dst)
            for d in ("include", "lib", "tools"):
                shutil.copytree(os.path.join(root, d), os.path.join(dst, d))
            with open(os.path.join(dst, "lib", "targets", "TestRealizationTarget.cpp"), "a",
                      encoding="utf-8") as fh:
                fh.write(probe)
            if gate(dst, baseline) == 0:
                fails.append(label)

        # 5. The ratchet bites an introduced throw.
        inject_and_expect_caught(
            "throw",
            '\nnamespace { void _cpp_policy_probe() { throw std::runtime_error("probe"); } }\n',
            "an introduced throw was not caught (ratchet is not biting)")
        # 6. Anti-fail-open: a real dynamic_cast (hard zero) hidden AFTER a string literal containing
        #    '//' must still be caught — the comment stripper is string-aware ( review Medium).
        inject_and_expect_caught(
            "strhide",
            '\nnamespace { void _hide(void *p) { const char *u = "http://x"; '
            '(void)dynamic_cast<int *>(p); (void)u; } }\n',
            "a dynamic_cast hidden after a string containing '//' was NOT caught (stripper fails open)")
        # 7. Raw `new` () is hard-zero: an introduced real heap allocation fails closed.
        inject_and_expect_caught(
            "rawnew",
            '\nnamespace { int *_rawnew_probe() { return new int(0); } }\n',
            "an introduced raw new was not caught (raw_new hard-zero not biting, )")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        print("cpp-policy selftest FAILED:", file=sys.stderr)
        for f in fails:
            print("    FAIL: " + f, file=sys.stderr)
        return 1
    print("    PASS (clean tree at/below baseline; empty tree + missing baseline + malformed "
          "baseline + an introduced throw + a string-hidden dynamic_cast + an introduced raw new "
          "all fail closed)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="C++ policy ratchet gate ()")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="repo root to scan (default: this repo)")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE, help="ratchet baseline JSON")
    ap.add_argument("--write-baseline", action="store_true",
                    help="(re)generate the baseline from the current tree, then exit 0")
    ap.add_argument("--selftest", action="store_true",
                    help="run the non-vacuous / fail-closed self-tests (the cpp-policy CTest gate)")
    args = ap.parse_args()

    if args.selftest:
        return selftest(args.root, args.baseline)

    counts, nfiles = scan(args.root)

    if args.write_baseline:
        with open(args.baseline, "w", encoding="utf-8") as fh:
            json.dump(build_baseline(counts), fh, indent=2)
            fh.write("\n")
        print(f"wrote {args.baseline} ({nfiles} C++ files scanned)")
        return 0

    # Fail closed: a scan that found too few files did not find the tree.
    if nfiles < FLOOR_FILES:
        print(f"error: discovered only {nfiles} C++ files under {args.root} "
              f"(floor {FLOOR_FILES}); refusing to pass a vacuous scan", file=sys.stderr)
        return 2

    baseline, err = load_baseline(args.baseline)
    if err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    if baseline.get("floor_files", FLOOR_FILES) != FLOOR_FILES:
        # informational only; the checker's floor is authoritative.
        pass

    problems = []
    for pol in POLICIES:
        base_files = baseline["policies"][pol["name"]]["files"]
        problems += diff_policy(pol["name"], pol["hard_zero"], counts[pol["name"]], base_files)

    if problems:
        print(f"C++ policy gate FAILED ({nfiles} files scanned):", file=sys.stderr)
        for _sev, msg in problems:
            print("  " + msg, file=sys.stderr)
        print("  (ratchet by equality: increases are new violations; decreases must be banked by "
              "regenerating the baseline)", file=sys.stderr)
        return 1

    total = {pol["name"]: sum(counts[pol["name"]].values()) for pol in POLICIES}
    summary = ", ".join(
        f"{pol['name']}={total[pol['name']]}" + (" (hard zero)" if pol["hard_zero"] else "")
        for pol in POLICIES)
    print(f"cpp policy OK: {nfiles} C++ files; {summary} "
          f"— all at or below the committed ratchet baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
