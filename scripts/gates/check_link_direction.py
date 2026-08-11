#!/usr/bin/env python3
"""Fail-closed target-level dependency-direction gate.

The include lock proves a renderer's source consumes only the spec contract;
the composition gate proves a leaf-only module holds only migrated renderers.
This gate proves the CMake target link graph points the right way, so dependency
creep back into core or across backends fails mechanically.

Source of truth: the parsed `lib/**/CMakeLists.txt` target declarations (the  subproject layout), so
the gate is deterministic and needs no build. A target's LAYER is its subproject directory (a new module
is classified by where it lives, no hand-list to drift):

  lib/spec-contract/   -> leaf     (NeutrinoSpecContract, the frozen capability-spec contract)
  lib/recipe/          -> leaf     (NeutrinoRecipe, generic target-blind recipe runtime)
  lib/backends/*/      -> backend   (solidity / postgres / oracle renderers)
  lib/slots/           -> core      (retained slot contract and registry adapter)
  lib/policy/*/        -> policy    (security-policy / capability-profile models)
  lib/ (top level)     -> core      (dialect / analysis / tooling / frontend) + the ENTRY aggregator

Enforced edges (only Neutrino* link deps are considered; LLVM/MLIR/system deps are always allowed):

  - the leaf depends on NO Neutrino target;
  - every backend / policy module depends ONLY on the shared bottom-of-graph
    leaves (not on core, not on a sibling backend, not on the entry) — this
    subsumes "backends don't depend on each other" and "policy does not depend
    on a backend";
  - core targets have ZERO edges to any backend or policy module;
  - the ENTRY aggregator (NeutrinoEmit — the registry-entry layer that composes analysis + every
    leaf-only module) is the one target allowed to link the leaf-only modules; that is its job.

Non-vacuous + fail-closed: a missing lib/**/CMakeLists.txt, a parse that finds too few targets, or a
missing expected layer aborts the scan (a wrong path / renamed target can't yield a vacuous pass).
`--selftest` runs the real tree (must pass), then injects forbidden edges and asserts each is caught.

Usage: check_link_direction.py            # scan the real tree (exit 0 clean / 1 on a forbidden edge)
       check_link_direction.py --selftest # + prove the negatives fail closed (the CTest entry point)
"""
import argparse
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEAF = "NeutrinoSpecContract"
# Bottom-of-the-graph leaves a backend/slot/policy module may depend on: the
# frozen capability-spec contract; the language-neutral code-emitter substrate
# (NeutrinoCodeText, /); and the generic, domain-/target-blind recipe
# runtime frozen by /. Each links only LLVM/MLIR support and owns no
# core, View, backend, or target-specific authority.
LEAVES = {LEAF, "NeutrinoCodeText", "NeutrinoRecipe"}
ENTRY = "NeutrinoEmit"
# core targets declared in the top-level lib/CMakeLists.txt (everything there except the ENTRY).
CORE = {"NeutrinoDialect", "NeutrinoAnalysis", "NeutrinoTooling", "NeutrinoFrontend"}
# Floors so a mis-parse cannot pass vacuously. Security, coverage, slots, and
# views are retained public core; the remaining leaf-only set is three backends
# plus the capability-profile policy.
MIN_LEAF_ONLY_MODULES = 4
MIN_TARGETS = 10

_ADD_LIB = re.compile(r"add_mlir(?:_dialect)?_library\(\s*(\w+)(.*?)\n\)", re.S)


def _renderer_leaf_dirs():
    """reldirs under lib/ that hold a spec-renderer `Gen*Spec.cpp` (a leaf-only renderer) — Gen*Spec-DRIVEN
    ( X2), so a renderer added to a NEW dir (e.g. `views`) is auto-classified leaf-only rather than
    falling through to `core`. Excludes entry-layer targets
    (CapabilitySpecTarget.cpp producer) and the shared leaves
    (spec-contract/codetext/recipe hold no Gen*Spec.cpp)."""
    dirs = set()
    for f in glob.glob(os.path.join(REPO, "lib", "**", "Gen*Spec.cpp"), recursive=True):
        rel = os.path.relpath(os.path.dirname(f), os.path.join(REPO, "lib")).replace(os.sep, "/")
        if rel not in (".", "emit"):
            dirs.add(rel)
    return dirs


