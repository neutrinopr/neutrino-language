#!/usr/bin/env python3
"""Renderer include-boundary lock (M5 R4, ).

Output-side extractability lock — NOT the physical renderer split (that stays
speculative for M5). This generalizes the existing `View.h`-free / `ProcedureView`
anti-backslide checks (self-test `[89]`) from a blocklist into a POSITIVE include
allowlist for renderer translation units: a renderer may consume the
capability-spec contract + standard library, but must not reach back into
`ProcedureView` or kernel/frontend/analysis internals to re-derive semantics
outside the compiled contract. See `architecture/repo-boundary-map.md` (R1,
neutrino-) for the boundary this enforces.

The set of renderer TUs is DISCOVERED structurally (same rule as `[89]`), so a new
backend joins the lock with no edit here:
  - `lib/**/Gen*Spec.cpp` — the spec-JSON renderers (postgres / solidity /
    views / **slot**), which consume ONLY the capability-spec JSON.

`SlotTarget.cpp` is the slot registry ENTRY (it emits + re-parses the spec, then calls
`GenSlotSpec.cpp`), NOT a renderer TU — so, like `ViewsTarget.cpp`, it is not scanned.

ALLOWED direct `#include`s (per renderer TU):
  - the TU's OWN header (`Neutrino/<Base>.h`) — the renderer-local contract
    serializer/adapter;
  - the capability-spec contract + View.h-free shared adapters:
      Neutrino/Expr.h       — the typed expression-AST contract ()
      Neutrino/ValueModel.h — the  value-model contract
      Neutrino/Lifecycle.h  — the canonical LifecycleModel contract ()
      Neutrino/StrCase.h    — a View.h-free string adapter
      Neutrino/Manifest.h   — the output-manifest writer (an output adapter)
      Neutrino/SqlEmitter.h — the structured target-text emitter ()
      Neutrino/JsonUtil.h   — leaf JSON-escape + sha256 primitives ()
  - any `llvm/...` support header;
  - any C++ standard-library header (`<...>` with no path).

FORBIDDEN (anything else), e.g.: `Neutrino/View.h` (ProcedureView),
`Neutrino/Analysis.h` (the ProcedureView view-analyses, which pull `View.h`),
`GenSpec.h` (the spec producer / `viewOf`), `Frontend.h`/`Lexer.h`/`ParseUtil.h`
(parser), `NeutrinoDialect.h`/`mlir/...` (kernel IR), `SourceLoad.h`/`Validate.h`.

No exceptions: the former `SlotTarget.cpp` `Analysis.h` allowance was retired by the
slot -> spec-JSON migration (). `GenSlotSpec.cpp` now consumes only the
capability-spec contract (it reconstructs the lifecycle via
`lifecycleModelFromSpec`, Lifecycle.h), so slot is under the SAME strict allowlist
as the other spec-JSON renderers.

Usage:
  check_renderer_includes.py            # scan the repo's renderer TUs (default)
  check_renderer_includes.py --file F   # check one file F (for the negative test)
Exit 0 ok / 1 violation / 2 usage.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import generated_artifacts

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD_DIR = ""

# Capability-spec contract + View.h-free shared adapters every renderer may use.
CONTRACT_HEADERS = {
    "Neutrino/Expr.h",
    "Neutrino/ValueModel.h",
    "Neutrino/Lifecycle.h",
    "Neutrino/StrCase.h",
    "Neutrino/Manifest.h",
    "Neutrino/SqlEmitter.h",  # structured target-text emitter (), View.h-free
    "Neutrino/CodeText.h",    # language-neutral structured code emitter leaf (/), View.h-free
    "Neutrino/JsonUtil.h",    # leaf JSON-escape + sha256 primitives (), View.h-free
    "Neutrino/Attestation.h", # the attestation-policy leaf contract (), View.h-free
    "Neutrino/CoordinationPlan.h", # the normalized coordination plan (), View.h-free
    "Neutrino/BackendProjection.h", # verified shared backend projection contract, View.h-free
    "Neutrino/BackendProjectionDriver.h", # target-neutral finalized projection traversal seam
    "Neutrino/CoordinationEnvelope.h", # the  execution-claim/coordination-identity digest contract, View.h-free
    "Neutrino/SolidityEmit.h", # shared Solidity type/escape/operand helpers (), View.h-free
    "Neutrino/TestRealization.h", # the View.h-free folded-scenario companion ()
    "Neutrino/RecipeModule.h", # target-neutral generated recipe runtime ()
    "Neutrino/RecipeProviderRegistry.h", # target-neutral provider registry ()
    "Neutrino/RecipeRuntime.h", # target-neutral recipe runtime interface (), View.h-free
    "Neutrino/RecipeSessionStore.h", # target-neutral shared emit-side recipe session store ( R3), View.h-free
}

# Same-leaf INTERNAL seam headers a split leaf's TUs may include (not the public interface): the header
# is itself checked View.h-/kernel-free (SEAM_HEADERS below), and only declares functions over the
# capability-spec contract. : the PostgreSQL leaf split by responsibility.
INTERNAL_SEAM_HEADERS = {
    "PostgresSpecInternal.h",
    "SolidityTargetAdapter.h",
    "SolidityTargetValidation.h",
    "SolidityRenderer.h",
    "SolidityRecipeProvider.h",
    "PostgresModel.h",  #  PR2: the PostgreSQL leaf's typed legalization model seam
    "PostgresRecipeProvider.h",  #  R4d: the roled from-spec provider seam ( provider/)
}

INCLUDE_RE = re.compile(r'^\s*#\s*include\s+(?:"([^"]+)"|<([^>]+)>)')

# The NeutrinoSpecContract leaf's PUBLIC interface headers (). These must
# stay View.h-/kernel-free at the HEADER level (not just in the .cpp): a bare
# `#include "Neutrino/View.h"` in one of these compiles the leaf fine, so the
# link-smoke can't catch it — this source check does. Keep in sync with the leaf
# sources in lib/CMakeLists.txt (NeutrinoSpecContract).
LEAF_HEADERS = (
    "include/Neutrino/Lifecycle.h",
    "include/Neutrino/ValueModel.h",
    "include/Neutrino/JsonUtil.h",
    "include/Neutrino/Expr.h",
    "include/Neutrino/CoordinationPlan.h",
    "include/Neutrino/BackendProjection.h",
)

# Headers the leaf's interface must never reach for: ProcedureView and kernel IR.
LEAF_FORBIDDEN = (
    "Neutrino/View.h",
    "Neutrino/NeutrinoDialect.h",
    "Neutrino/NeutrinoOps.h",
)

# ---  D7 (): the backend/policy MODULE-composition gate ---------------------------------
# The lib/ subprojects () carve per-backend renderers and per-policy model targets out of the
# NeutrinoEmit monolith (-), each in its own lib/**/CMakeLists.txt linking ONLY the
# NeutrinoSpecContract leaf (). A "leaf-only module" is exactly such a target: its `LINK_LIBS
# PUBLIC` is the leaf alone. Their sources MUST all be migrated capability-spec renderers
# (Gen*Spec.cpp) or an explicitly-named non-renderer support TU below — so the split cannot merely MOVE
# a legacy/naive hand-built emitter into a smaller library (the  acceptance: no anonymous catch-all
# legacy emit path hidden inside the new backend/policy targets). Discovered structurally across every
# lib/**/CMakeLists.txt, so D2/D4's future targets (solidity/slot) join with no edit here.
LIB_CMAKE = "lib/**/CMakeLists.txt"
LEAF_LIB = "NeutrinoSpecContract"
# The bottom-of-the-graph leaves a backend/policy renderer module may link: the frozen capability-spec
# contract, and the language-neutral code-emitter substrate (NeutrinoCodeText, /). A leaf-only
# module links ONLY these (and, being a spec renderer, the contract leaf among them) — so a module that
# also links NeutrinoCodeText (, the Solidity backend) still qualifies and stays under the
# composition gate rather than falling out of it.
BOTTOM_LEAVES = {LEAF_LIB, "NeutrinoCodeText", "NeutrinoRecipe"}


def all_lib_cmake_text() -> str | None:
    """The concatenated text of every lib/**/CMakeLists.txt (the subproject layout, ), so the
    module-composition gate discovers targets wherever their local CMakeLists declares them."""
    files = sorted(glob.glob(os.path.join(REPO, "lib", "**", "CMakeLists.txt"), recursive=True))
    if not files:
        return None
    return "\n".join(open(f, encoding="utf-8", errors="replace").read() for f in files)
# Non-Gen*Spec.cpp TUs allowed inside a leaf-only module — each an explicit,
# narrowly-scoped support emitter (NOT a legacy backend). Basenames in this set
# are intentionally valid across backend module locations.
BACKEND_MODULE_SUPPORT_ALLOWED = {
    "SqlEmitter.cpp",
    # : the Solidity backend split by concern — the Foundry-harness renderer, the reviewed
    # acceptance-guard emitter, and the shared type/escape/operand helpers (all View.h-free support TUs
    # alongside the GenSoliditySpec.cpp coordination renderer).
    "GenSolidityTest.cpp",
    "GenSolidityQuorumGuard.cpp",
    "SolidityEmit.cpp",
    # : the typed Solidity legalization + printer (GenSoliditySpec.cpp is now the thin public entry
    # that forwards to it, mirroring the  PostgreSQL split). View.h-free; the codetext/framing pins
    # moved onto it are asserted in the selftest below.
    "SolidityTargetValidation.cpp",
    "SolidityTargetAdapter.cpp",
    "SolidityRenderer.cpp",
    "SolidityRecipeProvider.cpp",
    # : the PostgreSQL leaf split by responsibility — decode primitives, the procedure/quorum-schema
    # renderer, and the reconciliation/db-test harness (all View.h-free, alongside the thin
    # GenPostgresSpec.cpp public entry; their ProcedureView-free property + moved structural pins are
    # asserted in the selftest below).
    "PostgresSpecModel.cpp",
    "PostgresModel.cpp",
    #  R4d ( provider/): the roled from-spec recipe provider — the public
    # ABI dispatches to it; View.h-free support TU alongside GenPostgresSpec.cpp.
    "PostgresRecipeProvider.cpp",
    "PostgresDbTest.cpp",
    # : the below-waist raw PL/pgSQL text authority (the sole sql::Stmt::line author + the Seam
    # capability) and the StringRef-only SQL-syntax leaf (escaper/quoter/type map). Syntax-only,
    # model-free support TUs — the  gate proves they reach no model/spec surface.
    "PgSqlText.cpp",
    "PgSqlSyntax.cpp",
}

# Public-core support files are authorized by exact repository path. They must
# never widen the basename allowlist used by backend modules.
EXACT_MODULE_SUPPORT_ALLOWED = {
    "lib/emit/TargetCatalog.cpp",
    "lib/security/SecurityAdmission.cpp",
}

# Same-leaf internal seam headers (INTERNAL_SEAM_HEADERS) checked to stay View.h-/kernel-free, like the
# leaf interface headers — a split leaf's TUs include them, so a bare View.h there would escape both the
# link-smoke and the renderer allowlist.
SEAM_HEADERS = (
    "lib/backends/postgres/leaf/PostgresSpecInternal.h",
    "lib/backends/solidity/provider/SolidityTargetAdapter.h",
    "lib/backends/solidity/provider/SolidityTargetValidation.h",
    "lib/backends/solidity/provider/SolidityRenderer.h",
    "lib/backends/solidity/provider/SolidityRecipeProvider.h",
    "lib/backends/postgres/model/PostgresModel.h",
    "lib/backends/postgres/provider/PostgresRecipeProvider.h",
)


def cmake_leaf_only_modules(text: str) -> dict:
    """Parse add_mlir_library() blocks in lib/CMakeLists.txt; return {name: [sources]} for the
    backend/policy modules — those whose LINK_LIBS PUBLIC is a SUBSET of the bottom leaves and includes
    the contract leaf (a spec renderer). The leaf itself (links MLIRSupport, not the contract leaf) and
    NeutrinoDialect/NeutrinoEmit (link MLIRIR / NeutrinoAnalysis / …) are correctly excluded; a module
    that ALSO links NeutrinoCodeText () still qualifies, so it can't fall out of the gate."""
    out = {}
    for m in re.finditer(r'add_mlir_library\(\s*(\w+)(.*?)\n\)', text, re.S):
        name, body = m.group(1), m.group(2)
        # Drop CMake comments so stray words never pollute the token scan.
        body = "\n".join(ln.split("#", 1)[0] for ln in body.splitlines())
        link_m = re.search(r'LINK_LIBS\s+PUBLIC(.*)', body, re.S)
        links = re.findall(r'\b([A-Z]\w+)\b', link_m.group(1)) if link_m else []
        links_set = set(links)
        if LEAF_LIB not in links_set or not links_set <= BOTTOM_LEAVES:
            continue
        head = body[:link_m.start()] if link_m else body
        head = re.split(r'\bPARTIAL_SOURCES_INTENDED\b|\bDEPENDS\b', head)[0]
        out[name] = re.findall(r'([A-Za-z0-9_./-]+\.cpp)', head)
    return out


