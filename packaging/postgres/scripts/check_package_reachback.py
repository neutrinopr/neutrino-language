#!/usr/bin/env python3
"""Fail-closed reach-back audit for the standalone PostgreSQL backend package ().

Proves the extracted package's DECLARED dependency surface is COMPLETE: every
`#include` in every file the extraction manifest owns resolves to one of

  * the package's own headers (public or internal), its own generated/carve-out
    `.inc`, or a build-time generated `.inc` it declares;
  * a DECLARED public-core header (`sharedLeafLinkDeps.consumedPublicCoreHeaders`)
    or a DECLARED package-internal header
    (`publicCoreContract.packageInternalNotExported.headers`);
  * a true external (`llvm/...`, `mlir/...`, or an angled header with no `/` —
    the C/C++ standard library).

Anything else is UNDECLARED TRANSLATOR-TREE / PRIVATE-HEADER REACH-BACK and the
audit fails closed. In particular a reach into a sibling backend header, an
undeclared `Neutrino/...` header, or a relative path that escapes the unit
(`../`, an absolute path, or a bare `lib/...`) is a reach-back — exactly the
class a clean clone (with only the declared surface present) would fail to
compile against.

The audit is MANIFEST-DRIVEN: the allow-lists come from
`packaging/postgres/extraction-manifest.json`, so the audit can never drift from
the declared contract without the manifest changing too. It mirrors the direct
`#include` scan of `scripts/gates/check_extraction_boundaries.py`.

Usage: check_package_reachback.py [--manifest PATH] [--repo PATH]
Exit 0 = every owned file reaches only the declared surface. Exit 1 = reach-back.
"""
import argparse
import json
import os
import re
import sys

# Delimiter-agnostic direct-include scan (mirrors check_extraction_boundaries.py):
# quoted "x" or angled <x>. Only the captured target is examined.
HERE = os.path.dirname(os.path.abspath(__file__))

INCLUDE_RE = re.compile(r'^\s*#\s*include\s+(?:"([^"]+)"|<([^>]+)>)', re.M)


def _basename(path):
    return path.rsplit("/", 1)[-1]


