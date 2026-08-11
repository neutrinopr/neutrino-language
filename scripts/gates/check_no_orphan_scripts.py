#!/usr/bin/env python3
"""No-orphan-script reachability gate (M5 scripts B4, ).

Every committed script under the managed roots (`scripts/**/*.py`, `scripts/**/*.sh`, `test/**/*.py`)
must be REACHABLE from a real INVOKER, or carry a small documented manual-only exemption. This is the
durable anti-cruft ratchet the  bash teardown + the  inventory earned: a committed script that no
lit test / CTest / CI workflow / make target / other live script invokes is dead weight CI keeps building
and shipping, and the sprawl silently regrows. This gate fails closed on one.

Reachability is deliberately conservative — an INVOCATION, not mere textual awareness ( review):

  * References are read only from INVOCATION CONTEXTS: `#`-comments (and, for `.py`, triple-quoted
    docstrings) are stripped, and a lit fixture contributes only its `RUN:` lines — so a filename in a
    comment / docstring / assertion string / migration note does NOT grant reachability.
  * Identity is PATH-AWARE: a repo-relative path (`scripts/…`, `test/…`, `%scripts/…`, or a lit `%S/…`
    resolved against the fixture's own dir) resolves that EXACT script; a bare-basename reference
    (`python3 foo.py`, `import foo`) resolves a script only when that basename is UNIQUE among the
    managed set — an ambiguous basename marks NOTHING reachable (the repo has many duplicate basenames,
    e.g. scripts/check_artifact_pins.py vs test/ir/compat/check_artifact_pins.py).
  * Reachability is TRANSITIVE but only THROUGH reachable scripts — a script referenced only by an orphan
    is itself an orphan.
  * `test/checks/fast/*_test.py` are reachable via the `fast` CTest's `unittest discover -p *_test.py`.

The ALLOWLIST is kept minimal + HONEST: a stale entry (no longer a committed script) or a redundant one
(actually reachable) also fails, and this gate excludes its OWN file from the corpus (its allowlist NAMES
a script to exempt it, not to invoke it).

Usage: check_no_orphan_scripts.py [--selftest]   (exit 0 ok / 1 violations)
"""
import ast
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELF_REL = os.path.relpath(os.path.abspath(__file__), REPO)
MIN_MANAGED = 120  # floor: managed set is ~154; a collapse toward zero = mis-scan, fail closed.
FAST_DISCOVER_DIR = "test/checks/fast"

ALLOWLIST = {
    "scripts/validate-slot-fixtures.sh":
        "documented manual slot-authoring validator — invoked by hand per docs/spec/"
        "SLOT_ARTIFACT_CONTRACT.md + examples/binding-manifests/README.md; its cross-layout "
        "\"every slot dir has the required files + valid JSON + envelope-schema conformance\" sweep is "
        "broader than the per-domain byte-golden slot tests (B2 retained it; B4 exempts it).",
}

# A repo-relative script path (incl. the lit `%scripts/` substitution). Path-aware -> exact target. The
# lookbehind allows a leading `/` (a path separator, e.g. `${PROJECT_SOURCE_DIR}/scripts/…`) but not a
# word char (so `myscripts/` is not mis-read as `scripts/`).
_REL_PATH = re.compile(r"(?:%scripts/|(?<![\w.-])(?:scripts|test)/)[\w./-]+\.(?:py|sh)")
# A lit `%S/foo.py` or `%S/Inputs/foo.py` — `%S` is the fixture's OWN source dir,
# so the complete relative suffix resolves against that dir.
_S_SUB = re.compile(r"%S/([\w.-]+(?:/[\w.-]+)*\.(?:py|sh))")
# A bare basename (`python3 foo.py`, `bash foo.sh`) — resolves only if the basename is unique.
_BASENAME = re.compile(r"(?<![\w./-])([\w-]+\.(?:py|sh))\b")
# A python import -> the module's basename.
_PY_IMPORT = re.compile(r"(?m)^\s*(?:import|from)\s+([\w.]+)")
_TRIPLE = re.compile(r'"""[\s\S]*?"""' + r"|'''[\s\S]*?'''")


