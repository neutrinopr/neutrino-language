#!/usr/bin/env python3
"""[] Solidity Foundry test-harness (.t.sol) printer retirement ratchet.

Companion to the / production-printer ratchet, applied to the HARNESS path
(GenSolidityTest.cpp). The handwritten harness authors literal `.t.sol` syntax through
the codetext `line()`/`block()` builders — the harness analogue of the raw seam
retired on the production side.  migrates each construct to a typed harness model +
SolidityTestHarness.td generated handlers over the generic driver, DELETING the
handwritten template as it goes.

Discipline (mirrors check_solidity_syntax_authority.py, per the  review):
  - COMMENT/STRING-AWARE scanning: authoring sites are counted on the comment-stripped,
    string-preserving view, so a commented-out `line(` or a string literal containing
    `line(` never changes the count (reuses `_strip_comments`);
  - STABLE SITE IDENTITIES `(path, enclosing function, full-argument digest)` — NOT a bare
    total — so a delete-one/add-one SUBSTITUTION is rejected (the added identity is not in
    the base), and construct counts are DERIVED from the scan, not hand-authored;
  - the committed inventory is `--emit`-regenerated and must reconcile exactly;
  - the cross-revision ratchet resolves the base via the shared / resolver
    (PR_BASE_SHA / GITHUB_BASE_SHA), and FAILS CLOSED when the base is unresolvable —
    never "skip the delta"; only DELETIONS are legal (subset vs base);
  - a `--selftest` proves the ratchet bites (new site / substitution) and is not fooled by
    a commented or string-embedded `line(`.
No production-domain-tree paths live in this governance manifest; `.t.sol` byte-identity is
bound by the golden/IR-lit test surface (solidity_goldens.test), not here.
"""

import argparse
import bisect
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Reuse the digest + function-header/enclosing-fn helpers, but NOT the ordinary-quote
# comment-stripper / arg-extractor: those mis-lex C++ RAW strings (R"delim(...)delim")
# by treating the first `"` inside raw content as the close. This gate provides a single
# raw-aware lexer (`_spans`) used consistently across comment-stripping, string-blanking,
# and argument extraction, so a valid raw literal containing quotes / `//` / `,` / `(`
# never corrupts detection or argument boundaries.
from check_solidity_syntax_authority import (  # noqa: E402
    _function_headers, _enclosing_fn, _digest)
from check_target_node_registry import _resolve_base_ref  # noqa: E402


def _spans(s):
    """Yield (start, end, kind) for every lexical span whose interior must NOT be scanned
    as code: 'line-comment', 'block-comment', 'string', 'char', 'raw'. Code between spans
    is not yielded. Handles C++ raw strings R"delim(...)delim" (optionally with an
    encoding prefix L/u/U/u8) and backslash escapes in ordinary string/char literals."""
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "/" and i + 1 < n and s[i + 1] == "/":
            j = s.find("\n", i)
            j = n if j == -1 else j
            yield (i, j, "line-comment")
            i = j
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "*":
            j = s.find("*/", i + 2)
            j = n if j == -1 else j + 2
            yield (i, j, "block-comment")
            i = j
            continue
        # raw string opener: R" possibly with an encoding prefix (L/u/U/u8) directly before
        # R, and R at a token boundary (not mid-identifier).
        if c == "R" and i + 1 < n and s[i + 1] == '"':
            pre = s[max(0, i - 2):i]
            boundary = (i == 0) or (not (s[i - 1].isalnum() or s[i - 1] == "_")) \
                or pre.endswith("L") or pre.endswith("u") or pre.endswith("U") or pre.endswith("u8")
            if boundary:
                k = i + 2
                delim = ""
                while k < n and s[k] != "(" and (k - (i + 2)) < 16:
                    delim += s[k]
                    k += 1
                if k < n and s[k] == "(":
                    close = ")" + delim + '"'
                    e = s.find(close, k + 1)
                    e = n if e == -1 else e + len(close)
                    yield (i, e, "raw")
                    i = e
                    continue
        if c == '"' or c == "'":
            j = i + 1
            while j < n:
                if s[j] == "\\":
                    j += 2
                    continue
                if s[j] == c:
                    j += 1
                    break
                j += 1
            yield (i, j, "string" if c == '"' else "char")
            i = j
            continue
        i += 1