def backend_module_violations_in(
    text: str, source_dir: str = "", require_minimum: bool = True
) -> list[str]:
    out = []
    modules = cmake_leaf_only_modules(text)
    if require_minimum and len(modules) < 3:
        out.append(f"expected >=3 leaf-only backend/policy modules in {LIB_CMAKE}, found "
                   f"{sorted(modules)} — parse drift, or the  split regressed?")
    for name in sorted(modules):
        for src in modules[name]:
            base = os.path.basename(src)
            if base.startswith("Gen") and base.endswith("Spec.cpp"):
                continue  # a migrated capability-spec renderer (swept by the include-lock)
            source_path = f"{source_dir}/{src}" if source_dir else src
            if source_path in EXACT_MODULE_SUPPORT_ALLOWED:
                continue  # exact public-core support path; never a backend basename exemption
            if base in BACKEND_MODULE_SUPPORT_ALLOWED:
                continue  # an explicit, allowlisted non-renderer support emitter
            out.append(f"{LIB_CMAKE}: leaf-only module {name} contains non-migrated source '{src}' — a "
                       "backend/policy module may hold only capability-spec renderers (Gen*Spec.cpp) or "
                       "an allowlisted support emitter; a legacy/naive emitter must not hide here ()")
    return out


def all_backend_module_violations() -> tuple[list[str], int]:
    out = []
    module_count = 0
    for cmake_path in sorted(
        glob.glob(os.path.join(REPO, "lib", "**", "CMakeLists.txt"), recursive=True)
    ):
        rel_dir = os.path.relpath(os.path.dirname(cmake_path), REPO).replace(os.sep, "/")
        text = open(cmake_path, encoding="utf-8", errors="replace").read()
        modules = cmake_leaf_only_modules(text)
        module_count += len(modules)
        # The global non-vacuity floor is checked after all individual CMake
        # files have retained their source-directory identity.
        out += backend_module_violations_in(
            text, rel_dir, require_minimum=False
        )
    if module_count < 3:
        out.append(
            f"expected >=3 leaf-only backend/policy modules in {LIB_CMAKE}, found "
            f"{module_count} — parse drift, or the  split regressed?"
        )
    return out, module_count