RENDERER_DIRS = _renderer_leaf_dirs()


_TLL = re.compile(r"target_link_libraries\(\s*(\w+)(.*?)\)", re.S)


def _strip_comments(text):
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())


def parse_targets(text_by_dir):
    """text_by_dir: {reldir: cmake_text}. Return {name: {"dir": reldir, "links": [Neutrino* deps]}}."""
    targets = {}
    for reldir, text in text_by_dir.items():
        for m in _ADD_LIB.finditer(text):
            name = m.group(1)
            body = _strip_comments(m.group(2))
            link_m = re.search(r"LINK_LIBS\s+(?:PUBLIC|PRIVATE|INTERFACE)?(.*)", body, re.S)
            links = re.findall(r"\b(Neutrino\w+)\b", link_m.group(1)) if link_m else []
            targets[name] = {"dir": reldir, "links": links}
    #  review P2: a SEPARATE `target_link_libraries(<lib> …)` is a link edge the add_mlir_library
    # LINK_LIBS parse misses — a leaf could grow a forbidden core dep out-of-band and the standalone
    # smoke would still link (CMake supplies the static lib's private requirement). Fold those Neutrino*
    # deps into the governed LIBRARY's edges. Only library targets (declared by add_mlir_library) are
    # governed — a smoke executable's `target_link_libraries(<smoke> NeutrinoX)` is its legitimate leaf
    # dependency, not a leaf growing an edge, so it is correctly ignored (the smoke is not in `targets`).
    for reldir, text in text_by_dir.items():
        for tm in _TLL.finditer(_strip_comments(text)):
            tgt = tm.group(1)
            if tgt in targets:
                targets[tgt]["links"] += re.findall(r"\b(Neutrino\w+)\b", tm.group(2))
    return targets


def layer_of(name, reldir):
    if reldir in {"spec-contract", "codetext", "recipe"}:
        return "leaf"
    if reldir in {"coverage", "security", "slots", "views"}:
        return "core"
    if reldir.startswith("backends/"):
        return "backend"
    if reldir.startswith("policy/"):
        return "policy"
    # Any OTHER dir holding a spec renderer (e.g. `views`, or a future leaf) is a leaf-only renderer —
    #  X2, so a new renderer-leaf layout can't fall through to `core` (where it could link core).
    if reldir in RENDERER_DIRS:
        return "renderer"
    # top-level lib/CMakeLists.txt
    return "entry" if name == ENTRY else "core"


def violations(targets):
    """Apply the direction rules; return a list of human-readable violation strings."""
    out = []
    layer = {n: layer_of(n, t["dir"]) for n, t in targets.items()}
    leaf_only = {"backend", "slot", "policy", "renderer"}

    for name, t in sorted(targets.items()):
        lyr = layer[name]
        # t["links"] holds only Neutrino* deps (parse_targets ignores external MLIR*/LLVM*/system libs,
        # which are always allowed). Every Neutrino edge is checked — a Neutrino* link the parser did NOT
        # discover as a declared target is an UNKNOWN internal edge whose direction can't be verified, so
        # it must fail CLOSED, not be dropped (an unverifiable dep is exactly what a closure gate guards).
        for d in t["links"]:
            if d not in targets:
                out.append(f"{name} ({lyr}) links {d} — an UNKNOWN Neutrino target (not declared by any "
                           "add_mlir_library in lib/**/CMakeLists.txt). An internal edge whose direction "
                           "cannot be verified fails closed (parser/layout drift, or a mis-declared dep "
                           "that could smuggle a forbidden dependency past this gate)")
                continue
            dlyr = layer[d]
            if lyr == "leaf":
                out.append(f"{name} (leaf) links {d} ({dlyr}) — the contract leaf must depend on NO "
                           "Neutrino target (only LLVM/MLIR)")
            elif lyr in leaf_only:
                if d not in LEAVES:
                    out.append(f"{name} ({lyr}) links {d} ({dlyr}) — a backend/slot/policy/renderer leaf "
                               f"may depend ONLY on a bottom-of-graph leaf ({', '.join(sorted(LEAVES))}) "
                               "(no core, no sibling renderer, no entry)")
            elif lyr == "core":
                if dlyr in leaf_only:
                    out.append(f"{name} (core) links {d} ({dlyr}) — core/kernel/frontend/analysis must "
                               "have ZERO edges to a backend/slot/policy/renderer leaf (dependency creep)")
            # entry (NeutrinoEmit) composes analysis + the leaf-only modules: allowed, no rule.
    return out


