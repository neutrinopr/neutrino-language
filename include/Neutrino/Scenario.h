#ifndef NEUTRINO_SCENARIO_H
#define NEUTRINO_SCENARIO_H

#include "llvm/ADT/StringRef.h"

#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace neutrino {

struct ScenarioInput {
  bool isInt = false;
  long long i = 0;
  std::string s;
};

struct Scenario {
  std::string name, procedure;
  std::map<std::string, ScenarioInput> inputs;
  std::map<std::string, long long> computed;
  std::vector<std::string> events;
  std::map<std::string, long long> ledger;
  std::vector<std::string> invariants;
  // Per-policy quorum acceptance (): attestation-policy input -> accepted?
  // An accepted()-gated leg posts iff its policy is accepted here; an
  // unaccepted policy SUPPRESSES its guarded legs (a balanced no-op), it does
  // not refuse the transition. A policy absent from this map is accepted (the
  // default happy path, so pre- scenarios keep their meaning).
  std::map<std::string, bool> accepted;
};

struct ScenarioError : std::runtime_error {
  // Stable diagnostic code: "scenario.io" (unreadable), "scenario.parse"
  // (malformed JSON), or "scenario.schema" (wrong shape/types).
  std::string code;
  ScenarioError(std::string code, const std::string &m)
      : std::runtime_error(m), code(std::move(code)) {}
};

// Loads a backend-neutral scenario from JSON (YAML retired for the C++ path).
Scenario loadScenario(llvm::StringRef path);

} // namespace neutrino

#endif // NEUTRINO_SCENARIO_H
