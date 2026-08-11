//===- backend_solidity_smoke.cpp - NeutrinoBackendSolidity link-smoke ----===//
//
// Proves the Solidity backend is usable STANDALONE: this executable links ONLY
// `NeutrinoBackendSolidity` (see CMakeLists.txt) — not `NeutrinoEmit`,
// `NeutrinoAnalysis`, or any other backend. If the carve were leaky (the
// Solidity renderer reached a ProcedureView / spec-producer / other-backend
// symbol), this would fail to LINK, so the target graph itself enforces the
//  D2 boundary. It renders the contract from a committed capability-spec
// (argv[1]) through the backend's public spec->Solidity entry point.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSoliditySpec.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

using namespace neutrino;

static int fail(const char *msg) {
  fprintf(stderr, "backend-solidity-smoke: %s\n", msg);
  return 1;
}

int main(int argc, char **argv) {
  if (argc < 2)
    return fail("usage: backend-solidity-smoke <capability-spec.json>");
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

  // The migrated spec->Solidity renderer (leaf-only): re-types compute ASTs
  // from the spec (typeExpr) and renders the contract, no ProcedureView.
  // Linking + calling it here with ONLY libNeutrinoBackendSolidity.a on the
  // link line is the boundary proof.
  llvm::Expected<neutrino::CoordinationPlan> coordinationPlan =
      neutrino::planFromSpec(*spec);
  if (!coordinationPlan)
    return fail("capability-spec failed coordination-plan normalization");
  std::string sol = generateSolidityContractFromSpec(*coordinationPlan);
  if (sol.find("pragma solidity") == std::string::npos)
    return fail("rendered contract missing the Solidity pragma");
  if (argc >= 3) {
    std::ifstream goldenIn(argv[2]);
    if (!goldenIn)
      return fail("cannot open the Solidity byte golden");
    std::stringstream golden;
    golden << goldenIn.rdbuf();
    if (sol != golden.str())
      return fail("rendered contract differs from the Solidity byte golden");
  }

  puts("backend-solidity-smoke OK (Solidity backend links standalone: "
       "capability-spec -> contract via the leaf, no NeutrinoEmit)");
  return 0;
}
