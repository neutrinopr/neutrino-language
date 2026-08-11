//===- security_policy_smoke.cpp - link-smoke for NeutrinoSecurityPolicy ----
//---===//
//
// Proves the security-policy model is usable STANDALONE: this executable links
// ONLY `NeutrinoSecurityPolicy` (see CMakeLists.txt) — not `NeutrinoEmit`,
// `NeutrinoAnalysis`, or any backend renderer. If the policy/model carve were
// leaky (it reached a ProcedureView / spec-producer / backend symbol), this
// would fail to link, so the target graph itself enforces the boundary. It
// builds the security report from a synthetic capability-spec (argv[1]).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSecuritySpec.h"
#include "SecurityAdmission.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <type_traits>

using namespace neutrino;

using DispatchFacade = SecurityDispatchDecision (*)(const llvm::json::Object &);
static_assert(
    std::is_same_v<decltype(&evaluateSecurityForDispatch), DispatchFacade>,
    "the production dispatch facade must not accept an insecure override");

static int fail(const char *msg) {
  fprintf(stderr, "security-policy-smoke: %s\n", msg);
  return 1;
}

int main(int argc, char **argv) {
  if (argc < 2)
    return fail("usage: security-policy-smoke <capability-spec.json>");
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

  // The security-policy model, built from the frozen spec alone (no
  // ProcedureView). Linking + calling it here with ONLY
  // libNeutrinoSecurityPolicy.a on the link line is the boundary proof. Also
  // exercise the sibling predicate.
  if (!specHasSecurityViolations(*spec))
    return fail("synthetic hard violation was not detected");
  SecurityDispatchDecision decision = evaluateSecurityForDispatch(*spec);
  if (decision.authorized())
    return fail("hard violation produced an authorized dispatch decision");
  std::string report = securityReportFromSpec(*spec);
  if (report.find("neutrino.capability-security") == std::string::npos)
    return fail("security report missing the capability-security envelope");
  if (report.find("\"ok\": false") == std::string::npos)
    return fail("security report did not record the hard refusal");

  puts("security-policy-smoke OK (public-core policy links standalone and "
       "hard violations cannot authorize dispatch)");
  return 0;
}