def _strip_comments(src):
    """Comment content -> spaces (length + newlines preserved); string/char/raw literals
    preserved verbatim; code preserved. Raw-aware."""
    out = list(src)
    for a, b, kind in _spans(src):
        if kind in ("line-comment", "block-comment"):
            for k in range(a, b):
                if out[k] != "\n":
                    out[k] = " "
    return "".join(out)


def _blank_strings(view):
    """String/char/raw literal CONTENTS -> spaces (delimiters + length preserved), so site
    DETECTION never matches a `line(`/`block(` inside a literal. Offsets unchanged."""
    out = list(view)
    for a, b, kind in _spans(view):
        if kind in ("string", "char", "raw"):
            for k in range(a, b):
                if out[k] != "\n":
                    out[k] = " "
    return "".join(out)


def _call_args(view, lparen, spans=None, starts=None):
    """Split the argument list of a call whose '(' is at `lparen`, skipping string/char/raw
    literals and comments (raw-aware) so a comma/paren inside a literal never splits an
    argument. `spans`/`starts` (precomputed once per view) keep this O(args + log spans).
    Returns (args, end)."""
    if spans is None:
        spans = [(a, b) for a, b, _ in _spans(view)]
        starts = [a for a, _ in spans]
    depth, i, nn = 1, lparen + 1, len(view)
    cur, args = [], []

    def in_span(pos):
        idx = bisect.bisect_right(starts, pos) - 1
        if idx >= 0 and spans[idx][0] <= pos < spans[idx][1]:
            return spans[idx][1]
        return None

    while i < nn:
        e = in_span(i)
        if e is not None:
            cur.append(view[i:e])
            i = e
            continue
        c = view[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                args.append("".join(cur).strip())
                return (args, i + 1)
        if depth == 1 and c == ",":
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    args.append("".join(cur).strip())
    return (args, nn)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PRIMARY = "lib/backends/solidity/harness/GenSolidityTest.cpp"
INVENTORY = os.path.join(REPO, "scripts", "gates",
                         "solidity_harness_printer_inventory.json")
INV_KIND = "neutrino.solidity-harness-printer.retirement-inventory.v2"

# An unqualified codetext authoring builder call: `line(` / `block(` (NOT `blank(`, a
# generic spacer; NOT a member `.line(`/`::line(`; NOT `inline(`/`deadline(` — the `\b`
# and the negative-lookbehind for `.`/`:` guarantee the builder call).
_SITE = re.compile(r"(?<![.:\w])(line|block)\s*\(")

# Derive the construct category from the authored literal's shape (mechanical, not
# hand-authored). Order matters — first match wins.
_CATEGORY = [
    (re.compile(r"^contract\s+\w+Test\b"), "test-contract-shell"),
    (re.compile(r"^contract\s+MockQuorumGuard"), "mock-quorum-guard"),
    (re.compile(r"^contract\b"), "contract-shell"),
    (re.compile(r"^interface\s+Vm\b"), "cheatcode-interface"),
    (re.compile(r"^interface\b"), "interface"),
    (re.compile(r"^function\s+setUp\b"), "setUp"),
    (re.compile(r"^function\s+test_"), "scenario-test-fn"),
    (re.compile(r"^function\b"), "helper-fn"),
    (re.compile(r"^vm\.expectEmit\b"), "expect-emit"),
    (re.compile(r"^vm\.expectRevert\b"), "expect-revert"),
    (re.compile(r"^event\s"), "event-redeclaration"),
    (re.compile(r"^(uint256|string|bytes32)\s+constant\b"), "const-declaration"),
    (re.compile(r"^import\s"), "import"),
    (re.compile(r"^// SPDX-License-Identifier"), "spdx"),
    (re.compile(r"^pragma\s+solidity"), "pragma"),
    (re.compile(r"^/// "), "doc-comment"),
    (re.compile(r"^mapping\("), "mock-quorum-guard"),
    (re.compile(r"^Vm\s+constant\b"), "state-var-declaration"),
    (re.compile(r"^\w+\s+\w+;$"), "state-var-declaration"),
    (re.compile(r"^(require\(|emit\s|c\.|guard\.)"), "assertion-and-call"),
]
_LIT = re.compile(r'^"((?:[^"\\]|\\.)*)"$')


def _category(arg0):
    """The construct category, DERIVED from the first argument's literal shape (a
    single string literal is classified; a computed/concatenated first arg is a
    'computed' site). Display/rollup metadata — the IDENTITY is the full call (below)."""
    if arg0 is None:
        return "computed"
    m = _LIT.match(arg0.strip())
    if not m:
        return "computed"
    content = m.group(1)
    for pat, cat in _CATEGORY:
        if pat.search(content):
            return cat
    return "other"


def _norm_arg(a):
    """Canonicalize C++ FORMATTING whitespace OUTSIDE string/char/raw-string literals
    while preserving literal CONTENTS byte-for-byte. Byte-significant whitespace inside a
    rendered `.t.sol` literal (`"a  b"` vs `"a b"`) is therefore part of the identity — a
    lossy `re.sub(r"\\s+"," ")` over the whole argument would erase it. The canonicalizer
    never crosses a literal boundary (handles `"…"`, `'…'`, escapes, and `R"delim(…)delim"`)."""
    out = []
    i, n = 0, len(a)
    while i < n:
        c = a[i]
        if c == "R" and i + 1 < n and a[i + 1] == '"':  # raw string R"delim(...)delim"
            k = i + 2
            delim = ""
            while k < n and a[k] != "(":
                delim += a[k]
                k += 1
            close = ")" + delim + '"'
            end = a.find(close, k)
            if end == -1:
                out.append(a[i:])
                break
            j = end + len(close)
            out.append(a[i:j])
            i = j
            continue
        if c == '"' or c == "'":  # string / char literal — copy verbatim
            q = c
            out.append(c)
            i += 1
            while i < n:
                if a[i] == "\\" and i + 1 < n:
                    out.append(a[i:i + 2])
                    i += 2
                    continue
                out.append(a[i])
                closed = a[i] == q
                i += 1
                if closed:
                    break
            continue
        if c.isspace():  # code whitespace — collapse a run to a single space
            out.append(" ")
            while i < n and a[i].isspace():
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out).strip()