def leaf_header_violations(path: str) -> list[str]:
    """Forbidden `#include`s in a NeutrinoSpecContract leaf public header."""
    out = []
    base = os.path.basename(path)
    for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), start=1):
        m = INCLUDE_RE.match(line)
        if not m or m.group(1) is None:
            continue
        inc = m.group(1)
        if inc in LEAF_FORBIDDEN:
            out.append(f"{base}:{i}: leaf interface header includes forbidden "
                       f"\"{inc}\" — NeutrinoSpecContract headers must stay "
                       f"View.h-/kernel-free ()")
    return out


def renderer_tus() -> list[str]:
    # The spec-JSON renderer TUs: `lib/**/Gen*Spec.cpp`. RECURSIVE since :
    # the migrated renderers moved into subproject dirs (lib/backends/postgres/
    # GenPostgresSpec.cpp, lib/security/GenSecuritySpec.cpp, …).
    # SlotTarget.cpp / ViewsTarget.cpp are registry ENTRIES, not renderer TUs, so
    # they are not scanned.
    return sorted(glob.glob(os.path.join(REPO, "lib", "**", "Gen*Spec.cpp"),
                            recursive=True))


def allowed_for(tu: str) -> set[str]:
    base = os.path.basename(tu)
    own = "Neutrino/" + base[:-4] + ".h"  # GenViewsSpec.cpp -> Neutrino/GenViewsSpec.h
    return set(CONTRACT_HEADERS) | INTERNAL_SEAM_HEADERS | {own}