def load_manifest(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


SHARED_RUNTIME_CONTRACT = "packaging/shared/backend-source-runtime-v1.json"


def _shared_runtime_closure(repo=None):
    """Materialized paths from the  backend-source-runtime contract."""
    root = repo or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
    path = os.path.join(root, SHARED_RUNTIME_CONTRACT)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        contract = json.load(f)
    out = [e["path"] for e in contract.get("sources", []) if e.get("path")]
    out += [e["path"] for e in contract.get("headers", []) if e.get("path")]
    out += list(contract.get("consumerHeaders", []) or [])
    return sorted(set(out))


def _shared_runtime_compile_definitions(repo=None):
    """The build mode the  contract freezes; includes guarded out under it are
    not dependencies of the frozen closure."""
    root = repo or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
    path = os.path.join(root, SHARED_RUNTIME_CONTRACT)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("compileDefinitions", []) or []


def owned_files(manifest):
    """Every physical file the package owns and whose includes we audit:
    compiled sources, internal headers, public headers, generated build
    products, committed includers, and the reviewed carve-out. Paths are
    unit-relative except public headers, which live under include/."""
    unit = manifest["unitRoot"]
    files = []
    for s in manifest["compiledSources"]["files"]:
        files.append(os.path.join(unit, s))
    for h in manifest["internalHeaders"]["files"]:
        files.append(os.path.join(unit, h["file"]))
    # Package-internal headers that still live outside the unit root: repo-relative.
    for h in manifest.get("packageInternalHeaders", {}).get("files", []):
        files.append(h["file"])
    for g in manifest["generatedBuildProducts"]["committed"]:
        files.append(os.path.join(unit, g["file"]))
    for inc in manifest["committedIncluders"]["files"]:
        files.append(os.path.join(unit, inc["file"]))
    for c in manifest["reviewedCarveoutIncludes"]["files"]:
        files.append(os.path.join(unit, c["file"]))
    # The shared recipe runtime is COMPILED INTO the package archive, so its
    # sources are owned for reach-back purposes even though they live outside the
    # unit root today. Paths are repo-relative, not unit-relative.
    # The  shared-runtime closure: every materialized source AND header the
    # verified contract covers. Naming the dependency without auditing its headers
    # would leave them outside the proof surface.
    files.extend(_shared_runtime_closure())
    # Public headers live under include/, named as declared (Neutrino/<name>).
    for h in manifest["publicHeaders"]["declared"]:
        files.append(os.path.join("include", h))
    return files


def allowed_includes(manifest):
    """The complete allow-list of `#include` targets, as the exact spellings a
    source may use: own headers/`.inc` by basename, own+declared `Neutrino/...`
    headers by full spelling, and the build-time generated `.inc` by basename."""
    unit = manifest["unitRoot"]
    own_basenames = set()
    own_neutrino = set()

    # Own internal headers — included by basename (each role subdir is on the
    # unit's private include path).
    for h in manifest["internalHeaders"]["files"]:
        own_basenames.add(_basename(h["file"]))
    for h in manifest.get("packageInternalHeaders", {}).get("files", []):
        own_basenames.add(_basename(h["file"]))
        if h["file"].startswith("include/"):
            own_neutrino.add(h["file"][len("include/"):])
    # Own generated build products, committed includers, carve-outs — by basename.
    for g in manifest["generatedBuildProducts"]["committed"]:
        own_basenames.add(_basename(g["file"]))
    for g in manifest["generatedBuildProducts"]["buildTimeOnly"]:
        own_basenames.add(_basename(g["file"]))
    for inc in manifest["committedIncluders"]["files"]:
        own_basenames.add(_basename(inc["file"]))
    for c in manifest["reviewedCarveoutIncludes"]["files"]:
        own_basenames.add(_basename(c["file"]))
    # A recorded contract gap is NOT an allowlist exception. Admitting it here
    # would convert a known-incomplete dependency into a passing one, which is
    # exactly the thing the audit exists to prevent — the gap header stays
    # undeclared and therefore stays a reach-back.
    for f in _shared_runtime_closure():
        own_basenames.add(_basename(f))
        if f.startswith("include/"):
            own_neutrino.add(f[len("include/"):])

    # Own public headers — Neutrino/<name>. Include the PgDdl.h finding header
    # (it is postgres-owned; the manifest records the disposition question, but
    # for the reach-back allow-list it is an OWN header, not a reach-back).
    for h in manifest["publicHeaders"]["declared"]:
        own_neutrino.add(h)

    # Declared public-core headers (the installed-artifact dependency surface).
    declared_core = set()
    consumed = manifest["sharedLeafLinkDeps"]["consumedPublicCoreHeaders"]
    for group in consumed.values():
        declared_core.update(group)
    # Declared package-internal headers (bundled, not public-core, but DECLARED).
    for h in manifest["publicCoreContract"]["packageInternalNotExported"]["headers"]:
        # Entries may carry a parenthetical note — take the header token.
        declared_core.add(h.split(" ")[0])

    return own_basenames, own_neutrino, declared_core


# --- compile-definition-aware include scan for the frozen closure -------------
# The  contract freezes `compileDefinitions`, so an include guarded out under
# that exact build mode is NOT a dependency of the frozen closure. Scanning source
# text without honouring those definitions reports producer-only includes as
# reach-backs (a false positive) and would push a producer-only dependency into the
# consumer closure if "fixed" by widening the contract.
#
# The evaluator is deliberately NARROW: it supports `#ifndef NAME` / `#endif`, which
# is the entire conditional grammar the frozen closure uses. ANY other conditional
# form FAILS CLOSED — it is reported, never silently skipped — so an unsupported or
# ambiguous construct can never hide an include.
_COND_RE = re.compile(r"^\s*#\s*(ifndef|ifdef|if|elif|else|endif)\b[ \t]*(.*)$", re.M)
_SUPPORTED_OPEN = ("ifndef",)


def active_includes(text, defines):
    """([(target, is_quoted)], [unsupported-form]) for includes on ACTIVE branches."""
    defined = set(defines or [])
    events = []
    for m in _COND_RE.finditer(text):
        events.append((m.start(), m.group(1), m.group(2).strip()))
    for m in INCLUDE_RE.finditer(text):
        events.append((m.start(), "include", m))
    events.sort(key=lambda e: e[0])

    unsupported, stack, out = [], [], []
    for _pos, kind, payload in events:
        if kind == "include":
            if all(stack):
                target = payload.group(1) or payload.group(2)
                out.append((target, payload.group(1) is not None))
        elif kind == "endif":
            if stack:
                stack.pop()
        elif kind in _SUPPORTED_OPEN:
            name = payload.split()[0] if payload else ""
            # `#ifndef NAME` body is active exactly when NAME is NOT defined.
            stack.append(name not in defined)
        else:
            # #if / #ifdef / #elif / #else — unsupported grammar. Fail closed.
            unsupported.append(kind)
            if kind in ("if", "ifdef"):
                stack.append(True)
    return out, unsupported


_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "scripts", "gates")
if _GATES not in sys.path:
    sys.path.insert(0, _GATES)
