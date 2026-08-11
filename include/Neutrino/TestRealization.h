#ifndef NEUTRINO_TEST_REALIZATION_H
#define NEUTRINO_TEST_REALIZATION_H

#include "Neutrino/Scenario.h"

#include <map>
#include <string>
#include <vector>

namespace neutrino {

// The TestRealization DATA is View.h-free: it holds only concrete values folded
// from a spec + scenario (ScenarioInput comes from Scenario.h), so a migrated
// View.h-free renderer (e.g. GenPostgresSpec.cpp, ) can consume the
// realized cases without pulling in ProcedureView. Only the
// realize()/emitTestRealization() entry points below take a ProcedureView, so
// it is forward-declared here and each *caller* of those includes View.h
// directly.
struct ProcedureView;
struct CoordinationPlan;

// The test-realization artifact (M5 WP2, ): the concrete backend test cases
// folded ONCE from a capability spec + a scenario, kept as data OUTSIDE the
// capability hash scope.
//
// The capability (its spec + capabilityHash) is scenario-independent. What each
// backend previously re-derived from the raw Scenario — the concrete input
// values, the computed expectations, the expected event chain, the net ledger
// deltas, the proven invariants — is folded here a single time and consumed by
// every renderer, so:
//   - changing only a scenario/test never changes the capabilityHash;
//   - the same fold feeds Solidity/Foundry AND PostgreSQL (no re-derivation);
//   - the cases are a machine-readable companion artifact
//   (test-realization.json)
//     that references the capability it realizes rather than being hashed into
//     it.
struct TestRealization {
  std::string scenario;  // the scenario name
  std::string procedure; // the procedure it realizes
  // The capability this realizes — a link/reference, NOT this file's identity.
  std::string capabilityHash;

  // The concrete cases, resolved against the view (scenario order preserved via
  // std::map for determinism).
  std::map<std::string, ScenarioInput> inputs; // input -> concrete value
  std::map<std::string, long long> computed;   // compute -> expected value
  std::vector<std::string> events;             // expected event chain
  std::map<std::string, long long> ledger;     // ledger -> expected net delta
  std::vector<std::string> invariants;         // invariants proven by the case
};

// Fold `scenario` against `view` into the concrete test cases, ONCE. This is
// the single place scenario data is realized: it validates the scenario's event
// chain against the IR-derived choreography (previously done inside the
// Solidity renderer), links the capabilityHash, and carries the cases the
// backends need. Throws ScenarioError / std::runtime_error on an inconsistent
// scenario.
TestRealization realize(const ProcedureView &view, const Scenario &scenario,
                        const CoordinationPlan &coordinationPlan);

// The deterministic companion JSON (the exact bytes written to
// test-realization.json). Sorted keys, no timestamps; carries capabilityHash as
// a reference so the file lives outside the hash it points at. Schema:
// docs/schemas/test-realization.schema.json.
std::string testRealizationJson(const TestRealization &tr);

// `--target=test-realization`: write test-realization.json. Consumes the
// scenario (not scenario-free). See docs/testing/TEST_REALIZATION.md.
std::vector<std::string>
emitTestRealization(const ProcedureView &view, const Scenario &scenario,
                    const std::string &outDir,
                    const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_TEST_REALIZATION_H
