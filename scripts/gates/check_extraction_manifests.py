#!/usr/bin/env python3
"""Per-backend extraction-manifest gate (M5 extraction A2, ).

Each discovered extraction unit ships an `EXTRACTION.md` declaring the sources
it owns, the shared libraries it may link, and the public headers it exposes.
Retained public-core units with multiple libraries additionally declare each
component's sources, dependencies, public headers, and integration headers.
This gate keeps those declarations HONEST against the live CMake/link graph.

Checked, fail-closed, for every `lib/backends/*` and `lib/policy/*` unit (discovered, not hand-listed):
  - EXTRACTION.md EXISTS (non-vacuous: a new/renamed unit without one fails — coverage can't shrink).
  - `## Sources owned` == every `.cpp`/`.inc` file physically under the unit dir (incl. `test/`): a source
    added to the module but not the manifest, or a manifest source that doesn't exist, FAILS.
  - `## Shared leaf dependencies` == the module's `LINK_LIBS PUBLIC` in its CMakeLists (exact set).
  - every `## Public headers` entry resolves under `include/`.
  - multi-library component declarations exactly partition compiled sources and
    public headers, including conditional `target_sources`.

Usage: check_extraction_manifests.py   (exit 0 ok / 1 violations)
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generated_artifacts  # noqa: E402

# : build products are checked where they are produced. Default lets CI set
# it once; --build-dir overrides.
BUILD_DIR = os.environ.get("NEUTRINO_BUILD_DIR", "")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# backends/{solidity,postgres,oracle} + policy/{security,capability-profile,coverage} + slots + views
# — every spec-renderer LEAF discovered from its Gen*Spec.cpp ( X1/X2, ).
MIN_UNITS = 8
# The capability-spec PRODUCER: lib/targets/CapabilitySpecTarget.cpp EMITS the frozen spec (it consumes
# IR/ProcedureView and is an entry-layer source), so it is NOT a spec-renderer leaf. No root-level
# Gen*Spec.cpp is allowed: root lib/ is no longer the entry-layer home after .
SPEC_PRODUCER_ALLOWLIST = set()


def _section(md, heading):
    # bullets ("- item") under `## heading`, up to the next `## `.
    m = re.search(r"^## " + re.escape(heading) + r"\s*$(.*?)(?=^## |\Z)", md, re.S | re.M)
    if not m:
        return None
    return re.findall(r"^- (\S+)", m.group(1), re.M)


def _cmake_target_links(cmake):
    links = {}
    for tm in re.finditer(r"target_link_libraries\(\s*(\w+)(.*?)\)", cmake, re.S):
        links.setdefault(tm.group(1), set()).update(
            re.findall(r"\b(Neutrino\w+)\b", tm.group(2)))
    return links


def _cmake_library_components(cmake):
    """Return every library component with its exact compiled sources and links.

    Retained public-core units contain a target-neutral model and a core adapter
    in separate add_mlir_library calls. Conditional target_sources belong to the
    named component; link-smoke sources inherit the single local component they
    link. This keeps the manifest tied to the real build graph without flattening
    component ownership.
    """
    components = {}
    for match in re.finditer(
            r"add_mlir_library\(\s*(\w+)(.*?)^\s*\)", cmake, re.S | re.M):
        name, body = match.group(1), match.group(2)
        head = re.split(r"\bPARTIAL_SOURCES_INTENDED\b|\bLINK_LIBS\b", body)[0]
        link_match = re.search(r"\bLINK_LIBS\s+PUBLIC(.*)", body, re.S)
        components[name] = {
            "sources": set(re.findall(r"([A-Za-z0-9_./]+\.cpp)", head)),
            "links": set(re.findall(r"\b(Neutrino\w+)\b",
                                    link_match.group(1) if link_match else "")),
        }

    target_links = _cmake_target_links(cmake)
    for target, extra_links in target_links.items():
        if target in components:
            components[target]["links"].update(extra_links)

    for match in re.finditer(r"target_sources\(\s*(\w+)(.*?)\)", cmake, re.S):
        target = match.group(1)
        if target in components:
            components[target]["sources"].update(
                re.findall(r"([A-Za-z0-9_./]+\.cpp)", match.group(2)))

    # A direct smoke belongs to the one local component it links. More complex
    # executables remain aggregate build evidence rather than being guessed into
    # a component.
    for match in re.finditer(r"add_executable\(\s*(\w+)(.*?)\)", cmake, re.S):
        target = match.group(1)
        sources = set(re.findall(r"([A-Za-z0-9_./]+\.cpp)", match.group(2)))
        local_links = set(components) & target_links.get(target, set())
        if len(local_links) == 1:
            components[next(iter(local_links))]["sources"].update(sources)
    return components


def _manifest_components(md):
    names = _section(md, "Components")
    if names is None:
        return None
    components = {}
    for name in names:
        components[name] = {
            "sources": _section(md, f"Component {name} sources owned"),
            "links": _section(md, f"Component {name} dependencies"),
            "headers": _section(md, f"Component {name} public headers"),
            "integration_headers": _section(
                md, f"Component {name} integration headers"),
        }
    return components


def _items(items):
    if items == ["none"]:
        return []
    return items


def _cmake_link_libs(cmake):
    components = _cmake_library_components(cmake)
    if not components:
        return None
    # Aggregate shared dependencies exclude links between components in this
    # same extraction unit; those remain exact in each component declaration.
    return sorted(set().union(*(c["links"] for c in components.values()))
                  - set(components))


def _cmake_cpp_sources(cmake):
    """Every library, conditional target source, and executable .cpp."""
    components = _cmake_library_components(cmake)
    if not components:
        return None
    sources = set().union(*(c["sources"] for c in components.values()))
    for match in re.finditer(r"add_executable\(\s*\w+(.*?)\)", cmake, re.S):
        sources.update(re.findall(r"([A-Za-z0-9_./]+\.cpp)",
                                  match.group(1)))
    # A unit may build a package executable whose entry source is owned by the
    # repository packaging surface. `${PROJECT_SOURCE_DIR}/...` is captured
    # with a leading slash by the deliberately narrow token regex above; it is
    # not a physical source under this extraction unit and must not be claimed
    # by the unit manifest.
    return {source for source in sources if not source.startswith("/")}


def check(unit_dir):
    reasons = []
    rel = os.path.relpath(unit_dir, REPO)
    manifest = os.path.join(unit_dir, "EXTRACTION.md")
    if not os.path.isfile(manifest):
        return [f"[manifest.missing] {rel}/EXTRACTION.md is missing (: every backend/policy "
                "extraction unit must carry one)"]
    md = open(manifest, encoding="utf-8").read()

    # (1) Sources owned == actual .cpp/.inc under the unit dir.
    actual = set()
    for ext in ("*.cpp", "*.inc"):
        for f in glob.glob(os.path.join(unit_dir, "**", ext), recursive=True):
            actual.add(os.path.relpath(f, unit_dir))
    # : a declared source may be a BUILD PRODUCT. It is still owned by the
    # unit -- an extraction must carry its .td and generator -- but it is not in
    # the source tree, so its existence is checked where it is actually
    # produced. Resolved through the migration registry rather than by pattern,
    # so only the declared 16 are treated this way and an undeclared missing
    # file still fails.
    unit_rel = os.path.relpath(unit_dir, REPO)
    for repo_relative in generated_artifacts.MIGRATED_ARTIFACTS:
        if not repo_relative.startswith(unit_rel + os.sep):
            continue
        try:
            generated_artifacts.resolve(repo_relative, BUILD_DIR)
        except generated_artifacts.GeneratedArtifactError as err:
            reasons.append(
                f"[manifest.build_product_missing] {rel}: declared build "
                f"product '{os.path.relpath(repo_relative, unit_rel)}' is not "
                f"in the build tree ({err.identity}); configure and build "
                "before running this gate")
            continue
        actual.add(os.path.relpath(repo_relative, unit_rel))
    cmake = open(os.path.join(unit_dir, "CMakeLists.txt"), encoding="utf-8").read()
    cmake_components = _cmake_library_components(cmake)
    declared = _section(md, "Sources owned")
    if declared is None:
        reasons.append(f"[manifest.no_sources] {rel}/EXTRACTION.md has no `## Sources owned` section")
    else:
        ds = set(declared)
        # (1a) declared == the physical .cpp/.inc under the dir.
        for extra in sorted(ds - actual):
            reasons.append(f"[manifest.source_absent] {rel}: declares source '{extra}' that does not exist")
        for missing in sorted(actual - ds):
            reasons.append(f"[manifest.source_undeclared] {rel}: source '{missing}' exists but is not "
                           "declared in EXTRACTION.md (add it, or the manifest drifted from the build)")
        # (1b) the declared .cpp == the .cpp CMake actually COMPILES (lib + smoke). Catches a source
        # dropped from add_mlir_library while the file + manifest remain ( review P1).
        cmake_cpp = _cmake_cpp_sources(cmake)
        if cmake_cpp is None:
            reasons.append(f"[manifest.no_cmake_lib] {rel}: no add_mlir_library() found")
        else:
            declared_cpp = {d for d in ds if d.endswith(".cpp")}
            for extra in sorted(declared_cpp - cmake_cpp):
                reasons.append(f"[manifest.source_not_built] {rel}: '{extra}' is declared but NOT compiled "
                               "by add_mlir_library()/add_executable() in CMakeLists (dropped from the "
                               "build but left in the manifest?)")
            for missing in sorted(cmake_cpp - declared_cpp):
                reasons.append(f"[manifest.cmake_source_undeclared] {rel}: CMake compiles '{missing}' but "
                               "it is not declared in EXTRACTION.md")

    # (2) Shared leaf dependencies == CMake LINK_LIBS PUBLIC.
    links = _cmake_link_libs(cmake)
    declared_leaves = _section(md, "Shared leaf dependencies")
    if links is None:
        reasons.append(f"[manifest.no_cmake_lib] {rel}: no add_mlir_library() found")
    elif declared_leaves is None:
        reasons.append(f"[manifest.no_leaves] {rel}/EXTRACTION.md has no `## Shared leaf dependencies`")
    elif set(declared_leaves) != set(links):
        reasons.append(f"[manifest.leaf_mismatch] {rel}: declared leaf deps {sorted(set(declared_leaves))} "
                       f"!= CMake LINK_LIBS PUBLIC {sorted(set(links))}")

    # (3) Public headers: the section MUST be present (each unit declares its public-header surface), and
    # every entry resolves under include/. A missing section is a coded failure, not a silent empty
    # ( review P2).
    headers = _section(md, "Public headers")
    if headers is None:
        reasons.append(f"[manifest.no_headers] {rel}/EXTRACTION.md has no `## Public headers` section — "
                       "each extraction unit must declare its exposed public-header surface")
    else:
        for h in headers:
            if not os.path.isfile(os.path.join(REPO, "include", h)):
                reasons.append(f"[manifest.header_absent] {rel}: declares public header '{h}' not found "
                               "under include/")
        # (3b) COMPLETENESS: every owned (non-test) `.cpp` whose same-named public header exists under
        # include/ MUST be declared. Without this the `## Public headers` list only had to keep its
        # LISTED entries honest — an OMITTED unit-owned header passed silently, and the boundary gate
        # () then misclassifies it as a shared leaf (`CONTRACT_HEADERS - all_owned_headers`), so an
        # extraction would leave a required unit header behind. This is what makes the M6 header move
        # genuinely complete-by-construction, not just "listed paths resolve" ( review P1).
        if declared is not None:
            hdrset = set(headers)
            for s in sorted(d for d in set(declared) if d.endswith(".cpp")):
                if s.startswith("test/") or "/test/" in s:
                    continue  # link-smokes / backend-local tests expose no public API.
                cand = "Neutrino/" + os.path.basename(s)[:-4] + ".h"
                if os.path.isfile(os.path.join(REPO, "include", cand)) and cand not in hdrset:
                    reasons.append(f"[manifest.header_incomplete] {rel}: owns '{s}' and its public header "
                                   f"'{cand}' exists under include/, but it is not declared in `## Public "
                                   "headers' — an omitted unit-owned header would be left behind at M6 "
                                   "extraction (and the boundary gate would misclassify it as a shared leaf)")
    integration_headers = _section(md, "Integration headers")
    for header in _items(integration_headers) or []:
        if not os.path.isfile(os.path.join(REPO, "include", header)):
            reasons.append(
                f"[manifest.integration_header_absent] {rel}: declares "
                f"integration header '{header}' not found under include/")

    # Retained public-core units may contain multiple independently constrained
    # libraries. Their component declarations must match the exact CMake source
    # and link graph; aggregate sections alone are insufficient because they
    # could hide a backend-facing adapter dependency inside a target-neutral
    # model.
    declared_components = _manifest_components(md)
    if len(cmake_components) > 1 and declared_components is None:
        reasons.append(
            f"[manifest.no_components] {rel}/EXTRACTION.md describes "
            f"{len(cmake_components)} add_mlir_library components but has no "
            "`## Components` declaration")
    if declared_components is not None:
        cmake_names = set(cmake_components)
        declared_names = set(declared_components)
        if declared_names != cmake_names:
            reasons.append(
                f"[manifest.component_set_mismatch] {rel}: declared components "
                f"{sorted(declared_names)} != CMake components "
                f"{sorted(cmake_names)}")

        component_source_owners = {}
        component_public_headers = set()
        for name in sorted(declared_names & cmake_names):
            declaration = declared_components[name]
            for key, heading in (
                    ("sources", "sources owned"),
                    ("links", "dependencies"),
                    ("headers", "public headers"),
                    ("integration_headers", "integration headers")):
                if declaration[key] is None:
                    reasons.append(
                        f"[manifest.component_section_missing] {rel}: "
                        f"`## Component {name} {heading}` is missing")

            component_sources = set(_items(declaration["sources"]) or [])
            expected_sources = cmake_components[name]["sources"]
            for source in sorted(component_sources - expected_sources):
                reasons.append(
                    f"[manifest.component_source_not_built] {rel}: component "
                    f"{name} declares '{source}' but that component does not "
                    "compile it")
            for source in sorted(expected_sources - component_sources):
                reasons.append(
                    f"[manifest.component_source_undeclared] {rel}: component "
                    f"{name} compiles '{source}' but does not declare it")
            for source in component_sources:
                component_source_owners.setdefault(source, []).append(name)

            component_links = set(_items(declaration["links"]) or [])
            expected_links = cmake_components[name]["links"]
            if component_links != expected_links:
                reasons.append(
                    f"[manifest.component_link_mismatch] {rel}: component "
                    f"{name} declares dependencies {sorted(component_links)} != "
                    f"CMake links {sorted(expected_links)}")

            component_headers = set(_items(declaration["headers"]) or [])
            component_public_headers.update(component_headers)
            for header in component_headers:
                if not os.path.isfile(os.path.join(REPO, "include", header)):
                    reasons.append(
                        f"[manifest.component_header_absent] {rel}: component "
                        f"{name} declares public header '{header}' not found "
                        "under include/")

            integration_headers = set(
                _items(declaration["integration_headers"]) or [])
            for header in integration_headers:
                if not os.path.isfile(os.path.join(REPO, "include", header)):
                    reasons.append(
                        f"[manifest.component_integration_header_absent] "
                        f"{rel}: component {name} declares integration header "
                        f"'{header}' not found under include/")

        for source, owners in sorted(component_source_owners.items()):
            if len(owners) != 1:
                reasons.append(
                    f"[manifest.component_source_overlap] {rel}: '{source}' "
                    f"belongs to components {sorted(owners)}")
        if declared is not None:
            aggregate_cpp = {
                source for source in declared if source.endswith(".cpp")}
            component_cpp = set(component_source_owners)
            for source in sorted(aggregate_cpp - component_cpp):
                reasons.append(
                    f"[manifest.component_source_unassigned] {rel}: aggregate "
                    f"source '{source}' belongs to no component")
            for source in sorted(component_cpp - aggregate_cpp):
                reasons.append(
                    f"[manifest.component_source_not_aggregate] {rel}: "
                    f"component source '{source}' is absent from `## Sources "
                    "owned`")
        if headers is not None and component_public_headers != set(headers):
            reasons.append(
                f"[manifest.component_header_mismatch] {rel}: component public "
                f"headers {sorted(component_public_headers)} != aggregate "
                f"headers {sorted(set(headers))}")
    return reasons


def scan():
    """Every spec-renderer LEAF: a directory under lib/ (NOT the root) that holds a `Gen*Spec.cpp`. This
    is Gen*Spec-DRIVEN ( X2) so a NEW renderer leaf is discovered automatically — one without an
    EXTRACTION.md then fails `check`, and one added to root lib/ is caught by `root_spec_renderers`. The
    shared leaves (spec-contract/codetext) hold no Gen*Spec.cpp, so they are correctly not units."""
    dirs = set()
    for f in glob.glob(os.path.join(REPO, "lib", "**", "Gen*Spec.cpp"), recursive=True):
        d = os.path.dirname(f)
        #  R1: a spec renderer may live in a structural subdir (e.g.
        # solidity/provider/GenSoliditySpec.cpp) while the extraction unit — the
        # CMakeLists.txt + EXTRACTION.md — is the backend root. Resolve the unit
        # dir up to the nearest ancestor that carries a CMakeLists.txt.
        while (not os.path.isfile(os.path.join(d, "CMakeLists.txt"))
               and os.path.dirname(d) != d):
            d = os.path.dirname(d)
        rel = os.path.relpath(d, REPO)
        if rel in ("lib", os.path.join("lib", "emit")):
            continue  # root/entry-layer Gen*Spec.cpp sources are checked by root_spec_renderers/root_emit_adapters.
        dirs.add(d)
    return sorted(dirs)


def root_spec_renderers(lib_root=None):
    """Root-level `Gen*Spec.cpp` = a spec renderer/producer in the wrong ownership folder.

    Spec renderers belong in extracted leaves; the capability-spec producer belongs in `lib/emit/`.
    Returns the offending basenames. `lib_root` defaults to the real `lib/`; the selftest passes a temp
    dir to prove the check bites.
    """
    lib_root = lib_root or os.path.join(REPO, "lib")
    return sorted(
        os.path.basename(f)
        for f in glob.glob(os.path.join(lib_root, "Gen*Spec.cpp"))
        if os.path.basename(f) not in SPEC_PRODUCER_ALLOWLIST)


def root_emit_adapters(lib_root=None):
    """Root-level `Gen*.cpp` entries are forbidden after the entry ownership split (/).

    `lib/targets/*Target.cpp` owns compiler target entries. Root `lib/` may hold core compiler modules,
    but not target-specific emit adapters; otherwise the old "thin Gen*.cpp in root" shape can silently
    regrow while the target still links through NeutrinoEmit.
    """
    lib_root = lib_root or os.path.join(REPO, "lib")
    return sorted(os.path.basename(f) for f in glob.glob(os.path.join(lib_root, "Gen*.cpp")))


def ambiguous_target_entries():
    """Target entries must be named `lib/targets/*Target.cpp`, not `Gen*.cpp`.

    This catches the  regression class directly: the entry exists under the right build layer but
    keeps the ambiguous `Gen<X>.cpp` name, or a new target-specific `Gen<X>.cpp` appears again under
    `lib/emit/`.
    """
    offenders = []
    for pat in (
        os.path.join(REPO, "lib", "emit", "Gen*.cpp"),
        os.path.join(REPO, "lib", "targets", "Gen*.cpp"),
    ):
        offenders.extend(os.path.relpath(f, REPO) for f in glob.glob(pat))
    return sorted(offenders)


def _root_leaf_duplicate_reasons(root_basenames, leaf_owner_by_base):
    """Root `lib/` sources must not duplicate an extracted leaf-owned source basename.

    This is narrower than the root `Gen*Spec.cpp` escape hatch above: it protects the inventory/ownership
    claim directly. If a stale root copy of an extracted leaf renderer is reintroduced, the tree again has
    two authoritative-looking implementations with the same basename, even if only one is linked.
    """
    reasons = []
    for base in sorted(set(root_basenames) & set(leaf_owner_by_base)):
        owners = ", ".join(sorted(leaf_owner_by_base[base]))
        reasons.append(f"[manifest.root_leaf_duplicate_source] lib/{base}: root source duplicates an "
                       f"extracted leaf-owned source ({owners}). Delete the stale root copy; each "
                       "extracted renderer/source basename must have exactly one authoritative owner.")
    return reasons


def root_leaf_duplicate_sources(lib_root=None, units=None):
    """Duplicate source basenames between root `lib/` and extracted leaves.

    `units` defaults to the real extraction leaves; tests can pass explicit unit dirs. Only `.cpp`/`.inc`
    are source inventory items because that is what `## Sources owned` governs.
    """
    lib_root = lib_root or os.path.join(REPO, "lib")
    units = units or scan()
    root_bases = [
        os.path.basename(f)
        for pat in ("*.cpp", "*.inc")
        for f in glob.glob(os.path.join(lib_root, pat))
    ]
    leaf_owner_by_base = {}
    for u in units:
        manifest = os.path.join(u, "EXTRACTION.md")
        if not os.path.isfile(manifest):
            continue
        rel = os.path.relpath(u, REPO)
        md = open(manifest, encoding="utf-8").read()
        for src in _section(md, "Sources owned") or []:
            if not (src.endswith(".cpp") or src.endswith(".inc")):
                continue
            leaf_owner_by_base.setdefault(os.path.basename(src), set()).add(f"{rel}/{src}")
    return _root_leaf_duplicate_reasons(root_bases, leaf_owner_by_base)


def run():
    units = scan()
    if len(units) < MIN_UNITS:
        print(f"extraction-manifest gate: found only {len(units)} spec-renderer leaves (< {MIN_UNITS}) — "
              "discovery path drift?", file=sys.stderr)
        return 1
    reasons = []
    # /: after the entry split, root lib/ cannot own target-specific Gen*.cpp adapters. Entries
    # belong under lib/targets/*Target.cpp (still in the NeutrinoEmit target); leaf renderers stay in their
    # subprojects.
    for f in root_emit_adapters():
        reasons.append(f"[manifest.root_emit_adapter] lib/{f}: target emit adapter lives in root lib/. "
                       "Move it to lib/targets/<Target>Target.cpp and keep it wired through the "
                       "NeutrinoEmit target.")
    for f in ambiguous_target_entries():
        reasons.append(f"[manifest.ambiguous_target_entry] {f}: compiler target entries must use "
                       "`lib/targets/<Target>Target.cpp`; `Gen*.cpp` is reserved for historical public "
                       "headers and post-waist Gen*Spec leaves.")
    # : stale duplicate source cleanup. A renderer/source extracted into a leaf must not also exist
    # as a root `lib/` copy. This catches the concrete GenViewsSpec/GenCoverageSpec class even when the
    # stale root file is not linked, and it generalizes to future extracted leaf sources.
    reasons += root_leaf_duplicate_sources(units=units)
    #  X2 / : no spec renderer/producer may live in root lib/.
    for f in root_spec_renderers():
        reasons.append(f"[manifest.root_spec_renderer] lib/{f}: a spec renderer/producer "
                       "(Gen*Spec.cpp) lives in root lib/. Spec renderers belong in extracted leaves; "
                       "the capability-spec producer belongs in lib/emit/.")
    for u in units:
        reasons += check(u)
    if reasons:
        print("extraction-manifest gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    print(f"extraction-manifest gate OK: {len(units)} spec-renderer leaves — each EXTRACTION.md's "
          "sources/leaf-deps/headers match the CMake/link graph, and no renderer/entry escaped into "
          "root lib/")
    return 0


def selftest():
    """Prove the gate BITES (non-vacuous): the real tree passes, and each tamper on a temp unit fails
    with its coded reason — so registration alone is not the guarantee (mirrors the arch/cpp-policy
    selftests)."""
    import tempfile
    if run() != 0:
        print("selftest: the current tree does not pass the gate", file=sys.stderr)
        return 1
    valid_md = ("## Sources owned\n- Foo.cpp\n\n## Shared leaf dependencies\n- NeutrinoSpecContract\n\n"
                "## Public headers\n- Neutrino/Expr.h\n")
    cmake = "add_mlir_library(NeutrinoFoo\n  Foo.cpp\n  LINK_LIBS PUBLIC\n  NeutrinoSpecContract\n)\n"
    probes = [
        ("valid", valid_md, ["Foo.cpp"], None),
        ("source_undeclared", valid_md, ["Foo.cpp", "Extra.cpp"], "manifest.source_undeclared"),
        ("source_absent", valid_md.replace("- Foo.cpp", "- Foo.cpp\n- Ghost.cpp"), ["Foo.cpp"],
         "manifest.source_absent"),
        # P1 (): a source dropped from CMake but left as a file + in the manifest — declared==physical
        # still holds, but it is not COMPILED, so it must fail.
        ("source_not_built", valid_md.replace("- Foo.cpp", "- Foo.cpp\n- Bar.cpp"), ["Foo.cpp", "Bar.cpp"],
         "manifest.source_not_built"),
        ("leaf_mismatch", valid_md.replace("- NeutrinoSpecContract",
                                           "- NeutrinoSpecContract\n- NeutrinoBogus"), ["Foo.cpp"],
         "manifest.leaf_mismatch"),
        ("header_absent", valid_md.replace("- Neutrino/Expr.h", "- Neutrino/DoesNotExist.h"), ["Foo.cpp"],
         "manifest.header_absent"),
        # P1 (): an owned .cpp whose same-named public header EXISTS under include/ but is OMITTED
        # from `## Public headers` must fail — else M6 leaves that unit-owned header behind. Uses the
        # real GenViewsSpec.cpp/Neutrino/GenViewsSpec.h pairing; the header section is present (Expr.h)
        # but omits GenViewsSpec.h. (Source-check noise from the renamed source is ignored by the probe.)
        ("header_incomplete",
         "## Sources owned\n- GenViewsSpec.cpp\n\n## Shared leaf dependencies\n- NeutrinoSpecContract\n\n"
         "## Public headers\n- Neutrino/Expr.h\n", ["GenViewsSpec.cpp"],
         "manifest.header_incomplete"),
        # P2 (): an ABSENT `## Public headers` section is a failure, not a silent empty.
        ("no_headers", "## Sources owned\n- Foo.cpp\n\n## Shared leaf dependencies\n- NeutrinoSpecContract\n",
         ["Foo.cpp"], "manifest.no_headers"),
    ]
    fails = []
    for label, md, srcs, want in probes:
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "CMakeLists.txt"), "w").write(cmake)
            open(os.path.join(d, "EXTRACTION.md"), "w").write(md)
            for s in srcs:
                open(os.path.join(d, s), "w").write("")
            got = check(d)
            if want is None and got:
                fails.append(f"probe '{label}' should pass but got {got}")
            if want is not None and not any(want in r for r in got):
                fails.append(f"probe '{label}' should fail with [{want}] but got {got}")
    # missing-manifest probe (no EXTRACTION.md).
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "CMakeLists.txt"), "w").write(cmake)
        if not any("manifest.missing" in r for r in check(d)):
            fails.append("probe 'manifest_missing' should fail with [manifest.missing]")
    #  review P2: a Neutrino leaf added via a SEPARATE target_link_libraries (not LINK_LIBS) must be
    # folded into the CMake link set — so a manifest declaring only NeutrinoSpecContract leaf_mismatches
    # (an out-of-band forbidden dep can't stay invisible while the manifest reads "honest").
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "CMakeLists.txt"), "w").write(
            cmake + "target_link_libraries(NeutrinoFoo PRIVATE NeutrinoAnalysis)\n")
        open(os.path.join(d, "EXTRACTION.md"), "w").write(valid_md)
        open(os.path.join(d, "Foo.cpp"), "w").write("")
        if not any("manifest.leaf_mismatch" in r for r in check(d)):
            fails.append("probe 'leaf_mismatch_tll' should fail with [manifest.leaf_mismatch]")

    # Retained-core component topology: model, adapter, conditional source, and
    # direct smoke remain distinct and exact.
    component_cmake = """add_mlir_library(NeutrinoFooSpec
  Foo.cpp
  LINK_LIBS PUBLIC
  NeutrinoSpecContract
)
add_mlir_library(NeutrinoFooCore
  Adapter.cpp
  LINK_LIBS PUBLIC
  NeutrinoAnalysis
  NeutrinoFooSpec
)
if(NOT NEUTRINO_CORE_ONLY)
  target_sources(NeutrinoFooCore PRIVATE Conditional.cpp)