def _signature(builder, args):
    """The full-call signature that IS the site identity: the builder (`line`/`block`)
    plus EVERY parsed, normalized argument. So `line(x)`->`block(x)` and any change to a
    non-first `block(open, close, …)` argument produce a DIFFERENT identity."""
    return builder + "(" + ", ".join(_norm_arg(a) for a in args) + ")"


def scan_file(rel, src):
    sview = _strip_comments(src)        # comments stripped, strings preserved (for args)
    sspans = [(a, b) for a, b, _ in _spans(sview)]  # computed ONCE, shared below
    starts = [a for a, _ in sspans]
    dview = _blank_strings(sview)       # + string contents blanked (for detection)
    headers = _function_headers(sview)
    sites = []
    for m in _SITE.finditer(dview):
        builder = m.group(1)
        j = m.end() - 1  # index of '(' (same offset in sview)
        args, _ = _call_args(sview, j, sspans, starts)
        sig = _signature(builder, args)
        sites.append({"path": rel, "function": _enclosing_fn(headers, m.start()),
                      "builder": builder, "category": _category(args[0] if args else None),
                      "fingerprint": sig[:80], "digest": _digest(sig)})
    return sites


def _ident(s):
    return (s["path"], s["function"], s["digest"])


def load_src(path=None):
    with open(path or os.path.join(REPO, PRIMARY), encoding="utf-8") as fh:
        return fh.read()


