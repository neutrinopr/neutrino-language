//===- CoordinationTraceTarget.cpp - serialize a reference realization --===//
//
// The `coordination-trace` target (). It runs the ONE deterministic
// reference evaluator (CoordinationEval) over the normalized CoordinationPlan
// () for a scenario's transition input and emits {outcome, trace,
// nextState} as a deterministic JSON artifact — so the semantic oracle is
// observable + FileCheck-pinnable, and the .neu / direct-MLIR / spec-
// reconstruction paths (which all normalize to the same coordination
// coordinationPlan) demonstrably reach the same result.
// coordinationTraceFromScenario is reused by neutrino-gen's --from-spec path so
// a trace from an external spec serializes identically.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenCoordinationTrace.h"

#include "Neutrino/CoordinationEval.h"
#include "Neutrino/CoordinationPlanBuild.h"

#include "llvm/Support/Error.h"

#include <filesystem>
#include <fstream>

using namespace llvm;

namespace neutrino {

TransitionInput
transitionInputFromScenario(const CoordinationPlan &coordinationPlan,
                            const Scenario &sc) {
  TransitionInput in;
  for (const auto &kv : sc.inputs) {
    if (kv.second.isInt)
      in.numeric[kv.first] = kv.second.i;
    else
      in.symbols[kv.first] = kv.second.s;
  }
  // Acceptance is scenario-driven (): a policy the scenario UNaccepts gates
  // its accepted() legs to suppressed; a policy the scenario omits is accepted
  // (the all-accepted default). The evaluator seeds its "accepted:" env from
  // this map, so the guard evaluates to the scenario's per-policy verdict.
  for (const AttestationPolicy &p : coordinationPlan.attestations) {
    auto it = sc.accepted.find(p.input);
    in.attestations[p.input] = it == sc.accepted.end() ? true : it->second;
  }
  in.authorized = true;
  return in;
}

TransitionResult referenceTransition(const CoordinationPlan &coordinationPlan,
                                     const Scenario &scenario) {
  return evaluateTransition(
      coordinationPlan, EvalState{},
      transitionInputFromScenario(coordinationPlan, scenario));
}

std::string
coordinationTraceFromScenario(const CoordinationPlan &coordinationPlan,
                              const Scenario &scenario) {
  TransitionInput input =
      transitionInputFromScenario(coordinationPlan, scenario);
  TransitionResult result =
      evaluateTransition(coordinationPlan, EvalState{}, input);
  return transitionToText(result);
}

std::vector<std::string>
emitCoordinationTrace(const ProcedureView &view, const Scenario &scenario,
                      const std::string &outDir,
                      const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);

  std::string path = (fs::path(outDir) / "coordination-trace.json").string();
  std::ofstream f(path);
  f << coordinationTraceFromScenario(coordinationPlan, scenario);
  return {path};
}

} // namespace neutrino
