#!/usr/bin/env python3
"""[ endpoint] Solidity statement-syntax-authority PROHIBITION gate.

 retired handwritten statement DISPATCH;  then retired statement SYNTAX
AUTHORITY by migrating every raw construct to a typed SolidityTargetNodes.td node
(the ratchet reached zero) and DELETING the raw seam (`RawCap`/`rawLine`/`rawBlock`)
outright. The graph-only materializer now authors NO raw Solidity — every
construct is a validated typed node.

The PRIMARY, non-bypassable enforcement is NOT this scanner — it is a RUNTIME
CONSTRUCTION SEAM: every SolStmt constructor routes through
`SolStmt::ensureAuthorable`, which REJECTS the two verbatim `${text}` kinds
(`Line`/`Block`) by their enum VALUE. That is spelling-independent — `Kind::Line`,
`Kind(0)`, a `static_cast`, a C-style cast, an alias all reduce to the same value
and are caught — so a differently named factory or an ordinal-cast bypass cannot
author a raw statement, and it is directly negative-tested for both kinds (see
solidity_model_test.cpp). A source regex could NOT guarantee this (it cannot
enumerate every cast spelling), so it is not the trust anchor.

This scanner is DEFENSE-IN-DEPTH on that runtime seam: it FAILS EARLY, with a
readable diagnostic, on any of —
  - a reference to `Kind::Line`/`Kind::Block` or a cast to the SolStmt Kind enum;
  - a raw seam call / wrapper (`rawLine`/`rawBlock`, or the seam name as a value);
  - a public `SolStmt::line`/`::block` factory reappearing;
  - a SolStmt aggregate/brace construction or const-field mutation (also compile
    errors — the private ctor + const fields, proven by the raw_seam_sealed.cpp
    compile-negative probes);
anywhere in the surface (primary TU, headers, any other TU). There is no inventory
to reconcile and no PR-base ratchet — the only legal count is ZERO.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import sys

import generated_artifacts

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOLIDITY_DIR = os.path.join(REPO, "lib", "backends", "solidity")
PRIMARY_BASENAME = "SolidityTargetAdapter.cpp"
SOURCE_EXT = (".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".inc")

_LIT = re.compile(r'^"((?:[^"\\]|\\.)*)"$')
_SEAM = re.compile(r"\braw(Line|Block)\b")
_REGRESSION = re.compile(r"\bSolStmt\s*::\s*(line|block)\b")
# The PRIMARY, name-INDEPENDENT prohibition ( endpoint): `Line` and `Block`
# are the ONLY two node kinds whose printer template is a verbatim `${text}` (every
# other kind has a fixed structured template — require(...)/emit .../if (...) — that
# cannot emit an arbitrary statement). So ANY production reference to `Kind::Line`
# or `Kind::Block` — through ANY factory name, any constructor syntax, a computed
# OR literal operand — is raw statement authoring and is forbidden. This closes the
# hole a name-based scanner leaves: a differently named SolStmt member (e.g.
# `static SolStmt verbatim(std::string t){ return SolStmt(Kind::Line,{t}); }`)
# legitimately reaches the private ctor, so only prohibiting the KIND catches it.
# The lookbehind excludes `LayoutKind::Line/Block` (a different, printer-layout enum).
_KIND_AUTHOR = re.compile(r"(?<![A-Za-z_])Kind\s*::\s*(Line|Block)\b")
# The ordinal-obfuscation vector: a cast to the SolStmt Kind enum could forge ANY
# kind (incl. Line=0 / Block=6) WITHOUT naming it. Production never casts to Kind
# (legalization always uses named `Kind::X` factory kinds), so any cast to it is
# forbidden — this stops `SolStmt(static_cast<Kind>(0), {text})`. `LayoutKind` (a
# different enum) is excluded by requiring the target to be exactly `[SolStmt::]Kind`.
_KIND_CAST = re.compile(r"(?:static_cast|reinterpret_cast)\s*<\s*(?:SolStmt\s*::\s*)?(?<![A-Za-z_])Kind\s*>")
# Defense-in-depth regressions for the structural encapsulation (these are all
# COMPILE ERRORS now — private ctor + const fields — so they are belt-and-braces):
_AGG_BRACE = re.compile(r"\bSolStmt\s*\{")            # aggregate construction
_FIELD_MUT = re.compile(r"\.(kind|text|aux)\s*=(?!=)")  # field mutation
# The runtime construction seam is only sound if the canonical SolStmt ctor
# actually routes through ensureAuthorable. `_CTOR_KIND_BIND` finds every ctor
# initializer that BINDS the `kind` member (`: kind(` / `, kind(`); each MUST wrap
# it as `kind((ensureAuthorable(k), …))`. A detached `kind(k)` re-opens ordinal
# construction, so it fails closed. (Delegating ctors use `: SolStmt(` and bind no
# member, so they never match — the guard cannot be dodged by a different overload.)
_CTOR_KIND_BIND = re.compile(r"[:,]\s*kind\s*\(")
_CTOR_KIND_GUARDED = re.compile(r"[:,]\s*kind\s*\(\s*\(\s*ensureAuthorable\b")
_CTOR_PROBE_NAME = re.compile(r"\bSolStmtCtorProbe\b")
PRIMARY_HEADER = "SolidityTargetAdapter.h"


# ---- comment-stripped, string-preserving code view -------------------------

def _strip_comments(src):
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '"' or c == "'":
            q = c
            out.append(c)
            i += 1
            while i < n:
                out.append(src[i])
                if src[i] == "\\" and i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
                if src[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append("  ")
                i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _call_args(view, lparen):
    depth, i, n = 1, lparen + 1, len(view)
    cur, args = [], []
    while i < n:
        c = view[i]
        if c == '"' or c == "'":
            j = i + 1
            while j < n:
                if view[j] == "\\":
                    j += 2
                    continue
                if view[j] == c:
                    j += 1
                    break
                j += 1
            cur.append(view[i:j])
            i = j
            continue
        if c in "([{":
            depth += 1
            cur.append(c)
            i += 1
            continue
        if c in ")]}":
            depth -= 1
            if depth == 0:
                args.append("".join(cur))
                return args, i
            cur.append(c)
            i += 1
            continue
        if c == "," and depth == 1:
            args.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    return None, None


# ---- classification --------------------------------------------------------

def _category(text):
    t = text.lstrip()
    if t.startswith("pragma "):
        return "pragma"
    if t.startswith("import "):
        return "import"
    if re.match(r"(interface|contract|library|function|constructor|modifier)\b", t):
        return "signature"
    if re.match(r"[A-Za-z_][\w<>\[\]. ]*(memory|storage|calldata)\b", t):
        return "declaration"
    if re.match(r"[A-Za-z_][\w<>\[\]. ]*\s+[A-Za-z_]\w*\s*=", t):
        return "declaration"
    if "[" in t and "]" in t and "=" in t:
        return "indexed-assign"
    if re.match(r"[A-Za-z_][\w.]*\s*=", t):
        return "assignment"
    return "expr-stmt"


def _digest(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _classify_arg(arg0):
    """(klass, category, prefix, digest). DIGEST covers the FULL normalized
    argument (never truncated); prefix is a human-readable head only."""
    raw = (arg0 or "").strip()
    m = _LIT.match(raw)
    if not m:
        norm = re.sub(r"\s+", " ", raw) or "<empty>"
        return "executable", "computed", norm[:80], _digest("expr:" + norm)
    content = m.group(1)
    norm = re.sub(r"\s+", " ", content).strip()
    if content.lstrip().startswith("//") and not re.search(r"\\n|\\r|\n|\r", content):
        return "comment", "comment", norm[:80], _digest("comment:" + content)
    return "executable", _category(content), norm[:80], _digest("lit:" + content)


# ---- scanning --------------------------------------------------------------

def _function_headers(view):
    out = []
    for m in re.finditer(r"(?m)^[A-Za-z_][\w:<>,&*\s]*?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", view):
        out.append((m.start(), m.group(1)))
    return out


def _enclosing_fn(headers, offset):
    name = "<file-scope>"
    for start, fn in headers:
        if start <= offset:
            name = fn
        else:
            break
    return name


def scan_file(rel, src):
    view = _strip_comments(src)
    headers = _function_headers(view)
    sites, forbidden = [], []

    def site(off, arg0, form):
        klass, cat, prefix, dg = _classify_arg(arg0)
        sites.append({"path": rel, "function": _enclosing_fn(headers, off), "fingerprint": prefix,
                      "digest": dg, "category": cat, "class": klass, "form": form})

    # The RawCap-gated seam: rawLine(cap, <text>) / rawBlock(cap, <open>, <close>).
    # The authored Solidity is the argument AFTER the capability (arg[1]). Skip the
    # seam DEFINITIONS (`SolStmt rawLine(SolStmt::RawCap cap, …)`, preceded by the
    # `SolStmt` return type) and the qualified member forwarders in the wrappers
    # (`SolStmt::rawLine(cap, …)`) — the governed authoring sites are the unqualified
    # `rawLine(cap, …)` / `rawBlock(cap, …)` calls in legalization.
    for m in _SEAM.finditer(view):
        pre = view[max(0, m.start() - 12):m.start()]
        if re.search(r"SolStmt(\s+$|\s*::\s*$)", pre):
            continue
        j = m.end()
        while j < len(view) and view[j] in " \t\n\r":
            j += 1
        if j >= len(view) or view[j] != "(":
            forbidden.append((rel, _enclosing_fn(headers, m.start()),
                              f"raw{m.group(1)} seam used as a value (alias/wrapper), not called directly"))
            continue
        args, _ = _call_args(view, j)
        # args[0] is the RawCap; the authored text is args[1].
        text = args[1] if args and len(args) > 1 else None
        site(m.start(), text, "seam")

    # Regression: the public SolStmt::line/::block factory must never reappear.
    for m in _REGRESSION.finditer(view):
        forbidden.append((rel, _enclosing_fn(headers, m.start()),
                          f"public SolStmt::{m.group(1)} factory reintroduced — raw statement authoring "
                          "is prohibited ( endpoint); build a typed .td node instead"))
    # Regression: SolStmt aggregate construction / field mutation must not reappear
    # (the encapsulation makes both compile errors; this catches a struct-shape
    # regression that would re-open the aggregate/mutation authoring paths).
    for m in _AGG_BRACE.finditer(view):
        if re.search(r"\b(struct|class)\s+$", view[max(0, m.start() - 12):m.start()]):
            continue  # the `struct SolStmt {` definition, not an aggregate init
        forbidden.append((rel, _enclosing_fn(headers, m.start()),
                          "SolStmt aggregate/brace construction — SolStmt is encapsulated; construct via a "
                          "typed factory (raw Line/Block authoring is prohibited,  endpoint)"))
    for m in _FIELD_MUT.finditer(view):
        forbidden.append((rel, _enclosing_fn(headers, m.start()),
                          f"SolStmt field mutation ('.{m.group(1)} =') — SolStmt fields are const/immutable"))
    # The former test-only constructor friend was externally completable: another
    # TU could define this namespace-scope type and bypass every structured
    # factory's operand validation. The name and friend grant are retired.
    for m in _CTOR_PROBE_NAME.finditer(view):
        forbidden.append((rel, _enclosing_fn(headers, m.start()),
                          "retired SolStmtCtorProbe constructor capability reintroduced — "
                          "external friend completion could bypass typed factory validation"))

    # DEFENSE-IN-DEPTH on the runtime construction seam (SolStmt::ensureAuthorable):
    # ANY reference to `Kind::Line` / `Kind::Block` is flagged early, whatever the
    # factory name, constructor syntax, or operand (literal or computed). The one
    # legitimate reference is the guard ITSELF — `ensureAuthorable` names the two
    # kinds precisely to REJECT them (`k == Kind::Line || k == Kind::Block`), so it
    # is exempt; any OTHER function naming the kinds is authoring and forbidden.
    for m in _KIND_AUTHOR.finditer(view):
        fn = _enclosing_fn(headers, m.start())
        if fn == "ensureAuthorable":
            continue
        forbidden.append((rel, fn,
                          f"constructs a raw Kind::{m.group(1)} — raw statement authoring is PROHIBITED "
                          f"( endpoint), independent of factory name; Line/Block are the only verbatim "
                          f"`${{text}}` kinds and must never be authored (build a typed .td node instead)"))
    # Ordinal obfuscation: a cast to the Kind enum could forge Line/Block without
    # naming it — production never casts to Kind, so any such cast is forbidden.
    # (The runtime seam catches the cast by VALUE regardless; this is the early
    # textual signal.)
    for m in _KIND_CAST.finditer(view):
        fn = _enclosing_fn(headers, m.start())
        if fn == "ensureAuthorable":
            continue
        forbidden.append((rel, fn,
                          "casts to SolStmt::Kind — raw statement authoring is PROHIBITED ( endpoint); a "
                          "cast could forge Kind::Line/Block by ordinal. Legalization uses only named factory "
                          "kinds; build a typed .td node instead"))

    return sites, forbidden


def _is_primary(rel):
    return os.path.basename(rel) == PRIMARY_BASENAME


def discover(scan_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(scan_dir, "**", "*"), recursive=True)):
        if path.endswith(SOURCE_EXT) and os.path.sep + "test" + os.path.sep not in path:
            out.append(path)
    return out


def load_files(cpp_override=None, scan_dir=None, build_dir=None):
    scan_dir = scan_dir or SOLIDITY_DIR
    files = {}
    for path in discover(scan_dir):
        rel = os.path.relpath(path, scan_dir if scan_dir != SOLIDITY_DIR else REPO)
        with open(path, encoding="utf-8") as fh:
            files[rel] = fh.read()
    if scan_dir is None:
        for rel in sorted(generated_artifacts.MIGRATED_ARTIFACTS):
            if not rel.startswith("lib/backends/solidity/"):
                continue
            path = generated_artifacts.resolve(rel, build_dir)
            with open(path, encoding="utf-8") as fh:
                files[rel] = fh.read()
    if cpp_override:
        rel = next((r for r in files if _is_primary(r)),
                   "lib/backends/solidity/provider/SolidityTargetAdapter.cpp")
        with open(cpp_override, encoding="utf-8") as fh:
            files[rel] = fh.read()
    return files


def scan_all(files):
    sites, forbidden = [], []
    for rel, src in sorted(files.items()):
        s, f = scan_file(rel, src)
        sites.extend(s)
        forbidden.extend(f)
    return sites, forbidden


# ---- inventory (vestigial: the  endpoint is EMPTY; --emit regenerates the
#      zero-site artifact the  meta-gate counts) --------------------------

def _ident(s):
    return (s["path"], s["function"], s["digest"])


def emit_inventory(files):
    sites, forbidden = scan_all(files)
    if forbidden:
        sys.exit("cannot emit: " + "; ".join(f"{p}:{fn}: {w}" for p, fn, w in forbidden))
    if sites:
        sys.exit("cannot emit: raw statement authoring is PROHIBITED ( endpoint) but "
                 "sites were found: "
                 + ", ".join(f"{s['path']}:{s['function']}" for s in sites))

    def entry(s):
        return {"path": s["path"], "function": s["function"], "digest": s["digest"],
                "fingerprint": s["fingerprint"], "category": s["category"], "form": s["form"]}
    ex = sorted((s for s in sites if s["class"] == "executable"), key=_ident)
    cm = sorted((s for s in sites if s["class"] == "comment"), key=_ident)
    return {
        "kind": "neutrino.solidity-syntax-authority.v2",
        "scope": "raw statement-authoring sites across the recursively-discovered Solidity "
                 "backend surface.  reached its endpoint: every construct is a typed "
                 "SolidityTargetNodes.td node, the raw seam was deleted, and this gate now "
                 "PROHIBITS any raw authoring — the only legal state is zero sites.",
        "note": "Prohibition gate (not a ratchet): no inventory reconcile, no PR-base compare. "
                "The public SolStmt::line/::block factories and the RawCap/rawLine/rawBlock seam "
                "are gone; the SolStmt encapsulation makes forging raw Line/Block a compile error.",
        "primaryTU": "lib/backends/solidity/provider/SolidityTargetAdapter.cpp",
        "baseline": len(ex),
        "executable": [entry(s) for s in ex],
        "comments": [entry(s) for s in cm],
    }


def check_ctor_seam(files, reasons):
    """The PRIMARY  defense is the runtime construction seam — every SolStmt
    ctor routes through ensureAuthorable. That is only sound if the canonical ctor
    actually invokes it; a future edit that detaches it (`kind((ensureAuthorable(k),
    k))` -> `kind(k)`) would silently re-open ordinal construction. This makes the
    routing a GATE-enforced invariant: every kind-binding ctor initializer in the
    header must be guarded, and at least one must exist."""
    hdr = next((src for rel, src in files.items()
                if os.path.basename(rel) == PRIMARY_HEADER), None)
    if hdr is None:
        reasons.append(f"{PRIMARY_HEADER} not found in the discovered surface — cannot verify the "
                       " runtime construction seam (ensureAuthorable routing)")
        return
    view = _strip_comments(hdr)
    if re.search(r"\bfriend\b", view):
        reasons.append(f"{PRIMARY_HEADER} grants SolStmt constructor friendship — a namespace type "
                       "could complete it in another TU and bypass typed factory validation")
    binds = _CTOR_KIND_BIND.findall(view)
    guarded = _CTOR_KIND_GUARDED.findall(view)
    if not binds:
        reasons.append(f"no SolStmt kind-binding constructor found in {PRIMARY_HEADER} — the  "
                       "runtime construction seam is missing (canonical ctor removed/refactored "
                       "without updating this gate)")
    elif len(guarded) != len(binds):
        reasons.append(f"a SolStmt kind-binding constructor in {PRIMARY_HEADER} does NOT route through "
                       f"ensureAuthorable ({len(guarded)}/{len(binds)} guarded) — the  construction "
                       "seam is DETACHED; the canonical ctor must bind `kind((ensureAuthorable(k), k))` "
                       "so raw Line/Block authoring is rejected by enum value")
    witness = len(re.findall(
        r"static\s+bool\s+rejectsAtConstructionForTest\s*\(\s*Kind\s+k\s*\)\s*;",
        view))
    if witness != 1:
        reasons.append(f"{PRIMARY_HEADER}: constructor witness must be the single non-authoring "
                       "bool(Kind) interface")


def check(files, reasons):
    """PROHIBITION ( endpoint): NO raw statement-authoring site — executable
    or comment, primary TU or off-TU — may exist in the discovered surface, no
    forbidden structural regression (public factory, seam-as-value, aggregate,
    field mutation) may reappear, and the runtime construction seam stays guarded.
    The only legal count is zero."""
    sites, forbidden = scan_all(files)
    for path, fn, w in forbidden:
        reasons.append(f"forbidden raw authoring in {path} [{fn}]: {w}")
    for s in sites:
        where = "" if _is_primary(s["path"]) else " (and only typed .td nodes may be authored anywhere)"
        reasons.append(f"raw {s['form']} statement authoring is PROHIBITED ( endpoint) in "
                       f"{s['path']} [{s['function']}] '{s['fingerprint']}' — legalization must build a "
                       f"typed SolidityTargetNodes.td node, never raw Line/Block text{where}")
    check_ctor_seam(files, reasons)


# ---- non-vacuity selftest --------------------------------------------------

def run_selftest(reasons):
    """Non-vacuity: inject each reintroduction bypass into the CLEAN (=0)
    source and prove the PROHIBITION gate rejects it. The clean source has zero
    raw sites, so `r` is empty IFF an injection escaped."""
    files0 = load_files()
    prim = next(r for r in files0 if _is_primary(r))
    clean = files0[prim]
    # The exact target-adapter ownership point: splice the rogue into the
    # typed-node -> CodeText adapter, not an unrelated provider/renderer.
    insert_anchor = "codetext::Node toNode(const SolStmt &s) {"
    if insert_anchor not in clean:
        reasons.append(f"selftest insertion anchor not found in {prim}; update the probe")
        return

    def files_with(prim_src):
        f = dict(files0)
        f[prim] = prim_src
        return f

    def mut(extra):
        return files_with(clean.replace(insert_anchor, insert_anchor + "\n  " + extra, 1))

    # The header carries the SolStmt class; a bypass member is spliced beside
    # the generated Emit declarations (a member LEGITIMATELY reaches the private
    # ctor — only prohibiting the Kind catches it).
    hdr_key = next((r for r in files0
                    if os.path.basename(r) == "SolidityTargetAdapter.h"), None)
    hdr_src = files0.get(hdr_key, "")
    hdr_anchor = '#include "SolidityEmitBuilderDecls.inc"'

    def mut_member(member_decl):
        if hdr_key is None or hdr_anchor not in hdr_src:
            reasons.append("selftest header anchor not found; update the probe")
            return files0
        f = dict(files0)
        f[hdr_key] = hdr_src.replace(hdr_anchor, hdr_anchor + "\n  " + member_decl, 1)
        return f

    def expect(name, files, needle):
        r = []
        check(files, r)
        blob = " || ".join(r)
        if not r:
            reasons.append(f"probe {name} did NOT trip (a reintroduction bypass escaped the prohibition)")
        elif needle not in blob:
            reasons.append(f"probe {name} tripped for the wrong reason: {blob}")

    # PRIMARY hole (the review P1): a DIFFERENTLY NAMED SolStmt member that reaches
    # the private ctor to author a raw Kind::Line/Block with a COMPUTED operand. A
    # name-based scanner misses it; the Kind-level prohibition catches it.
    expect("member-factory-verbatim-line",
           mut_member('static SolStmt verbatim(std::string text) { return SolStmt(Kind::Line, {std::move(text)}); }'),
           "PROHIBITED")
    expect("member-factory-computed-block",
           mut_member('static SolStmt rawblk(std::string o, std::string c, std::vector<SolStmt> b) '
                      '{ return SolStmt(Kind::Block, {std::move(o), std::move(c)}, std::move(b)); }'),
           "PROHIBITED")
    # A re-added raw seam call (the seam is deleted; a re-added spelling is caught
    # textually before it can compile).
    expect("reintroduced-seam-line", mut('body.push_back(rawLine(cap, "selfdestruct();"));'), "PROHIBITED")
    expect("reintroduced-seam-block", mut('body.push_back(rawBlock(cap, "while(true){", "}", {}));'), "PROHIBITED")
    # The seam name used as a value (alias/wrapper indirection).
    expect("seam-value-use", mut("auto rogue = rawLine;"), "used as a value")
    # The removed public factory reappearing.
    expect("regression-public-factory", mut('body.push_back(SolStmt::line("selfdestruct();"));'),
           "public SolStmt::line factory reintroduced")
    # SolStmt aggregate/brace construction + const-field mutation (also compile
    # errors; the scanner catches a struct-shape regression that would re-open them).
    expect("regression-aggregate", mut('SolStmt r = SolStmt{SolStmt::Kind::Line, std::string("evil"), {}, {}};'),
           "aggregate/brace construction")
    expect("regression-field-mutation", mut("body.back().kind = SolStmt::Kind::Block;"),
           "field mutation")
    # The exact  exploit: restore the old friend grant, complete its
    # namespace-scope name in another TU, and construct a malformed structured
    # kind that bypasses localDecl's separator validation.
    friend_escape = dict(files0)
    if hdr_key is not None:
        friend_escape[hdr_key] = hdr_src.replace(
            "\n};\n\n// The GENERATED node-metadata table",
            "\n  friend struct SolStmtCtorProbe;\n};\n\nstruct SolStmtCtorProbe;\n\n"
            "// The GENERATED node-metadata table", 1)
        friend_escape["lib/backends/solidity/CtorEscape.cpp"] = (
            "namespace neutrino::solidity_model { struct SolStmtCtorProbe { "
            "static SolStmt go() { return SolStmt(SolStmt::Kind::LocalDecl, "
            "{std::string(\"uint256 x; selfdestruct(); //\"), "
            "std::string(\"ignored\"), std::string(\"0\")}, {}); } }; }\n")
        expect("constructor-friend-completion", friend_escape,
               "constructor capability reintroduced")
    else:
        reasons.append("selftest constructor-friend header not found; update the probe")
    # Direct `Kind::Line` authoring with a literal operand.
    expect("direct-kind-line", mut('SolStmt rogue = make(SolStmt::Kind::Line, "selfdestruct();");'), "PROHIBITED")
    # A COMPUTED operand through a non-seam spelling — name-INDEPENDENT (this is the
    # probe the review noted must not merely re-spell `rawLine(...)`).
    expect("computed-kind-arg", mut('SolStmt rogue = build(SolStmt::Kind::Line, makeRogue());'), "PROHIBITED")
    # Ordinal obfuscation: forge a kind by CASTING an ordinal (never names Kind::Line).
    expect("kind-cast-obfuscation",
           mut_member('static SolStmt sneaky(std::string t) '
                      '{ return SolStmt(static_cast<Kind>(0), {std::move(t)}); }'),
           "casts to SolStmt::Kind")
    # SEAM DETACHMENT — the review's exact regression: dropping ensureAuthorable
    # from the canonical ctor (`kind((ensureAuthorable(k), k))` -> `kind(k)`) must
    # FAIL, so the runtime routing is a gate-enforced invariant, not just a helper.
    seam_anchor = "kind((ensureAuthorable(k), k))"
    if hdr_key is not None and seam_anchor in hdr_src:
        detached = dict(files0)
        detached[hdr_key] = hdr_src.replace(seam_anchor, "kind(k)")
        expect("ctor-seam-detached", detached, "construction seam is DETACHED")
    else:
        reasons.append("selftest ctor-seam anchor not found in the header; update the probe")
    # A re-added seam call with a `//`-prefixed argument carrying a smuggled newline.
    expect("comment-code-tail", mut(r'body.push_back(rawLine(cap, "// ok?\nselfdestruct();"));'), "PROHIBITED")
    # A single-line `//` comment is ALSO prohibited now (no reviewed-comment seam
    # survives the  endpoint).
    expect("comment-authoring", mut('body.push_back(rawLine(cap, "// a fresh doc line"));'), "PROHIBITED")
    # Off-TU authoring in another discovered TU (recursive/header discovery).
    hdr = dict(files0)
    hdr["lib/backends/solidity/RawWrapper.h"] = "inline SolStmt mk() { return rawLine(\"selfdestruct();\"); }\n"
    expect("header-wrapper", hdr, "PROHIBITED")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cpp", default=None, help="override the primary TU source (testing)")
    ap.add_argument("--dir", default=None, help="scan an alternate directory (discovery testing)")
    ap.add_argument(
        "--build-dir",
        default=os.environ.get("NEUTRINO_BUILD_DIR", os.path.join(REPO, "out")),
    )
    args = ap.parse_args()

    if args.emit:
        print(json.dumps(emit_inventory(load_files(args.cpp, args.dir, args.build_dir)), indent=2))
        return 0

    reasons = []
    check(load_files(args.cpp, args.dir, args.build_dir), reasons)
    if args.selftest:
        run_selftest(reasons)
    if reasons:
        print("solidity-syntax-authority gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    print("solidity-syntax-authority gate OK: raw statement authoring is PROHIBITED and absent "
          "( endpoint) — 0 raw sites across the recursively-discovered Solidity backend surface; "
          "the RawCap/rawLine/rawBlock seam and the public SolStmt::line/::block factories are deleted; "
          "SolStmt stays encapsulated (private ctor + const fields); no forbidden authoring or off-TU leakage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