def violations_in(tu: str) -> list[str]:
    allowed = allowed_for(tu)
    out = []
    for i, line in enumerate(open(tu), start=1):
        m = INCLUDE_RE.match(line)
        if not m:
            continue
        quoted, angled = m.group(1), m.group(2)
        if angled is not None:
            # <...>: C++ stdlib (no path) or an angled llvm header — both allowed.
            if "/" not in angled or angled.startswith("llvm/"):
                continue
            out.append(f"{os.path.basename(tu)}:{i}: forbidden system include <{angled}>")
            continue
        inc = quoted
        if inc.startswith("llvm/"):
            continue
        if inc in allowed:
            continue
        out.append(f"{os.path.basename(tu)}:{i}: forbidden include \"{inc}\" — "
                   f"renderers must consume only the capability-spec contract "
                   f"(not ProcedureView / kernel / parser internals); see ")
    return out


# Structural-renderer carve-out (renderer_include_lock.sh): these read spec fields / counts /
# category-participant-topology metadata, never a compute expression, so they do NOT rebuild an AST
# via exprFromJson (GenSlotSpec , GenViewsSpec , GenCapabilityModelSpec ,
# GenSecuritySpec , GenCoverageSpec ).
_EXPR_CARVE_OUT = frozenset({
    "GenViewsSpec", "GenSlotSpec", "GenCapabilityModelSpec", "GenSecuritySpec", "GenCoverageSpec",
    # : the oracle observer renders from the attestation POLICY + binding, not compute expressions.
    "GenOracleObserverSpec",
    # : GenPostgresSpec.cpp is now the thin PUBLIC ENTRY (it forwards to the split render TUs); the
    # compute-AST rebuild moved to PostgresModel.cpp, pinned by an explicit exprFromJson _need below.
    "GenPostgresSpec",
    # /: GenSoliditySpec.cpp is the thin PUBLIC ENTRY forwarding to the
    # exact recipe-provider, target-validation/adapter, and renderer surfaces.
    "GenSoliditySpec",
})


