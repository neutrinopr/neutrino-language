//===- capability_profile_smoke.cpp - link-smoke for NeutrinoCapabilityProfile
//() ---===//
//
// Proves the capability-profile model is usable STANDALONE: this executable
// links ONLY `NeutrinoCapabilityProfile` (see CMakeLists.txt) — not
// `NeutrinoEmit`, `NeutrinoAnalysis`, or any backend renderer. A leaky carve
// (reaching a ProcedureView / spec-producer / backend symbol) would fail to
// LINK, so the target graph itself enforces the  D5 boundary. It builds the
// per-target capability model from a committed capability-spec (argv[1]).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenCapabilityModelSpec.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <string>

using namespace neutrino;

static int fail(const char *msg) {
  fprintf(stderr, "capability-profile-smoke: %s\n", msg);
  return 1;
}

int main() {
  llvm::json::Object spec{
      {"identity",
       llvm::json::Object{{"capabilityHash", std::string(64, 'a')}}},
      {"procedure", "smoke"},
      {"specVersion", "1.0.0"},
  };

  backend_package::TargetProfile profile;
  profile.profileId = "target.synthetic.v1";
  profile.profileVersion = 1;
  profile.target = "synthetic";
  profile.runtimeFamily = "off_chain";
  profile.executionMode = "simulated";
  profile.fallbackPolicy = "fail_closed";
  profile.semanticProfileVersion = 3;
  profile.digest = "sha256:profile";
  std::vector<backend_package::TargetProfile> profiles{profile};
  llvm::Expected<std::vector<CapabilityModelArtifact>> models =
      generateCapabilityModelsFromSpec(spec, "sha256:catalog", profiles);
  if (!models || models->size() != 1)
    return fail("capability model generation failed");
  if (models->front().bytes.find("neutrino.backend-capability-model") ==
      std::string::npos)
    return fail(
        "capability model missing the backend-capability-model envelope");

  puts(
      "capability-profile-smoke OK (capability profile model links standalone: "
      "capability-spec -> capability model via the leaf, no NeutrinoEmit)");
  return 0;
}
