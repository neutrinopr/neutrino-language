#!/usr/bin/env python3
"""Extraction-unit dependency-boundary gate (M5 extraction A3, ).

The leaf-only link-smoke (/) proves at LINK time that a unit doesn't reach a sibling backend, and
the  manifest gate keeps `LINK_LIBS` == the declared shared leaves. This gate closes the remaining
SOURCE-level hole: the global renderer include-lock () allows any renderer to include the shared
`CONTRACT_HEADERS` set — but that set contains UNIT-OWNED headers (`SqlEmitter.h` is PostgreSQL's,
`SolidityEmit.h` is Solidity's). So the include-lock alone would let the Solidity backend `#include
"Neutrino/SqlEmitter.h"` — a direct sibling-backend dependency.

Driven by the  EXTRACTION.md manifests (the declared ownership data), for every backend/policy unit:
  - INCLUDE boundary: each owned `.cpp` may `#include` only (a) the unit's OWN declared public headers,
    (b) the SHARED leaf/contract headers (`CONTRACT_HEADERS` minus every unit-owned header), (c) its own
    owned files (the `.inc`), (d) `llvm/…` / the C++ stdlib. A sibling unit's owned header is
    `boundary.sibling_include`; any other `Neutrino/…` is `boundary.undeclared_include`.
    Multi-library units apply their declared public and integration headers per
    component; linking another local component exposes only that component's
    declared public headers.
  - LINK boundary: the unit's `add_mlir_library` LINK_LIBS + its link-smoke `target_link_libraries` name
    no OTHER unit's library (`boundary.sibling_link`).

Usage: check_extraction_boundaries.py [--selftest]   (exit 0 ok / 1 violations)
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_extraction_manifests import (  # noqa: E402  (sibling gate, same dir)
    _cmake_library_components,
    _items,
    _manifest_components,
    _section,
    scan,
)
from check_renderer_includes import CONTRACT_HEADERS    # noqa: E402  (the shared-leaf allowlist)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INCLUDE_RE = re.compile(r'^\s*#\s*include\s+(?:"([^"]+)"|<([^>]+)>)')


def _lib_name(cmake):
    components = _cmake_library_components(cmake)
    return next(iter(components), None)


def _link_libs_all(cmake):
    """Every library linked by any component, excluding internal edges."""
    components = _cmake_library_components(cmake)
    return (set().union(*(component["links"]
                         for component in components.values()))
            - set(components))


def load_units(unit_dirs=None):
    units = {}
    diagnostics = []
    for d in scan() if unit_dirs is None else unit_dirs:
        manifest = os.path.join(d, "EXTRACTION.md")
        rel = os.path.relpath(d, REPO)
        try:
            md = open(manifest, encoding="utf-8").read()
        except FileNotFoundError:
            diagnostics.append(
                f"[boundary.manifest_missing] {rel}/EXTRACTION.md is missing; "
                "every discovered extraction unit must declare ownership")
            continue
        except OSError as error:
            diagnostics.append(
                f"[boundary.manifest_unreadable] {rel}/EXTRACTION.md: "
                f"{error.strerror or error}")
            continue
        cmake = open(os.path.join(d, "CMakeLists.txt"), encoding="utf-8").read()
        cmake_components = _cmake_library_components(cmake)
        manifest_components = _manifest_components(md)
        components = {}
        if manifest_components is not None:
            for name, declaration in manifest_components.items():
                components[name] = {
                    "sources": set(_items(declaration["sources"]) or []),
                    "links": set(_items(declaration["links"]) or []),
                    "headers": set(_items(declaration["headers"]) or []),
                    "integration_headers": set(
                        _items(declaration["integration_headers"]) or []),
                }
        units[d] = {
            "rel": rel,
            "sources": set(_section(md, "Sources owned") or []),
            "headers": set(_section(md, "Public headers") or []),
            "integration_headers": set(
                _items(_section(md, "Integration headers")) or []),
            "lib": _lib_name(cmake),
            "libs": set(cmake_components),
            "links": _link_libs_all(cmake),
            "components": components,
        }
    return units, diagnostics


def check(units, contract_headers=None):
    reasons = []
    all_owned_headers = set().union(*(u["headers"] for u in units.values())) if units else set()
    all_libs = set().union(*(u.get("libs", {u["lib"]})
                            for u in units.values())) if units else set()
    declared_contract_headers = (
        set(CONTRACT_HEADERS)
        if contract_headers is None
        else set(contract_headers)
    )
    shared_headers = declared_contract_headers - all_owned_headers
    for d, u in units.items():
        rel = u["rel"]
        source_components = {}
        for name, component in u.get("components", {}).items():
            for source in component["sources"]:
                source_components[source] = (name, component)
        # INCLUDE boundary — scan each owned .cpp's direct includes.
        for src in sorted(s for s in u["sources"] if s.endswith(".cpp")):
            path = os.path.join(d, src)
            if not os.path.isfile(path):
                continue
            component_name = None
            component = None
            if src in source_components:
                component_name, component = source_components[src]
            own_headers = (
                component["headers"] if component is not None else u["headers"])
            linked_component_headers = set()
            if component is not None:
                for linked_component in component["links"]:
                    if linked_component in u["components"]:
                        linked_component_headers.update(
                            u["components"][linked_component]["headers"])
            integration_headers = (
                component["integration_headers"]
                if component is not None else u["integration_headers"])
            own_sources = (
                component["sources"] if component is not None else u["sources"])
            own_bases = {os.path.basename(source) for source in own_sources}
            for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
                m = INCLUDE_RE.match(line)
                if not m:
                    continue
                inc = m.group(1) or m.group(2)  # the include path — delimiter-AGNOSTIC (a project header
                is_angled = m.group(2) is not None  # can be spelled <Neutrino/…> too, so `<>` != external)
                # True externals (either delimiter): an angled `llvm/…`, or a stdlib header (angled, no
                # path). Everything else — including `<Neutrino/…>` — gets the boundary check.
                if inc.startswith("llvm/") or (is_angled and "/" not in inc):
                    continue
                if (inc in own_headers or inc in linked_component_headers
                        or inc in integration_headers
                        or inc in shared_headers
                        or os.path.basename(inc) in own_bases):
                    continue
                if inc in u["headers"] and component_name is not None:
                    reasons.append(
                        f"[boundary.component_include] {rel}/{src}:{i}: "
                        f"component {component_name} includes '{inc}', which "
                        "belongs to another component in the same extraction "
                        "unit")
                    continue
                if inc in all_owned_headers:
                    owner = next(v["rel"] for v in units.values() if inc in v["headers"])
                    reasons.append(f"[boundary.sibling_include] {rel}/{src}:{i}: includes '{inc}' — a header "
                                   f"OWNED by sibling unit {owner}. A unit may include only its own public "
                                   "headers + the shared leaves, never another unit's.")
                elif inc.startswith("Neutrino/"):
                    reasons.append(f"[boundary.undeclared_include] {rel}/{src}:{i}: includes '{inc}', which "
                                   "is neither this unit's own header nor a shared leaf/contract header "
                                   "(outside the declared extraction boundary).")
        # LINK boundary — no sibling unit's library on the link line.
        for sib in sorted((all_libs - u.get("libs", {u["lib"]}))
                          & u["links"]):
            reasons.append(f"[boundary.sibling_link] {rel}: CMake links sibling backend library '{sib}' — "
                           "an extraction unit must link only its declared shared leaves, not a sibling.")
    return reasons


def run(unit_dirs=None):
    units, load_diagnostics = load_units(unit_dirs)
    if load_diagnostics:
        print("extraction-boundary gate FAILED:", file=sys.stderr)
        for reason in load_diagnostics:
            print(f"    {reason}", file=sys.stderr)
        return 1
    if len(units) < 5:
        print(f"boundary gate: found only {len(units)} units (< 5) — discovery drift?", file=sys.stderr)
        return 1
    reasons = check(units)
    if reasons:
        print("extraction-boundary gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    print(f"extraction-boundary gate OK: {len(units)} units — each includes only its own headers + the "
          "shared leaves and links no sibling backend")
    return 0


def selftest():
    """Prove the gate BITES: the real tree passes, removing either shared projection declaration
    rejects both real backend consumers, and fabricated sibling-include, undeclared-include, and
    sibling-link cases each fail with their coded reason."""
    import copy
    if run() != 0:
        print("selftest: current tree does not pass the gate", file=sys.stderr)
        return 1
    real, load_diagnostics = load_units()
    if load_diagnostics:
        print("selftest: current tree has unreadable extraction ownership:",
              file=sys.stderr)
        for reason in load_diagnostics:
            print(f"    {reason}", file=sys.stderr)
        return 1
    sol = next(k for k, v in real.items() if v["lib"] == "NeutrinoBackendSolidity")
    pg = next(v for v in real.values() if v["lib"] == "NeutrinoBackendPostgres")
    sib_hdr = sorted(pg["headers"])[0]          # a PostgreSQL-owned header, e.g. Neutrino/SqlEmitter.h
    fails = []

    # A required manifest that is renamed must take the same coded diagnostic
    # path as a missing manifest in the live tree. It must never escape as a
    # FileNotFoundError traceback.
    import contextlib
    import io
    import tempfile
    with tempfile.TemporaryDirectory(
            prefix="neutrino-boundary-missing-manifest-") as directory:
        open(os.path.join(directory, "CMakeLists.txt"), "w").write(
            "add_mlir_library(NeutrinoProbeSpec\n"
            "  GenProbeSpec.cpp\n"
            "  LINK_LIBS PUBLIC\n"
            "  NeutrinoSpecContract\n"
            ")\n")
        open(os.path.join(directory, "GenProbeSpec.cpp"), "w").write("")
        manifest = os.path.join(directory, "EXTRACTION.md")
        renamed = os.path.join(directory, "EXTRACTION.md.renamed")
        open(manifest, "w").write("probe\n")
        os.rename(manifest, renamed)
        error_output = io.StringIO()
        with contextlib.redirect_stderr(error_output):
            missing_result = run([directory])
        diagnostic = error_output.getvalue()
        if (missing_result == 0
                or "[boundary.manifest_missing]" not in diagnostic
                or "Traceback" in diagnostic
                or "FileNotFoundError" in diagnostic):
            fails.append(
                "probe 'manifest_renamed' expected a coded non-zero "
                f"diagnostic without traceback, got rc={missing_result}, "
                f"stderr={diagnostic!r}")

    # The projection contract and target-neutral traversal driver are exact
    # shared leaves, not blanket project-header exemptions. Removing either
    # declaration must reject each real model TU that consumes it.
    for projection_header in (
        "Neutrino/BackendProjection.h",
        "Neutrino/BackendProjectionDriver.h",
    ):
        without_projection = set(CONTRACT_HEADERS) - {projection_header}
        undeclared_projection = check(real, without_projection)
        solidity_consumer = (
            "lib/backends/solidity/provider/SolidityRecipeProvider.cpp"
            if projection_header == "Neutrino/BackendProjectionDriver.h"
            else "lib/backends/solidity/provider/GenSoliditySpec.cpp"
        )
        for consumer in (
            "lib/backends/postgres/model/PostgresModel.cpp",
            solidity_consumer,
        ):
            if not any(
                "boundary.undeclared_include" in reason
                and consumer in reason
                and projection_header in reason
                for reason in undeclared_projection
            ):
                fails.append(
                    f"probe 'projection_declaration:{projection_header}:"
                    f"{consumer}' expected [boundary.undeclared_include], "
                    f"got {undeclared_projection}"
                )

    def expect(mut, code, label):
        # write a temp source into the solidity unit dir, run check, then remove it.
        tmp = os.path.join(sol, "_boundary_probe.cpp")
        open(tmp, "w").write(mut)
        try:
            u = copy.deepcopy(real)
            u[sol]["sources"] = set(u[sol]["sources"]) | {"_boundary_probe.cpp"}
            got = check(u)
        finally:
            os.remove(tmp)
        if not any(code in r for r in got):
            fails.append(f"probe '{label}' expected [{code}], got {got}")

    expect(f'#include "{sib_hdr}"\n', "boundary.sibling_include", "sibling_include")
    expect('#include "Neutrino/View.h"\n', "boundary.undeclared_include", "undeclared_include")
    #  review P1: angle brackets must not smuggle a project header past the boundary.
    expect(f'#include <{sib_hdr}>\n', "boundary.sibling_include", "sibling_include_angled")
    expect('#include <Neutrino/View.h>\n', "boundary.undeclared_include", "undeclared_include_angled")

    # sibling-link: fabricate a solidity unit that links the postgres lib.
    u = copy.deepcopy(real)
    u[sol]["links"] = set(u[sol]["links"]) | {"NeutrinoBackendPostgres"}
    if not any("boundary.sibling_link" in r for r in check(u)):
        fails.append("probe 'sibling_link' expected [boundary.sibling_link]")

    # A retained adapter may name a core integration header without widening
    # the target-neutral renderer allowlist or granting that header to its model
    # component.
    coverage_path = next(
        path for path, unit in real.items()
        if unit["rel"] == "lib/coverage")
    coverage_core = real[coverage_path]["components"]["NeutrinoCoverageCore"]
    if "Neutrino/GenSpec.h" in CONTRACT_HEADERS:
        fails.append(
            "probe 'component_integration_not_global' found GenSpec.h in "
            "CONTRACT_HEADERS")
    if "Neutrino/GenSpec.h" not in coverage_core["integration_headers"]:
        fails.append(
            "probe 'component_integration_declared' expected coverage core "
            "adapter to declare Neutrino/GenSpec.h")
    without_integration = copy.deepcopy(real)
    without_integration[coverage_path]["components"][
        "NeutrinoCoverageCore"]["integration_headers"].discard(
            "Neutrino/GenSpec.h")
    integration_errors = check(without_integration)
    if not any(
            "boundary.undeclared_include" in reason
            and "lib/coverage/CoverageTarget.cpp" in reason
            and "Neutrino/GenSpec.h" in reason
            for reason in integration_errors):
        fails.append(
            "probe 'component_integration_missing' expected coverage adapter "
            f"GenSpec.h failure, got {integration_errors}")

    probe_name = "_component_boundary_probe.cpp"
    probe_path = os.path.join(coverage_path, probe_name)
    open(probe_path, "w").write('#include "Neutrino/GenSpec.h"\n')
    try:
        model_uses_integration = copy.deepcopy(real)
        model_uses_integration[coverage_path]["sources"].add(probe_name)
        model_uses_integration[coverage_path]["components"][
            "NeutrinoCoverageSpec"]["sources"].add(probe_name)
        model_errors = check(model_uses_integration)
    finally:
        os.remove(probe_path)
    if not any(
            "boundary.undeclared_include" in reason
            and probe_name in reason
            and "Neutrino/GenSpec.h" in reason
            for reason in model_errors):
        fails.append(
            "probe 'component_integration_isolation' expected target-neutral "
            f"model GenSpec.h failure, got {model_errors}")

    if fails:
        print("extraction-boundary SELFTEST FAILED:", file=sys.stderr)
        for f in fails:
            print(f"    {f}", file=sys.stderr)
        return 1
    print("extraction-boundary selftest PASS (real tree clean; a renamed required manifest fails "
          "with a coded diagnostic and no traceback; removing either shared projection "
          "declaration rejects both real backend consumers; a sibling-header include and an out-of-"
          "boundary include — in BOTH quoted and angle-bracket spelling — and a sibling-library link "
          "fail closed; retained-adapter integration headers remain component-scoped)")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else run())
