//===- oracle_observer_smoke.cpp - link-smoke for NeutrinoBackendOracle ()
//---===//
//
// Proves the oracle observer backend is usable STANDALONE: this executable
// links ONLY `NeutrinoBackendOracle` (see CMakeLists.txt) — not `NeutrinoEmit`,
// `NeutrinoAnalysis`, or any other backend. A leaky carve (the renderer
// reaching a ProcedureView / spec-producer / other-backend symbol) would fail
// to LINK, so the target graph itself enforces the  dependency direction.
// It renders the observers from a minimal in-memory attestation spec + binding.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenOracleObserverSpec.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <string>
#include <vector>

using namespace neutrino;
using llvm::json::Array;
using llvm::json::Object;

static int fail(const char *msg) {
  fprintf(stderr, "oracle-observer-smoke: %s\n", msg);
  return 1;
}

int main() {
  // A minimal frozen spec carrying one attestation policy (the  shape) …
  Object spec{{"attestations",
               Array{Object{{"input", "delivery_proof"},
                            {"quorum", Object{{"threshold", 2}}},
                            {"observerSet", Object{{"ref", "delivery_oracles"},
                                                   {"role", nullptr}}},
                            {"canonicalization",
                             Object{{"mode", "exact"}, {"tolerance", nullptr}}},
                            {"timeout", nullptr},
                            {"fallback", "abort"}}}}};
  // … and a binding that resolves it to a mock source + 3 observers.
  Object binding{
      {"kind", "neutrino.observation-binding"},
      {"schemaVersion", 1},
      {"observerSets",
       Array{Object{
           {"ref", "delivery_oracles"},
           {"source", Object{{"type", "mock"},
                             {"id", "ev"},
                             {"claimField", "delivered"}}},
           {"members", Array{Object{{"id", "a"}, {"publicKey", "0x1"}},
                             Object{{"id", "b"}, {"publicKey", "0x2"}},
                             Object{{"id", "c"}, {"publicKey", "0x3"}}}}}}}};

  std::vector<OracleFile> files = generateOracleObserverFromSpec(spec, binding);
  // 3 observers + 1 aggregator.
  if (files.size() != 4)
    return fail("expected 4 rendered files (3 observers + aggregator)");

  bool sawAgg = false, sawSign = false;
  for (const OracleFile &f : files) {
    if (f.path.find("aggregate.js") != std::string::npos) {
      sawAgg = true;
      if (f.content.find("THRESHOLD = 2") == std::string::npos)
        return fail("aggregator missing the M=2 threshold");
    } else if (f.content.find("signer(digest)") != std::string::npos &&
               f.content.find("keccak256(encode(c))") != std::string::npos) {
      sawSign = true; // observer signs keccak256 of the canonical claim
    }
  }
  if (!sawAgg)
    return fail("no aggregator rendered");
  if (!sawSign)
    return fail("observers do not sign keccak256(canonical claim)");

  puts("oracle-observer-smoke OK (oracle backend links standalone: attestation "
       "policy + binding -> observers/aggregator via the leaf, no "
       "NeutrinoEmit)");
  return 0;
}
