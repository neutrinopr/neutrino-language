#ifndef NEUTRINO_DIAGNOSTIC_TAXONOMY_H
#define NEUTRINO_DIAGNOSTIC_TAXONOMY_H

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"

#include <string>

namespace neutrino {

// The SHARED failure taxonomy (M5 WP1c, ). It is the single source of truth
// for the stable, dotted diagnostic `code`s emitted across the toolchain — the
// kernel verifier, the frontend, scenario validation, the expression gate, the
// value model, the security pass, generation, and equivalence — and it is the
// vocabulary that target-profile legality diagnostics (later WPs) draw from
// too.
//
// Two properties the rest of the pipeline relies on:
//  - Every semantic diagnostic `code` comes from this table (no ad-hoc
//  strings);
//    a self-test asserts the codes the tools emit are registered here.
//  - Diagnostics are ROOT-CAUSE ORDERED: the first diagnostic is the primary
//    failure, cascades are subordinated. `rootCausePrecedence` supplies the
//    rank and `orderByRootCause` (Diagnostics.h) applies it.
//
// The compiler owns this table; it is emitted as deterministic JSON
// (`--diagnostic-taxonomy`, byte-matched against docs/diagnostic-taxonomy.json)
// and narrated in docs/language/DIAGNOSTIC_TAXONOMY.md — the same
// compiler-owned + drift tested pattern as the language metadata (, ADR
// D10).

// Which layer owns a code — the coarse category, also the dotted code prefix.
enum class DiagCategory {
  Frontend,       // source parse / structural (.neu -> IR)
  Kernel,         // the semantic kernel verifier (the IR/spec-level checks)
  Value,          // the typed value model (WP1a, )
  Expr,           // the compute-expression gate (WP1b, )
  Scenario,       // scenario document validation
  Security,       // the capability security pass
  Generate,       // backend generation / tooling
  Equivalence,    // cross-backend equivalence
  Classification, // the solidity-classification profile validator ()
  Spec,           // the canonical executable capability spec validator ()
  Profile,        // the target-profile validator (WP4, /)
  Legality,       // the fail-closed spec-legality gate (WP4, /)
  Realization,    // the test-realization companion validator (WP2, )
  View,           // the participant-view validator (M5, )
  Observation,    // the domain-observation-set corpus-extraction validator (S0,
                  // )
  Domain, // the L2 domain layer: versioned import resolution against the
          // cross-rail registry ()
};

// Which producer emits a code. The taxonomy is the single registry for BOTH the
// C++ toolchain and the stdlib validators that are part of it ( shipped its
// codes deferring to this table). `emitter` records provenance so a consumer
// can tell a compiler diagnostic from a validator one, and so each side can be
// enforced against the table by its own gate.
enum class DiagEmitter {
  Cpp,       // a C++ tool (neutrino-gen/-translate/-equiv/verifier)
  Validator, // a stdlib (Python) validator in scripts/
  // Emitted by BOTH a C++ tool and a stdlib validator — e.g. the spec-legality
  // gate, whose canonical Python implementation (check_spec_legality.py) is
  // mirrored in-process by neutrino-gen (WP6/); a parity test pins
  // agreement.
  Both,
};

// A code is `Active` if the toolchain emits it today; `Reserved` codes are
// named here so the kernel-rule follow-ups (state machines, compensation,
// reservations, evidence gates, ordering) and target profiles bind to a stable
// code before the rule that emits it lands — but they must not appear in
// emitted diagnostics yet.
enum class DiagStatus { Active, Reserved };

// Field order is chosen for readability of the constexpr table (code, then its
// classification, then the human summary), not for packing — this is a small
// compile-time-constant lookup table, so the analyzer's padding suggestion does
// not apply.
// NOLINTNEXTLINE(clang-analyzer-optin.performance.Padding)
struct TaxonomyEntry {
  llvm::StringRef code;    // e.g. "kernel.balance.unbalanced" (dotted, stable)
  DiagCategory category;   // owning layer
  DiagStatus status;       // Active | Reserved
  int precedence;          // root-cause rank; LOWER = more primary/fundamental
  llvm::StringRef summary; // one-line human description
  // Provenance. C++17 default member initializer: existing C++-emitter entries
  // omit it and default to Cpp; validator entries set Validator explicitly.
  DiagEmitter emitter = DiagEmitter::Cpp;
};

// The canonical table (source of truth), in precedence order.
llvm::ArrayRef<TaxonomyEntry> diagnosticTaxonomy();

// Machine-readable category / status names (stable, lowercase) for the JSON and
// for callers that key on them.
llvm::StringRef categoryName(DiagCategory c);
llvm::StringRef statusName(DiagStatus s);
llvm::StringRef emitterName(DiagEmitter e);

// True if `code` is in the taxonomy at all (Active or Reserved).
bool isRegisteredCode(llvm::StringRef code);
// True if `code` is Active (emittable today). The membership gate uses this.
bool isActiveCode(llvm::StringRef code);

// Root-cause rank for `code`: lower sorts earlier (more primary). An
// unregistered code sorts last (a large sentinel) so a stray code never masks a
// real root cause. Ties keep their original relative order (see
// orderByRootCause).
int rootCausePrecedence(llvm::StringRef code);

// Deterministic JSON (schemaVersion + the code table). Byte-stable: no gitSha /
// timestamp, so docs/diagnostic-taxonomy.json is regenerated + byte-matched.
std::string diagnosticTaxonomyJson();

// Early argv intercept (mirrors handleLanguageMetadataFlag):
// `--diagnostic-taxonomy` prints the JSON and returns true so the caller
// exits(0), before any cl parsing.
bool handleDiagnosticTaxonomyFlag(int argc, char **argv);

} // namespace neutrino

#endif // NEUTRINO_DIAGNOSTIC_TAXONOMY_H