def managed_scripts():
    out = set()
    for pat in ("scripts/**/*.py", "scripts/**/*.sh", "test/**/*.py"):
        out |= {os.path.relpath(f, REPO).replace(os.sep, "/")
                for f in glob.glob(os.path.join(REPO, pat), recursive=True)}
    return out


def _read(rel):
    try:
        return open(os.path.join(REPO, rel), encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def _invocation_text(text, is_lit, is_py):
    """Only the invocation-bearing text: for lit, just `RUN:` lines; for `.py`, docstrings removed; then
    `#`-to-EOL comments stripped. So a name in prose / a comment / a docstring is NOT an invocation."""
    if is_lit:
        # a lit fixture invokes scripts on RUN: lines AND DEFINE: lines (a DEFINE binds a %{sub} that a
        # RUN line then executes, e.g. `// DEFINE: %{par} = %scripts/gates/check_x.py`).
        text = "\n".join(ln for ln in text.splitlines() if "RUN:" in ln or "DEFINE:" in ln)
    if is_py:
        text = _TRIPLE.sub(" ", text)
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())


def refs_of(text, containing_dir, is_lit):
    """entrypoint / shell reference model: a conservative line/token scan. `#`-comments (and, for lit,
    all but RUN:/DEFINE: lines) are dropped; path + basename tokens are then read from the remainder."""
    code = _invocation_text(text, is_lit, is_py=False)
    paths, bases = set(), set()
    for m in _REL_PATH.finditer(code):
        paths.add(m.group(0).replace("%scripts/", "scripts/"))
    for m in _S_SUB.finditer(code):
        paths.add(os.path.normpath(os.path.join(containing_dir, m.group(1))).replace(os.sep, "/"))
    for m in _BASENAME.finditer(code):
        bases.add(m.group(1))
    for m in _PY_IMPORT.finditer(code):
        bases.add(m.group(1).split(".")[-1] + ".py")
    return paths, bases


_EXEC_FUNCS = {
    # stdlib process execution
    "run", "call", "check_call", "check_output", "Popen", "system",
    "execv", "execvp", "execl", "execlp", "execle", "spawnv", "spawnl",
    # the repo's own test execution wrappers (test/checks/fast/_fastcase.py): each runs a script named in
    # a string argument. `val_ok(desc, script, *args)` / `val_reject(...)` put the script in arg[1];
    # `assert_ok(desc, *cmd)` / `run_cmd(*cmd)` put it among the cmd tokens — so collecting ALL string
    # args + the path/basename regex resolves the script (the `desc`/flag strings never match a path).
    "val_ok", "val_reject", "assert_ok", "assert_reject", "run_cmd",
}


def _arg_strings(nodes):
    out = []
    for a in nodes:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            out.append(a.value)
        elif isinstance(a, (ast.List, ast.Tuple, ast.Set)):
            out += _arg_strings(a.elts)
    return out


def py_refs(text):
    """Python SCRIPT reference model — INVOCATION-AWARE via AST, not a scan of residual source text
    ( review): edges come ONLY from `import`/`from … import` (module -> `<name>.py`) and from the
    string arguments of known execution calls (`subprocess.run/Popen/…`, `os.system/exec*`). An ordinary
    constant used by print / an assertion / a diagnostic / fixture data does NOT create an edge."""
    paths, bases = set(), set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return paths, bases
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                bases.add(n.name.split(".")[-1] + ".py")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                bases.add(node.module.split(".")[-1] + ".py")
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if fname in _EXEC_FUNCS:
                for s in _arg_strings(node.args):
                    for m in _REL_PATH.finditer(s):
                        paths.add(m.group(0).replace("%scripts/", "scripts/"))
                    for m in _BASENAME.finditer(s):
                        bases.add(m.group(1))
    return paths, bases


def script_refs(rel, text):
    """A reachable SCRIPT's outgoing edges: AST-based for `.py`, the conservative line model for `.sh`."""
    return py_refs(text) if rel.endswith(".py") else refs_of(text, os.path.dirname(rel), is_lit=False)


