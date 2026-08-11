#!/usr/bin/env python3
""" (M6 correction C1) — target-node printer replacement gate.

The Solidity typed-target-model statement kinds () are GENERATED from
`SolidityTargetNodes.td` into the committed X-macro registry `SolidityTargetNodes.inc`
(by `scripts/generators/gen_target_node_registry.py`). Before the pilot the same kind
list was hand-triplicated (enum + `toNode` switch + unit test) with no gate — only the
compiler's switch-exhaustiveness plus a manual `return blank(); // unreachable` crutch.
This gate makes the generated registry the single source of truth and reconciles it with
both generated and not-yet-retired handwritten printer dispatch:

  - STALE-OUTPUT   : the committed generated `.inc` files match the `.td`.
  - DETERMINISTIC  : regenerating twice yields byte-identical output.
  - GENERATED ENUM : the model header expands the `.inc` (it did not silently re-grow a
                     hand-written enum that could drift from the registry).
  - COVERAGE       : every registry kind has exactly one handler, either generated or
                     handwritten during the partial  slice.
  - RETIREMENT     : generated handlers have no retained handwritten fallback/case.
  - INVENTORY      : handwritten target-specific per-node emission strictly decreases.

Fail-closed. `--selftest` runs it against the committed repo files. The lit test drives
non-vacuous tampers via --inc/--cpp/--header overrides.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys

from check_cpp_policy import strip_comments as strip_cpp_comments

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
GEN = os.path.join(REPO, "scripts", "generators", "gen_target_node_registry.py")
TD = os.path.join(REPO, "lib", "backends", "solidity", "model", "SolidityTargetNodes.td")
#  A1: these are build products. NEUTRINO_BUILD_DIR (or --build-dir) selects
# the configured build tree; the source-tree path is kept only as the value a
# caller sees when neither is supplied, and resolution then fails closed rather
# than silently reading a stale committed copy that no longer exists.
_GENERATED_REL = os.path.join("lib", "backends", "solidity", "generated")
_BUILD_DIR = os.environ.get("NEUTRINO_BUILD_DIR", "")


def _in_build_tree(source_path):
    """The configured build tree's counterpart of a source-tree path, if any.

    The build tree mirrors the source layout, so the mapping is the same relative
    path under the build root. Returns None when no build tree is configured, so
    callers keep their source-tree behaviour for unmigrated backends.
    """
    if not _BUILD_DIR:
        return None
    return os.path.join(_BUILD_DIR, os.path.relpath(source_path, REPO))


def _generated(name, build_dir=None):
    root = build_dir or _BUILD_DIR or REPO
    return os.path.join(root, _GENERATED_REL, name)


INC = _generated("SolidityTargetNodes.inc")
PRINTER = _generated("SolidityPrinterHandlers.inc")
CPP = os.path.join(REPO, "lib", "backends", "solidity", "provider", "SolidityTargetAdapter.cpp")
HDR = os.path.join(REPO, "lib", "backends", "solidity", "provider", "SolidityTargetAdapter.h")
INVENTORY = os.path.join(REPO, "scripts", "gates", "target_printer_inventory.json")


def discover_backends():
    """Every registered target-printer backend, DISCOVERED from its committed `.td`
    (glob `lib/backends/**/*TargetNodes.td`) rather than a hardcoded path list — a
    backend joins the generator + this gate by adding its `.td` + generated `.inc`s,
    no gate edit.

     P1.2 (naming/descriptor): the model source/header + generated-output names
    are DERIVED FROM THE RECORD'S `Target` FIELD (read from the `.td`'s
    `TargetPrinterNode<"target","model", …>` instantiation) — NOT from the `.td`
    filename STEM. So `Target="postgres"` -> `PostgresModel.{cpp,h}` /
    `PostgresTargetNodes.inc` / `PostgresPrinterHandlers.inc`. Solidity's split
    target-node ownership is the exact `SolidityTargetAdapter.{cpp,h}` pair; no
    directory-wide fallback is accepted. The X-macro name is read from the committed `.inc` and the dispatch model
    type from the committed printer; `_backend_identity_reasons` then validates every
    derived name fail-closed (P1.3: no Solidity fallback)."""
    import glob
    out = []
    root = os.path.join(REPO, "lib", "backends")
    suffix = "TargetNodes.td"
    for td in sorted(glob.glob(os.path.join(root, "**", "*" + suffix), recursive=True)):
        d = os.path.dirname(td)
        td_text = _read(td)
        # Target/Model are the record fields (the shared TargetPrinterNode base is
        # instantiated as `TargetPrinterNode<"target","model", …>`).
        node_identities = re.findall(
            r'TargetPrinterNode\s*<\s*"([^"]+)"\s*,\s*"([^"]+)"', td_text)
        model_decls = re.findall(
            r'TargetPrinterModel\s*<\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*'
            r'"([^"]+)"\s*,\s*([01])\s*>', td_text)
        target = node_identities[0][0] if node_identities else None
        primary_models = [model_name for _target, model_name, _abbrev, primary in model_decls
                          if primary == "1"]
        model = primary_models[0] if len(primary_models) == 1 else None
        models = set(re.findall(
            r'TargetPrinterNode\s*<\s*"[^"]+"\s*,\s*"([^"]+)"', td_text))
        models.update(re.findall(
            r'TargetPrinterModel\s*<\s*"[^"]+"\s*,\s*"([^"]+)"', td_text))
        cap = target[:1].upper() + target[1:] if target else None
        #  R1/R4: generated .inc live under the package `generated/` dir; when
        # the `.td` sits in a `model/` subdir with a sibling `generated/`, resolve
        # the generated outputs there. Flat (not-yet-restructured) backends keep the
        # .td-co-located outputs.
        # : generated outputs may live in the configured BUILD tree rather
        # than the source tree. Prefer the build-tree `generated/` dir when one is
        # configured; fall back to a source-tree `generated/` only for backends
        # not yet migrated. A backend whose outputs exist in neither is caught by
        # the fail-closed identity checks below rather than silently resolving to
        # the model dir.
        gen_d = d
        if os.path.basename(d) == "model":
            source_generated = os.path.join(os.path.dirname(d), "generated")
            build_generated = _in_build_tree(source_generated)
            if build_generated and os.path.isdir(build_generated):
                gen_d = build_generated
            elif os.path.isdir(source_generated):
                gen_d = source_generated
        inc = os.path.join(gen_d, cap + "TargetNodes.inc") if cap else None
        printer = os.path.join(gen_d, cap + "PrinterHandlers.inc") if cap else None
        owner_stem = cap + ("TargetAdapter" if target == "solidity" else "Model") if cap else None
        # The handwritten owner cpp/hdr live under the package `provider/` dir when
        # the backend puts them there (Solidity  R1: provider/SolidityTargetAdapter),
        # otherwise beside the `.td` (PostgreSQL keeps PostgresModel.{cpp,h} in model/;
        # flat backends co-locate). Resolve by where the file actually is.
        cpp = hdr = None
        if owner_stem:
            prov = (os.path.join(os.path.dirname(d), "provider")
                    if os.path.basename(d) == "model" else None)
            cpp_prov = os.path.join(prov, owner_stem + ".cpp") if prov else None
            hdr_prov = os.path.join(prov, owner_stem + ".h") if prov else None
            cpp = (cpp_prov if cpp_prov and os.path.isfile(cpp_prov)
                   else os.path.join(d, owner_stem + ".cpp"))
            hdr = (hdr_prov if hdr_prov and os.path.isfile(hdr_prov)
                   else os.path.join(d, owner_stem + ".h"))
        macro = None
        macros = {}
        if inc and os.path.isfile(inc):
            inc_text = _read(inc)
            for mm in re.finditer(r"//\s+(\w+):\s+(NEU_[A-Z0-9_]+_NODE)\(", inc_text):
                macros[mm.group(1)] = mm.group(2)
            if not macros:
                mm = re.search(r"#define\s+(NEU_[A-Z0-9_]+_NODE)\b", inc_text)
                if mm and model:
                    macros[model] = mm.group(1)
            macro = macros.get(model)
        printer_models = set()
        if printer and os.path.isfile(printer):
            printer_models.update(re.findall(r"handlerFor\((\w+)::Kind", _read(printer)))
        out.append({
            # The role directory is commonly named `model` after  and is
            # therefore not a backend identity. Use the `.td`-declared target
            # that also derives every generated/owner path above.
            "name": target,
            "target": target,
            "td": td,
            "inc": inc,
            "printer": printer,
            "cpp": cpp,
            "hdr": hdr,
            "inc_basename": os.path.basename(inc) if inc else None,
            "macro": macro,
            "macros": macros,
            "model": model,
            "models": sorted(models),
            "model_declarations": model_decls,
            "primary_models": primary_models,
            "printer_model": model if model in printer_models else None,
            "printer_models": sorted(printer_models),
        })
    return out


# The per-target syntax-authority inventories the retirement ratchet reads (
# P1.1): each backend accounts against ITS OWN raw-authoring inventory.
_SYNTAX_AUTHORITY_REL = {
    "solidity": "scripts/gates/solidity_syntax_authority_inventory.json",
    "postgres": "scripts/gates/postgres_syntax_authority_inventory.json",
}


def _backend_identity_reasons(b):
    """Fail-closed validation of a discovered backend's registry-derived identity
    ( P1.3): every descriptor must be derivable from the `Target`/`Model` record
    fields and every derived committed file must exist — no Solidity fallback, and a
    missing/malformed identity is rejected explicitly rather than silently defaulted."""
    reasons = []
    for key in ("target", "model", "macro", "models", "macros", "model_declarations",
                "primary_models", "inc", "printer", "cpp", "hdr", "inc_basename"):
        if not b.get(key):
            reasons.append(f"backend {b['name']}: could not derive '{key}' from the record "
                           "Target/Model field or committed generated files (fail closed; "
                           "no default backend identity)")
    for key in ("inc", "printer", "cpp", "hdr"):
        p = b.get(key)
        if p and not os.path.isfile(p):
            reasons.append(f"backend {b['name']}: Target-derived {key} "
                           f"{os.path.relpath(p, REPO)} does not exist — the .td Target must "
                           "match the committed model-source/generated-output names (fail closed)")
    if set(b.get("printer_models", [])) - set(b.get("models", [])):
        reasons.append(f"backend {b['name']}: committed printer has undeclared model(s) "
                       f"{sorted(set(b.get('printer_models', [])) - set(b.get('models', [])))}")
    if set(b.get("macros", {})) != set(b.get("models", [])):
        reasons.append(f"backend {b['name']}: model-qualified registry macros "
                       f"{sorted(b.get('macros', {}))} do not cover declared models "
                       f"{sorted(b.get('models', []))}")
    declarations = b.get("model_declarations", [])
    if declarations:
        declared_models = [model for _target, model, _abbrev, _primary in declarations]
        if len(declared_models) != len(set(declared_models)):
            reasons.append(f"backend {b['name']}: duplicate TargetPrinterModel declaration")
        if set(declared_models) != set(b.get("models", [])):
            reasons.append(f"backend {b['name']}: TargetPrinterModel declarations do not cover every wrapper model")
        if len(b.get("primary_models", [])) != 1:
            reasons.append(f"backend {b['name']}: exactly one TargetPrinterModel must be Primary")
    if b.get("target") and b["target"] not in _SYNTAX_AUTHORITY_REL:
        reasons.append(f"backend {b['name']}: target {b['target']!r} has no registered "
                       "syntax-authority inventory for the per-target retirement ratchet")
    return reasons


def fail(reasons, msg):
    reasons.append(msg)


def inc_records(inc_text, macro="NEU_SOL_NODE"):
    # <macro>(Sym, Ordinal, "handler", leaf, "feature")
    return [(m.group(1), int(m.group(2)))
            for m in re.finditer(re.escape(macro) + r'\((\w+),\s*(\d+),', inc_text)]


def dispatch_cases(cpp_text, model="SolStmt"):
    # `case <Model>::Kind::Sym:` inside toNode — the hand-written printer handlers.
    body = re.search(r"codetext::Node toNode\(const " + re.escape(model) + r" &s\)\s*\{(.*?)\n\}",
                     cpp_text, re.S)
    scope = body.group(1) if body else cpp_text
    return [m.group(1) for m in re.finditer(
        r"case\s+(?:[A-Za-z_]\w*::)*" + re.escape(model) + r"::Kind::(\w+):", scope)]


def generated_handlers(printer_text):
    out = []
    arrays = re.finditer(
        r"target_printer::Handler\s+k(\w+)Handlers\[\]\s*=\s*\{(.*?)\n\};",
        printer_text, re.S)
    for array in arrays:
        model, body = array.group(1), array.group(2)
        for m in re.finditer(
                r'\{\s*(\d+),\s*"([^"]+)",\s*"([^"]+)",\s*"[^"]+",\s*target_printer::LayoutKind::',
                body):
            out.append((model, int(m.group(1)), m.group(2), m.group(3)))
    if not out:
        mm = re.search(r"handlerFor\((\w+)::Kind", printer_text)
        model = mm.group(1) if mm else ""
        for m in re.finditer(
                r'\{\s*(\d+),\s*"([^"]+)",\s*"([^"]+)",\s*"[^"]+",\s*target_printer::LayoutKind::',
                printer_text):
            out.append((model, int(m.group(1)), m.group(2), m.group(3)))
    return out


def generated_templates(printer_text):
    # node -> (openSyntax, closeSyntax, operandCount) for each generated handler
    # row. Strings may carry escaped quotes (\"), so the quoted-string capture
    # allows escapes. The operand count is part of the framing classification:
    # fieldless Blank is structural, while a Blank carrying even a placeholder
    # operand is an open pass-through and must not inherit that classification.
    rx = re.compile(
        r'\{\s*\d+,\s*"[^"]+",\s*"([^"]+)",\s*"[^"]+",\s*'
        r'target_printer::LayoutKind::\w+,\s*(?:true|false),\s*'
        r'"((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)",\s*'
        r'(?:nullptr|k[A-Za-z_]\w*),\s*(\d+)')
    return {m.group(1): (m.group(2), m.group(3), int(m.group(4)))
            for m in rx.finditer(printer_text)}


def is_bare_passthrough(open_syntax, close_syntax):
    # A "bare pass-through" template carries NO literal target syntax of its own:
    # after removing every ${field} placeholder, only whitespace remains (the empty
    # `blank`, the verbatim `${text}` line, the `${text}`…`${close}` block). Such a
    # node emits whatever handwritten text legalization hands it — it does NOT
    # retire target syntax into the .td, so it must be an explicitly reviewed
    # generic-framing handler, never credited as a migrated typed-syntax node.
    combined = (open_syntax or "") + (close_syntax or "")
    return re.sub(r"\$\{[^}]*\}", "", combined).strip() == ""


def _read(path):
    return open(path, encoding="utf-8").read()


def _rel(path):
    """Repo-relative identity for a path, stable across the  relocation.

    A generated artifact resolved from the configured build tree is recorded by
    its canonical repo-relative path, because the build tree mirrors the source
    layout. Handler identity therefore does not change when generation moves out
    of the source tree, and the PR-relative ratchet keeps comparing handler SETS
    rather than file locations -- a pure relocation is correctly a no-op instead
    of reading as a wholesale add that retires nothing.
    """
    absolute = os.path.abspath(path)
    if _BUILD_DIR:
        build_root = os.path.abspath(_BUILD_DIR)
        if absolute.startswith(build_root + os.sep):
            return os.path.relpath(absolute, build_root)
    return os.path.relpath(absolute, REPO)


def _git_lines(*args):
    try:
        return subprocess.check_output(["git", "-C", REPO] + list(args), text=True,
                                       stderr=subprocess.DEVNULL).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return []


def _git_show(ref, path):
    try:
        return subprocess.check_output(["git", "-C", REPO, "show", f"{ref}:{path}"],
                                       text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_ok(*args):
    """True iff `git <args>` exits 0 (for `cat-file -e` presence checks, which
    succeed with EMPTY stdout — so _git_lines cannot distinguish success)."""
    try:
        subprocess.check_output(["git", "-C", REPO] + list(args),
                                stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _default_model(target):
    return {"solidity": "SolStmt", "postgres": "PgStmt"}.get(target, "")


def _item_model(item):
    return item.get("model") or _default_model(item.get("target"))


def _qualified(model, node):
    return f"{model}::{node}"


def _inventory_key(item):
    return (item["target"], _item_model(item), item["path"], item["node"], item["matcher"])


#  governance capability: the GENERIC sealed-body-carrier exemption. A backend
# may register an emitter `case` in `/sealedBodyCarriers` to exempt it from the
# handwritten-printer inventory — but ONLY while that case is the SOLE permitted
# opaque pass-through: it hands a pre-rendered node straight to the document and
# authors nothing else. This is the ONE shape allowed:
#
#     <dst>.push_back(*<s>.<member>); return;
#
# (identifier + member names free, everything else fixed.) Any extra statement,
# call, or literal inside the case — a `ct::line("…")`, a raw block, a second
# push_back — makes the body no longer match, so the exemption is DENIED and the
# site is re-counted as a genuinely handwritten dispatch case. The seal is thus
# STRUCTURAL (the whole case body, not just its `case` label) and MUTATION-
# SENSITIVE (any edit to the body trips it), so the allowlist can never mask
# handwritten syntax added later. This is the reusable gate machinery only; a
# migration that consumes it registers its concrete carrier + retirement in its
# own separately-reviewed PR (per  — governance widening is never bundled
# with the slice that benefits from it).
_SEALED_PASSTHROUGH_RE = re.compile(
    r"^[A-Za-z_]\w*\.push_back\(\*[A-Za-z_]\w*\.[A-Za-z_]\w*\);return;$")


def _strip_cpp_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def sealed_case_body(src, matcher):
    """The NORMALIZED executable body of the emitter `case` named by `matcher`
    (e.g. 'case Stmt::Kind::Guard:') — comments stripped and ALL whitespace
    removed, so it is exactly the statement text between the case label and the
    next case/default label or the switch close. None if the case is absent."""
    idx = src.find(matcher)
    if idx < 0:
        return None
    rest = src[idx + len(matcher):]
    stop = re.search(r"\n[ \t]*(?:case\s|default:|\}\s*\n)", rest)
    body = rest[:stop.start()] if stop else rest
    return re.sub(r"\s+", "", _strip_cpp_comments(body))


def sealed_carrier_reasons(inv, scanned, read_source):
    """Validate `sealedBodyCarriers` STRUCTURALLY. `read_source(path)` returns the
    source text (injectable so a gate self-test can feed a tampered case). Returns
    (reasons, ok_keys): `reasons` is non-empty when an exemption is denied (a
    phantom site, or a case body that is not the sole permitted opaque
    pass-through); `ok_keys` are the inventory keys that EARNED the exemption and
    may be filtered from the handwritten scan. A denied carrier is NOT in ok_keys,
    so it stays in the scan and is re-counted as a handwritten site (fail-closed)."""
    reasons = []
    scanned_keys = {_inventory_key(s) for s in scanned}
    ok_keys = set()
    for c in inv.get("sealedBodyCarriers", []):
        key = _inventory_key(c)
        if key not in scanned_keys:
            reasons.append(
                "sealedBodyCarriers allowlist references a site not present in the scan "
                f"(a phantom seal cannot mask a real handwritten site): {c['target']}:"
                f"{c['path']}:{c['node']}")
            continue
        body = sealed_case_body(read_source(c["path"]), c["matcher"])
        if body is None or not _SEALED_PASSTHROUGH_RE.match(body):
            reasons.append(
                f"sealedBodyCarriers case {c['node']} ({c['path']}) is not the sole permitted "
                "opaque pass-through `<dst>.push_back(*<s>.<member>); return;` — it authors "
                f"extra statements/calls/literals, so it can hide handwritten syntax; exemption "
                f"DENIED (normalized body: {body!r})")
            continue
        ok_keys.add(key)
    return reasons, ok_keys


def load_inventory(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("kind") != "neutrino.target-printer-inventory.v1":
        raise ValueError("target-printer inventory kind is missing or unsupported")
    sites = data.get("handwrittenSites")
    if not isinstance(sites, list):
        raise ValueError("target-printer inventory has no handwrittenSites list")
    return data


# The handwritten Solidity CONSTRUCT-emission sites ( substrate). `printSolidity`
# is a REVIEWED emitter span, so its per-construct syntax (the enum/event/contract
# framing) and the SolStorage/SolFunction decl-rendering helpers are invisible to
# the statement inventory that scan_handwritten_inventory builds above. This governs
# each construct as a distinct site keyed on the construct's GRAMMAR MARKER — a
# marker that is present while the construct is handwritten and GONE once it migrates
# to a typed .td node — so each construct migration STRICTLY DECREASES the count
# (the  construct ratchet), exactly like the statement slices.
_CPP_REL = "lib/backends/solidity/provider/SolidityTargetAdapter.cpp"
_HDR_REL = "lib/backends/solidity/provider/SolidityTargetAdapter.h"
# (node, literal grammar marker inside printSolidity, human matcher).
_SOLIDITY_PRINTSOLIDITY_CONSTRUCTS = (
    ("EnumDecl", '"enum "', "printSolidity emits `enum <name> { <variants> }`"),
    ("EventDecl", '"event "', "printSolidity emits `event <name>(<params>);`"),
    ("ContractShell", '"contract "', "printSolidity emits `contract <name> { ... }`"),
)


def _strip_comments_keep_strings(src):
    """Remove `//` and `/* */` comments but PRESERVE string/char literals — the
    construct grammar we key on lives INSIDE the string literals (unlike
    strip_cpp_comments, which blanks strings too), while a marker mentioned in a
    comment must not count."""
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
                if src[i] == "\\":
                    i += 1
                    if i < n:
                        out.append(src[i])
                        i += 1
                    continue
                if src[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _balanced_body(text, open_brace_index):
    """The `{...}` substring starting at `open_brace_index` (a `{`), or ""."""
    depth = 0
    for i in range(open_brace_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_index:i + 1]
    return ""


def solidity_construct_sites(cpp_text, hdr_text):
    """The governed handwritten construct-emission sites, comment-stripped so a
    marker mentioned in prose does not count. Each site vanishes when its construct
    migrates to a generated .td handler."""
    sites = []
    cpp_nc = _strip_comments_keep_strings(cpp_text)
    hdr_nc = _strip_comments_keep_strings(hdr_text)
    m = re.search(
        r"renderSolidityProjection\s*\([^;{}]*\)\s*\{", cpp_nc
    )
    ps_body = _balanced_body(cpp_nc, m.end() - 1) if m else ""
    for node, marker, matcher in _SOLIDITY_PRINTSOLIDITY_CONSTRUCTS:
        if marker in ps_body:
            sites.append({"target": "solidity", "node": node, "path": _CPP_REL,
                          "matcher": matcher})
    # The storage-slot decl grammar `<type> <modifiers> <name>;`, rendered by the
    # storageDecl helper (retired when the StorageDecl node migrates).
    if re.search(r"std::string\s+storageDecl\s*\(", cpp_nc):
        sites.append({"target": "solidity", "node": "StorageDecl", "path": _CPP_REL,
                      "matcher": "storageDecl renders `<type> <modifiers> <name>;`"})
    # The function-signature grammar, rendered by SolFunction::signature.
    if re.search(r"std::string\s+signature\s*\(\s*\)\s*const", hdr_nc):
        sites.append({"target": "solidity", "node": "FunctionSig", "path": _HDR_REL,
                      "matcher": "SolFunction::signature renders "
                                 "`<keyword> <name>(<params>) <modifiers>`"})
    # The per-PARAMETER grammar `<type> [<location>] <name>`, authored by the
    # handwritten SolParam::render (): a Solidity-syntax authority that must
    # not be hidden. The event path no longer uses it (params are the EventDecl
    # repeated-field projection), but SolFunction::signature still does — so it is
    # surfaced here and retires WITH FunctionSig at item 12 (they are the one
    # `<type> [<location>] <name>` authority the signature depends on). The match is
    # SCOPED to the balanced `struct SolParam { … }` body ( P1.1), so an
    # unrelated `std::string render() const` elsewhere in the header cannot
    # false-green the site, nor can renaming SolParam::render away leave it standing.
    m_param = re.search(r"struct\s+SolParam\s*\{", hdr_nc)
    param_body = _balanced_body(hdr_nc, m_param.end() - 1) if m_param else ""
    if re.search(r"std::string\s+render\s*\(\s*\)\s*const", param_body):
        sites.append({"target": "solidity", "node": "ParamRender", "path": _HDR_REL,
                      "matcher": "SolParam::render authors "
                                 "`<type> [<location>] <name>` (retires with "
                                 "FunctionSig at item 12)"})
    return sites


_PG_TARGET_REL = "lib/targets/PostgresTarget.cpp"
_PG_MODEL_REL = "lib/backends/postgres/model/PostgresModel.cpp"
# Classification registry only. Discovery scans every string literal in both
# governed source files before consulting these identities.
_PG_SCHEMA_IDENTITIES = (
    (_PG_TARGET_REL, "schemaSql", "ledger_balance", "LedgerBalanceTable"),
    (_PG_TARGET_REL, "schemaSql", "posting_idempotency", "PostingIdempotencyTable"),
    (_PG_TARGET_REL, "schemaSql", "postings", "PostingsTable"),
    (_PG_TARGET_REL, "schemaSql", "coordination_status", "CoordinationStatusTable"),
    (_PG_TARGET_REL, "schemaSqlEvidence", "coordination_status", "CoordinationStatusTable"),
    (_PG_MODEL_REL, "renderTemporalSchema", "authorized_observer", "AuthorizedObserverTable"),
    (_PG_MODEL_REL, "renderTemporalSchema", "quorum_acceptance", "TemporalQuorumAcceptanceTable"),
    (_PG_MODEL_REL, "renderTemporalSchema", "committed_group", "CommittedGroupTable"),
    (_PG_MODEL_REL, "renderTemporalSchema", "key_claim", "KeyClaimTable"),
    (_PG_MODEL_REL, "renderQuorumSchema", "authorized_observer", "AuthorizedObserverTable"),
    (_PG_MODEL_REL, "renderQuorumSchema", "quorum_acceptance", "QuorumAcceptanceTable"),
)
_PG_ZERO_DECLARATION_CLASSES = (
    ("CreateIndex", "CREATE INDEX"),
    ("CreateType", "CREATE TYPE"),
    ("AlterTable", "ALTER TABLE"),
    ("ForeignKey", "FOREIGN KEY"),
    ("UniqueConstraint", "UNIQUE"),
)


def _cpp_adjacent_string_runs(src):
    """Decode C++ string literals, joining only lexically adjacent literals."""
    literal = re.compile(
        r'(?:(?:u8|u|U|L)?R"(?P<delim>[^ ()\\\t\r\n]{0,16})\('
        r'(?P<raw>.*?)\)(?P=delim)"|'
        r'(?:u8|u|U|L)?"(?P<normal>(?:[^"\\]|\\.)*)")', re.S)
    runs = []
    current = ""
    current_start = None
    previous_end = None
    for match in literal.finditer(src):
        value = (match.group("raw") if match.group("raw") is not None
                 else bytes(match.group("normal"), "utf-8").decode("unicode_escape"))
        if previous_end is not None and src[previous_end:match.start()].strip() == "":
            current += value
        else:
            if current:
                runs.append((current_start, previous_end, current))
            current = value
            current_start = match.start()
        previous_end = match.end()
    if current:
        runs.append((current_start, previous_end, current))
    return runs


def _named_function_span(clean_src, name):
    match = re.search(r"\b" + re.escape(name) + r"\s*\([^;{}]*\)\s*\{", clean_src)
    if not match:
        return None
    start = match.end() - 1
    body = _balanced_body(clean_src, start)
    return (start, start + len(body)) if body else None


def postgres_schema_construct_sites(target_cpp, model_cpp):
    """Stable identities for every governed handwritten table declaration.

    Table names are matched inside their reviewed author function, so duplicate
    declarations remain separate identities. Zero declaration classes are
    surfaced as unclassified sites on reintroduction, independently of table
    counting, and therefore cannot silently establish a new raw grammar class.
    """
    sources = {_PG_TARGET_REL: target_cpp, _PG_MODEL_REL: model_cpp}
    registered = {(rel, function, table): node
                  for rel, function, table, node in _PG_SCHEMA_IDENTITIES}
    authors = sorted({(rel, function) for rel, function, _table, _node in _PG_SCHEMA_IDENTITIES})
    candidate = re.compile(
        r"\bCREATE\s+(?:(?:TEMP|TEMPORARY|UNLOGGED)\s+)?TABLE\b",
        re.IGNORECASE)
    canonical = re.compile(
        r"CREATE TABLE IF NOT EXISTS ([A-Za-z_][A-Za-z0-9_]*) \(")
    sites = []
    clean_sources = {rel: _strip_comments_keep_strings(src)
                     for rel, src in sources.items()}
    spans = {(rel, function): _named_function_span(clean_sources[rel], function)
             for rel, function in authors}
    for rel, clean in clean_sources.items():
        rel_spans = [(function, span) for (path, function), span in spans.items()
                     if path == rel and span is not None]
        for run_start, _run_end, run in _cpp_adjacent_string_runs(clean):
            function = next((name for name, span in rel_spans
                             if span[0] <= run_start < span[1]), "<file-scope>")
            for match in candidate.finditer(run):
                # Mentions in rendered SQL comments explain the contract but
                # do not author declarations in the rendered stream.
                line = run[run.rfind("\n", 0, match.start()) + 1:match.start()]
                if line.lstrip().startswith("--"):
                    continue
                suffix = run[match.start():]
                parsed = canonical.match(suffix)
                table = parsed.group(1) if parsed else None
                node = registered.get((rel, function, table)) if table else None
                if node is not None:
                    matcher = f"{function} emits `CREATE TABLE IF NOT EXISTS {table} (...)`"
                else:
                    node = "UnclassifiedTable"
                    preview = re.sub(r"\s+", " ", suffix[:96]).strip()
                    matcher = f"{function} emits unclassified `{preview}` candidate"
                sites.append({
                    "target": "postgres", "model": "PgSchemaDecl", "node": node,
                    "path": rel, "matcher": matcher,
                })
    for rel, clean in clean_sources.items():
        for node, marker in _PG_ZERO_DECLARATION_CLASSES:
            if marker in clean:
                sites.append({
                    "target": "postgres", "model": "PgSchemaDecl", "node": node,
                    "path": rel,
                    "matcher": f"unclassified raw schema declaration `{marker}`",
                })
    return sites


# The former callable emitter path is retained only to reconstruct the
# authoritative base-side identities that earned generated-handler retirement.
# It must never participate in current-tree discovery or an allowlist.
_PG_RETIRED_SQLEMITTER_REL = "lib/backends/postgres/leaf/SqlEmitter.cpp"
_PG_MODEL_HDR_REL = "lib/backends/postgres/model/PostgresModel.h"


def postgres_callable_construct_sites(
        sqlemitter_cpp, model_hdr, model_cpp="",
        emitter_path=_PG_RETIRED_SQLEMITTER_REL,
        model_path=_PG_MODEL_REL):
    """Governed handwritten PostgreSQL callable grammar sites ()."""
    sites = []
    emitter_nc = _strip_comments_keep_strings(sqlemitter_cpp)
    hdr_nc = _strip_comments_keep_strings(model_hdr)
    # The outer-callable header grammar, authored by SqlEmitter addFunction. The
    # header is FOUR handwritten clauses (the signature, RETURNS, LANGUAGE, and
    # the `AS $$` body-open); the CallableSig identity survives while ANY of them
    # is still authored by hand, so a partial migration that moves only the
    # signature line and leaves RETURNS/LANGUAGE/AS $$ handwritten does NOT earn
    # the retirement — the site is retired ONLY when the COMPLETE handwritten
    # header is gone ( review P1).
    _CALLABLE_HEADER_MARKERS = ('"CREATE OR REPLACE FUNCTION ', '"RETURNS void"',
                                '"LANGUAGE plpgsql"', '"AS $$"')
    m = re.search(r"\baddFunction\s*\([^;{}]*\)\s*\{", emitter_nc)
    body = _balanced_body(emitter_nc, m.end() - 1) if m else ""
    if any(mk in body for mk in _CALLABLE_HEADER_MARKERS):
        sites.append({
            "target": "postgres", "node": "CallableSig", "path": emitter_path,
            "matcher": "addFunction renders `CREATE OR REPLACE FUNCTION "
                       "<name>(<params>) / RETURNS void / LANGUAGE plpgsql / AS $$`",
        })
    # The per-PARAMETER grammar `<p_name> <type>`, authored by the handwritten
    # PgParam::render. SCOPED to the balanced `struct PgParam { … }` body so an
    # unrelated `render() const` elsewhere cannot false-green the site, nor can
    # renaming PgParam::render away leave it standing. Retires WITH CallableSig
    # (its `${params}` repeated-field projection is the one `<name> <type>`
    # authority the signature depends on).
    m_param = re.search(r"struct\s+PgParam\s*\{", hdr_nc)
    param_body = _balanced_body(hdr_nc, m_param.end() - 1) if m_param else ""
    if re.search(r"std::string\s+render\s*\(\s*\)\s*const", param_body):
        sites.append({
            "target": "postgres", "node": "PgParamRender", "path": _PG_MODEL_HDR_REL,
            "matcher": "PgParam::render authors `<p_name> <type>` "
                       "(retires with CallableSig)",
        })
    # Slice 2: one identity covers the DECLARE container and declaration-line
    # grammar. A partial migration cannot earn retirement while either remains.
    model_nc = _strip_comments_keep_strings(model_cpp)
    has_declare_header = '"DECLARE"' in body
    has_declare_line = bool(
        re.search(r'"v_"\s*\+\s*v\s*\+\s*" bigint;"', model_nc))
    if has_declare_header or has_declare_line:
        sites.append({
            "target": "postgres", "node": "DeclareSection",
            "path": emitter_path if has_declare_header else model_path,
            "matcher": "addFunction/printPostgres author `DECLARE` plus "
                       "indented `<name> <type> [:= <initializer>];` lines",
        })
    # The outer body frame is TWO callable identities, migrated in sequence:
    #  * CallableBody — the `BEGIN … END;` block frame (migrated to the generated
    #    CallableBody `block` node).
    #  * CallableClose — the trailing `$$;` dollar-quote function-close (migrated to
    #    the generated CallableClose `line` node).
    # At the  ENDPOINT both are gone from the committed emitter: addFunction
    # places OPAQUE `RenderedSection` carriers (nodes the generated-printer adapter
    # minted, wrapped by the Seam-gated author) and authors NO frame literal — so
    # neither detector fires and the callable inventory is ZERO. The seal against a
    # constant/helper raw-string bypass is STRUCTURAL (a section slot has no string
    # type; the carrier's constructor is private + Seam-gated), not lexical. These
    # detectors survive only to credit the base→current retirement: run against the
    # base sources they still fire (the base emitter authors the raw frame), so the
    # base_counts derivation books each retirement against the base it removed it
    # from.
    body_joined = re.sub(r'"\s*"', "", body)
    has_block_frame = ('"BEGIN"' in body_joined or '"END;"' in body_joined
                       or bool(re.search(
                           r"\b(?:ct|codetext)\s*::\s*block\s*\(", body)))
    if has_block_frame:
        sites.append({
            "target": "postgres", "node": "CallableBody",
            "path": emitter_path,
            "matcher": "addFunction authors the `BEGIN … END;` outer body block",
        })
    if '"$$;"' in body_joined:
        sites.append({
            "target": "postgres", "node": "CallableClose",
            "path": emitter_path,
            "matcher": "addFunction authors the `$$;` dollar-quote function-close "
                       "(handwritten; migrates in the follow-up endpoint slice)",
        })
    return sites


def postgres_schema_carrier_reasons(header_text):
    """The schema carrier cannot be stored in a procedure-body slot."""
    clean = _strip_comments_keep_strings(header_text)
    m = re.search(r"struct\s+PgFunction\s*\{", clean)
    body = _balanced_body(clean, m.end() - 1) if m else ""
    reasons = []
    if not body:
        reasons.append("PgFunction definition is missing")
    elif not re.search(r"std::vector\s*<\s*PgStmt\s*>\s+body\s*;", body):
        reasons.append("PgFunction::body is not the closed PgStmt carrier")
    if "PgSchemaDecl" in body:
        reasons.append("PgSchemaDecl can inhabit PgFunction::body")
    return reasons


# One-time  substrate baseline. The handwritten target-printer inventory grows
# 4 -> 9 the FIRST time scan_handwritten_inventory becomes CONSTRUCT-AWARE (it now
# governs printSolidity's per-construct grammar + the storageDecl/signature decl
# helpers). That growth is NOT new handwritten code — the construct emission was
# always there; it was merely invisible to the statement inventory. This narrowly
# pinned recovery permits the growth EXACTLY ONCE, only when: base==4 & current==9,
# the five ADDED sites are EXACTLY the governed construct sites (nothing removed),
# and SolidityTargetAdapter.cpp/.h are BYTE-IDENTICAL to the base (proving the growth is
# detection-only). Non-reusable: once it lands base==9, so `9 > 9` never fires and
# any later real regression (>9 or a changed model source) fails closed.
_CONSTRUCT_BASELINE_NODES = frozenset(
    {"EnumDecl", "EventDecl", "ContractShell", "StorageDecl", "FunctionSig"})


def _construct_baseline_recovery_permitted(base_ref, base_handwritten,
                                           current_handwritten, scanned):
    if not base_ref or base_handwritten != 4 or current_handwritten != 9:
        return False
    base_inv = _git_show(base_ref, _rel(INVENTORY))
    if base_inv is None:
        return False
    try:
        base_sites = {_inventory_key(s)
                      for s in json.loads(base_inv).get("handwrittenSites", [])}
    except (ValueError, TypeError):
        return False
    cur_sites = {_inventory_key(s) for s in scanned}
    if base_sites - cur_sites:  # the recovery only ADDS the construct baseline
        return False
    added = cur_sites - base_sites
    if len(added) != 5 or {key[3] for key in added} != _CONSTRUCT_BASELINE_NODES:
        return False
    # Detection-only: the model source that carries the construct grammar must be
    # unchanged vs base (no handwritten construct was added under cover of this).
    for rel in (_CPP_REL, _HDR_REL):
        if _git_show(base_ref, rel) != _read(os.path.join(REPO, rel)):
            return False
    return True


def _pg_schema_baseline_recovery_permitted(base_ref, base_handwritten,
                                           current_handwritten, scanned):
    """One-time detection-only 4 -> 15 PostgreSQL schema baseline growth."""
    if not base_ref or base_handwritten != 4 or current_handwritten != 15:
        return False
    base_inv = _git_show(base_ref, _rel(INVENTORY))
    if base_inv is None:
        return False
    try:
        base_sites = {_inventory_key(s)
                      for s in json.loads(base_inv).get("handwrittenSites", [])
                      if s.get("target") == "postgres"}
    except (ValueError, TypeError):
        return False
    cur_sites = {_inventory_key(s) for s in scanned}
    if base_sites - cur_sites:
        return False
    added = cur_sites - base_sites
    expected = {(rel, function, table, node)
                for rel, function, table, node in _PG_SCHEMA_IDENTITIES}
    actual = {(key[2], key[4].split(" emits `", 1)[0],
               key[4].split("CREATE TABLE IF NOT EXISTS ", 1)[1].split(" ", 1)[0],
               key[3])
              for key in added
              if "CREATE TABLE IF NOT EXISTS " in key[4]}
    if len(added) != 11 or actual != expected:
        return False
    for rel in (_PG_TARGET_REL, _PG_MODEL_REL):
        if _git_show(base_ref, rel) != _read(os.path.join(REPO, rel)):
            return False
    return True


def scan_handwritten_inventory(cpp_override=None):
    tracked = _git_lines("ls-files", "lib/backends")
    files = [p for p in tracked
             if p.endswith((".cpp", ".h", ".hpp", ".hh"))
             and "/test/" not in p
             and not p.endswith(".inc")]
    sol_rel = _rel(CPP)
    out = []
    sol_kind_rx = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Za-z_]\w*::)*SolStmt::Kind::(\w+)")
    sql_kind_rx = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Za-z_]\w*::)*Stmt::Kind::(\w+)")

    def function_infos(text):
        funcs = []
        header_rx = re.compile(
            r"(?<![A-Za-z0-9_])(?:[A-Za-z_]\w*[\w:<>&*~\s]*\s+)?"
            r"([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{",
            re.S,
        )
        for m in header_rx.finditer(text):
            name = m.group(1)
            if name in {"if", "for", "while", "switch", "catch"}:
                continue
            start = m.end() - 1
            depth = 0
            end = None
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end is not None:
                funcs.append((name, text[start:end], m.start(), end))
        return funcs

    def function_bodies(text):
        return [(name, body) for name, body, _, _ in function_infos(text)]

    def blank_function_bodies(text):
        chars = list(text)
        for _, _, start, end in function_infos(text):
            for i in range(start, end):
                chars[i] = " "
        return "".join(chars)

    def blank_function_spans(text, allowed_names):
        chars = list(text)
        for name, _, start, end in function_infos(text):
            if name not in allowed_names:
                continue
            for i in range(start, end):
                chars[i] = " "
        return "".join(chars)

    def codetext_aliases(src):
        aliases = {"codetext", "ct"}
        for m in re.finditer(r"namespace\s+([A-Za-z_]\w*)\s*=\s*(?:::)?(?:neutrino::)?codetext\s*;",
                             src):
            aliases.add(m.group(1))
        for m in re.finditer(r"namespace\s+([A-Za-z_]\w*)\s*=\s*(?:::)?neutrino::codetext\s*;",
                             src):
            aliases.add(m.group(1))
        return aliases

    def codetext_bare_emitters(src, aliases):
        symbols = set()
        if re.search(r"\busing\s+namespace\s+(?:::)?(?:neutrino::)?codetext\s*;", src):
            symbols.update({"line", "blank", "block", "ifThen", "flatIf", "lineGroup"})
        alias_prefixes = "|".join(re.escape(a) for a in sorted(aliases))
        if alias_prefixes:
            using_rx = re.compile(rf"\busing\s+(?:(?:::)?(?:neutrino::)?codetext|{alias_prefixes})::"
                                  r"(line|blank|block|ifThen|flatIf|lineGroup)\s*;")
            symbols.update(m.group(1) for m in using_rx.finditer(src))
        return symbols

    # `lineGroup`/`LineGroup` (): the Lines-layout substrate exposes a public
    # codetext factory + node shape that can author arbitrary target text, so a
    # direct call from a governed backend printer is a raw-emitter route around
    # the sealed authority seams and must be inventoried like line/block.
    emitter_symbols = {"line", "blank", "block", "ifThen", "flatIf", "lineGroup",
                       "Line", "Blank", "Block", "LineGroup"}

    def cpp_tokens(src):
        tokens = []
        i = 0
        while i < len(src):
            ch = src[i]
            if ch.isspace():
                i += 1
                continue
            if ch == '"' or ch == "'":
                quote = ch
                i += 1
                while i < len(src):
                    if src[i] == "\\":
                        i += 2
                        continue
                    if src[i] == quote:
                        i += 1
                        break
                    i += 1
                continue
            if ch == ":" and i + 1 < len(src) and src[i + 1] == ":":
                tokens.append("::")
                i += 2
                continue
            if ch.isalpha() or ch == "_":
                start = i
                i += 1
                while i < len(src) and (src[i].isalnum() or src[i] == "_"):
                    i += 1
                tokens.append(src[start:i])
                continue
            tokens.append(ch)
            i += 1
        return tokens

    def is_qualified_emit(tokens, i, aliases):
        if tokens[i] not in emitter_symbols:
            return False
        if i >= 2 and tokens[i - 1] == "::" and tokens[i - 2] in aliases:
            return True
        if (i >= 4 and tokens[i - 1] == "::" and tokens[i - 2] == "codetext"
                and tokens[i - 3] == "::" and tokens[i - 4] == "neutrino"):
            return True
        return False

    def has_target_emitter_reference(src, aliases, bare_emitters):
        tokens = cpp_tokens(src)
        for i, tok in enumerate(tokens):
            if tok in bare_emitters:
                return True
            if is_qualified_emit(tokens, i, aliases):
                return True
            if (i >= 4 and tokens[i - 1] == "::" and tokens[i - 2] == "Stmt"
                    and tokens[i - 3] == "::" and tokens[i - 4] == "sql"):
                return True
        return False

    def macro_definitions(src):
        defs = []
        lines = src.splitlines()
        i = 0
        while i < len(lines):
            m = re.match(r"\s*#\s*define\s+([A-Za-z_]\w*)(\(([^)]*)\))?(.*)$", lines[i])
            if not m:
                i += 1
                continue
            name = m.group(1)
            params = None if m.group(2) is None else tuple(
                p.strip() for p in m.group(3).split(",") if p.strip())
            start = i
            body = [lines[i]]
            while body[-1].rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                body.append(lines[i])
            replacement = "\n".join(body)
            replacement = re.sub(r"^\s*#\s*define\s+[A-Za-z_]\w*(?:\([^)]*\))?", "", replacement, count=1)
            replacement = replacement.replace("\\\n", "\n").strip()
            defs.append((name, params, start + 1, replacement))
            i += 1
        return defs

    def local_includes(src, rel):
        base = os.path.dirname(rel)
        includes = []
        for m in re.finditer(r'^\s*#\s*include\s+"([^"]+)"', src, re.M):
            inc = m.group(1)
            if not inc.endswith((".h", ".hh", ".hpp")):
                continue
            candidates = []
            if inc.startswith("Neutrino/"):
                candidates.append(os.path.join("include", inc))
            candidates.append(os.path.normpath(os.path.join(base, inc)))
            for cand in candidates:
                path = os.path.join(REPO, cand)
                if os.path.exists(path):
                    includes.append(cand)
                    break
        return includes

    def local_include_graph(rel, src):
        seen = set()
        stack = local_includes(src, rel)
        out_files = []
        while stack:
            inc = stack.pop()
            if inc in seen:
                continue
            seen.add(inc)
            try:
                inc_src = _read(os.path.join(REPO, inc))
            except OSError:
                continue
            out_files.append((inc, inc_src))
            stack.extend(local_includes(inc_src, inc))
        return out_files

    def include_guard_names(src):
        m = re.search(r"^\s*#\s*ifndef\s+([A-Za-z_]\w*)\s*\n\s*#\s*define\s+\1(?:\s*)$",
                      src, re.M)
        return {m.group(1)} if m else set()

    def allowed_include_guard(scan_src, name, params, replacement):
        return name in include_guard_names(scan_src) and params is None and replacement == ""

    def allowed_sol_node_macro(scan_rel, name, params, replacement):
        # A backend model header's generated target-node X-macro expansion: the
        # `.td` registry drives the Kind enum (and, for Solidity, the node-metadata
        # table). Governed per backend so a NEW ungoverned macro still fails.
        if params != ("Sym", "Ordinal", "Handler", "IsLeaf", "Feature"):
            return False
        normalized = re.sub(r"\s+", " ", replacement)
        if scan_rel == "lib/backends/solidity/provider/SolidityTargetAdapter.h" and name == "NEU_SOL_NODE":
            return normalized in {
                "Sym = Ordinal,",
                "{SolStmt::Kind::Sym, #Sym, Handler, IsLeaf, Feature},",
            }
        if (scan_rel == "lib/backends/postgres/model/PostgresModel.h"
                and name in {"NEU_PG_PGSTMT_NODE", "NEU_PG_PGSCHEMADECL_NODE"}):
            # Each PostgreSQL carrier expands only its own model-qualified enum.
            return normalized in {"Sym = Ordinal,"}
        return False

    def allowed_tablegen_macro(scan_rel, name, params, replacement):
        expected = {
            "include/Neutrino/NeutrinoDialect.h": {
                "GET_TYPEDEF_CLASSES",
                "GET_ATTRDEF_CLASSES",
                "GET_OP_CLASSES",
            },
            "include/Neutrino/L2Dialect.h": {"GET_OP_CLASSES"},
        }
        return name in expected.get(scan_rel, set()) and params is None and replacement == ""

    def allowed_callable_enum_macro(scan_rel, name, params, replacement):
        # The generated closed-enum X-macro expansions (): the `.td` drives the
        # C++ `enum class` (Sym = Ordinal,), the coverage POSITION probe (Sym,), and
        # the per-member coverage static_assert. Governed per macro-name shape so a
        # NEW ungoverned macro still fails; the member LIST lives in the generated
        # SolidityTargetEnums.inc (freshness-gated), not here.
        if params != ("Sym", "Ordinal", "Spelling"):
            return False
        if not re.fullmatch(r"NEU_SOL_ENUM_[A-Za-z_]\w*", name):
            return False
        if scan_rel not in (
            "lib/backends/solidity/provider/SolidityTargetAdapter.h",
            "lib/backends/solidity/provider/SolidityCallableCoverage.inc",
        ):
            return False
        normalized = re.sub(r"\s+", " ", replacement).strip()
        if normalized in {"Sym = Ordinal,", "Sym,"}:
            return True
        # The per-member position-drift coverage assertion.
        return normalized.startswith("static_assert(") and \
            "declaration position" in normalized

    def allowed_status_atom_macro(scan_rel, name, params, replacement):
        # The generated status-authority idiom accessor X-macro ( G1-S1): the
        # `.td` `LifecycleAtom` rows drive the (mode, role) -> atom table in
        # *TargetEnums.inc, and the model header expands it into the SOLE
        # `<backend>StatusAtom(mode, role)` reader. Governed per macro-name shape +
        # exact expansion so a NEW ungoverned macro still fails; the ROWS live in
        # the freshness-gated .inc (not here), and the accessor spells no atom
        # inline — it only forwards the projected (mode, role) to the table atom.
        if params != ("ModeSym", "RoleSym", "Atom"):
            return False
        expected_name = {
            "lib/backends/solidity/provider/SolidityTargetAdapter.h": "NEU_SOL_STATUS_ATOM",
            "lib/backends/postgres/model/PostgresModel.h": "NEU_PG_STATUS_ATOM",
        }.get(scan_rel)
        if expected_name != name:
            return False
        normalized = re.sub(r"\s+", " ", replacement).strip()
        return normalized in {
            (
                "if (mode == ExecutionMode::ModeSym && role == "
                "LifecycleRole::RoleSym) return Atom;"
            ),
            "{ExecutionMode::ModeSym, LifecycleRole::RoleSym, Atom},",
        }

    def allowed_governed_macro(scan_rel, scan_src, name, params, replacement):
        return (
            allowed_include_guard(scan_src, name, params, replacement)
            or allowed_sol_node_macro(scan_rel, name, params, replacement)
            or allowed_callable_enum_macro(scan_rel, name, params, replacement)
            or allowed_status_atom_macro(scan_rel, name, params, replacement)
            or allowed_tablegen_macro(scan_rel, name, params, replacement)
        )

    def add_forbidden_macros(src, rel, target):
        if rel not in reviewed_direct_emitters:
            return
        for scan_rel, scan_src in [(rel, src)] + local_include_graph(rel, src):
            for name, params, line_no, replacement in macro_definitions(strip_cpp_comments(scan_src)):
                if allowed_governed_macro(scan_rel, scan_src, name, params, replacement):
                    continue
                out.append({
                    "target": target,
                    "node": "MacroEmitterBoundary",
                    "path": scan_rel,
                    "matcher": f"governed macro {name} at line {line_no}",
                })

    def forbidden_callable_aliases(src):
        aliases = []
        for m in re.finditer(
            r"\b(?:const\s+)?auto(?:\s*[*&]{1,2})?\s+([A-Za-z_]\w*)\s*"
            r"(?:=\s*&?\s*((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)"
            r"|\{\s*&?\s*((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*\})\s*;",
            src,
            re.S,
        ):
            aliases.append((m.group(1), m.group(2) or m.group(3)))
        for m in re.finditer(
            r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)\s*\([^;=]*\)\s*=\s*&?\s*"
            r"((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*;",
            src,
            re.S,
        ):
            aliases.append((m.group(1), m.group(2)))
        return aliases

    def add_forbidden_aliases(src, rel, target):
        stripped = strip_cpp_comments(src)
        for name, _ in forbidden_callable_aliases(stripped):
            out.append({
                "target": target,
                "node": "CallableAlias",
                "path": rel,
                "matcher": f"callable alias {name}",
            })

    reviewed_direct_emitters = {
        "lib/backends/solidity/provider/SolidityTargetAdapter.cpp": {
            "toNode",
            "renderSolidityProjection",
        },
        "lib/backends/postgres/model/PostgresModel.cpp": {"addStmt"},
    }

    def add_body_emitters(src, rel, target, kind_rx, case_rx, matcher_prefix):
        add_forbidden_macros(src, rel, target)
        stripped = case_rx.sub("", strip_cpp_comments(src))
        aliases = codetext_aliases(stripped)
        file_scope = blank_function_bodies(stripped)
        file_bare_emitters = codetext_bare_emitters(file_scope, aliases)

        def callable_is_emitter(name, bare_emitters):
            if name in bare_emitters:
                return True
            return has_target_emitter_reference(name, aliases, bare_emitters)

        if rel in reviewed_direct_emitters:
            governed_scope = blank_function_spans(stripped, reviewed_direct_emitters[rel])
            governed_bare_emitters = codetext_bare_emitters(governed_scope, aliases)
            if has_target_emitter_reference(governed_scope, aliases, governed_bare_emitters):
                out.append({
                    "target": target,
                    "node": "DirectEmitter",
                    "path": rel,
                    "matcher": "target emitter outside reviewed printer spans",
                })

        funcs = {}
        for idx, (name, body) in enumerate(function_bodies(stripped)):
            key = f"{name}#{idx}"
            kind_nodes = set(m.group(1) for m in kind_rx.finditer(body))
            body_bare_emitters = codetext_bare_emitters(body, aliases)
            bare_emitters = file_bare_emitters | body_bare_emitters
            raw_calls = set(m.group(1) for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", body))
            calls = set(raw_calls)
            emits = (
                has_target_emitter_reference(body, aliases, bare_emitters)
                or any(callable_is_emitter(c, bare_emitters) for c in calls)
            )
            funcs[key] = {"name": name, "kind_nodes": kind_nodes, "emits": emits, "calls": calls}

        changed = True
        while changed:
            changed = False
            for f in funcs.values():
                for g in funcs.values():
                    if g["name"] not in f["calls"]:
                        continue
                    before_nodes = set(f["kind_nodes"])
                    before_emits = f["emits"]
                    f["kind_nodes"].update(g["kind_nodes"])
                    f["emits"] = f["emits"] or g["emits"]
                    if f["kind_nodes"] != before_nodes or f["emits"] != before_emits:
                        changed = True

        for f in funcs.values():
            if not (f["kind_nodes"] and f["emits"]):
                continue
            for node in sorted(f["kind_nodes"]):
                out.append({
                    "target": target,
                    "node": node,
                    "path": rel,
                    "matcher": f"body {matcher_prefix}{node}",
                })

    for rel in files:
        if cpp_override and rel == sol_rel:
            src = _read(cpp_override)
        else:
            try:
                src = _read(os.path.join(REPO, rel))
            except OSError:
                continue
        if rel.startswith("lib/backends/solidity/"):
            add_forbidden_aliases(src, rel, "solidity")
            case_rx = re.compile(r"case\s+(?<![A-Za-z0-9_])(?:[A-Za-z_]\w*::)*SolStmt::Kind::(\w+):")
            for m in case_rx.finditer(src):
                node = m.group(1)
                out.append({
                    "target": "solidity",
                    "node": node,
                    "path": rel,
                    "matcher": f"case SolStmt::Kind::{node}:",
                })
            add_body_emitters(src, rel, "solidity", sol_kind_rx, case_rx, "SolStmt::Kind::")
        if rel.startswith("lib/backends/postgres/"):
            add_forbidden_aliases(src, rel, "postgres")
            case_rx = re.compile(r"case\s+(?<![A-Za-z0-9_])(?:[A-Za-z_]\w*::)*Stmt::Kind::(\w+):")
            for m in case_rx.finditer(src):
                node = m.group(1)
                out.append({
                    "target": "postgres",
                    "node": node,
                    "path": rel,
                    "matcher": f"case Stmt::Kind::{node}:",
                })
            add_body_emitters(src, rel, "postgres", sql_kind_rx, case_rx, "Stmt::Kind::")
    # The Solidity construct-emission sites (): printSolidity is a reviewed span,
    # so its per-construct grammar is governed here rather than by the emitter scan.
    try:
        cpp_src = _read(cpp_override) if cpp_override else _read(CPP)
        hdr_src = _read(HDR)
        out.extend(solidity_construct_sites(cpp_src, hdr_src))
    except OSError:
        pass
    try:
        out.extend(postgres_schema_construct_sites(
            _read(os.path.join(REPO, _PG_TARGET_REL)),
            _read(os.path.join(REPO, _PG_MODEL_REL))))
    except OSError:
        pass
    # Current-tree callable discovery reads only live model sources. The retired
    # emitter is consulted separately by base_counts for historical retirement
    # reconstruction and can never be current authority.
    try:
        out.extend(postgres_callable_construct_sites(
            "",
            _read(os.path.join(REPO, _PG_MODEL_HDR_REL)),
            _read(os.path.join(REPO, _PG_MODEL_REL)),
            emitter_path="",
            model_path=_PG_MODEL_REL))
    except OSError:
        pass
    out.sort(key=_inventory_key)
    return out


def generated_count_from_text(text):
    return len(generated_handlers(text))


# Set by --simulate-no-base to exercise the shallow-checkout path (no LOCAL base and
# fetch suppressed) in the selftest, so a local pass cannot disagree with required
# CI and the fail-closed behavior is proven.
# The event's AUTHORITATIVE PR base, resolved once. Set from --base-ref (local /
# stacked PRs), else PR_BASE_SHA / GITHUB_BASE_SHA (CI passes the event base).
_SIMULATE_NO_BASE = False
_BASE_REF_OVERRIDE = None


def _resolve_base_ref():
    """The AUTHORITATIVE PR base commit, or None (the caller then FAILS CLOSED).

    Resolution order (), highest precedence first: (1) --simulate-no-base
    forces None to exercise the fail-closed path; (2) the CI event's base SHA is
    AUTHORITATIVE — PR_BASE_SHA / GITHUB_BASE_SHA win outright over any local
    --base-ref, so a mis-declared --base-ref cannot override the real event base;
    (3) an explicit --base-ref, the local / stacked-PR declaration consulted only
    when no event base is present (a normal checked-out head, and especially a
    STACKED PR, must name its real base); (4) the base BRANCH GITHUB_BASE_REF,
    fetched and reduced to `merge-base(HEAD, base)`. NEVER `HEAD^1` and never a
    hard-coded `origin/main` substitute — both are wrong for merge commits, plain
    checked-out heads, and stacked PRs. If the resolved object is absent (shallow
    clone), it is fetched once; if it still cannot be resolved, return None."""
    if _SIMULATE_NO_BASE:
        return None
    # CI's event base wins (PR_BASE_SHA / GITHUB_BASE_SHA); an explicit --base-ref
    # is the local / stacked-PR declaration used when the event base is absent.
    candidate = (os.environ.get("PR_BASE_SHA")
                 or os.environ.get("GITHUB_BASE_SHA")
                 or _BASE_REF_OVERRIDE)
    if not candidate:
        branch = os.environ.get("GITHUB_BASE_REF")
        if branch:
            subprocess.run(["git", "-C", REPO, "fetch", "--quiet", "--depth=200",
                            "origin", branch], capture_output=True)
            mb = (_git_lines("merge-base", "HEAD", f"origin/{branch}")
                  or _git_lines("merge-base", "HEAD", "FETCH_HEAD"))
            candidate = mb[0] if mb else None
    if not candidate:
        return None
    if not _git_ok("cat-file", "-e", f"{candidate}^{{commit}}"):
        subprocess.run(["git", "-C", REPO, "fetch", "--quiet", "--depth=1",
                        "origin", candidate], capture_output=True)
        if not _git_ok("cat-file", "-e", f"{candidate}^{{commit}}"):
            return None
    return candidate


def base_counts(backend, base_ref):
    """PER-TARGET ( P1.1)
    (base_handwritten, base_generated, base_generated_nodes, base_handwritten_nodes)
    from the resolved authoritative PR base, for THIS backend's target only, or
    (None, None, None, None) when the base inventory cannot be read. Callers MUST
    treat None as FAIL CLOSED — never as a zero baseline. Each count is filtered to
    the backend's target (its own handwritten sites, its own committed printer, its
    own generated-handler nodes) so PG's generated count is never compared against
    Solidity's base. `base_handwritten_nodes` is the identity set of the target's
    handwritten sites, so a genuine RETIREMENT (a base site now gone) is credited
    even when an unrelated pre-existing site is surfaced in the same slice (the
    count-only view would mask the retirement)."""
    if base_ref is None:
        return None, None, None, None
    target = backend["target"]
    raw = _git_show(base_ref, "scripts/gates/target_printer_inventory.json")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, None, None, None
    hw_sites = [s for s in data.get("handwrittenSites", [])
                if s.get("target") == target]
    #  slices 2/3 each govern a pre-existing callable-framing construct that
    # the base tree emitted handwritten but did not yet track. Derive those base
    # identities from the authoritative base sources with the SAME construct
    # scanner used for the current tree, so a retirement is credited against the
    # base the slice actually removes it from — AND a base identity that stays
    # handwritten (CallableClose this slice) is present on BOTH sides so it is not
    # miscounted as a newly-added handwritten site. DeclareSection/CallableBody are
    # retired by their slices; CallableClose persists handwritten until the
    # follow-up endpoint slice.
    if target == "postgres":
        existing = {_inventory_key(s) for s in hw_sites}
        for site in postgres_callable_construct_sites(
                _git_show(base_ref, _PG_RETIRED_SQLEMITTER_REL) or "",
                _git_show(base_ref, _PG_MODEL_HDR_REL) or "",
                _git_show(base_ref, _PG_MODEL_REL) or "",
                emitter_path=_PG_RETIRED_SQLEMITTER_REL,
                model_path=_PG_MODEL_REL):
            if (site.get("node") in ("DeclareSection", "CallableBody",
                                     "CallableClose")
                    and _inventory_key(site) not in existing):
                hw_sites.append(site)
    handwritten = len(hw_sites)
    hw_nodes = frozenset(_qualified(_item_model(s), s.get("node"))
                         for s in hw_sites if s.get("node"))
    printer = _git_show(base_ref, _rel(backend["printer"]))
    generated = generated_count_from_text(printer) if printer else 0
    # Base generated IDENTITIES come from the base PRINTER (the generated `.inc`
    # handler rows), NOT the base inventory JSON: the printer is machine-generated
    # from the `.td`, so a hand-edited inventory cannot relabel a base identity to
    # forge a retirement credit against it ( P1.2).
    gen_nodes = frozenset(_qualified(model, node)
                          for (model, _ord, tgt, node) in generated_handlers(printer)
                          if tgt == target) if printer else frozenset()
    return handwritten, generated, gen_nodes, hw_nodes


def _syntax_authority_facts(text):
    """(executable_count, frozenset(governed comment digests)) of a
    syntax-authority inventory JSON blob, or (None, None) if unparseable."""
    try:
        d = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, None
    digests = frozenset(
        c.get("digest") for c in (d.get("comments") or [])
        if isinstance(c, dict) and c.get("digest"))
    return d.get("baseline"), digests


def _dispatch_retirement_credited(base_hw_nodes, cur_hw_nodes,
                                  base_gen_nodes, cur_gen_nodes):
    """A generated handler is credited by a DISPATCH retirement iff the node it
    ADDED to the generated set is the SAME node RETIRED from the handwritten set —
    the shape genuinely MOVED handwritten -> generated. IDENTITY-based, not a
    `current < base` count decrease: so surfacing an unrelated PRE-EXISTING
    handwritten site in the same slice (e.g.  ParamRender) neither MASKS the
    real migration (the count nets to zero yet {retired ∩ added} still holds) nor,
    via a SUBSTITUTION (retire A, add unrelated B), FALSELY credits (A ∉ added).
    Fails closed on an unreadable base (None)."""
    if base_hw_nodes is None or base_gen_nodes is None:
        return False
    retired = base_hw_nodes - cur_hw_nodes
    added = cur_gen_nodes - base_gen_nodes
    return bool(retired & added)


def _generated_row_is_fixed(printer_text, target, qualified):
    """True iff the generated handler row for `qualified` (Model::Node) declares
    a ZERO-operand fixed shape — no projected fields. A table-level discriminator
    would carry a projected field, so a variant that is not field-free is not a
    fixed variant. Fails closed if the row is absent."""
    node = qualified.split("::", 1)[-1]
    row = re.search(
        r'\{\s*\d+,\s*"' + re.escape(target) + r'",\s*"' + re.escape(node) + r'",'
        r'[^\n]*?,\s*(?:nullptr|k[A-Za-z_]\w*),\s*(\d+),',
        printer_text)
    return bool(row) and row.group(1) == "0"


def _two_variant_retirement_permitted(target, inv, added_generated,
                                      base_hw_nodes, cur_hw_nodes, printer_text):
    """ narrowly-governed exception: a slice may add EXACTLY TWO fixed
    generated variants ONLY when both are the declared variants of ONE handwritten
    authority retired in the SAME diff. Fails closed on anything wider:
      * an unrelated second handler (the added pair != a declared variant set);
      * a fake/missing retirement mapping (the declared authority was not actually
        removed from the handwritten inventory this diff);
      * a third variant (a group must declare EXACTLY two distinct variants);
      * an unreachable variant (declared but not present in the generated printer,
        since `added` is derived from printer reality);
      * a table-level discriminator (a variant that carries a projected field,
        i.e. is not a field-free fixed shape);
      * more than one same-model authority retiring this diff (the exception is
        for EXACTLY one authority -> two variants, so the retirement set within
        the variants' model must equal exactly {retires}, not merely contain it —
        it must never mask a second, uncredited retirement).
    Approved by the architect for  PostingsTable (base + memo)."""
    if base_hw_nodes is None:
        return False
    added = frozenset(added_generated)
    if len(added) != 2:
        return False
    retired_hw = frozenset(base_hw_nodes) - frozenset(cur_hw_nodes)
    # The groups (for this target) that declare EXACTLY this added pair as two
    # distinct variants. Zero = no mapping; more than one = ambiguous (two groups
    # claim the same pair, possibly through different retirement IDs) — reject.
    candidates = [g for g in inv.get("variantGroups", [])
                  if g.get("target") == target
                  and isinstance(g.get("variants"), list)
                  and len(g["variants"]) == 2 and len(set(g["variants"])) == 2
                  and frozenset(g["variants"]) == added]
    if len(candidates) != 1:
        return False
    g = candidates[0]
    retires = g.get("retires")
    if not isinstance(retires, str) or "::" not in retires:
        return False
    # EXACTLY one authority retires within the variants' model scope — credit one
    # retirement, never mask a second uncredited one.
    model = retires.split("::", 1)[0]
    retired_in_model = frozenset(
        r for r in retired_hw if r.split("::", 1)[0] == model)
    if retired_in_model != frozenset({retires}):
        return False
    # Both variants must be field-free fixed shapes (no table-level discriminator).
    return all(_generated_row_is_fixed(printer_text, target, v)
               for v in g["variants"])


def _comment_retirement(dig_cur, dig_base):
    """IDENTITY-BASED comment retirement ( policy): True iff a governed comment
    IDENTITY present at the base is gone now (`dig_base - dig_cur` non-empty) AND no
    new comment identity was introduced (`dig_cur <= dig_base`, a strict identity
    shrink). Keying on the retired digests — not len(comments) — means a
    SUBSTITUTION (retire one reviewed comment, add another) does NOT credit, so an
    unrelated comment edit cannot mechanically authorize a new generated handler."""
    if dig_cur is None or dig_base is None:
        return False
    return bool(dig_base - dig_cur) and dig_cur <= dig_base


def _node_features(backend):
    """{node symbol: requiredFeature} across every model in one backend registry.

    Multi-model registries use one model-qualified X-macro per carrier, so
    parsing only the primary macro would make generated secondary-model nodes
    invisible to comment-retirement classification.
    """
    text = _read(backend["inc"])
    features = {}
    for macro in backend.get("macros", {}).values():
        features.update({m.group(1): m.group(2) for m in re.finditer(
            re.escape(macro) +
            r'\((\w+),\s*\d+,\s*"[^"]*",\s*(?:true|false),\s*"([^"]+)"\)',
            text)})
    return features


def _generated_nodes(inventory_text):
    """frozenset of generatedHandlers node symbols from a target_printer inventory
    JSON blob, or None if unparseable."""
    try:
        d = json.loads(inventory_text)
    except (json.JSONDecodeError, TypeError):
        return None
    return frozenset(h.get("node") for h in d.get("generatedHandlers", [])
                     if isinstance(h, dict) and h.get("node"))


def _comment_retirement_credit(added_nodes, node_features, dig_cur, dig_base):
    """The comment-retirement credit binds BOTH sides ( review): it applies ONLY
    when (a) a governed comment identity was retired (_comment_retirement) AND (b)
    EVERY newly-ADDED generated handler is a comment-class node (registry feature
    'comment'). So retiring a comment can credit only the comment-derived handler
    that migrated it — never an unrelated (non-comment) handler added in the same
    slice."""
    if not added_nodes:
        return False
    if not all(node_features.get(n) == "comment" for n in added_nodes):
        return False
    return _comment_retirement(dig_cur, dig_base)


def _syntax_authority_baselines(backend, base_ref):
    """PER-TARGET ( P1.1) (exec_cur, exec_base, comment_digests_cur,
    comment_digests_base) of the backend's OWN / syntax-authority inventory,
    read from the resolved AUTHORITATIVE PR base. Used to recognize a NEW generated
    handler that retired a raw-seam shape (executable count drop — e.g. the two
    `v_progress` pgLine sites) OR a governed COMMENT shape (keyed to retired
    IDENTITIES). Solidity reads solidity_syntax_authority_inventory.json; PostgreSQL
    reads postgres_syntax_authority_inventory.json — never cross-target."""
    rel = _SYNTAX_AUTHORITY_REL.get(backend["target"])
    if not rel or not os.path.isfile(os.path.join(REPO, rel)):
        return None, None, None, None
    exec_cur, dig_cur = _syntax_authority_facts(_read(os.path.join(REPO, rel)))
    exec_base = dig_base = None
    if base_ref is not None:
        raw = _git_show(base_ref, rel)
        if raw is not None:
            exec_base, dig_base = _syntax_authority_facts(raw)
    return exec_cur, exec_base, dig_cur, dig_base


def check_inventory(backend, printer_text, cpp_override, reasons):
    target = backend["target"]
    try:
        inv = load_inventory(INVENTORY)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        fail(reasons, f"target-printer inventory is missing or malformed: {e}")
        return
    scanned = scan_handwritten_inventory(cpp_override)
    # : SEALED body-statement carriers registered in `/sealedBodyCarriers` are
    # MACHINERY, not handwritten authority — an emitter case that hands a
    # pre-rendered node straight through and authors nothing else. The exemption is
    # validated STRUCTURALLY (`sealed_carrier_reasons`): the case body must be the
    # SOLE permitted opaque pass-through, so any extra statement/call/literal denies
    # it and re-counts the site as handwritten. Only earned exemptions are filtered.
    # The allowlist is empty until a separately-reviewed migration registers a
    # concrete carrier.
    sealed_reasons, sealed_ok = sealed_carrier_reasons(
        inv, scanned, lambda p: _read(os.path.join(REPO, p)))
    for r in sealed_reasons:
        fail(reasons, r)
    scanned = [s for s in scanned if _inventory_key(s) not in sealed_ok]
    # Repo-wide reconciliation of the handwritten-site inventory (target-agnostic:
    # every scanned site must be governed, no stale/dup entries). Cheap to run once
    # per backend and keeps the whole inventory honest.
    expected = sorted(inv["handwrittenSites"], key=_inventory_key)
    scanned_counter = collections.Counter(_inventory_key(i) for i in scanned)
    expected_counter = collections.Counter(_inventory_key(i) for i in expected)
    extra = sorted(scanned_counter.keys() - expected_counter.keys())
    missing = sorted(expected_counter.keys() - scanned_counter.keys())
    duplicated = sorted(k for k, count in scanned_counter.items()
                        if count > expected_counter.get(k, 0) and k in expected_counter)
    if extra:
        fail(reasons, "repo-wide target-printer inventory has ungoverned handwritten site(s): "
                      + ", ".join(f"{t}:{m}:{p}:{n}" for t, m, p, n, _ in extra))
    if missing:
        fail(reasons, "target-printer inventory lists stale handwritten site(s): "
                      + ", ".join(f"{t}:{m}:{p}:{n}" for t, m, p, n, _ in missing))
    if duplicated:
        fail(reasons, "repo-wide target-printer inventory has duplicate handwritten site(s): "
                      + ", ".join(f"{t}:{m}:{p}:{n}" for t, m, p, n, _ in duplicated))

    # PER-TARGET ratchet ( P1.1): each backend reconciles the registry against
    # ITS OWN generated printer, ITS OWN inventory entries (filtered by target), and
    # ITS OWN syntax-authority inventory — never PG's generated count against
    # Solidity's base. `scanned_target` is this backend's handwritten sites only.
    scanned_target = [s for s in scanned if s["target"] == target]
    current_handwritten = len(scanned_target)
    current_generated = generated_count_from_text(printer_text)
    base_ref = _resolve_base_ref()
    base_handwritten, base_generated, base_gen_nodes, base_hw_nodes = \
        base_counts(backend, base_ref)
    cur_hw_nodes = frozenset(_qualified(_item_model(s), s["node"])
                             for s in scanned_target if s.get("node"))
    # The handwritten-regression and one-slice generated-handler ratchets are
    # PR-RELATIVE (this change vs the PR base). The base is the event's
    # AUTHORITATIVE base (--base-ref / PR_BASE_SHA / GITHUB_BASE_SHA), never HEAD^1
    # or a silent origin/main substitute; an unresolvable base FAILS CLOSED.
    if base_handwritten is None:
        fail(reasons, f"no authoritative PR base resolvable for {target} (pass --base-ref, or "
                      "set PR_BASE_SHA / GITHUB_BASE_SHA in CI) — the anti-decoration handler "
                      "ratchet cannot be verified against the base, so it fails closed.")
    else:
        recovery = (
            target == "solidity" and _construct_baseline_recovery_permitted(
                base_ref, base_handwritten, current_handwritten,
                [s for s in scanned if s["target"] == "solidity"])
        ) or (
            target == "postgres" and _pg_schema_baseline_recovery_permitted(
                base_ref, base_handwritten, current_handwritten,
                [s for s in scanned if s["target"] == "postgres"])
        )
        if current_handwritten > base_handwritten and not recovery:
            fail(reasons, f"handwritten target-printer inventory for {target} regressed "
                          f"({current_handwritten} > base {base_handwritten})")
        if current_generated > base_generated:
            # A NEW generated handler must correspond to a RETIRED grammar shape, not
            # decoration. A migration slice retires exactly one shape (per target), so
            # it may add at most ONE generated handler, and that addition must be
            # matched by a retirement of THIS target — EITHER a handwritten dispatch
            # case (the target's handwritten inventory shrinks) OR a raw-seam shape
            # (the target's OWN syntax-authority baseline shrinks; for PG that is the
            # two `v_progress` pgLine sites, 20 -> 18).
            delta = current_generated - base_generated
            # Current generated IDENTITIES come from the current PRINTER (the
            # generated `.inc` rows), NOT the inventory JSON — same reason as the
            # base: the credit must key on generated REALITY, so relabeling an
            # inventory row cannot forge a `retired ∩ added` credit ( P1.2).
            cur_gen_nodes_now = frozenset(
                _qualified(model, node)
                for (model, _ord, tgt, node) in generated_handlers(printer_text)
                if tgt == target)
            added_generated = (cur_gen_nodes_now - base_gen_nodes
                               if base_gen_nodes is not None else frozenset())
            #  narrowly-governed exception: exactly two fixed variants of ONE
            # retired authority (declared in variantGroups) count as one grammar
            # shape. Everything wider still fails closed (see the helper).
            two_variant = (delta == 2 and _two_variant_retirement_permitted(
                target, inv, added_generated, base_hw_nodes, cur_hw_nodes,
                printer_text))
            if delta > 1 and not two_variant:
                fail(reasons, f"a {target} migration slice may add at most ONE generated handler (one grammar "
                              f"shape per slice); generated grew by {delta} ({current_generated} > {base_generated}). "
                              "Split additional shapes — or any decorative node piggybacking on a real migration — "
                              "into their own reviewed slices. (Exactly two fixed variants of a single retired "
                              "authority, declared in /variantGroups, are the only permitted pair.)")
            sa_exec_cur, sa_exec_base, sa_dig_cur, sa_dig_base = \
                _syntax_authority_baselines(backend, base_ref)
            retired_dispatch = _dispatch_retirement_credited(
                base_hw_nodes, cur_hw_nodes, base_gen_nodes, cur_gen_nodes_now)
            retired_exec = (sa_exec_cur is not None and sa_exec_base is not None
                            and sa_exec_cur < sa_exec_base)
            # IDENTITY-BASED comment retirement ( policy) BOUND to the added
            # handler and to THIS target: credit applies only when a governed comment
            # identity was retired AND the newly-ADDED generated handler(s) are
            # comment-class (registry feature 'comment').
            cur_gen_nodes = frozenset(
                _qualified(_item_model(h), h.get("node"))
                for h in inv.get("generatedHandlers", [])
                if h.get("target") == target and h.get("node"))
            added_nodes = (cur_gen_nodes - base_gen_nodes
                           if base_gen_nodes is not None else None)
            retired_comment = _comment_retirement_credit(
                added_nodes, _node_features(backend), sa_dig_cur, sa_dig_base)
            if not (retired_dispatch or retired_exec or retired_comment):
                fail(reasons, f"the new generated {target} handler retired nothing (handwritten "
                              f"{current_handwritten} >= {base_handwritten}; the {target} syntax-authority "
                              "executable baseline did not decrease; and no governed comment identity was "
                              "retired) — a generated handler must retire a grammar/comment shape, not add "
                              "decoration")

    inv_gen_target = [h for h in inv.get("generatedHandlers", []) if h.get("target") == target]
    if current_generated != len(inv_gen_target):
        fail(reasons, f"generated handler inventory count for {target} {len(inv_gen_target)} does not "
                      f"match committed generated printer count {current_generated}")
    # IDENTITY reconciliation ( P1.2), not just count: the inventory's generated
    # node identities MUST equal the generated printer's actual handler-row
    # identities. A count-only check let a substitution keep the count while
    # relabeling an unrelated row as the retired node to forge a retirement credit;
    # this fails closed on any identity mismatch.
    inv_gen_nodes = frozenset(_qualified(_item_model(h), h.get("node"))
                              for h in inv_gen_target if h.get("node"))
    printer_gen_nodes = frozenset(
        _qualified(model, node)
        for (model, _ord, tgt, node) in generated_handlers(printer_text) if tgt == target)
    if inv_gen_nodes != printer_gen_nodes:
        fail(reasons, f"generated handler inventory identities for {target} "
                      f"{sorted(inv_gen_nodes)} do not match the generated printer's "
                      f"handler-row identities {sorted(printer_gen_nodes)} — a "
                      "count-preserving identity substitution is rejected")
    if "Neutrino/TargetPrinter.h" not in _read(os.path.join(REPO, "lib", "codetext", "TargetPrinter.cpp")):
        fail(reasons, "generic target-printer driver helper missing from the ratchet exclusion proof")

    # GENERIC-FRAMING CLOSURE: a "bare pass-through" generated handler (empty, a
    # verbatim `${text}` line, or a `${text}`…`${close}` block) carries NO literal
    # target syntax in its `.td` template — it emits whatever text legalization
    # hands it, so it does NOT retire target syntax and must not be credited as a
    # migrated typed-syntax node. Such handlers are only sound as *reviewed generic
    # framing*, so the set of bare handlers must exactly equal the reviewed
    # `genericFramingHandlers` allowlist. This makes the escape-hatch set CLOSED: a
    # future `.td` node that sneaks in as a bare `${…}` pass-through (laundering
    # handwritten syntax past the ratchet) fails the gate unless it is explicitly
    # reviewed and allowlisted here.
    templates = generated_templates(printer_text)
    bare = {node for node, (syn, cls, _operand_count) in templates.items()
            if is_bare_passthrough(syn, cls)}
    framing = {h["node"] for h in inv.get("genericFramingHandlers", [])
               if h.get("target") == target}
    payload_blanks = sorted(
        node for node in framing
        if node == "Blank" and templates.get(node, ("", "", 0))[2] != 0)
    if payload_blanks:
        fail(reasons, "generic-framing Blank must be fieldless (zero operands); "
                      "a payload-bearing Blank cannot inherit framing classification: "
                      f"{payload_blanks}")
    unlisted = sorted(bare - framing)
    stale_framing = sorted(framing - bare)
    if unlisted:
        fail(reasons, "generated bare-pass-through handler(s) not on the reviewed generic-framing allowlist "
                      f"(they launder handwritten target syntax and cannot be credited as migrations): {unlisted}")
    if stale_framing:
        fail(reasons, "genericFramingHandlers allowlist lists handler(s) whose template is no longer a bare "
                      f"pass-through (they now carry literal target syntax — recredit as a typed node): {stale_framing}")


def check(backend, inc, printer, cpp, hdr, reasons):
    macro = backend["macro"]
    model = backend["model"]
    target = backend["target"]
    inc_text = open(inc, encoding="utf-8").read()
    printer_text = open(printer, encoding="utf-8").read()
    cpp_text = open(cpp, encoding="utf-8").read()
    hdr_text = open(hdr, encoding="utf-8").read()

    if target == "postgres":
        reasons.extend(postgres_schema_carrier_reasons(hdr_text))

    all_generated = generated_handlers(printer_text)
    for declared_model in backend.get("models", [model]):
        declared_macro = backend.get("macros", {}).get(declared_model)
        if not declared_macro:
            fail(reasons, f"declared model {declared_model} has no model-qualified registry macro")
            continue
        if backend["inc_basename"] not in hdr_text or declared_macro not in hdr_text:
            fail(reasons, f"{os.path.relpath(hdr, REPO)} does not expand the generated registry for "
                          f"model {declared_model} via {declared_macro}")
        if declared_model == model:
            continue
        other_recs = inc_records(inc_text, declared_macro)
        other_generated = [row for row in all_generated if row[0] == declared_model]
        other_syms = [s for s, _ in other_recs]
        other_gen_syms = [row[3] for row in other_generated]
        if len(other_syms) != len(set(other_syms)):
            fail(reasons, f"registry model {declared_model} has duplicate kind symbols")
        other_ords = [o for _, o in other_recs]
        if sorted(other_ords) != list(range(len(other_ords))):
            fail(reasons, f"registry model {declared_model} ordinals {sorted(other_ords)} "
                          f"are not contiguous 0..{len(other_ords) - 1}")
        if set(other_gen_syms) != set(other_syms):
            fail(reasons, f"registry model {declared_model} kinds {sorted(other_syms)} do not "
                          f"exactly match its generated handlers {sorted(other_gen_syms)}")
        if dispatch_cases(cpp_text, declared_model):
            fail(reasons, f"registry model {declared_model} retains handwritten dispatch; "
                          "schema carriers must be generated-only")

    recs = inc_records(inc_text, macro)
    if not recs:
        fail(reasons, f"registry {os.path.relpath(inc, REPO)} has no {macro} records")
        return
    reg_syms = [s for s, _ in recs]
    reg_set = set(reg_syms)

    # DUP: a symbol declared twice.
    dups = sorted({s for s in reg_syms if reg_syms.count(s) > 1})
    if dups:
        fail(reasons, f"registry declares duplicate kind(s) {dups}")
    # ORDINALS unique + contiguous 0..N-1 (the enum's integer identity).
    ords = [o for _, o in recs]
    if len(set(ords)) != len(ords):
        fail(reasons, f"registry has duplicate ordinals {sorted(o for o in ords if ords.count(o) > 1)}")
    if sorted(ords) != list(range(len(ords))):
        fail(reasons, f"registry ordinals {sorted(ords)} are not contiguous 0..{len(ords) - 1}")

    # GENERATED ENUM: the header must expand the registry, not re-hand-write the enum.
    if backend["inc_basename"] not in hdr_text or macro not in hdr_text:
        fail(reasons, f"{os.path.relpath(hdr, REPO)} does not expand the generated registry "
                      f"(the enum must #include {backend['inc_basename']}, not be hand-written)")

    # DUP/MISSING reconciliation against generated + not-yet-retired handwritten dispatch.
    cases = dispatch_cases(cpp_text, model)
    case_set = set(cases)
    case_dups = sorted({c for c in cases if cases.count(c) > 1})
    if case_dups:
        fail(reasons, f"toNode has duplicate case(s) {case_dups}")

    generated = all_generated
    generated = [row for row in generated if row[0] == model]
    generated_syms = [sym for _, _, _, sym in generated]
    generated_set = set(generated_syms)
    generated_dups = sorted({s for s in generated_syms if generated_syms.count(s) > 1})
    if generated_dups:
        fail(reasons, f"generated printer declares duplicate handler(s) {generated_dups}")
    unreachable = sorted(generated_set - reg_set)
    if unreachable:
        fail(reasons, f"generated printer handler(s) {unreachable} are unreachable from the registry")
    multiply_bound = sorted(generated_set & case_set)
    if multiply_bound:
        fail(reasons, f"generated handler(s) {multiply_bound} still have retained handwritten toNode fallback")

    handled_set = case_set | generated_set
    missing = sorted(reg_set - handled_set)
    #  C3 endpoint: PostgreSQL Kind::Line is retained only as ordinal 0 for
    # ABI/enum stability. Its constructor value is prohibited and the raw
    # printer dispatch is deliberately deleted, so it must have no handler.
    if target == "postgres" and "Line" in missing:
        try:
            sa = json.loads(_read(os.path.join(REPO, _SYNTAX_AUTHORITY_REL[target])))
        except (OSError, json.JSONDecodeError):
            sa = {}
        if (sa.get("kind") == "neutrino.postgres-syntax-authority.v2"
                and sa.get("baseline") == 0
                and sa.get("executable") == [] and sa.get("comments") == []):
            missing.remove("Line")
    if missing:
        fail(reasons, f"registry kind(s) {missing} have NO generated or handwritten printer handler")
    extra = sorted(case_set - reg_set)
    if extra:
        fail(reasons, f"toNode handles kind(s) {extra} absent from the registry (drift; add or remove the .td record)")
    extra_generated = sorted(generated_set - reg_set)
    if extra_generated:
        fail(reasons, f"generated printer handles kind(s) {extra_generated} absent from the registry")

    # scan_handwritten_inventory's cpp_override substitutes ONLY the SOLIDITY model
    # source (the lit tamper matrix path). It is meaningful only for the Solidity
    # backend and MUST be None for every other backend — otherwise a sibling
    # backend's cpp (e.g. PostgresModel.cpp) would be read IN PLACE of
    # SolidityTargetAdapter.cpp, vanishing the Solidity construct sites and mis-attributing
    # the sibling's emitters to Solidity.
    cpp_override = (cpp if backend["target"] == "solidity"
                    and os.path.abspath(cpp) != os.path.abspath(CPP) else None)
    check_inventory(backend, printer_text, cpp_override, reasons)


def run_td_mutation_selftests(tblgen, reasons):
    if not tblgen:
        fail(reasons, "target-node registry selftest needs --tblgen for .td mutation probes")
        return
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="target_node_td.")
    try:
        td_dir = os.path.join(tmp, "lib", "backends", "solidity")
        os.makedirs(td_dir)
        shutil.copyfile(os.path.join(REPO, "lib", "backends", "TargetPrinter.td"),
                        os.path.join(tmp, "lib", "backends", "TargetPrinter.td"))
        base = _read(TD)

        def expect_fail(name, text, needle):
            td = os.path.join(td_dir, f"{name}.td")
            out = os.path.join(tmp, f"{name}.inc")
            printer = os.path.join(tmp, f"{name}.printer.inc")
            with open(td, "w", encoding="utf-8") as fh:
                fh.write(text)
            cmd = [sys.executable, GEN, "--td", td, "--out", out, "--printer-out", printer,
                   "--tblgen", tblgen]
            r = subprocess.run(cmd, capture_output=True, text=True)
            msg = r.stderr + r.stdout
            if r.returncode == 0:
                fail(reasons, f".td mutation probe {name} unexpectedly passed")
            elif needle not in msg:
                fail(reasons, f".td mutation probe {name} failed for the wrong reason: {msg.strip()}")

        expect_fail(
            "empty_syntax",
            base.replace('"require(${condition}, \\"${message}\\");"', '""'),
            "empty Syntax",
        )
        expect_fail(
            "unsupported_layout",
            base.replace('"revert", "line",', '"revert", "paragraph",'),
            "unsupported Layout",
        )
        expect_fail(
            "undeclared_placeholder",
            base.replace('"require(${condition}, \\"${message}\\");"',
                         '"require(${missing});"'),
            "undeclared field",
        )
        expect_fail(
            "duplicate_field",
            base.replace("[FCondition, FMessage]", "[FCondition, FCondition]"),
            "duplicate field",
        )
        expect_fail(
            "unused_field",
            base.replace('"require(${condition}, \\"${message}\\");"',
                         '"require(${condition});"'),
            "unused field",
        )
        # IsLeaf ⇔ (layout != block): a block-layout node marked leaf, or a
        # non-block node marked non-leaf, must fail generation (the runtime driver
        # re-checks the same invariant, but an inconsistent .td must never
        # regenerate in the first place).
        expect_fail(
            "block_as_leaf",
            base.replace('"guarded",    /*leaf=*/0,', '"guarded",    /*leaf=*/1,'),
            "inconsistent with layout",
        )
        expect_fail(
            "leaf_as_non_leaf",
            base.replace('"line",       /*leaf=*/1,', '"line",       /*leaf=*/0,'),
            "inconsistent with layout",
        )
        # Arity-generic projection ( slice 2a): a node's field indices must be a
        # dense 0..N-1 range. A gap (LocalDecl's rhs bound to operand 3, not 2)
        # leaves operand 2 unconsumed and must fail generation.
        expect_fail(
            "sparse_field_index",
            base.replace('def FRhs       : PrinterField<"rhs",       2>;',
                         'def FRhs       : PrinterField<"rhs",       3>;'),
            "dense",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_sealed_carrier_selftests(reasons):
    """: non-vacuous proof that the sealed-carrier exemption is STRUCTURAL and
    MUTATION-SENSITIVE, run INSIDE the registered `--selftest` path so the
    meta-gate governs it. Synthetic data only — independent of a concrete carrier.
    The exact standalone suite also runs here and emits a proof token only after
    all five of its assertions execute."""
    entry = {"target": "synthetic", "node": "Probe",
             "path": "synthetic/Emitter.cpp", "matcher": "case Stmt::Kind::Probe:"}
    inv = {"sealedBodyCarriers": [dict(entry)]}
    scanned = [dict(entry)]
    passthrough = ("  case Stmt::Kind::Probe:\n    // opaque carrier\n"
                   "    dst.push_back(*s.probe);\n    return;\n"
                   "  case Stmt::Kind::Other:\n    return;\n")
    tampered = ('  case Stmt::Kind::Probe:\n    dst.push_back(ct::line("raw"));\n'
                "    dst.push_back(*s.probe);\n    return;\n"
                "  case Stmt::Kind::Other:\n    return;\n")
    # POSITIVE: a sole opaque pass-through earns the exemption (no reasons).
    r, ok = sealed_carrier_reasons(inv, scanned, lambda _p: passthrough)
    if r or len(ok) != 1:
        fail(reasons, f"sealed-carrier selftest: the sole pass-through case was not "
                      f"exempted (reasons={r})")
    # TAMPER (the biting proof): a raw emit inside the SAME case DENIES the
    # exemption. If this passed, the structural check would be vacuous.
    r, ok = sealed_carrier_reasons(inv, scanned, lambda _p: tampered)
    if ok or not any("opaque pass-through" in x for x in r):
        fail(reasons, "sealed-carrier selftest VACUOUS: a raw emit injected into the "
                      "sealed case was NOT rejected")
    # PHANTOM: an allowlist entry with no matching scanned site is rejected.
    r, ok = sealed_carrier_reasons(inv, [], lambda _p: passthrough)
    if ok or not any("phantom" in x for x in r):
        fail(reasons, "sealed-carrier selftest: a phantom allowlist entry was NOT rejected")
    # ABSENT: a matcher with no case body in the source is rejected.
    r, ok = sealed_carrier_reasons(inv, scanned, lambda _p: "switch (s.kind) {}\n")
    if ok or not r:
        fail(reasons, "sealed-carrier selftest: an absent sealed case was NOT rejected")

    test = os.path.join(REPO, "test/checks/fast/sealed_carrier_gate_test.py")
    result = subprocess.run(
        [sys.executable, test],
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    proof = "sealed-carrier-proof:positive,extra,phantom,absent,committed"
    if result.returncode != 0 or proof not in (result.stdout or ""):
        fail(
            reasons,
            "sealed-body-carrier selftest failed:\n"
            + (result.stdout or "")[-1200:],
        )


def main():
    ap = argparse.ArgumentParser(description="target-node registry reconciliation gate ()")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--inc", default=INC)
    ap.add_argument("--printer", default=PRINTER)
    ap.add_argument("--cpp", default=CPP)
    ap.add_argument("--header", default=HDR)
    ap.add_argument("--tblgen", default=None)
    ap.add_argument("--build-dir", default=None,
                    help="configured build tree holding the  generated .inc; "
                         "overrides NEUTRINO_BUILD_DIR")
    ap.add_argument("--reconcile-only", action="store_true",
                    help="skip the tblgen stale/deterministic checks (reconciliation only) — for the "
                         "lit tamper matrix; the CMake ctest runs the full check with the pinned tblgen")
    ap.add_argument("--base-ref", default=None,
                    help="the AUTHORITATIVE PR base ref/SHA for the PR-relative ratchet. In CI the "
                         "workflow passes the event base (PR_BASE_SHA / GITHUB_BASE_SHA); locally and in "
                         "the lit/ctest surface pass it explicitly. HEAD^1 and a silent origin/main "
                         "substitute are NOT used; an unresolvable base fails closed ().")
    ap.add_argument("--simulate-no-base", action="store_true",
                    help="force the no-resolvable-PR-base path (shallow single-SHA checkout, as required "
                         "release CI uses) so a local pass cannot disagree with shallow CI; the ratchet "
                         "then FAILS CLOSED rather than skipping the invariant")
    args = ap.parse_args()
    global _BUILD_DIR
    if args.build_dir:
        _BUILD_DIR = os.path.abspath(args.build_dir)
    if args.build_dir:
        if args.inc == INC:
            args.inc = _generated("SolidityTargetNodes.inc", args.build_dir)
        if args.printer == PRINTER:
            args.printer = _generated("SolidityPrinterHandlers.inc", args.build_dir)
    if not args.tblgen:
        args.tblgen = os.environ.get("LLVM_TABLEGEN") or os.environ.get("MLIR_TABLEGEN_EXE")
    global _SIMULATE_NO_BASE, _BASE_REF_OVERRIDE
    _SIMULATE_NO_BASE = args.simulate_no_base
    _BASE_REF_OVERRIDE = args.base_ref
    reasons = []
    backends = discover_backends()

    # FAIL-CLOSED ( P1.3): reject zero discovered backends and any backend whose
    # registry-derived identity (Target/Model + committed files) is missing or
    # malformed — BEFORE any file reconciliation, since the derived paths would
    # otherwise be None. No Solidity fallback.
    if not backends:
        reasons.append("no target-printer backends discovered (no lib/backends/**/*TargetNodes.td) — "
                       "fail closed")
    for b in backends:
        reasons.extend(_backend_identity_reasons(b))
    if reasons:
        print("target-node registry gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1

    # STALE-OUTPUT + DETERMINISTIC: the committed CI zero-diff gate, run per REGISTERED
    # backend `.td` (fail closed on any drift). Skipped for tampered `--inc` copies.
    if args.inc == INC and not args.reconcile_only:
        import tempfile
        for b in backends:
            # The generated C++ enum source () lives alongside the registry as
            # `<stem>TargetEnums.inc`; verifying its freshness here catches a
            # hand-edited/aliased generated enum (the enum is the single source, so
            # an edit that is not regenerated from the `.td` is stale). A backend
            # with no closed enums emits none, and the generator's --check skips it.
            # : the enums `.inc` is co-located with the other generated
            # artifacts (generated/), NOT with the `.td` (model/) — derive it from
            # the (already layout-resolved) inc path, not the td path.
            enums_out = re.sub(r"TargetNodes\.inc$", "TargetEnums.inc", b["inc"])
            cmd = [sys.executable, GEN, "--td", b["td"], "--out", b["inc"], "--check",
                   "--printer-out", b["printer"], "--enums-out", enums_out]
            if args.tblgen:
                cmd += ["--tblgen", args.tblgen]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                fail(reasons, r.stderr.strip() or f"committed registry is stale vs {b['td']}")
            # Deterministic order: regenerate to two temp files and compare.
            outs = []
            for _ in range(2):
                tf = tempfile.NamedTemporaryFile(suffix=".inc", delete=False)
                tf.close()
                pf = tempfile.NamedTemporaryFile(suffix=".inc", delete=False)
                pf.close()
                gcmd = [sys.executable, GEN, "--td", b["td"], "--out", tf.name, "--printer-out", pf.name]
                if args.tblgen:
                    gcmd += ["--tblgen", args.tblgen]
                g = subprocess.run(gcmd, capture_output=True, text=True)
                if g.returncode != 0:
                    fail(reasons, "regeneration failed: " + (g.stderr.strip()))
                    outs = None
                    break
                outs.append((open(tf.name, encoding="utf-8").read(),
                             open(pf.name, encoding="utf-8").read()))
                os.unlink(tf.name)
                os.unlink(pf.name)
            if outs and outs[0] != outs[1]:
                fail(reasons, f"non-deterministic generation: two regenerations of {b['td']} differ")

    # RECONCILIATION, per registered backend. The lit tamper matrix drives ONE backend
    # (Solidity) through the `--inc/--printer/--cpp/--header` overrides; the committed
    # run reconciles every discovered backend, so a new backend joins with no gate edit.
    sol = next((b for b in backends if b["name"] == "solidity"), backends[0] if backends else None)
    if args.inc == INC and args.printer == PRINTER and args.cpp == CPP and args.header == HDR:
        for b in backends:
            check(b, b["inc"], b["printer"], b["cpp"], b["hdr"], reasons)
    else:
        check(sol, args.inc, args.printer, args.cpp, args.header, reasons)
    if args.selftest and not args.reconcile_only:
        run_td_mutation_selftests(args.tblgen, reasons)
        run_sealed_carrier_selftests(reasons)

    if reasons:
        print("target-node registry gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    summary = ", ".join(
        f"{b['target']}: {len(inc_records(_read(b['inc']), b['macro']))} kinds" for b in backends)
    print(f"target-node registry gate OK for {len(backends)} backend(s) [{summary}]: committed generated "
          "files fresh + deterministic per backend, each enum expanded from its registry, every kind has "
          "exactly one generated-or-handwritten printer handler, generated handlers have no retained "
          "handwritten fallback, and each backend's handwritten printer inventory reconciled per-target")
    return 0


if __name__ == "__main__":
    sys.exit(main())