endif()
add_executable(foo-smoke FooSmoke.cpp)
target_link_libraries(foo-smoke PRIVATE NeutrinoFooSpec)
"""
    component_md = """## Sources owned
- Foo.cpp
- Adapter.cpp
- Conditional.cpp
- FooSmoke.cpp

## Shared leaf dependencies
- NeutrinoAnalysis
- NeutrinoSpecContract

## Public headers
- Neutrino/Expr.h
- Neutrino/GenSpec.h

## Components
- NeutrinoFooSpec
- NeutrinoFooCore

## Component NeutrinoFooSpec sources owned
- Foo.cpp
- FooSmoke.cpp

## Component NeutrinoFooSpec dependencies
- NeutrinoSpecContract

## Component NeutrinoFooSpec public headers
- Neutrino/Expr.h

## Component NeutrinoFooSpec integration headers
- none

## Component NeutrinoFooCore sources owned
- Adapter.cpp
- Conditional.cpp

## Component NeutrinoFooCore dependencies
- NeutrinoAnalysis
- NeutrinoFooSpec

## Component NeutrinoFooCore public headers
- Neutrino/GenSpec.h

## Component NeutrinoFooCore integration headers
- Neutrino/Validate.h
"""

    def component_probe(label, manifest_text, cmake_text, want=None):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "CMakeLists.txt"), "w").write(cmake_text)
            open(os.path.join(d, "EXTRACTION.md"), "w").write(manifest_text)
            for source in ("Foo.cpp", "Adapter.cpp", "Conditional.cpp",
                           "FooSmoke.cpp"):
                open(os.path.join(d, source), "w").write("")
            got = check(d)
            if want is None and got:
                fails.append(
                    f"probe '{label}' should pass but got {got}")
            if want is not None and not any(want in reason for reason in got):
                fails.append(
                    f"probe '{label}' should fail with [{want}] but got {got}")

    component_probe("component_valid", component_md, component_cmake)
    component_probe(
        "component_source_undeclared",
        component_md.replace(
            "## Component NeutrinoFooCore sources owned\n"
            "- Adapter.cpp\n- Conditional.cpp",
            "## Component NeutrinoFooCore sources owned\n"
            "- Conditional.cpp"),
        component_cmake,
        "manifest.component_source_undeclared")
    component_probe(
        "component_conditional_source_dropped",
        component_md,
        component_cmake.replace(
            "  target_sources(NeutrinoFooCore PRIVATE Conditional.cpp)\n",
            ""),
        "manifest.component_source_not_built")
    component_probe(
        "component_link_mismatch",
        component_md.replace(
            "## Component NeutrinoFooCore dependencies\n"
            "- NeutrinoAnalysis\n- NeutrinoFooSpec",
            "## Component NeutrinoFooCore dependencies\n"
            "- NeutrinoBogus\n- NeutrinoFooSpec"),
        component_cmake,
        "manifest.component_link_mismatch")
    #  X2 / : root-level spec-renderer/producer probe — any Gen*Spec.cpp in root lib/ is
    # flagged; a leaf's own Gen*Spec.cpp (in a subdir) is not.
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "GenSpec.cpp"), "w").write("")       # producer in root — MUST flag
        open(os.path.join(d, "GenFooSpec.cpp"), "w").write("")    # escaped renderer — MUST flag
        os.makedirs(os.path.join(d, "leaf"))
        open(os.path.join(d, "leaf", "GenBarSpec.cpp"), "w").write("")  # a leaf renderer — not root, OK
        bad = root_spec_renderers(d)
        if bad != ["GenFooSpec.cpp", "GenSpec.cpp"]:
            fails.append("probe 'root_spec_renderer' should flag exactly ['GenFooSpec.cpp', "
                         f"'GenSpec.cpp'], got {bad}")
    # : root-level emit adapter probe — any root Gen*.cpp belongs in lib/targets/ now.
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "GenViews.cpp"), "w").write("")
        open(os.path.join(d, "GenCapabilityModel.cpp"), "w").write("")
        bad = root_emit_adapters(d)
        if bad != ["GenCapabilityModel.cpp", "GenViews.cpp"]:
            fails.append("probe 'root_emit_adapter' should flag root Gen*.cpp adapters, got "
                         f"{bad}")
    # : even inside entry-layer folders, target entries must use *Target.cpp names rather than
    # ambiguous Gen*.cpp names.
    with tempfile.TemporaryDirectory() as d:
        fake_repo = os.path.join(d, "repo")
        os.makedirs(os.path.join(fake_repo, "lib", "emit"))
        os.makedirs(os.path.join(fake_repo, "lib", "targets"))
        open(os.path.join(fake_repo, "lib", "emit", "GenFoo.cpp"), "w").write("")
        open(os.path.join(fake_repo, "lib", "targets", "GenBar.cpp"), "w").write("")
        old_repo = REPO
        try:
            globals()["REPO"] = fake_repo
            bad = ambiguous_target_entries()
        finally:
            globals()["REPO"] = old_repo
        if bad != ["lib/emit/GenFoo.cpp", "lib/targets/GenBar.cpp"]:
            fails.append("probe 'ambiguous_target_entry' should flag lib/emit/Gen*.cpp and "
                         f"lib/targets/Gen*.cpp entries, got {bad}")
    # : explicit duplicate inventory probe — a stale root copy with the same basename as an extracted
    # leaf-owned source must fail, while unrelated root sources and leaf-only sources do not.
    dup_reasons = _root_leaf_duplicate_reasons(
        ["GenSpec.cpp", "GenViewsSpec.cpp", "GenCoverageSpec.cpp", "Unrelated.cpp"],
        {
            "GenViewsSpec.cpp": {"lib/views/GenViewsSpec.cpp"},
            "GenCoverageSpec.cpp": {"lib/policy/coverage/GenCoverageSpec.cpp"},
            "GenSlotSpec.cpp": {"lib/slots/GenSlotSpec.cpp"},
        },
    )
    if not any("GenViewsSpec.cpp" in r and "manifest.root_leaf_duplicate_source" in r for r in dup_reasons):
        fails.append("probe 'duplicate_root_leaf_views' should fail with "
                     "[manifest.root_leaf_duplicate_source]")
    if not any("GenCoverageSpec.cpp" in r and "manifest.root_leaf_duplicate_source" in r for r in dup_reasons):
        fails.append("probe 'duplicate_root_leaf_coverage' should fail with "
                     "[manifest.root_leaf_duplicate_source]")
    if any("GenSpec.cpp" in r or "Unrelated.cpp" in r or "GenSlotSpec.cpp" in r for r in dup_reasons):
        fails.append(f"probe 'duplicate_root_leaf_source' flagged unrelated/non-root sources: {dup_reasons}")
    if fails:
        print("extraction-manifest SELFTEST FAILED:", file=sys.stderr)
        for f in fails:
            print(f"    {f}", file=sys.stderr)
        return 1
    print("extraction-manifest selftest PASS (real tree clean; undeclared/absent source, a source dropped "
          "from CMake, a leaf mismatch — via LINK_LIBS AND via a separate target_link_libraries — an "
          "absent header, an OMITTED unit-owned header, a missing `## Public headers` section, a missing "
          "manifest, a root-lib spec renderer, a root-lib emit adapter, an ambiguous Gen*.cpp target "
          "entry under lib/emit or lib/targets, stale root duplicates, an undeclared component source, "
          "a dropped conditional source, and a component-link mismatch all fail closed)")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else run())
