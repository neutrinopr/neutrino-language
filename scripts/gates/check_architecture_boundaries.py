#!/usr/bin/env python3
"""Architecture boundary scanners ( /  S3).

Keep backend- and domain-specific names out of the backend-agnostic, domain-agnostic
compiler CORE (the .neu frontend + neutrino IR/dialect + kernel), so that coupling cannot
drift back in by omission. Complements the C++ policy ratchet () and the tooling-layout
boundary (), and consumes the same reviewed config style.

Two rules over the C++ compiler surface (git-tracked `include/` + `lib/` + `tools/`), COMMENT
STRIPPED so this governs code coupling (string literals / identifiers), not prose that merely
documents a lowering:

  --rule backend : the controlled backend identifiers (solidity/postgres, from the config) may
                   appear only in files matching the config's backend allowed_path_globs — the
                   backend renderers, the target registry/profiles, the shared expression-lowering
                   AST, the artifact manifest, and the CLI tools. Anywhere else is a violation.
  --rule domain  : sample/domain names (live examples plus the persistent externalized-domain
                   registry) may appear nowhere in the C++ surface — the core is
                   domain-agnostic (no allowlist).

Fail-closed / non-vacuous: a missing/malformed config, an empty token/vocabulary set, or a scan
that covered fewer than `min_files_scanned` files all exit non-zero rather than passing empty.

Usage:
  check_architecture_boundaries.py --rule backend|domain            # scan the repo (default)
  check_architecture_boundaries.py --rule backend|domain --file F   # check one file (negative test)
Exit 0 ok / 1 violation / 2 usage or fail-closed config error.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/ (for check_cpp_policy)
# Reuse the ONE hardened, string/char/raw-string-aware comment stripper (), with strings KEPT —
# a backend/domain name inside a string literal in core IS coupling and must be seen (unlike the
# policy gate, which blanks strings). No second, weaker stripper to drift.
from check_cpp_policy import strip_comments as _strip_comments  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(REPO, "scripts", "architecture_boundaries.json")


def strip_comments(src: str) -> str:
    return _strip_comments(src, keep_string_content=True)


def _fail_closed(msg: str) -> int:
    print(f"check_architecture_boundaries: {msg}", file=sys.stderr)
    return 2


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def scan_files(cfg: dict) -> list[str]:
    """Discover the C++ surface via `git ls-files` (not a hand-maintained list)."""
    import subprocess
    roots = cfg["scan_roots"]
    exts = tuple(cfg["scan_extensions"])
    tracked = subprocess.check_output(
        ["git", "-C", REPO, "ls-files"] + roots, text=True).splitlines()
    return [f for f in tracked if f.endswith(exts)]


def path_allowed(rel: str, globs: list[str]) -> bool:
    for g in globs:
        # `tools/**` (and any `dir/**`) matches everything under that dir.
        if g.endswith("/**") and (rel == g[:-3] or rel.startswith(g[:-2])):
            return True
        if fnmatch.fnmatch(rel, g):
            return True
    return False


def domain_vocab(cfg: dict) -> list[str]:
    d = os.path.join(REPO, cfg["domain"]["domains_dir"])
    live = {
        name for name in os.listdir(d)
        if os.path.isdir(os.path.join(d, name))
    } if os.path.isdir(d) else set()
    registry_path = cfg["domain"].get("externalized_registry")
    if not registry_path:
        raise ValueError("domain.externalized_registry is missing")
    with open(os.path.join(REPO, registry_path), encoding="utf-8") as fh:
        registry = json.load(fh)
    externalized = {
        row["id"] for row in registry.get("domains", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    return sorted(live | externalized)


def externalized_domain_vocab(cfg: dict) -> list[str]:
    registry_path = cfg["domain"].get("externalized_registry")
    if not registry_path:
        return []
    with open(os.path.join(REPO, registry_path), encoding="utf-8") as fh:
        registry = json.load(fh)
    return sorted(
        row["id"] for row in registry.get("domains", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    )


def token_regex(tokens: list[str]) -> re.Pattern:
    # word-boundary, case-insensitive (catches Solidity / SOLIDITY / a SolidityFoo identifier).
    return re.compile(r"(?i)\b(" + "|".join(re.escape(t) for t in tokens) + r")\b")


def violations(files: list[str], rx: re.Pattern, allowed: list[str], boundary: str) -> list[str]:
    out = []
    for rel in files:
        if path_allowed(rel, allowed):
            continue
        try:
            src = open(os.path.join(REPO, rel), encoding="utf-8", errors="replace").read()
        except OSError as e:
            out.append(f"{rel}: cannot read ({e})")
            continue
        for i, line in enumerate(strip_comments(src).splitlines(), start=1):
            m = rx.search(line)
            if m:
                out.append(f"{rel}:{i}: {boundary.format(token=m.group(0))}")
    return out


def root_script_ok(base: str, src: str, allowed: set, marker: str) -> bool:
    """A scripts/ root .py is allowed iff it is a core-allowlisted script or a marked transitional
    wrapper (). Anything else is domain-scaling tooling that belongs in a subtree (or a new core
    script that must be consciously added to the allowlist)."""
    return base in allowed or marker in src


def check_root_scripts(cfg: dict, one_file: str | None) -> int:
    rc = cfg.get("root_scripts")
    if not rc:
        return _fail_closed("root_scripts config section missing (fail-closed)")
    marker = rc.get("wrapper_marker", "")
    dirs = rc.get("dirs", [])
    if not dirs or not marker:
        return _fail_closed("root_scripts dirs list or wrapper_marker is empty (fail-closed)")
    # union of every dir's allowlist — used only for the single-file (--file) mode, where the caller
    # names one path and we ask "is this a recognized script anywhere in the layout, or a wrapper?".
    union_allowed = set()
    for d in dirs:
        union_allowed |= set(d.get("allowed", []))
    if not union_allowed:
        return _fail_closed("root_scripts allowlists are all empty (fail-closed)")
    boundary = ("{rel}: unrecognized script — base-compiler tooling is organized by ROLE under "
                "scripts/{{gates,validators,generators}}/ and domain tooling under "
                "scripts/{{domain,corpus,rails,samples}}/; move it to the right subtree, or add it to "
                "that dir's `allowed` in scripts/architecture_boundaries.json (//)")

    if one_file:
        base = os.path.basename(one_file)
        try:
            src = open(one_file, encoding="utf-8", errors="replace").read()
        except OSError as e:
            return _fail_closed(f"cannot read {one_file}: {e}")
        if root_script_ok(base, src, union_allowed, marker):
            return 0
        print(boundary.format(rel=os.path.basename(one_file)), file=sys.stderr)
        return 1

    import glob
    viol = []
    total = 0
    # Scan each declared dir against ITS OWN allowlist, so a misfiled script — e.g. a validate_*.py
    # dropped into scripts/gates/ — is flagged (not silently accepted by a shared union allowlist).
    for d in dirs:
        rel = d["path"]
        scan_dir = os.path.join(REPO, rel)
        allowed = set(d.get("allowed", []))
        min_files = d.get("min_files", 1)
        pyfiles = sorted(glob.glob(os.path.join(scan_dir, "*.py")))
        if len(pyfiles) < min_files:
            return _fail_closed(
                f"root_scripts scanned {len(pyfiles)} .py under {rel}, "
                f"expected >= {min_files} (empty/mis-rooted scan — fail-closed)")
        total += len(pyfiles)
        for p in pyfiles:
            base = os.path.basename(p)
            src = open(p, encoding="utf-8", errors="replace").read()
            if not root_script_ok(base, src, allowed, marker):
                viol.append(boundary.format(rel=os.path.join(rel, base)))
    if viol:
        print("\n".join(viol), file=sys.stderr)
        return 1
    print(f"ok: root-scripts boundary — {total} .py across {len(dirs)} role/infra dirs, "
          f"each allowlisted for its dir or a marked transitional wrapper")
    return 0


def selftest(rule: str, config: str) -> int:
    """Prove the boundary gate actually bites (): the current tree is clean (and, via the
    checker's own floors, non-vacuously scanned), a malformed config fails closed, a forbidden token
    in a core TU is flagged, and the false-positive guards hold (comment-only mentions — including
    after a char literal,  — and allowlisted TUs are not flagged). Ported from the retired
    test/checks/arch_boundaries.sh ( /  S5d); registered as the `arch-<rule>-isolation` CTest
    test. Drives temp fixtures through the checker's own `--file` mode (no writes into the repo tree,
    so parallel `ctest` runs can't collide)."""
    import subprocess
    import tempfile

    me = [sys.executable, os.path.abspath(__file__)]

    def gate(*args: str) -> int:
        return subprocess.run(
            me + list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode

    tmp = tempfile.mkdtemp(prefix="arch_selftest.")

    def probe(name: str, text: str) -> str:
        p = os.path.join(tmp, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    fails = []
    try:
        # 1. FAIL-CLOSED config: a malformed allowlist must abort (never pass silently).
        if gate("--rule", rule, "--config", probe("bad.json", "{ this is not json")) == 0:
            fails.append("a malformed config did not fail closed")

        if rule == "root-scripts":
            # 2. Positive: the current scripts/ root is clean (and >= the checker's min_files floor).
            if gate("--rule", "root-scripts", "--config", config) != 0:
                fails.append("a scripts/ root script is neither core-allowlisted nor a marked wrapper")
            # 3. NEGATIVE: a new unmarked, non-allowlisted root script is flagged (via --file).
            stray = probe("_arch_probe_root.py", 'DOMAIN = "not core tooling"\n')
            if gate("--rule", "root-scripts", "--config", config, "--file", stray) == 0:
                fails.append("a stray unmarked scripts/ root script was NOT flagged (boundary fails open)")
            # Exact registration only: a lookalike of a newly registered gate
            # must remain outside the allowlist.
            lookalike = probe(
                "check_backend_projection_bijection_extra.py",
                'DOMAIN = "not the registered gate"\n',
            )
            if gate("--rule", "root-scripts", "--config", config, "--file", lookalike) == 0:
                fails.append("a registered-script lookalike was NOT flagged (allowlist broadened)")
            # 4. FALSE-POSITIVE GUARD: a marked transitional wrapper () is allowed.
            marked = probe("_wrap.py", "# TRANSITIONAL wrapper ( /  S1) probe\nx = 1\n")
            if gate("--rule", "root-scripts", "--config", config, "--file", marked) != 0:
                fails.append("a marked transitional wrapper was wrongly flagged")
        else:
            # 2. Positive + NON-VACUOUS (the checker fails closed below its file/vocab floor).
            if gate("--rule", rule, "--config", config) != 0:
                fails.append(f"{rule} boundary violated on the current tree")
            # 3. NEGATIVE FIXTURE: a forbidden token in CODE in a core-path TU must be flagged.
            if rule == "backend":
                token = '"solidity"'
            else:
                vocab = domain_vocab(load_config(config))
                if not vocab:
                    fails.append("no domain vocabulary discovered under examples/domains")
                    token = '"__none__"'
                else:
                    token = f'"{vocab[0]}"'
            core = probe("_arch_probe_core.cpp",
                         f"void _p(){{ const char* x = {token}; (void)x; }}\n")
            if gate("--rule", rule, "--config", config, "--file", core) == 0:
                fails.append(f"a misplaced {rule} token in a core TU was NOT caught (scanner fails open)")
            if rule == "domain":
                cfg = load_config(config)
                externalized = externalized_domain_vocab(cfg)
                live = {
                    name for name in os.listdir(os.path.join(REPO, cfg["domain"]["domains_dir"]))
                    if os.path.isdir(os.path.join(REPO, cfg["domain"]["domains_dir"], name))
                }
                if not externalized:
                    fails.append("no persistent externalized-domain identity was registered")
                elif externalized[0] in live:
                    fails.append("externalized-domain probe is still discoverable from the live tree")
                else:
                    retired = probe(
                        "_arch_probe_externalized.cpp",
                        f'void _p(){{ const char* x = "{externalized[0]}"; (void)x; }}\n',
                    )
                    if gate("--rule", "domain", "--config", config, "--file", retired) == 0:
                        fails.append("an externalized identity absent from the live tree was NOT caught")
            # 4. FALSE-POSITIVE GUARDS (backend): comment-only mentions and allowlisted TUs.
            if rule == "backend":
                c1 = probe("_c1.cpp", "// this construct lowers to solidity and postgres\nvoid _p(){}\n")
                if gate("--rule", "backend", "--config", config, "--file", c1) != 0:
                    fails.append("a comment-only backend mention was wrongly flagged (stripper regressed)")
                # A char literal on a prior line must not desync the comment stripper ().
                c2 = probe("_c2.cpp",
                           "void _l(char c){ if (c == '\"') return; }\n"
                           "// lowers to postgres and solidity\n")
                if gate("--rule", "backend", "--config", config, "--file", c2) != 0:
                    fails.append("a comment after a char literal was wrongly flagged (char-literal stripper regressed)")
                # An allowlisted target-entry TU (lib/targets/*Target.cpp) MAY name the backend — anchor
                # on the real solidity entry, which legitimately contains "solidity".
                anchor = os.path.join(REPO, "lib", "targets", "SolidityTarget.cpp")
                if gate("--rule", "backend", "--config", config, "--file", anchor) != 0:
                    fails.append("an allowlisted target-entry TU (lib/targets/*Target.cpp) was wrongly flagged")
                td_anchor = os.path.join(REPO, "lib", "backends", "solidity", "model", "SolidityTargetNodes.td")
                if gate("--rule", "backend", "--config", config, "--file", td_anchor) != 0:
                    fails.append("a backend-local .td file was wrongly flagged")
                core_td = probe("_core_leak.td", 'def CoreLeak { string Backend = "solidity"; }\n')
                if gate("--rule", "backend", "--config", config, "--file", core_td) == 0:
                    fails.append("a backend token in a core .td was NOT flagged (TableGen allowlist too broad)")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        print(f"arch-{rule} selftest FAILED:", file=sys.stderr)
        for f in fails:
            print("    FAIL: " + f, file=sys.stderr)
        return 1
    if rule == "root-scripts":
        detail = ("current scripts/ root clean + non-vacuously scanned; a stray unmarked script, "
                  "a registered-script lookalike, and a malformed config fail closed; a marked  "
                  "wrapper is allowed")
    else:
        detail = ("current tree clean + non-vacuously scanned; a code token in a core TU + a "
                  "malformed config fail closed; comment mentions (incl. after a char literal) + "
                  "allowlisted TUs are not false-positives")
    print(f"    PASS (arch-{rule}: {detail})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="architecture boundary scanner ()")
    ap.add_argument("--rule", required=True, choices=["backend", "domain", "root-scripts"])
    ap.add_argument("--file", help="check a single file instead of scanning the repo")
    ap.add_argument("--config", default=CONFIG,
                    help="boundary config path (default scripts/architecture_boundaries.json)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the fail-closed / false-positive self-tests (the arch-<rule> CTest gate)")
    args = ap.parse_args()

    if args.selftest:
        return selftest(args.rule, args.config)

    try:
        cfg = load_config(args.config)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return _fail_closed(f"config {args.config} missing or malformed: {e}")

    if args.rule == "root-scripts":
        return check_root_scripts(cfg, args.file)

    if args.rule == "backend":
        tokens = cfg.get("backend", {}).get("tokens", [])
        allowed = cfg["backend"].get("allowed_path_globs", [])
        if not tokens:
            return _fail_closed("backend token list is empty (fail-closed)")
        boundary = ("backend token '{token}' appears in the compiler core — only the backend "
                    "renderers / target registry / expression-lowering AST / manifest / tools "
                    "may name a backend (see scripts/architecture_boundaries.json)")
    else:
        try:
            vocab = domain_vocab(cfg)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            return _fail_closed(f"externalized domain registry missing or malformed: {e}")
        min_vocab = cfg["domain"].get("min_domain_vocab", 1)
        if len(vocab) < min_vocab:
            return _fail_closed(
                f"domain vocabulary discovered {len(vocab)} names under "
                f"{cfg['domain']['domains_dir']}, expected >= {min_vocab} (fail-closed)")
        tokens = vocab
        allowed = cfg["domain"].get("allowed_path_globs", [])
        boundary = ("domain/sample name '{token}' appears in the compiler core — sample names "
                    "belong under examples/ / tests / manifests / docs, not the domain-agnostic "
                    "core (see scripts/architecture_boundaries.json)")

    rx = token_regex(tokens)

    if args.file:
        rel = os.path.relpath(os.path.abspath(args.file), REPO)
        viol = violations([rel], rx, allowed, boundary)
        if viol:
            print("\n".join(viol), file=sys.stderr)
            return 1
        return 0

    files = scan_files(cfg)
    floor = cfg.get("min_files_scanned", 1)
    if len(files) < floor:
        return _fail_closed(
            f"scanned {len(files)} files, expected >= {floor} (empty/mis-rooted scan — fail-closed)")

    viol = violations(files, rx, allowed, boundary)
    if viol:
        print("\n".join(viol), file=sys.stderr)
        return 1
    print(f"ok: {args.rule} boundary — {len(files)} C++ core/surface files scanned, "
          f"{len(tokens)} controlled name(s), no core coupling")
    return 0


if __name__ == "__main__":
    sys.exit(main())