def _resolve(paths, bases, managed, by_base):
    """Map a set of path/basename refs to the managed scripts they invoke — path-aware, unique-basename."""
    hit = set()
    for p in paths:
        if p in managed:
            hit.add(p)
    for b in bases:
        cands = by_base.get(b, ())
        if len(cands) == 1:                 # ambiguous basenames resolve NOTHING (require a path)
            hit.add(cands[0])
    return hit


def reachable_set(managed, entrypoints, allowlist, read):
    """entrypoints: list of (relpath, text). read(relpath)->text for scripts. Return the reachable set.

    Seed from the entrypoints (+ the fast-discover glob + the allowlisted MANUAL entrypoints, whose
    documented `bash …`/`exec` invocations are real), then follow refs THROUGH reachable scripts only.
    This gate's OWN file never contributes refs (it documents/exempts, it does not invoke)."""
    by_base = {}
    for m in managed:
        by_base.setdefault(os.path.basename(m), []).append(m)

    reach = {m for m in managed
             if m.startswith(FAST_DISCOVER_DIR + "/") and m.endswith("_test.py")}
    # An allowlisted script is a documented MANUAL entrypoint, so scripts IT invokes (a wrapper it execs)
    # are reachable through it — that keeps the allowlist to the chain's ROOT, not every wrapper link.
    reach |= {a for a in allowlist if a in managed}
    for rel, text in entrypoints:
        is_lit = rel.endswith((".test", ".neu", ".mlir"))
        paths, bases = refs_of(text, os.path.dirname(rel), is_lit)
        reach |= _resolve(paths, bases, managed, by_base)

    changed = True
    while changed:
        changed = False
        for src in list(reach):
            if src == SELF_REL:
                continue
            paths, bases = script_refs(src, read(src))
            for m in _resolve(paths, bases, managed, by_base) - reach:
                reach.add(m)
                changed = True
    return reach


def check(managed, entrypoints, allowlist, read):
    reasons = []
    reach = reachable_set(managed, entrypoints, allowlist, read)
    # for the redundancy check: is an allowlisted script reachable from a REAL entrypoint on its own,
    # WITHOUT the manual-only exemption seeding it? If so, the exemption is redundant.
    reach_no_allow = reachable_set(managed, entrypoints, {}, read)
    for m in sorted(managed - reach - set(allowlist)):
        reasons.append(f"[orphan.unreachable] {m}: not INVOKED from any entrypoint "
                       "(make/ctest/ci/lit) nor another reachable script, and not in the manual-only "
                       "allowlist — remove it, wire it to an entrypoint, or add a reviewed allowlist entry")
    for a in sorted(allowlist):
        if a not in managed:
            reasons.append(f"[orphan.stale_allowlist] {a}: allowlisted but no longer a committed script "
                           "— remove the stale exemption")
        elif a in reach_no_allow:
            reasons.append(f"[orphan.redundant_allowlist] {a}: allowlisted but IS reachable from an "
                           "entrypoint — drop the exemption (the allowlist must stay minimal)")
    return reasons


def _entrypoint_files():
    files = ["Makefile"]
    for pat in (".github/workflows/*.yml", "**/CMakeLists.txt", "cmake/*.cmake",
                "test/**/*.test", "test/**/*.neu", "test/**/*.mlir", "test/**/*.cfg.py"):
        files += [os.path.relpath(f, REPO).replace(os.sep, "/")
                  for f in glob.glob(os.path.join(REPO, pat), recursive=True)]
    return files


def run():
    managed = managed_scripts()
    if len(managed) < MIN_MANAGED:
        print(f"no-orphan-script gate: found only {len(managed)} managed scripts (< {MIN_MANAGED}) — "
              "mis-scan / glob drift?", file=sys.stderr)
        return 1
    entrypoints = [(f, _read(f)) for f in _entrypoint_files()]
    reasons = check(managed, entrypoints, ALLOWLIST, _read)
    if reasons:
        print("no-orphan-script gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    print(f"no-orphan-script gate OK: all {len(managed)} committed scripts invoked from an entrypoint "
          f"(or in the {len(ALLOWLIST)}-entry documented manual-only allowlist)")
    return 0


