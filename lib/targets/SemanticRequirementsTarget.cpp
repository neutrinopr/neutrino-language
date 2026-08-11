//===- SemanticRequirementsTarget.cpp - emit requirements ----------------===//

#include "Neutrino/GenSemanticRequirements.h"

#include "Neutrino/SemanticRequirements.h"
#include "Neutrino/VersionInfo.h"

#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <tuple>

using namespace llvm;

namespace neutrino {

std::string
semanticRequirementsToText(const CoordinationPlan &coordinationPlan) {
  PlanRequirements derived = coordinationPlanRequirements(coordinationPlan);
  std::sort(derived.features.begin(), derived.features.end(),
            [](const SemanticRequirement &lhs, const SemanticRequirement &rhs) {
              return std::tie(lhs.feature, lhs.primitive) <
                     std::tie(rhs.feature, rhs.primitive);
            });

  json::Array requirements;
  for (const SemanticRequirement &requirement : derived.features)
    requirements.push_back(json::Object{{"feature", requirement.feature},
                                        {"primitive", requirement.primitive}});

  const PlanMetrics &metrics = derived.metrics;
  json::Object root{
      {"kind", "neutrino.semantic-requirements"},
      {"schemaVersion", 1},
      {"semanticProfileVersion", kSemanticProfileVersion},
      {"requirements", std::move(requirements)},
      {"metrics", json::Object{{"expressionDepth", metrics.expressionDepth},
                               {"effectCount", metrics.effectCount},
                               {"effectGroupCount", metrics.effectGroupCount},
                               {"attestationCount", metrics.attestationCount},
                               {"computeCount", metrics.computeCount},
                               {"operationSteps", metrics.operationSteps}}},
  };
  std::string text;
  raw_string_ostream os(text);
  os << formatv("{0:2}", json::Value(std::move(root))) << "\n";
  os.flush();
  return text;
}

std::vector<std::string>
emitSemanticRequirements(const ProcedureView &, const Scenario &,
                         const std::string &outDir,
                         const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);
  std::string path = (fs::path(outDir) / "semantic-requirements.json").string();
  std::ofstream f(path);
  f << semanticRequirementsToText(coordinationPlan);
  return {path};
}

} // namespace neutrino
