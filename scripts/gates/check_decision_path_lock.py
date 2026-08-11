#!/usr/bin/env python3
""": decision-path MLIR/target-dialect dependency lock.

The M6 backend decision path is: target-registry entry -> capability-spec /
coordination-plan contract -> backend legalizer -> typed target model ->
language-neutral printer/framing.  This gate pins that path as MLIR-dialect-free:
it may consume the already-normalized contract, but it must not introduce target
MLIR dialects, PDL/rewrite machinery, target-op construction, or MLIR/rewrite
link dependencies.

The governed source set is derived, not hand-entered:

  * target-registry rows with a matching `lib/backends/<target>/CMakeLists.txt`
    identify backend decision targets (currently solidity/postgres);
  * those backend CMake targets provide the legalization/printer source set;
  * `NeutrinoCodeText` is included as the shared projection/printer core;
  * registry entry TUs (`lib/targets/<Target>Target.cpp`) for those backends are
    included from the same registry membership;
  * backend/shared printer TableGen files are swept, but legitimate printer
    records such as `def LocalDecl : SolNode<...>` are allowed.  The forbidden
    condition is record ancestry/registration (`Dialect`, `Op`, `TypeDef`,
    `AttrDef`), not the `def` token.

The current tree is expected to be exact zero.  Any violation is a regression.
`--selftest` proves each red-line bite independently.
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from check_cpp_policy import strip_comments

TARGET_REGISTRY = os.path.join(REPO, "include", "Neutrino", "TargetRegistry.def")

ADD_LIB_RE = re.compile(
    r"(?:add_mlir(?:_dialect)?_library|add_library)\(\s*(\w+)(.*?)\n\)",
    re.S,
)
TLL_RE = re.compile(r"target_link_libraries\(\s*(\w+)(.*?)\)", re.S)
TARGET_SOURCES_RE = re.compile(r"target_sources\(\s*(\w+)(.*?)\)", re.S)
SOURCE_RE = re.compile(r"^\s*([A-Za-z0-9_./+-]+\.(?:cpp|cc|cxx|c|h|hpp|hh|td))\s*$")
SOURCE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_./+-])([A-Za-z0-9_./+-]+\.(?:cpp|cc|cxx|c|h|hpp|hh|td))(?![A-Za-z0-9_./+-])")
INCLUDE_RE = re.compile(r'^\s*#\s*include\s+(?:"([^"]+)"|<([^>]+)>)')
TD_INCLUDE_RE = re.compile(r'^\s*include\s+"([^"]+)"', re.M)
TD_PARENT_RE = re.compile(r"\b(?:def|class)\s+(\w+)(?:\s*<[^>{;]*>)?\s*:\s*([^;{]+)")

FORBIDDEN_LINKS = {
    "NeutrinoDialect",
    "NeutrinoL2",
    "NeutrinoAnalysis",
    "NeutrinoFrontend",
    "MLIRIR",
    "MLIRParser",
    "MLIRRewrite",
    "MLIRPDL",
    "MLIRPDLInterp",
    "MLIRTransformUtils",
    "MLIRTransforms",
}

MIN_BACKEND_TARGETS = 2
MIN_GOVERNED_SOURCES = 10
MIN_GOVERNED_TABLEGEN = 2

MLIR_DIALECT_HEADER_RE = re.compile(r"^(?:mlir/|Neutrino/(?:Neutrino|L2)(?:Dialect|Ops)\.h)")
REWRITE_OR_PDL_RE = re.compile(
    r"\b(?:RewritePattern|OpRewritePattern|PatternRewriter|PDLPatternModule|"
    r"ConversionPattern|ConversionTarget|DialectConversion|applyPatternsAndFoldGreedily)\b"
)
TARGET_OP_CONSTRUCTION_RE = re.compile(
    r"\b(?:\w+\.|\w+->)?create\s*<\s*(?:(?:neutrino|mlir)::)?"
    r"(?:(?:\w+)::)*[A-Za-z_]\w*Op\b|"
    r"\b(?:OperationState|OpBuilder|getOrLoadDialect|loadDialect)\b|"
    r"\bmlir::[a-z]\w*::[A-Z]\w*Op\b"
)
ODS_RECORD_RE = re.compile(
    r"\b(?:def|class)\s+\w+(?:\s*<[^>{;]*>)?\s*:\s*"
    r"[^;{]*(?:\bDialect\b|\bOp\s*<|\bTypeDef\s*<|\bAttrDef\s*<|"
    r"\b(?:Neutrino|L2)_Op\s*<)"
)
ODS_INCLUDE_RE = re.compile(
    r'include\s+"?(?:mlir/(?:IR/OpBase|IR/AttrTypeBase|TableGen/)|'
    r"Neutrino/(?:Neutrino|L2)Ops\.td)"
)


def _strip_cmake_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _extract_sources(body: str) -> list[str]:
    return SOURCE_TOKEN_RE.findall(body)


def _cmake_unresolved_tokens(body: str) -> list[str]:
    return sorted(set(re.findall(r"\$\{[^}]+\}|\$<[^>]+>", body)))


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _rel(path: str, root: str = REPO) -> str:
    return os.path.relpath(os.path.abspath(path), root).replace(os.sep, "/")


def _target_rows(root: str) -> list[str]:
    text = _read(os.path.join(root, "include", "Neutrino", "TargetRegistry.def"))
    return re.findall(r'NEUTRINO_TARGET\("([^"]+)"\s*,', text)


def _camel_target(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("-"))


def _backend_targets_from_registry(root: str) -> list[str]:
    out = []
    for name in _target_rows(root):
        if os.path.exists(os.path.join(root, "lib", "backends", name, "CMakeLists.txt")):
            out.append(name)
    return out


def _external_backend_targets(root: str) -> list[str]:
    out = []
    for path in sorted(glob.glob(
            os.path.join(root, "packaging", "*", "extraction-manifest.json"))):
        target = os.path.basename(os.path.dirname(path))
        try:
            manifest = json.loads(_read(path))
        except (ValueError, OSError):
            continue
        if (manifest.get("kind") == f"neutrino.{target}-extraction-manifest/1"
                and manifest.get("sourceBoundary")
                == f"lib/backends/{target}/EXTRACTION.md"):
            out.append(target)
    return out


def _cmake_text_by_dir(root: str) -> dict[str, str]:
    out = {}
    for f in sorted(glob.glob(os.path.join(root, "lib", "**", "CMakeLists.txt"),
                              recursive=True)):
        reldir = os.path.relpath(os.path.dirname(f), os.path.join(root, "lib"))
        reldir = "" if reldir == "." else reldir.replace(os.sep, "/")
        out[reldir] = _read(f)
    return out


def _parse_cmake_targets(text_by_dir: dict[str, str]) -> dict[str, dict]:
    targets: dict[str, dict] = {}
    for reldir, text in text_by_dir.items():
        for m in ADD_LIB_RE.finditer(text):
            name = m.group(1)
            body = _strip_cmake_comments(m.group(2))
            link_m = re.search(r"\bLINK_LIBS\s+(?:PUBLIC|PRIVATE|INTERFACE)?(.*)", body, re.S)
            source_part = body[:link_m.start()] if link_m else body
            source_part = re.split(r"\bPARTIAL_SOURCES_INTENDED\b|\bDEPENDS\b", source_part)[0]
            sources = _extract_sources(source_part)
            links = re.findall(r"\b(?:Neutrino\w+|MLIR\w+)\b",
                               link_m.group(1) if link_m else "")
            unresolved = _cmake_unresolved_tokens(body)
            targets[name] = {
                "dir": reldir,
                "sources": sources,
                "links": links,
                "unresolved": unresolved,
            }
    for reldir, text in text_by_dir.items():
        for m in TARGET_SOURCES_RE.finditer(_strip_cmake_comments(text)):
            name = m.group(1)
            if name in targets:
                body = m.group(2)
                targets[name]["sources"] += _extract_sources(body)
                targets[name]["unresolved"] += _cmake_unresolved_tokens(body)
    for reldir, text in text_by_dir.items():
        for m in TLL_RE.finditer(_strip_cmake_comments(text)):
            if m.group(1) in targets:
                targets[m.group(1)]["links"] += re.findall(
                    r"\b(?:Neutrino\w+|MLIR\w+)\b", m.group(2))
                targets[m.group(1)]["unresolved"] += _cmake_unresolved_tokens(m.group(2))
    return targets


def _modules_for_backend(targets: dict[str, dict], backend: str) -> list[str]:
    want_dir = f"backends/{backend}"
    out = []
    for name, meta in sorted(targets.items()):
        if meta["dir"] == want_dir:
            out.append(name)
    return out


def governed_surface(root: str = REPO) -> dict:
    text_by_dir = _cmake_text_by_dir(root)
    targets = _parse_cmake_targets(text_by_dir)
    backend_names = sorted(set(
        _backend_targets_from_registry(root) + _external_backend_targets(root)))
    modules = []
    rel_sources = set()
    rel_tds = set()

    for backend in backend_names:
        backend_modules = _modules_for_backend(targets, backend)
        if not backend_modules:
            continue
        base = os.path.join("lib", f"backends/{backend}")
        for module in backend_modules:
            modules.append(module)
            module_base = os.path.join("lib", targets[module]["dir"])
            for src in targets[module]["sources"]:
                if src.endswith(".td"):
                    rel_tds.add(f"{module_base}/{src}")
                elif src.endswith((".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh")):
                    rel_sources.add(f"{module_base}/{src}")
        for h in glob.glob(os.path.join(root, base, "**", "*.h"), recursive=True):
            rel_sources.add(_rel(h, root))
        for h in glob.glob(os.path.join(root, base, "**", "*.hpp"), recursive=True):
            rel_sources.add(_rel(h, root))
        for h in glob.glob(os.path.join(root, base, "**", "*.hh"), recursive=True):
            rel_sources.add(_rel(h, root))
        for td in glob.glob(os.path.join(root, base, "**", "*.td"), recursive=True):
            rel_tds.add(_rel(td, root))
        entry = os.path.join(root, "lib", "targets", f"{_camel_target(backend)}Target.cpp")
        if os.path.exists(entry):
            rel_sources.add(_rel(entry, root))

    if "NeutrinoCodeText" in targets:
        modules.append("NeutrinoCodeText")
        base = os.path.join("lib", targets["NeutrinoCodeText"]["dir"])
        for src in targets["NeutrinoCodeText"]["sources"]:
            rel_sources.add(f"{base}/{src}")
        for h in ("include/Neutrino/CodeText.h", "include/Neutrino/TargetPrinter.h"):
            if os.path.exists(os.path.join(root, h)):
                rel_sources.add(h)
        td = "lib/backends/TargetPrinter.td"
        if os.path.exists(os.path.join(root, td)):
            rel_tds.add(td)

    return {
        "backend_names": sorted(backend_names),
        "modules": sorted(set(modules)),
        "sources": sorted(rel_sources),
        "tds": sorted(rel_tds),
        "targets": targets,
    }


def _source_violations(root: str, rel: str, text: str | None = None) -> list[str]:
    path = os.path.join(root, rel)
    code = strip_comments(_read(path) if text is None else text, keep_string_content=True)
    out = []
    for i, line in enumerate(code.splitlines(), start=1):
        m = INCLUDE_RE.match(line)
        if not m:
            continue
        inc = m.group(1) or m.group(2)
        if MLIR_DIALECT_HEADER_RE.search(inc):
            out.append(f"{rel}:{i}: forbidden MLIR/dialect/rewrite include {inc!r}")
    for rx, label in (
        (REWRITE_OR_PDL_RE, "PDL/rewrite API"),
        (TARGET_OP_CONSTRUCTION_RE, "target-op construction / dialect loading"),
    ):
        m = rx.search(code)
        if m:
            line = code.count("\n", 0, m.start()) + 1
            out.append(f"{rel}:{line}: forbidden {label}: {m.group(0)!r}")
    return out


def _td_violations(root: str, rel: str, text: str | None = None) -> list[str]:
    path = os.path.join(root, rel)
    code = strip_comments(_read(path) if text is None else text, keep_string_content=True)
    out = []
    m = ODS_INCLUDE_RE.search(code)
    if m:
        line = code.count("\n", 0, m.start()) + 1
        out.append(f"{rel}:{line}: forbidden MLIR/ODS include in decision-path TableGen")
    for m in ODS_RECORD_RE.finditer(code):
        line = code.count("\n", 0, m.start()) + 1
        out.append(f"{rel}:{line}: forbidden MLIR/ODS dialect/op/type/attr record ancestry")
    out.extend(_td_ancestry_violations(root, rel, code))
    return out


def _resolve_td_include(root: str, current_rel: str, inc: str) -> str | None:
    candidates = [
        os.path.normpath(os.path.join(os.path.dirname(current_rel), inc)),
        inc,
        os.path.join("include", inc),
        os.path.join("lib", "backends", inc),
    ]
    for cand in candidates:
        full = os.path.join(root, cand)
        if os.path.isfile(full):
            return cand.replace(os.sep, "/")
    return None


def _td_include_closure(root: str, rel: str, code: str | None = None) -> dict[str, str]:
    docs: dict[str, str] = {}

    def visit(item: str, override: str | None = None) -> None:
        item = item.replace(os.sep, "/")
        if item in docs:
            return
        raw = override if override is not None else _read(os.path.join(root, item))
        stripped = strip_comments(raw, keep_string_content=True)
        docs[item] = stripped
        for m in TD_INCLUDE_RE.finditer(stripped):
            resolved = _resolve_td_include(root, item, m.group(1))
            if resolved:
                visit(resolved)

    visit(rel, code)
    return docs


def _record_parent_graph(docs: dict[str, str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for doc in docs.values():
        for m in TD_PARENT_RE.finditer(doc):
            name = m.group(1)
            parent_text = m.group(2)
            parents = set()
            for token in re.findall(r"\b[A-Za-z_]\w*\b", parent_text):
                if token not in {"list", "string", "int", "bit"}:
                    parents.add(token)
            graph.setdefault(name, set()).update(parents)
    return graph


def _td_ancestry_violations(root: str, rel: str, code: str) -> list[str]:
    docs = _td_include_closure(root, rel, code)
    graph = _record_parent_graph(docs)
    forbidden = {"Dialect", "Op", "TypeDef", "AttrDef", "Neutrino_Op", "L2_Op"}
    memo: dict[str, bool] = {}

    def reaches_forbidden(name: str, seen: set[str] | None = None) -> bool:
        if name in forbidden:
            return True
        if name in memo:
            return memo[name]
        seen = set() if seen is None else seen
        if name in seen:
            memo[name] = False
            return False
        seen.add(name)
        memo[name] = any(reaches_forbidden(parent, seen) for parent in graph.get(name, set()))
        return memo[name]

    out = []
    for m in TD_PARENT_RE.finditer(code):
        name = m.group(1)
        parents = graph.get(name, set())
        if any(reaches_forbidden(parent) for parent in parents):
            line = code.count("\n", 0, m.start()) + 1
            out.append(f"{rel}:{line}: forbidden resolved MLIR/ODS record ancestry for {name}")
    return out


def _link_violations(surface: dict) -> list[str]:
    out = []

    def visit(module: str, dep: str, chain: tuple[str, ...], seen: set[str]) -> None:
        if dep == "MLIRSupport":
            return
        if dep.startswith("MLIR") or dep in FORBIDDEN_LINKS:
            path = " -> ".join((*chain, dep))
            out.append(f"{module}: forbidden decision-path link dependency {path}")
            return
        if dep in seen:
            return
        if dep in surface["targets"]:
            seen.add(dep)
            for next_dep in sorted(set(surface["targets"][dep]["links"])):
                visit(module, next_dep, (*chain, dep), seen)

    for module in surface["modules"]:
        meta = surface["targets"].get(module)
        if not meta:
            out.append(f"{module}: governed module missing from parsed CMake targets")
            continue
        for token in sorted(set(meta.get("unresolved", []))):
            out.append(f"{module}: unresolved decision-path CMake source/link expression {token}")
        for dep in sorted(set(meta["links"])):
            visit(module, dep, (module,), {module})
    return out


def check_all(root: str = REPO) -> list[str]:
    surface = governed_surface(root)
    fails = []
    if len(surface["backend_names"]) < MIN_BACKEND_TARGETS:
        fails.append("discovered fewer than two registry-backed backend decision targets")
    if "NeutrinoCodeText" not in surface["modules"]:
        fails.append("shared projection core NeutrinoCodeText was not governed")
    if len(surface["sources"]) < MIN_GOVERNED_SOURCES:
        fails.append(f"discovered only {len(surface['sources'])} governed source files")
    if len(surface["tds"]) < MIN_GOVERNED_TABLEGEN:
        fails.append(f"discovered only {len(surface['tds'])} governed TableGen files")

    for rel in surface["sources"]:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            fails.append(f"{rel}: governed source is missing")
            continue
        fails.extend(_source_violations(root, rel))
    for rel in surface["tds"]:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            fails.append(f"{rel}: governed TableGen file is missing")
            continue
        fails.extend(_td_violations(root, rel))
    fails.extend(_link_violations(surface))
    return fails


def run(root: str = REPO) -> int:
    fails = check_all(root)
    if fails:
        print("decision-path MLIR/dialect lock VIOLATED ():\n  "
              + "\n  ".join(fails), file=sys.stderr)
        return 1
    s = governed_surface(root)
    print("decision-path lock OK: "
          f"{len(s['sources'])} sources, {len(s['tds'])} TableGen files, "
          f"{len(s['modules'])} CMake modules governed; MLIR/dialect/rewrite/PDL "
          "surface is pinned at zero ()")
    return 0


def check_one(path: str) -> int:
    abs_path = os.path.abspath(path)
    rel = os.path.basename(path)
    text = _read(abs_path)
    if path.endswith(".td"):
        fails = _td_violations(os.path.dirname(abs_path), rel, text)
    else:
        fails = _source_violations(os.path.dirname(abs_path), rel, text)
    if fails:
        print("decision-path MLIR/dialect lock VIOLATED ():\n  "
              + "\n  ".join(fails), file=sys.stderr)
        return 1
    print(f"ok: {os.path.basename(path)} has no decision-path MLIR/dialect authority")
    return 0


def selftest() -> int:
    fails = []
    if run(REPO) != 0:
        fails.append("committed tree does not satisfy the decision-path lock")

    source = os.path.join(
        REPO, "lib", "backends", "solidity", "provider", "SolidityTargetValidation.cpp")
    base = _read(source)
    source_probes = [
        ('#include "Neutrino/NeutrinoDialect.h"\n',
         "MLIR dialect include"),
        ('#include "mlir/Dialect/Func/IR/FuncOps.h"\n'
         'void useDialect(mlir::func::FuncOp op) { (void)op; }\n',
         "generic MLIR Func dialect surface"),
        ('#include "mlir/IR/PatternMatch.h"\n'
         'struct BadPattern : mlir::RewritePattern {};\n',
         "PDL/RewritePattern surface"),
        ('const char *url = "http://example"; struct BadPattern : mlir::RewritePattern {};\n',
         "RewritePattern after // inside string"),
        ('const char *raw = R"(// not a comment)"; struct BadPattern : mlir::RewritePattern {};\n',
         "RewritePattern after // inside raw string"),
        ('void _bad(mlir::OpBuilder &b, mlir::Location loc) { '
         'b.create<neutrino::DebitOp>(loc); }\n',
         "target-op construction"),
    ]
    for inj, label in source_probes:
        with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as tmp:
            tmp.write(base + "\n" + inj)
            tmp_path = tmp.name
        try:
            if check_one(tmp_path) == 0:
                fails.append(f"source probe did not reject {label}")
        finally:
            os.unlink(tmp_path)

    td = os.path.join(REPO, "lib", "backends", "solidity", "model", "SolidityTargetNodes.td")
    td_base = _read(td)
    td_probes = [
        ('\ninclude "mlir/IR/OpBase.td"\ndef BadDialect : Dialect { let name = "bad"; }\n',
         "new dialect record"),
        ('\ninclude "mlir/IR/OpBase.td"\ndef BadOp : Op<BadDialect, "bad"> {}\n',
         "new op record"),
        ('\ninclude "Neutrino/NeutrinoOps.td"\n'
         'def BadDecisionOp : Neutrino_Op<"bad_decision", []>;\n',
         "indirect Neutrino op record"),
        ('\ninclude "mlir/IR/AttrTypeBase.td"\ndef BadType : TypeDef<BadDialect, "bad"> {}\n',
         "new typedef record"),
    ]
    for inj, label in td_probes:
        with tempfile.NamedTemporaryFile("w", suffix=".td", delete=False) as tmp:
            tmp.write(td_base + "\n" + inj)
            tmp_path = tmp.name
        try:
            if check_one(tmp_path) == 0:
                fails.append(f"TableGen probe did not reject {label}")
        finally:
            os.unlink(tmp_path)

    surface = governed_surface(REPO)
    mutated = copy.deepcopy(surface)
    if "NeutrinoBackendSolidity" in mutated["targets"]:
        mutated["targets"]["NeutrinoBackendSolidity"]["links"].append("MLIRFuncDialect")
        if not _link_violations(mutated):
            fails.append("forbidden MLIRFuncDialect link edge was not rejected")
        mutated["targets"]["NeutrinoDialectCarrier"] = {
            "dir": "backends/solidity",
            "sources": [],
            "links": ["MLIRFuncDialect"],
            "unresolved": [],
        }
        mutated["targets"]["NeutrinoBackendSolidity"]["links"].append("NeutrinoDialectCarrier")
        if not _link_violations(mutated):
            fails.append("transitive MLIRFuncDialect carrier link edge was not rejected")
    else:
        fails.append("could not find NeutrinoBackendSolidity for link-edge probe")

    def copy_source_tree(destination):
        shutil.copytree(
            REPO, destination, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                ".git", "out", "out-*", "build", "build-*", "__pycache__"))

    extra_root = tempfile.mkdtemp(prefix="decision_path_extra_target.")
    try:
        copy_source_tree(extra_root)
        cmake = os.path.join(extra_root, "lib", "backends", "solidity", "CMakeLists.txt")
        with open(cmake, "a", encoding="utf-8") as fh:
            fh.write(
                "\nadd_mlir_library(ZZZSolidityEscape\n"
                "  RogueDecision.cpp\n"
                "  LINK_LIBS PUBLIC\n"
                "  MLIRFuncDialect\n"
                ")\n"
            )
        rogue = os.path.join(extra_root, "lib", "backends", "solidity", "RogueDecision.cpp")
        with open(rogue, "w", encoding="utf-8") as fh:
            fh.write('#include "mlir/Dialect/Func/IR/FuncOps.h"\n')
        if not check_all(extra_root):
            fails.append("extra governed backend target/source self-excluded from decision path")
    finally:
        shutil.rmtree(extra_root, ignore_errors=True)

    target_sources_root = tempfile.mkdtemp(prefix="decision_path_target_sources.")
    try:
        copy_source_tree(target_sources_root)
        cmake = os.path.join(target_sources_root, "lib", "backends", "solidity", "CMakeLists.txt")
        with open(cmake, "a", encoding="utf-8") as fh:
            fh.write("\ntarget_sources(NeutrinoBackendSolidity PRIVATE RogueDecision.cpp)\n")
        rogue = os.path.join(target_sources_root, "lib", "backends", "solidity", "RogueDecision.cpp")
        with open(rogue, "w", encoding="utf-8") as fh:
            fh.write('#include "mlir/Dialect/Func/IR/FuncOps.h"\n')
        if not check_all(target_sources_root):
            fails.append("target_sources-owned backend source self-excluded from decision path")
    finally:
        shutil.rmtree(target_sources_root, ignore_errors=True)

    hidden_base_root = tempfile.mkdtemp(prefix="decision_path_hidden_base.")
    try:
        copy_source_tree(hidden_base_root)
        hidden = os.path.join(hidden_base_root, "include", "Neutrino", "HiddenTargetBase.td")
        with open(hidden, "w", encoding="utf-8") as fh:
            fh.write('include "Neutrino/NeutrinoOps.td"\n'
                     'class HiddenTargetOp<string mnemonic> : Neutrino_Op<mnemonic, []>;\n')
        rogue_td = os.path.join(hidden_base_root, "lib", "backends", "solidity", "RogueTarget.td")
        with open(rogue_td, "w", encoding="utf-8") as fh:
            fh.write('include "Neutrino/HiddenTargetBase.td"\n'
                     'def RogueDecisionOp : HiddenTargetOp<"rogue_decision">;\n')
        if not check_all(hidden_base_root):
            fails.append("hidden intermediate Neutrino_Op TableGen base was not rejected")
    finally:
        shutil.rmtree(hidden_base_root, ignore_errors=True)

    if fails:
        print("decision-path lock SELFTEST FAILED:\n  " + "\n  ".join(fails),
              file=sys.stderr)
        return 1
    print("decision-path lock selftest PASS: committed tree is clean and probes reject "
          "generic MLIR dialect include/link edges, PDL/rewrite API, comment-hidden "
          "rewrite probes, target-op construction, extra/target_sources CMake targets, "
          "transitive link carriers, and direct/indirect Dialect/Op/TypeDef TableGen records")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="scan a single source or .td file")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.file:
        return check_one(args.file)
    return run(REPO)


if __name__ == "__main__":
    sys.exit(main())