def selftest() -> int:
    """Structural anti-backslide sweep over the migrated spec renderers (/), plus a negative
    that proves the include allowlist bites. Ported from the retired renderer_include_lock.sh ( /
     S5d); registered as the `renderer-include-lock` CTest test. Source-only (no build). Non-
    vacuous: the sweep DISCOVERS renderers via lib/Gen*Spec.cpp and refuses below the known floor."""
    renderers = renderer_tus()
    fails = []
    if len(renderers) < 3:
        fails.append(f"expected >=3 migrated renderers discovered, got {len(renderers)} "
                     "(glob lib/Gen*Spec.cpp — wrong dir / renamed files?)")

    for f in renderers:
        base = os.path.basename(f)
        src = open(f, encoding="utf-8", errors="replace").read()
        if re.search(r'#include\s+.*Neutrino/View\.h', src):
            fails.append(f"migrated renderer {base} includes View.h (ProcedureView backslide)")
        if "parseExpr(" in src:
            fails.append(f"migrated renderer {base} re-parses expression text (parseExpr backslide)")
        # Every VALUE-LOWERING spec renderer rebuilds compute ASTs via exprFromJson.
        if base[:-4] not in _EXPR_CARVE_OUT and "exprFromJson" not in src:
            fails.append(f"{base} should rebuild the compute AST via exprFromJson")

    # Per-renderer structural pins migrated from run_cpp_tests.sh [81]/[83]/[96] ( S5i): the
    # backend spec renderers re-type the ingested AST (typeExpr, ) and single-source their test
    # harness from the SAME spec as the artifact (no ProcedureView harness); the PG procedure renderer
    # builds against the structured SqlEmitter boundary (sql::Document + sql::print) with the SQL
    # framing owned by the printer, not hand-assembled in the renderer. (The byte-golden proof that
    # these render identically to the committed fixtures lives in the lit backend goldens.)
    def _read(rel):
        p = (generated_artifacts.resolve(rel, BUILD_DIR)
             if generated_artifacts.is_migrated(rel)
             else os.path.join(REPO, rel))
        return open(p, encoding="utf-8", errors="replace").read() if os.path.isfile(p) else None

    def _need(rel, token, why, *, regex=False):
        s = _read(rel)
        if s is None:
            fails.append(f"{rel} missing ({why})")
            return
        present = bool(re.search(token, s)) if regex else (token in s)
        if not present:
            fails.append(f"{rel} must contain `{token}` ({why})")

    def _forbid(rel, token, why, *, regex=False):
        s = _read(rel) or ""
        if (re.search(token, s) if regex else token in s):
            fails.append(f"{rel} must NOT contain `{token}` ({why})")

    # [83] Solidity renderer: spec-sourced Foundry harness (its own TU since ). The harness
    # single-sources its structure from the SAME spec as the contract. Since  the renderer must NOT
    # re-type ingested ASTs — the structured expression is typed ONCE upstream (IR-verify on the
    # authoring path, planFromSpec on --from-spec), so a renderer that re-typed would duplicate the
    # inference the issue removed.
    for tu in (
        "lib/backends/solidity/provider/SolidityTargetValidation.cpp",
        "lib/backends/solidity/provider/SolidityTargetAdapter.cpp",
        "lib/backends/solidity/provider/SolidityRenderer.cpp",
        "lib/backends/solidity/provider/SolidityRecipeProvider.cpp",
    ):
        _forbid(tu, r"\btypeExpr\(|\btypeGuard\(",
                "split Solidity ownership surfaces must not re-type; typing is once, upstream ()",
                regex=True)
    _need("lib/backends/solidity/harness/GenSolidityTest.cpp", "generateSolidityTestFromSpec", "Foundry harness spec-sourced, ")
    # [81] PostgreSQL renderer: spec-sourced db-test harness; the ProcedureView harness is gone.
    # Since  the leaf is split by responsibility, and  relocates the split into role subdirs:
    # the procedure/quorum-schema renderer is model/PostgresModel.cpp, the reconciliation/db-test harness
    # harness/PostgresDbTest.cpp, the decode/spec seam provider/PostgresSpecModel.cpp; GenPostgresSpec.cpp
    # is the thin public entry. The pins follow the code to its new units. The render TUs must not
    # backslide to ProcedureView (the  acceptance: no new ProcedureView dependency).
    for tu in ("lib/backends/postgres/model/PostgresModel.cpp",
               "lib/backends/postgres/harness/PostgresDbTest.cpp",
               "lib/backends/postgres/provider/PostgresSpecModel.cpp"):
        _forbid(tu, r'#include\s+.*Neutrino/View\.h', "a split PG render TU must not include View.h", regex=True)
    _forbid("lib/backends/postgres/model/PostgresModel.cpp", r"\btypeExpr\(|\btypeGuard\(",
            "renderers must not re-type; typing is once, upstream ()", regex=True)
    _need("lib/backends/postgres/model/PostgresModel.cpp",
          "projection::BackendProjectionGraph",
          "lower typed target nodes from the verified projection")
    _need("lib/backends/postgres/harness/PostgresDbTest.cpp", "renderDbTest", "db-test harness spec-sourced")
    #  moved the registry ENTRY to lib/targets/PostgresTarget.cpp.
    _forbid("lib/targets/PostgresTarget.cpp", r"\bgeneratePostgresDbTest\b",
            "the ProcedureView-based harness must be gone (single-sourced onto the spec)", regex=True)
    # [96]/ C3: the raw sql::Document SqlEmitter boundary is RETIRED — the procedure renders solely
    # through the GENERATED printer. The model consumes the generated printer include and lowers each
    # typed node via generated_printer::render;  keeps the callable-header grammar in the typed
    # TableGen registry (model/PostgresTargetNodes.td), never hand-assembled in a TU.
    _need("lib/backends/postgres/model/PostgresModel.cpp", '#include "PostgresPrinterHandlers.inc"',
          "PG renderer consumes the generated printer (SqlEmitter retired,  C3)")
    _need("lib/backends/postgres/model/PostgresModel.cpp", "generated_printer::render(",
          "PG renderer renders each typed node via the generated printer")
    for frag in ("CREATE OR REPLACE FUNCTION", "RETURNS void", "LANGUAGE plpgsql"):
        _need("lib/backends/postgres/model/PostgresTargetNodes.td", frag,
              "the typed registry owns callable-header framing ()")
        for tu in ("lib/backends/postgres/model/PostgresModel.cpp",
                   "lib/backends/postgres/harness/PostgresDbTest.cpp"):
            _forbid(tu, frag, "the renderer must not hand-assemble the framing")
    _need("lib/backends/postgres/generated/PostgresPrinterHandlers.inc", "END IF;",
          "the generated printer owns IF/END IF block framing ( C3)")
    # [ review]/ C3: the conditional-effect () guard and the replay/attestation guards are
    # STRUCTURED typed nodes; the IF/END IF framing lives in the generated printer, never hand-assembled
    # in a render TU. Forbid the raw framing string literals in the model + harness.
    for tu in ("lib/backends/postgres/model/PostgresModel.cpp",
               "lib/backends/postgres/harness/PostgresDbTest.cpp"):
        _forbid(tu, '"IF ',
                "SQL IF framing must be a structured typed node, not a hand-assembled line")
        _forbid(tu, '"END IF;"',
                "SQL END IF; framing must be a structured typed node, not a hand-assembled line")

    # [] no-hand-framing gate extended to Solidity: the coordination + Foundry renderers describe
    # their STRUCTURE with the codetext block/line model () — the printer owns indentation + the
    # structural newlines — instead of hand-assembling indented strings. Delimiters stay caller-provided
    # (block("contract … {", "}")); the leaf statement/expression text stays verbatim in a line(). The
    # byte-golden proof that this renders identically to the committed fixtures lives in the lit Solidity
    # goldens.
    _need("include/Neutrino/CodeText.h", "class Document", "the structured code-emitter boundary exists")
    # Both Solidity renderers (the exact layout-only renderer and the Foundry
    # harness) describe framing with codetext nodes rendered by the printer.
    for tu in ("lib/backends/solidity/provider/SolidityRenderer.cpp",
               "lib/backends/solidity/harness/GenSolidityTest.cpp"):
        _need(tu, '#include "Neutrino/CodeText.h"', "Solidity renderer consumes the codetext boundary")
        _need(tu, "doc.print(", "Solidity renderer renders framing via the codetext printer")
    # SolidityTargetAdapter.cpp owns the single typed-node -> generated-printer
    # adapter; the renderer consumes that exact adapter.
    # construct — including the last, the contract CONTAINER — is a typed node
    # rendered by the generated printer, so the legalizer/printer frames via
    # `generated_printer::render(` rather than a handwritten `block(` call. The
    # Foundry harness (GenSolidityTest.cpp) still hand-frames its test scaffold with
    # codetext blocks.
    _need("lib/backends/solidity/provider/SolidityTargetAdapter.cpp",
          "generated_printer::render(",
          "Solidity target adapter frames every construct via the generated .td printer")
    _need("lib/backends/solidity/harness/GenSolidityTest.cpp", "block(",
          "Solidity Foundry-harness renderer describes structural framing as codetext blocks")
    for tu in ("lib/backends/solidity/provider/SolidityRenderer.cpp",
               "lib/backends/solidity/harness/GenSolidityTest.cpp"):
        # No new hand-assembled structural newlines: a string literal ending in `\\n` is the renderer
        # managing the structural newlines the codetext printer now owns. (The reviewed guard reference is
        # a verbatim R"(…)" raw string with real newlines in GenSolidityQuorumGuard.cpp — not a `\\n`
        # escape, and it is a support emitter not a renderer TU — so it is unaffected; the string ESCAPER
        # builds `\\"`/`\\\\`, never `\\n"`.)
        _forbid(tu, r'\\n"',
                "structural newlines are the codetext printer's — do not hand-assemble a string literal "
                "that ends in \\n (frame with block()/line() instead)", regex=True)

    # [] no-hand-framing gate extended to the oracle-JS observer renderer: the observer + aggregator
    # framing is codetext blocks/lines, which also CLOSES the  comment-injection class by
    # construction (the header comments are line() nodes, and codetext's line() rejects an embedded
    # newline, so an untrusted comment value can't break out into code position — structural safety, not
    # only safeIdent). Byte-golden proof: the committed test/ir/oracle observer goldens.
    _need("lib/backends/oracle/GenOracleObserverSpec.cpp", '#include "Neutrino/CodeText.h"',
          "oracle-JS renderer consumes the codetext boundary")
    _need("lib/backends/oracle/GenOracleObserverSpec.cpp", "doc.print(",
          "oracle-JS renderer renders framing via the codetext printer")
    _need("lib/backends/oracle/GenOracleObserverSpec.cpp", "block(",
          "oracle-JS renderer describes structural framing as codetext blocks")
    _forbid("lib/backends/oracle/GenOracleObserverSpec.cpp", r'\\n"',
            "structural newlines are the codetext printer's — no hand-assembled JS string literal ending "
            "in \\n (frame with block()/line(); this is also what closes the  comment-injection "
            "class by construction)", regex=True)

    # POSITIVE allowlist (): every renderer TU consumes only the capability-spec contract.
    for tu in renderers:
        fails += violations_in(tu)

    # LEAF interface headers () stay View.h-/kernel-free at the HEADER level — the link-smoke
    # can't see a bare unused include, so check the source. Non-vacuous: refuse if a leaf header is
    # missing (renamed / moved out of the leaf).
    for rel in LEAF_HEADERS:
        path = os.path.join(REPO, rel)
        if not os.path.isfile(path):
            fails.append(f"leaf interface header missing: {rel} (renamed / moved out of the leaf?)")
            continue
        fails += leaf_header_violations(path)

    # : a split leaf's INTERNAL seam header stays View.h-/kernel-free too (its TUs include it, so a
    # bare View.h there escapes both the link-smoke and the renderer allowlist). Reuse the leaf-header
    # forbidden-include check. Non-vacuous: refuse if the seam header is gone.
    for rel in SEAM_HEADERS:
        path = os.path.join(REPO, rel)
        if not os.path.isfile(path):
            fails.append(f"internal seam header missing: {rel} (renamed / moved?)")
            continue
        fails += leaf_header_violations(path)

    #  D7 (): the leaf-only backend/policy modules hold ONLY migrated Gen*Spec.cpp renderers
    # (or an allowlisted support TU) — the split cannot smuggle a legacy/naive emitter into a smaller
    # library. Non-vacuous: refuses if the config file is gone or <3 modules are discovered.
    cmake_src = all_lib_cmake_text()
    if cmake_src is None:
        fails.append(f"{LIB_CMAKE} missing (backend-module composition gate cannot run)")
        module_count = 0
    else:
        module_fails, module_count = all_backend_module_violations()
        fails += module_fails

    # NEGATIVE that BITES: a renderer with an injected View.h include is flagged by the allowlist.
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="renderer_selftest.")
    try:
        anchor = next((f for f in renderers if os.path.basename(f) == "GenViewsSpec.cpp"),
                      renderers[0] if renderers else None)
        if anchor:
            probe = os.path.join(tmp, os.path.basename(anchor))
            shutil.copy(anchor, probe)
            with open(probe, "a", encoding="utf-8") as fh:
                fh.write('#include "Neutrino/View.h"\n')
            if not violations_in(probe):
                fails.append("an injected View.h include was NOT flagged by the allowlist (fails open)")
        obsolete_probe = os.path.join(tmp, "GenSpec.cpp")
        with open(obsolete_probe, "w", encoding="utf-8") as fh:
            fh.write('#include "Neutrino/View.h"\n')
        if not violations_in(obsolete_probe):
            fails.append("an obsolete GenSpec.cpp renderer leaf was NOT flagged by the allowlist "
                         "(fails open)")
        # And that the leaf-header check bites on an injected View.h in a leaf interface header.
        leaf_probe = os.path.join(tmp, "Lifecycle.h")
        shutil.copy(os.path.join(REPO, "include", "Neutrino", "Lifecycle.h"), leaf_probe)
        with open(leaf_probe, "a", encoding="utf-8") as fh:
            fh.write('#include "Neutrino/View.h"\n')
        if not leaf_header_violations(leaf_probe):
            fails.append("an injected View.h include in a leaf header was NOT flagged (fails open)")
        # And that the backend-module gate bites when a legacy (non-Gen*Spec, non-allowlisted) source
        # is smuggled into a leaf-only module's block.
        if cmake_src is not None:
            security_cmake = open(
                os.path.join(REPO, "lib", "security", "CMakeLists.txt"),
                encoding="utf-8",
            ).read()
            injected = re.sub(r'(add_mlir_library\(\s*NeutrinoSecurityPolicy\n)',
                              r'\1  LegacyEmit.cpp\n', security_cmake, count=1)
            if injected != security_cmake and not backend_module_violations_in(
                injected, "lib/security", require_minimum=False
            ):
                fails.append("a legacy source injected into a leaf-only module was NOT flagged (fails open)")
            # And that a module linking MULTIPLE bottom leaves (NeutrinoBackendSolidity: contract leaf
            # + NeutrinoCodeText, ) STAYS under the composition gate — a legacy source smuggled
            # into it must still be caught (the fail-open path  review flagged).
            solidity_cmake = open(
                os.path.join(REPO, "lib", "backends", "solidity", "CMakeLists.txt"),
                encoding="utf-8",
            ).read()
            injected_sol = re.sub(r'(add_mlir_library\(\s*NeutrinoBackendSolidity\n)',
                                  r'\1  LegacyEmit.cpp\n', solidity_cmake, count=1)
            if injected_sol == solidity_cmake:
                fails.append("could not inject into NeutrinoBackendSolidity — the multi-leaf module "
                             "was not found (the composition gate would not cover it)")
            elif not any(
                "NeutrinoBackendSolidity" in v
                for v in backend_module_violations_in(
                    injected_sol,
                    "lib/backends/solidity",
                    require_minimum=False,
                )
            ):
                fails.append("a legacy source injected into the multi-leaf NeutrinoBackendSolidity module "
                             "was NOT flagged — a backend linking two bottom leaves fell out of the  gate")
            # The public-core admission helper is path-authorized, not
            # basename-authorized: the same filename under a backend must bite.
            injected_security_name = re.sub(
                r'(add_mlir_library\(\s*NeutrinoBackendSolidity\n)',
                r'\1  SecurityAdmission.cpp\n',
                solidity_cmake,
                count=1,
            )
            if injected_security_name == solidity_cmake:
                fails.append(
                    "could not inject SecurityAdmission.cpp into "
                    "NeutrinoBackendSolidity"
                )
            elif not any(
                "SecurityAdmission.cpp" in violation
                for violation in backend_module_violations_in(
                    injected_security_name,
                    "lib/backends/solidity",
                    require_minimum=False,
                )
            ):
                fails.append(
                    "a backend-path SecurityAdmission.cpp was NOT flagged — "
                    "the public-core exact-path exception widened by basename"
                )
            # The target-neutral catalog is likewise authorized only at its
            # retained-core path. A backend-local namesake must not inherit the
            # exception.
            injected_catalog_name = re.sub(
                r'(add_mlir_library\(\s*NeutrinoBackendSolidity\n)',
                r'\1  TargetCatalog.cpp\n',
                solidity_cmake,
                count=1,
            )
            if injected_catalog_name == solidity_cmake:
                fails.append(
                    "could not inject TargetCatalog.cpp into "
                    "NeutrinoBackendSolidity"
                )
            elif not any(
                "TargetCatalog.cpp" in violation
                for violation in backend_module_violations_in(
                    injected_catalog_name,
                    "lib/backends/solidity",
                    require_minimum=False,
                )
            ):
                fails.append(
                    "a backend-path TargetCatalog.cpp was NOT flagged — "
                    "the public-core exact-path exception widened by basename"
                )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        print("renderer-include-lock selftest FAILED:", file=sys.stderr)
        for f in fails:
            print("    FAIL: " + f, file=sys.stderr)
        return 1
    print(f"    PASS ({len(renderers)} migrated renderers swept: none include View.h/ProcedureView, "
          "none call parseExpr; value-lowering renderers rebuild ASTs via exprFromJson; the include "
          "allowlist () holds and bites on an injected View.h; per-renderer guards present; "
          f"{len(LEAF_HEADERS)} NeutrinoSpecContract leaf headers () are View.h-/kernel-free; "
          f"{module_count} leaf-only backend/policy modules () hold only migrated Gen*Spec renderers "
          "+ allowlisted support — no legacy emitter smuggled in)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="check a single renderer TU (negative test)")
    ap.add_argument("--build-dir")
    ap.add_argument("--selftest", action="store_true",
                    help="run the structural sweep + allowlist self-test (the renderer-include-lock gate)")
    args = ap.parse_args()
    global BUILD_DIR
    BUILD_DIR = args.build_dir or ""

    if args.selftest:
        return selftest()

    tus = [args.file] if args.file else renderer_tus()
    if not tus or (args.file and not os.path.isfile(args.file)):
        print("error: no renderer TUs found", file=sys.stderr)
        return 2

    problems = []
    for tu in tus:
        problems += violations_in(tu)
    if problems:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        return 1
    print(f"ok: {len(tus)} renderer TU(s) consume only the allowlisted "
          f"capability-spec contract / adapters / stdlib (include boundary locked, )")
    return 0


if __name__ == "__main__":
    sys.exit(main())
