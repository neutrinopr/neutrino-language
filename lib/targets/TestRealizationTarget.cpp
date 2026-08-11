//===- TestRealizationTarget.cpp - fold spec + scenario into backend test cases
//-===//
//
// The test-realization artifact (M5 WP2, ): scenario/test data folded ONCE,
// outside the capability hash scope. See Neutrino/TestRealization.h.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/TestRealization.h"

#include "Neutrino/GenSpec.h"

#include "llvm/Support/FormatVariadic.h"
#include "llvm/Support/JSON.h"

#include <filesystem>
#include <fstream>
#include <stdexcept>

using namespace llvm;

namespace neutrino {

TestRealization realize(const ProcedureView &view, const Scenario &scenario,
                        const CoordinationPlan &coordinationPlan) {
  TestRealization tr;
  tr.scenario = scenario.name;
  tr.procedure = scenario.procedure;
  // The capability being realized. capabilityHashOf is a pure function of the
  // source-derived view, so it is identical for every scenario of a capability.
  tr.capabilityHash = capabilityHashOf(view, coordinationPlan);

  // Fold ONCE: the event chain is the IR-DERIVED choreography (always present),
  // not the scenario's optional `expect.events` echo — so the realization
  // always carries the events the backends derive, even for a scenario that
  // omits them. Any declared scenario events must still MATCH the choreography
  // (a check that previously lived inside the Solidity renderer; now both
  // backends inherit it).
  // A guarded leg contributes its event iff its predicate holds for THIS
  // scenario, so the realized chain is scenario-aware: build the
  // numeric env from the scenario's inputs + computed values.
  std::map<std::string, long long> env;
  for (const auto &kv : scenario.inputs)
    if (kv.second.isInt)
      env[kv.first] = kv.second.i;
  for (const auto &kv : scenario.computed)
    env[kv.first] = kv.second;
  std::vector<std::string> chain = eventChain(view, env);
  if (!scenario.events.empty() && chain != scenario.events)
    throw std::runtime_error(
        "scenario events do not match IR-derived choreography");

  tr.inputs = scenario.inputs;
  tr.computed = scenario.computed;
  tr.events = std::move(chain);
  tr.ledger = scenario.ledger;
  tr.invariants = scenario.invariants;
  return tr;
}

std::string testRealizationJson(const TestRealization &tr) {
  auto valueOf = [](const ScenarioInput &in) -> json::Value {
    return in.isInt ? json::Value(in.i) : json::Value(in.s);
  };

  json::Object inputs;
  for (const auto &kv : tr.inputs)
    inputs[kv.first] = valueOf(kv.second);
  json::Object computed;
  for (const auto &kv : tr.computed)
    computed[kv.first] = kv.second;
  json::Object ledger;
  for (const auto &kv : tr.ledger)
    ledger[kv.first] = kv.second;
  json::Array events;
  for (const auto &e : tr.events)
    events.push_back(e);
  json::Array invariants;
  for (const auto &i : tr.invariants)
    invariants.push_back(i);

  json::Object root{
      {"schemaVersion", 1},
      {"kind", "neutrino.test-realization"},
      // A REFERENCE to the capability these cases realize — this file lives
      // outside the hash it points at (WP2 hash-scope separation, ).
      {"capabilityHash", tr.capabilityHash},
      {"scenario", tr.scenario},
      {"procedure", tr.procedure},
      {"inputs", std::move(inputs)},
      {"computed", std::move(computed)},
      {"eventChain", std::move(events)},
      {"ledgerDeltas", std::move(ledger)},
      {"invariants", std::move(invariants)},
  };
  return formatv("{0:2}", json::Value(std::move(root))).str() + "\n";
}

std::vector<std::string>
emitTestRealization(const ProcedureView &view, const Scenario &scenario,
                    const std::string &outDir,
                    const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);
  std::string path = (fs::path(outDir) / "test-realization.json").string();
  std::ofstream os(path);
  os << testRealizationJson(realize(view, scenario, coordinationPlan));
  return {path};
}

} // namespace neutrino
