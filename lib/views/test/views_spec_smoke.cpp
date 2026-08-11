//===- views_spec_smoke.cpp - link-smoke for NeutrinoViewsSpec () -----===//
//
// Proves the per-participant views renderer is usable STANDALONE: this
// executable links ONLY `NeutrinoViewsSpec` (see CMakeLists.txt) — not
// `NeutrinoEmit`, `NeutrinoAnalysis`, the frontend, or any backend renderer. A
// leaky carve (reaching a ProcedureView / spec-producer / sibling-renderer
// symbol) would fail to LINK, so the target graph itself enforces the /
// ENTRY-vs-LEAF boundary. It renders the per-participant views from a committed
// capability-spec (argv[1]) via the leaf's spec-only entry point.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenViewsSpec.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>

using namespace neutrino;

static int fail(const char *msg) {
  fprintf(stderr, "views-spec-smoke: %s\n", msg);
  return 1;
}

int main(int argc, char **argv) {
  if (argc != 3)
    return fail(
        "usage: views-spec-smoke <capability-spec.json> <expected-directory>");
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

  // The per-participant views, rendered from the frozen spec alone (no
  // ProcedureView). Linking + calling it here with ONLY libNeutrinoViewsSpec.a
  // on the link line is the boundary proof.
  std::vector<std::pair<std::string, std::string>> views =
      generateParticipantViewsFromSpec(*spec);
  if (views.size() != 2)
    return fail("expected exactly two participant views from the spec");

  std::map<std::string, std::string> expected;
  for (const auto &entry : std::filesystem::directory_iterator(argv[2])) {
    if (!entry.is_regular_file() || entry.path().extension() != ".json")
      continue;
    std::ifstream golden(entry.path());
    std::stringstream bytes;
    bytes << golden.rdbuf();
    expected.emplace(entry.path().stem().string(), bytes.str());
  }
  if (expected.size() != views.size())
    return fail("expected view fixture count differs");
  for (const auto &view : views) {
    auto found = expected.find(view.first);
    if (found == expected.end() || found->second != view.second)
      return fail("derived participant view differs from the fixture");
  }

  puts(
      "views-spec-smoke OK (participant views link standalone: capability-spec "
      "-> views via the leaf, no NeutrinoEmit)");
  return 0;
}