try:
    from generated_artifacts import MIGRATED_ARTIFACTS as _MIGRATED
    _MIGRATED_BASENAMES = {os.path.basename(p) for p in _MIGRATED}
except ImportError:
    _MIGRATED_BASENAMES = set()
    _MIGRATED = {}
BUILD_DIR = os.environ.get("NEUTRINO_BUILD_DIR", "")


def classify_include(target, is_quoted, own_basenames, own_neutrino, declared_core):
    """Return None if `target` is allowed, else a reach-back reason string.

    The QUOTED/ANGLED delimiter is significant. An ANGLED slashless name is a
    standard-library header (`<string>`); an ANGLED `llvm/…` / `mlir/…` / `clang/…`
    is a toolchain header — both are true externals. A QUOTED include is a LOCAL
    include: a slashless quoted name is NEVER stdlib — it must be an owned header
    or `.inc` by basename. Any `Neutrino/…` (quoted or angled) must be an owned or
    declared header. Everything else fails closed."""
    # Toolchain headers are external regardless of delimiter — LLVM/MLIR code
    # conventionally includes them with QUOTES (`#include "llvm/Support/Error.h"`).
    if target.startswith(("llvm/", "mlir/", "llvm-c/", "clang/")):
        return None
    # A slashless name is a standard-library header ONLY in the ANGLED form
    # (`<string>`). A slashless QUOTED name is a local include and must be owned —
    # this is the P1 the old audit missed.
    if not is_quoted and "/" not in target:
        return None

    base = _basename(target)
    # Owned header / .inc by basename (a quoted local include, the common form).
    if "/" not in target and base in own_basenames:
        return None
    # Owned or declared Neutrino/… header (quoted or angled).
    if target in own_neutrino or target in declared_core:
        return None

    # A path that escapes the unit, an absolute path, or a bare in-tree path.
    if target.startswith(("../", "/")) or target.startswith("lib/"):
        return "reach-back: escapes the package into the translator tree"
    if target.startswith("Neutrino/"):
        return "reach-back: undeclared public-core / private Neutrino header"
    if not is_quoted and "/" in target:
        return "reach-back: undeclared angled third-party header"
    # : a bare basename naming a BUILD PRODUCT is not a reach-back. The
    # artifact is generated into the build tree and reached via -I, exactly as
    # before -- only its location moved. Matched against the migration registry
    # by basename, so only the declared 16 qualify and any other slashless
    # quoted include is still refused.
    if _MIGRATED_BASENAMES and target in _MIGRATED_BASENAMES:
        return None
    # A slashless quoted basename that is not an owned header — the exact case
    # the old `is_external` waved through.
    return "reach-back: undeclared local/private header not in the package surface"


