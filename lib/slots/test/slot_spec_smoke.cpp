//===- slot_spec_smoke.cpp - standalone typed slot API witness ----------===//
//
// Proves the slot module is usable STANDALONE: this executable links ONLY
// `NeutrinoSlotSpec` (see CMakeLists.txt) — not `NeutrinoEmit`,
// `NeutrinoAnalysis`, or any backend/policy. If the carve were leaky (the slot
// renderer reached a ProcedureView / spec-producer / backend symbol), this
// would fail to LINK. It renders the slot artifact set from a synthetic
// capability-spec (argv[1])
// through the module's public spec->slot entry point.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSlotSpec.h"

#include "llvm/Support/JSON.h"

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

using namespace neutrino;

static int fail(const char *msg) {
  fprintf(stderr, "slot-spec-smoke: %s\n", msg);
  return 1;
}

int main(int argc, char **argv) {
  if (argc < 2)
    return fail("usage: slot-spec-smoke <capability-spec.json> [out-dir]");
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

  SlotArtifacts files = generateSlotFromSpec(*spec);
  auto capability = std::find_if(files.begin(), files.end(),
                                 [](const SlotArtifact &artifact) {
                                   return artifact.name == "capability.json";
                                 });
  auto lock = std::find_if(files.begin(), files.end(),
                           [](const SlotArtifact &artifact) {
                             return artifact.name == "capability.lock";
                           });
  if (files.empty() || capability == files.end())
    return fail("slot artifact set missing capability.json");
  if (lock == files.end())
    return fail("slot artifact set missing capability.lock");
  if (capability->content.find("\"backends\"") != std::string::npos ||
      capability->content.find("solidity") != std::string::npos ||
      capability->content.find("postgres") != std::string::npos ||
      capability->content.find("oracle") != std::string::npos)
    return fail("target-neutral slot capability invented backend claims");

  SlotArtifacts tampered = files;
  auto tamperedCapability = std::find_if(
      tampered.begin(), tampered.end(), [](const SlotArtifact &artifact) {
        return artifact.name == "capability.json";
      });
  auto oldLock = std::find_if(tampered.begin(), tampered.end(),
                              [](const SlotArtifact &artifact) {
                                return artifact.name == "capability.lock";
                              });
  const std::string oldLockContent = oldLock->content;
  tamperedCapability->content += " ";
  refreshSlotCapabilityLock(tampered);
  auto newLock = std::find_if(tampered.begin(), tampered.end(),
                              [](const SlotArtifact &artifact) {
                                return artifact.name == "capability.lock";
                              });
  if (newLock == tampered.end() || newLock->content == oldLockContent)
    return fail("capability.lock did not bite on a capability tamper");

  if (argc >= 3) {
    namespace fs = std::filesystem;
    std::error_code ec;
    fs::create_directories(argv[2], ec);
    if (ec)
      return fail("cannot create output directory");
    for (const auto &f : files) {
      std::ofstream out(fs::path(argv[2]) / f.name);
      if (!out)
        return fail("cannot write slot artifact");
      out << f.content;
    }
  }

  puts("slot-spec-smoke OK (slot module links standalone: "
       "capability-spec -> slot artifacts via the leaf, no NeutrinoEmit)");
  return 0;
}
