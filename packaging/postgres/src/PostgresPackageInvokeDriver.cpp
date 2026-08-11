//===- PostgresPackageInvokeDriver.cpp -  acceptance driver ----------===//
//
// Drives the VERIFIED PostgreSQL backend package over the real subprocess
// protocol and writes the artifacts it streams back. This is the  witness
// harness's invocation leg.
//
// It goes through package discovery + BackendInvoker DIRECTLY rather than
// through the target catalog. That is deliberate and is not a shortcut: the
// catalog refuses a package whose target name a built-in already claims
// (E_PACKAGE_DUPLICATE_TARGET), and retiring the built-in "postgres" row is
//  seam work with a 26-test blast radius that this PR does not take on.
// Everything the acceptance endpoint actually asserts -- descriptor
// verification, protocol negotiation, streamed artifacts, receipt digest -- is
// exercised identically either way; only target-name resolution is bypassed.
//
// Test scaffolding, not shipped: this driver is not part of the extracted
// package's install surface.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/BackendInvoker.h"
#include "Neutrino/BackendPackage.h"
#include "Neutrino/BackendProjection.h"
#include "Neutrino/CoordinationPlan.h"

#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

namespace {

int fail(llvm::StringRef stage, llvm::StringRef detail) {
  llvm::errs() << "[ invoke-driver] " << stage << ": " << detail << "\n";
  return 1;
}

} // namespace

int main(int argc, char **argv) {
  if (argc != 4) {
    llvm::errs() << "usage: " << argv[0]
                 << " <package-dir> <capability-spec.json> <out-dir>\n";
    return 2;
  }
  const std::string packageDir = argv[1];
  const std::string specPath = argv[2];
  const std::string outDir = argv[3];

  std::ifstream in(specPath);
  if (!in)
    return fail("spec", "cannot read " + specPath);
  std::stringstream buffer;
  buffer << in.rdbuf();
  llvm::Expected<llvm::json::Value> parsed = llvm::json::parse(buffer.str());
  if (!parsed)
    return fail("spec", llvm::toString(parsed.takeError()));
  const llvm::json::Object *spec = parsed->getAsObject();
  if (!spec)
    return fail("spec", "capability-spec is not a JSON object");

  llvm::Expected<neutrino::CoordinationPlan> plan =
      neutrino::planFromSpec(*spec);
  if (!plan)
    return fail("plan", llvm::toString(plan.takeError()));

  llvm::Expected<neutrino::projection::BackendProjectionGraph> graph =
      neutrino::projection::projectBackendGraph(*plan);
  if (!graph)
    return fail("projection", llvm::toString(graph.takeError()));

  // Discovery is the REAL one: the descriptor is verified (manifestDigest,
  // closure digests, compatibility bounds) before any invocation happens.
  std::unique_ptr<neutrino::backend_package::PackageFilesystem> filesystem =
      neutrino::backend_package::createNativePackageFilesystem();
  neutrino::backend_package::Compatibility compatibility;
  llvm::Expected<std::vector<neutrino::backend_package::VerifiedPackage>>
      packages = neutrino::backend_package::discoverPackages(
          {packageDir}, compatibility, *filesystem);
  if (!packages)
    return fail("discovery", llvm::toString(packages.takeError()));
  if (packages->size() != 1)
    return fail("discovery", "expected exactly one verified package, found " +
                                 std::to_string(packages->size()));

  neutrino::backend_invocation::InvocationOptions options;
  options.coreIdentity = neutrino::backend_invocation::coreIdentity();
  // The protocol requires explicit, nonzero output limits -- a backend may not
  // stream unbounded artifacts. Generous but finite: the point of the witness
  // is byte parity, not limit tuning.
  options.outputSpec.maxArtifacts = 64;
  options.outputSpec.maxTotalBytes = 16u * 1024u * 1024u;
  llvm::Expected<neutrino::backend_invocation::Result> result =
      neutrino::backend_invocation::invoke(packages->front(), *graph, options);
  if (!result)
    return fail("invoke", llvm::toString(result.takeError()));

  std::error_code ec;
  std::filesystem::create_directories(outDir, ec);
  if (ec)
    return fail("write", "cannot create " + outDir + ": " + ec.message());
  for (const neutrino::backend_invocation::Artifact &artifact :
       result->artifacts) {
    const std::filesystem::path path =
        std::filesystem::path(outDir) / artifact.path;
    std::filesystem::create_directories(path.parent_path(), ec);
    std::ofstream out(path, std::ios::binary);
    if (!out)
      return fail("write", "cannot write " + path.string());
    out.write(artifact.bytes.data(),
              static_cast<std::streamsize>(artifact.bytes.size()));
  }

  // The identities the receipt witness binds against, emitted so the harness
  // reads them from the invocation rather than recomputing them itself.
  llvm::outs() << "targetIdentity=" << result->targetIdentity << "\n"
               << "targetProfileIdentity=" << result->targetProfileIdentity
               << "\n"
               << "packageManifestDigest=" << result->packageManifestDigest
               << "\n"
               << "projectionDigest=" << result->projectionDigest << "\n"
               << "receiptDigest=" << result->receiptDigest << "\n"
               << "artifacts=" << result->artifacts.size() << "\n";
  return 0;
}