def scan():
    """Parse the real lib/**/CMakeLists.txt; return (targets, fatal_error_or_None)."""
    files = sorted(glob.glob(os.path.join(REPO, "lib", "**", "CMakeLists.txt"), recursive=True))
    if not files:
        return {}, "no lib/**/CMakeLists.txt found (wrong repo root?)"
    text_by_dir = {}
    for f in files:
        reldir = os.path.relpath(os.path.dirname(f), os.path.join(REPO, "lib"))
        reldir = "" if reldir == "." else reldir.replace(os.sep, "/")
        text_by_dir[reldir] = open(f, encoding="utf-8", errors="replace").read()
    targets = parse_targets(text_by_dir)
    # non-vacuity: the split's layers must all be present, above the floors.
    layers = {layer_of(n, t["dir"]) for n, t in targets.items()}
    leaf_only = sum(1 for n, t in targets.items()
                    if layer_of(n, t["dir"]) in ("backend", "slot", "policy", "renderer"))
    if len(targets) < MIN_TARGETS:
        return targets, f"parsed only {len(targets)} targets (< {MIN_TARGETS}) — parse drift?"
    if leaf_only < MIN_LEAF_ONLY_MODULES:
        return targets, (f"found only {leaf_only} leaf-only backend/slot/policy modules "
                         f"(< {MIN_LEAF_ONLY_MODULES}) — the  split regressed or the layout moved?")
    for need in ("leaf", "core", "entry", "backend"):
        if need not in layers:
            return targets, f"no '{need}'-layer target discovered — parse drift / layout change?"
    recipe = targets.get("NeutrinoRecipe")
    if recipe is None or recipe["dir"] != "recipe" or layer_of(
        "NeutrinoRecipe", recipe["dir"]
    ) != "leaf":
        return targets, (
            "generic NeutrinoRecipe bottom-of-graph leaf was not discovered "
            "from lib/recipe — parse/layout drift?"
        )
    return targets, None


def run_real():
    targets, fatal = scan()
    if fatal:
        print(f"    FAIL: {fatal}", file=sys.stderr)
        return 1
    v = violations(targets)
    if v:
        print("arch-link-direction: forbidden module dependency edges:", file=sys.stderr)
        for x in v:
            print("    FAIL: " + x, file=sys.stderr)
        return 1
    print(f"    ok: {len(targets)} lib targets; direction holds (leaves depend on nothing; every "
          "backend/slot/policy module links only shared bottom-of-graph leaves; core has no edge to "
          "a leaf-only module)")
    return 0


