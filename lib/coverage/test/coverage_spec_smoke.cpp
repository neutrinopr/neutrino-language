//===- coverage_spec_smoke.cpp - link-smoke for NeutrinoCoverageSpec -----
//===//
//
// Proves the coverage-report renderer is usable STANDALONE: this executable
// links ONLY `NeutrinoCoverageSpec` (see CMakeLists.txt) — not `NeutrinoEmit`,
// `NeutrinoAnalysis`, the frontend, or any backend renderer. A leaky carve
// (reaching a ProcedureView / spec-producer / sibling-renderer symbol) would
// fail to LINK, so the target graph itself enforces the entry-vs-model
// boundary. It renders the coverage report from a synthetic capability-spec
// (argv[1]) via the leaf's spec-only entry point.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenCoverageSpec.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

using namespace neutrino;

static int fail(const char *msg) {
  fprintf(stderr, "coverage-spec-smoke: %s\n", msg);
  return 1;
}

int main(int argc, char **argv) {
  if (argc < 2)
    return fail("usage: coverage-spec-smoke <capability-spec.json>");
  std::ifstream in(argv[1]);
  if (!in)
    return fail("cannot open the capability-spec");
  std::stringstream ss;
  ss << in.rdbuf();

  llvm::Expected<llvm::json::Value> j = llvm::json::parse(ss.str());
  if (!j)
    return fail("capability-spec is not valid JSON");
  const llvm::json::Object *spec = j->getAsObject();
  if (!spec)
    return fail("capability-spec is not a JSON object");

  // The coverage report, rendered from the frozen spec alone (no
  // ProcedureView). Linking + calling it here with ONLY
  // libNeutrinoCoverageSpec.a on the link line is the boundary proof.
  std::string report = coverageReportFromSpec(*spec);
  if (report.find("\"procedure\": \"synthetic_coverage\"") == std::string::npos)
    return fail("coverage report did not preserve the synthetic procedure");
  if (report.find("\"highestLevel\": \"L5\"") == std::string::npos)
    return fail("balanced value movement did not exercise coverage through L5");
  if (report.find("\"level\": \"L8\"") == std::string::npos ||
      report.find("\"present\": \"partial\"") == std::string::npos)
    return fail("multi-organization topology did not produce partial L8");
  if (report.find("\"targets\"") != std::string::npos ||
      report.find("\"maturityRule\"") != std::string::npos ||
      report.find("solidity") != std::string::npos ||
      report.find("postgres") != std::string::npos)
    return fail("target-neutral core report invented backend maturity claims");

  puts("coverage-spec-smoke OK (coverage report links standalone: "
       "capability-spec -> coverage via the leaf, no NeutrinoEmit)");
  return 0;
}