def selftest():
    """Prove the gate BITES (non-vacuous) on a synthetic world served by a dict `read`."""
    if run() != 0:
        print("selftest: the current tree does not pass the gate", file=sys.stderr)
        return 1
    fails = []

    world = {
        # entrypoint-invoked live script -> transitively pulls in dep via a real subprocess call.
        "scripts/live.py": "subprocess.run(['python3', 'scripts/dep.py'])",
        "scripts/dep.py": "print('helper')",
        # an orphan-ROOTED chain: orphan -> dead_chain -> orphan2, with NO entrypoint edge to orphan.
        "scripts/orphan.py": "subprocess.run(['python3', 'scripts/dead_chain.py'])",
        "scripts/dead_chain.py": "subprocess.run(['python3', 'scripts/orphan2.py'])",
        "scripts/orphan2.py": "print('deep')",
        # P1b: a REACHABLE live script that only MENTIONS an orphan — in a docstring, a `#` comment, an
        # ordinary print string, AND an assertion message — must NOT reach it (AST: no import/exec edge).
        "scripts/prose.py": (
            "'''docstring mentions scripts/prose_orphan.py'''\n"
            "# comment mentions scripts/prose_orphan.py\n"
            "print('see scripts/prose_orphan.py for migration history')\n"
            "assert True, 'scripts/prose_orphan.py should not be produced'\n"),
        "scripts/prose_orphan.py": "print('orphan')",
        # P1a: two DIFFERENT scripts share basename dup.py; only the path-qualified one is reachable.
        "scripts/dup.py": "print('root dup')",
        "test/ir/x/dup.py": "print('test dup')",
        # A common lit layout keeps helpers below the fixture's Inputs/ directory.
        "test/ir/x/Inputs/nested.py": "print('nested helper')",
    }
    read = lambda rel: world.get(rel, "")  # noqa: E731
    managed = set(world)
    # entrypoints: only live.py is invoked, plus a lit RUN line that path-qualifies test/ir/x/dup.py.
    entrypoints = [
        ("Makefile", "run:\n\tpython3 scripts/live.py\n\tpython3 scripts/prose.py"),
        ("test/ir/x/dup.test",
         "// RUN: python3 %S/dup.py\n"
         "// RUN: python3 %S/Inputs/nested.py\n"
         "// a comment mentioning scripts/dup.py must not count"),
    ]
    got = check(managed, entrypoints, {}, read)

    def flagged(path):
        return any(f"[orphan.unreachable] {path}:" in r for r in got)

    for want_orphan in ("scripts/orphan.py", "scripts/dead_chain.py", "scripts/orphan2.py",
                        "scripts/prose_orphan.py", "scripts/dup.py"):
        if not flagged(want_orphan):
            fails.append(f"{want_orphan} should be flagged unreachable")
    for want_reach in ("scripts/live.py", "scripts/dep.py", "test/ir/x/dup.py",
                       "test/ir/x/Inputs/nested.py"):
        if flagged(want_reach):
            fails.append(f"{want_reach} must NOT be flagged (it is invoked / path-qualified)")

    # stale + redundant allowlist entries.
    if not any("orphan.stale_allowlist" in r for r in check(managed, entrypoints, {"scripts/gone.py": "x"}, read)):
        fails.append("a nonexistent allowlist entry should be flagged stale")
    if not any("orphan.redundant_allowlist" in r for r in check(managed, entrypoints, {"scripts/live.py": "x"}, read)):
        fails.append("a reachable allowlist entry should be flagged redundant")

    if fails:
        print("no-orphan-script SELFTEST FAILED:", file=sys.stderr)
        for f in fails:
            print(f"    {f}", file=sys.stderr)
        return 1
    print("no-orphan-script selftest PASS (real tree clean; an orphan-rooted chain (orphan -> dead_chain "
          "-> orphan2), a name mentioned only in a comment / docstring / ordinary print string / assertion "
          "message, and the wrong half of a duplicate basename all stay unreachable; direct and nested "
          "path-qualified + transitively-invoked (import/exec) scripts pass; stale/redundant allowlist "
          "entries fail closed)")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else run())