def selftest():
    # 1. the real tree must pass.
    if run_real() != 0:
        print("    FAIL: the committed lib/ target graph does not satisfy the link-direction rules",
              file=sys.stderr)
        return 1
    targets, fatal = scan()
    if fatal:
        print(f"    FAIL: {fatal}", file=sys.stderr)
        return 1

    # 2. injected forbidden edges must each be caught (non-vacuous negatives). Pick a representative of
    #    each layer from the real graph so the probes track the actual module names.
    def one(layer):
        return next((n for n, t in targets.items() if layer_of(n, t["dir"]) == layer), None)

    a_backend, another = None, None
    backends = sorted(n for n, t in targets.items() if layer_of(n, t["dir"]) == "backend")
    if len(backends) >= 2:
        a_backend, another = backends[0], backends[1]
    core, leaf, renderer = one("core"), one("leaf"), one("renderer")
    recipe = "NeutrinoRecipe" if "NeutrinoRecipe" in targets else None

    probes = []
    if a_backend and another:
        probes.append(("backend -> sibling backend", a_backend, another))
    if core and a_backend:
        probes.append(("core -> backend", core, a_backend))
    if leaf and a_backend:
        probes.append(("leaf -> backend", leaf, a_backend))
    if recipe and core:
        probes.append(("generic recipe leaf -> core", recipe, core))
    #  review P1: the extracted `views` renderer leaf must be leaf-only — a renderer -> core edge
    # (e.g. NeutrinoViewsSpec -> NeutrinoAnalysis) must fail, else its "leaf-only" contract is unenforced.
    if renderer and core:
        probes.append(("renderer leaf -> core", renderer, core))
    # an UNKNOWN Neutrino target the parser never discovered must fail closed (not be silently dropped),
    # else a module could smuggle a forbidden dep via a differently-declared / undiscovered target.
    if a_backend:
        probes.append(("leaf-only module -> unknown Neutrino target", a_backend, "NeutrinoUnparsedCore"))
    if not probes:
        print("    FAIL: could not construct negative probes (too few modules discovered)", file=sys.stderr)
        return 1

    for label, src, dst in probes:
        import copy
        mutated = copy.deepcopy(targets)
        mutated[src]["links"] = mutated[src]["links"] + [dst]
        if not violations(mutated):
            print(f"    FAIL: an injected forbidden edge ({label}: {src} -> {dst}) was NOT caught — the "
                  "gate is vacuous", file=sys.stderr)
            return 1

    #  review P2: a SEPARATE target_link_libraries(<lib> …) must be PARSED into the graph (not only
    # add_mlir_library LINK_LIBS), else a leaf grows a forbidden dep out-of-band while the smoke still
    # links. Prove: the TLL edge on a LIBRARY is discovered AND caught; a smoke exe's TLL is NOT folded
    # into the library it links.
    lib_tll = ("add_mlir_library(NeutrinoProbeSpec\n  X.cpp\n  LINK_LIBS PUBLIC\n  NeutrinoSpecContract\n)\n"
               "target_link_libraries(NeutrinoProbeSpec PRIVATE NeutrinoAnalysis)\n")
    parsed = parse_targets({"views": lib_tll})
    if "NeutrinoAnalysis" not in parsed.get("NeutrinoProbeSpec", {}).get("links", []):
        print("    FAIL: a target_link_libraries(<lib> …) edge was NOT parsed into the link graph (P2 "
              "out-of-band dependency would be invisible)", file=sys.stderr)
        return 1
    smoke_tll = ("add_mlir_library(NeutrinoProbeSpec\n  X.cpp\n  LINK_LIBS PUBLIC\n  NeutrinoSpecContract\n)\n"
                 "add_executable(probe-smoke t.cpp)\n"
                 "target_link_libraries(probe-smoke PRIVATE NeutrinoProbeSpec)\n")
    if parse_targets({"views": smoke_tll})["NeutrinoProbeSpec"]["links"] != ["NeutrinoSpecContract"]:
        print("    FAIL: a smoke executable's target_link_libraries was wrongly folded into the library "
              "it links (a leaf-only smoke is not the library growing an edge)", file=sys.stderr)
        return 1

    print(f"    PASS (committed lib/ link graph satisfies the direction rules; {len(probes)} injected "
          "forbidden edges — backend->sibling / core->backend / leaf->backend / recipe->core / "
          "renderer->core / ->unknown-Neutrino-target — each fail closed, and a "
          "target_link_libraries out-of-band edge is parsed into the graph)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="arch-link-direction: module dependency-direction gate ()")
    ap.add_argument("--selftest", action="store_true",
                    help="run the real check AND prove injected forbidden edges fail closed (CTest entry)")
    args = ap.parse_args()
    return selftest() if args.selftest else run_real()


if __name__ == "__main__":
    sys.exit(main())