def emit_inventory(src):
    sites = sorted(scan_file(PRIMARY, src), key=_ident)
    counts = collections.Counter(s["category"] for s in sites)
    return {
        "kind": INV_KIND,
        "documentId": "urn:neutrino:document:solidity-harness-printer-v1",
        "primaryTU": PRIMARY,
        "scope": "Handwritten .t.sol authoring sites (codetext line()/block()) in the Foundry "
                 "test-harness generator. Emitted by check_solidity_harness_printer.py --emit; "
                 "the fail-closed ratchet drives this toward zero as constructs migrate to typed "
                 "harness nodes over the generic driver (). Byte-identity of the .t.sol "
                 "goldens is bound by the golden/IR-lit test surface, not by this manifest.",
        "baseline": len(sites),
        "constructCounts": dict(sorted(counts.items())),
        "sites": [{"path": s["path"], "function": s["function"], "builder": s["builder"],
                   "category": s["category"], "fingerprint": s["fingerprint"],
                   "digest": s["digest"]} for s in sites],
    }


def load_inventory():
    with open(INVENTORY, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("kind") != INV_KIND:
        raise ValueError(f"harness inventory kind must be {INV_KIND}")
    if not isinstance(data.get("sites"), list):
        raise ValueError("harness inventory has no sites list")
    if data.get("baseline") != len(data["sites"]):
        raise ValueError(f"baseline {data.get('baseline')} != {len(data['sites'])} listed sites")
    return data


def _ident_of_entry(e):
    return (e["path"], e["function"], e["digest"])


_UNSET = object()


def check(src, inv, reasons, base_src=_UNSET, base_ref=_UNSET):
    sites = scan_file(PRIMARY, src)
    emitted = emit_inventory(src)
    # Emit-freshness — EVERY identity-bearing field is validated (deep reconcile of the
    # full site records + derived counts + baseline), NOT merely the identity multiset:
    # `builder`, `category`, `fingerprint`, and `digest` must all be the derived values,
    # so `builder` is a governed field, not decorative metadata.
    if inv.get("baseline") != emitted["baseline"]:
        reasons.append(f"harness inventory baseline {inv.get('baseline')} != {emitted['baseline']} scanned sites")
    if inv.get("constructCounts") != emitted["constructCounts"]:
        reasons.append("harness constructCounts are not the derived scan counts — re-emit the inventory")
    if inv.get("sites") != emitted["sites"]:
        # Point at the first divergent record for a precise diagnostic.
        cur, com = emitted["sites"], inv.get("sites") or []
        cset = {(s["path"], s["function"], s["builder"], s["digest"]) for s in cur}
        oset = {(s["path"], s["function"], s["builder"], s["digest"]) for s in com}
        for k in sorted(cset - oset)[:8]:
            reasons.append(f"ungoverned harness authoring site {k} — re-emit the inventory "
                           "(--emit); a new/changed .t.sol site (any builder OR any argument) is a "
                           " regression unless it replaces a migrated construct")
        for k in sorted(oset - cset)[:8]:
            reasons.append(f"stale harness inventory entry {k} — the site is gone/changed; re-emit")
        if not (cset ^ oset):
            reasons.append("harness inventory sites drifted in a non-identity field "
                           "(category/fingerprint) — re-emit the inventory")

    # Cross-revision SUBSET ratchet vs the shared-resolved base — fail closed.
    if base_ref is _UNSET:
        base_ref = _resolve_base_ref()
    if base_src is _UNSET:
        base_src = None
        if base_ref is not None:
            import subprocess
            try:
                base_src = subprocess.run(["git", "show", f"{base_ref}:{PRIMARY}"], cwd=REPO,
                                          capture_output=True, text=True, check=True).stdout
            except subprocess.CalledProcessError:
                base_src = None
    if base_ref is None:
        reasons.append("cannot resolve the PR base (PR_BASE_SHA / GITHUB_BASE_SHA / origin/main) — "
                       "the harness ratchet fails closed; provide the event base")
    elif base_src is None:
        reasons.append(f"cannot read {PRIMARY} at the resolved base {base_ref} — failing closed")
    else:
        base_ids = collections.Counter(_ident(s) for s in scan_file(PRIMARY, base_src))
        added = collections.Counter(_ident(s) for s in sites) - base_ids
        for k in sorted(added):
            reasons.append(f"harness authoring identity {k} (or added multiplicity) is NOT in the base "
                           "— every  slice may only DELETE harness sites; a new OR REPLACEMENT site "
                           "(delete-one/add-one at unchanged total) is forbidden")
    return sites


def run_selftest(src, inv, reasons):
    base_ids = collections.Counter(_ident(s) for s in scan_file(PRIMARY, src))

    def probe(name, mutated, must_trip, expect_change=True):
        if expect_change and mutated == src:
            reasons.append(f"selftest probe {name}: anchor not found in the source; update the probe")
            return
        r = []
        # Hold base = the clean source: only the mutation should (or shouldn't) trip the ratchet.
        check(mutated, inv, r, base_src=src, base_ref="HEAD")
        tripped = any(("is NOT in the base" in x) or ("ungoverned harness authoring" in x)
                      or ("baseline" in x) or ("stale harness" in x) for x in r)
        if must_trip and not tripped:
            reasons.append(f"selftest probe {name} did NOT trip the ratchet")
        if not must_trip and tripped:
            reasons.append(f"selftest probe {name} tripped but should not: {' || '.join(r)}")

    # A genuinely new authoring site must trip.
    probe("new-site", src + '\nstatic void _p(){ (void)line("selfdestruct();"); }\n', True,
          expect_change=False)
    # A commented-out `line(` must NOT be counted (comment-aware).
    probe("commented-out", src + '\n// (void)line("selfdestruct();");\n', False, expect_change=False)
    # A string literal containing `line(` must NOT be counted (string-aware).
    probe("string-embedded", src + '\nstatic const char* _s = "line(evil)";\n', False,
          expect_change=False)
    # line -> block with the SAME first argument: identity is builder + args, so it trips
    # (an arg0-only identity would MISS this — the review's exact bypass).
    probe("line-to-block",
          src.replace('line("MockQuorumGuard guard;")', 'block("MockQuorumGuard guard;", "}", {})', 1),
          True)
    # A change to a NON-FIRST block argument (the close), first argument unchanged, trips.
    probe("block-nonfirst-arg",
          src.replace('block("interface Vm {", "}",', 'block("interface Vm {", "};",', 1),
          True)
    # Byte-significant whitespace INSIDE a rendered literal (one space -> two) changes the
    # .t.sol bytes and must trip — a lossy whole-arg whitespace collapse would erase it.
    probe("literal-whitespace",
          src.replace('line("MockQuorumGuard guard;")', 'line("MockQuorumGuard  guard;")', 1),
          True)
    # The canonicalizer must not cross an ESCAPED literal boundary: whitespace added inside
    # an escaped `\"…\"` literal (a real harness form) changes the bytes and must trip.
    probe("escaped-literal-whitespace",
          src.replace(r'"vm.expectRevert(bytes(\"replay\"));"',
                      r'"vm.expectRevert(bytes(\"replay \"));"', 1),
          True)
    # A harmless C++ RAW string containing an embedded quote, `//`, `,`, `(`, and even the
    # literal text `line(`/`block(` is NOT a builder call and must NOT change the inventory
    # (raw-aware lexing across comment-strip / string-blank / arg-extraction).
    probe("raw-string-noise",
          src + '\nstatic const char* _r = R"tag(a " // b , ( line(evil) block(x))tag";\n',
          False, expect_change=False)
    # A REAL raw-string authoring call is lexed as a site: line("x") -> line(R"y(x)y") is a
    # different identity (a raw-content byte change likewise) and must reject.
    probe("raw-authoring-call",
          src.replace('line("MockQuorumGuard guard;")', 'line(R"y(MockQuorumGuard guard;)y")', 1),
          True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cpp", default=None, help="override the primary TU (testing)")
    args = ap.parse_args()

    src = load_src(args.cpp)
    if args.emit:
        print(json.dumps(emit_inventory(src), indent=2))
        return 0
    reasons = []
    try:
        inv = load_inventory()
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"solidity-harness-printer gate FAILED: inventory: {e}", file=sys.stderr)
        return 1
    sites = check(src, inv, reasons)
    if args.selftest:
        run_selftest(src, inv, reasons)
    if reasons:
        print("solidity-harness-printer gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    print(f"solidity-harness-printer gate OK: {len(sites)} handwritten .t.sol authoring sites in "
          f"{PRIMARY} (identity-tracked, comment/string-aware, subset-ratcheted vs the resolved base, "
          " toward zero). Committed inventory + derived construct counts reconcile.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