def audit(manifest, repo):
    own_basenames, own_neutrino, declared_core = allowed_includes(manifest)
    closure_files = set(_shared_runtime_closure(repo))
    compile_definitions = _shared_runtime_compile_definitions(repo)
    violations = []
    scanned = 0
    for rel in owned_files(manifest):
        path = os.path.join(repo, rel)
        # : an owned BUILD PRODUCT lives in the build tree. It is still
        # owned -- an extraction carries its .td and generator -- so it is
        # scanned where it is produced rather than reported absent.
        if _MIGRATED and rel in _MIGRATED and BUILD_DIR:
            candidate = os.path.join(BUILD_DIR, _MIGRATED[rel])
            if os.path.exists(candidate):
                path = candidate
        if not os.path.exists(path):
            violations.append((rel, None, "manifest declares a file that does not exist"))
            continue
        scanned += 1
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if rel in closure_files:
            includes, unsupported = active_includes(text, compile_definitions)
            for form in sorted(set(unsupported)):
                violations.append((
                    rel, f"#{form}",
                    "unsupported conditional form in a frozen-closure source — the "
                    "audit fails closed rather than guessing which branch is active"))
        else:
            includes = [(m.group(1) or m.group(2), m.group(1) is not None)
                        for m in INCLUDE_RE.finditer(text)]
        for target, is_quoted in includes:
            reason = classify_include(target, is_quoted,
                                      own_basenames, own_neutrino, declared_core)
            if reason:
                violations.append((rel, target, reason))
    return scanned, violations


def selftest():
    """Biting mutations: the classifier must ACCEPT owned/declared/stdlib and
    REJECT an undeclared quoted local header (the P1 the old audit missed)."""
    own_basenames = {"PostgresModel.h", "PostgresRecipeAdapter.inc"}
    own_neutrino = {"Neutrino/PgDdl.h"}
    declared_core = {"Neutrino/Expr.h"}

    def cls(target, is_quoted):
        return classify_include(target, is_quoted, own_basenames, own_neutrino, declared_core)

    cases = [
        # (target, is_quoted, expect_allowed)
        ("string", False, True),                    # angled stdlib
        ("cstdint", False, True),                    # angled stdlib
        ("llvm/Support/Error.h", False, True),       # angled toolchain
        ("PostgresModel.h", True, True),             # owned header by basename
        ("PostgresRecipeAdapter.inc", True, True),   # owned .inc by basename
        ("Neutrino/PgDdl.h", True, True),            # owned public header
        ("Neutrino/Expr.h", True, True),             # declared public-core header
        # --- must FAIL closed ---
        ("UndeclaredPrivateHeader.h", True, False),  # THE P1: quoted local basename
        ("string", True, False),                     # quoted, not stdlib — not owned
        ("Neutrino/PgSqlText.h", True, False),       # quoted undeclared Neutrino header
        ("Neutrino/UndeclaredPrivate.h", False, False),  # angled undeclared Neutrino
        ("../lib/backends/solidity/Foo.h", True, False), # escaping path
        ("gtest/gtest.h", False, False),             # angled third-party w/ slash
    ]
    failures = []
    for target, is_quoted, expect_allowed in cases:
        reason = cls(target, is_quoted)
        allowed = reason is None
        if allowed != expect_allowed:
            failures.append(f"{'quoted' if is_quoted else 'angled'} {target!r}: "
                            f"expected {'ALLOW' if expect_allowed else 'REJECT'}, "
                            f"got {'ALLOW' if allowed else 'REJECT (' + reason + ')'}")
    if failures:
        print("reach-back audit SELFTEST FAILED:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        return 1
    print("reach-back audit selftest OK (undeclared quoted local header is rejected)")
    return 0


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_manifest = os.path.join(os.path.dirname(here), "extraction-manifest.json")
    # packaging/postgres/scripts -> packaging/postgres -> packaging -> repo root
    default_repo = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=default_manifest)
    ap.add_argument("--repo", default=default_repo)
    ap.add_argument("--selftest", action="store_true",
                    help="run the classifier biting mutations and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    manifest = load_manifest(args.manifest)
    scanned, violations = audit(manifest, args.repo)

    if violations:
        print(f"package reach-back audit FAILED ({scanned} owned files scanned):", file=sys.stderr)
        for rel, target, reason in violations:
            where = f"{rel}: {target}" if target else rel
            print(f"  [reachback] {where} — {reason}", file=sys.stderr)
        return 1
    print(f"package reach-back audit OK: {scanned} owned files reach only the "
          f"declared package + public-core surface")
    return 0


if __name__ == "__main__":
    sys.exit(main())
