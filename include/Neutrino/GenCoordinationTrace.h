#ifndef NEUTRINO_GENCOORDINATIONTRACE_H
#define NEUTRINO_GENCOORDINATIONTRACE_H

#include "Neutrino/CoordinationEval.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// Run the reference evaluator () on `coordinationPlan` for the invocation
// described by `scenario`, from an empty initial state, and serialize {outcome,
// trace, nextState}. Shared by the from-MLIR target and neutrino-gen's
// --from-spec reconstruction path so both serialize identically. The scenario
// provides the numeric/symbolic transition inputs; the target drives the
// authorized, declared-policies-accepted happy path (the
// refusal/replay/rollback cases are the reference evaluator's C++ unit tier,
// which constructs those inputs directly).
std::string
coordinationTraceFromScenario(const CoordinationPlan &coordinationPlan,
                              const Scenario &scenario);

// The reference evaluator's transition for a scenario, from an empty initial
// state (the input built as the authorized, all-attestations-accepted happy
// path) — the oracle the differential harness compares realizations against.
TransitionInput
transitionInputFromScenario(const CoordinationPlan &coordinationPlan,
                            const Scenario &scenario);
TransitionResult referenceTransition(const CoordinationPlan &coordinationPlan,
                                     const Scenario &scenario);

// The `coordination-trace` target (): the observable, deterministic
// realization of a coordination plan under one transition input — the semantic
// oracle every backend realization is checked against. Scenario-bearing +
// non-gated (a derived semantic projection, like
// coordination-coordinationPlan).
std::vector<std::string>
emitCoordinationTrace(const ProcedureView &view, const Scenario &scenario,
                      const std::string &outDir,
                      const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GENCOORDINATIONTRACE_H
