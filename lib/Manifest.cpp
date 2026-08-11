//===- Manifest.cpp - emit manifest.json for a generation run -------------===//
//
// A stable, machine-readable record of one backend generation: content hashes
// of the inputs, the produced artifacts (path/type/hash), tool version, command
// line, timestamp, and success state. This is the foundation for a future
// translator-agent's output bundle.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/Manifest.h"
#include "Neutrino/VersionInfo.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/SHA256.h"
#include "llvm/Support/raw_ostream.h"

#include <cstdlib>
#include <ctime>

using namespace llvm;

namespace {

// Tool version is the single constant in Neutrino/VersionInfo.h ().
const char *kToolVersion = neutrino::kToolVersion;

std::string artifactType(StringRef path) {
  if (path.endswith(".t.sol"))
    return "foundry-test";
  if (path.endswith(".sol"))
    return "solidity";
  if (path.endswith(".toml"))
    return "config";
  if (path.endswith("run_db_test.sh"))
    return "shell-test";
  if (path.endswith(".sql"))
    return "sql";
  if (path.endswith(".mlir"))
    return "mlir";
  return "file";
}

// Wall-clock time, unless SOURCE_DATE_EPOCH pins it (so a caller that needs a
// byte-stable manifest can fix the one non-deterministic field).
std::string isoNow() {
  std::time_t t = std::time(nullptr);
  if (const char *e = getenv("SOURCE_DATE_EPOCH"))
    t = static_cast<std::time_t>(std::strtoll(e, nullptr, 10));
  char buf[32];
  if (std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&t)) == 0)
    buf[0] = '\0'; // truncated — cannot happen for this fixed format/buffer
  return std::string(buf);
}

} // namespace

std::string neutrino::sha256OfFile(const std::string &path) {
  auto buf = MemoryBuffer::getFile(path);
  if (!buf)
    return "";
  StringRef d = (*buf)->getBuffer();
  auto digest = SHA256::hash(ArrayRef<uint8_t>(
      reinterpret_cast<const uint8_t *>(d.data()), d.size()));
  return toHex(digest, /*LowerCase=*/true);
}

void neutrino::writeManifest(const std::string &outDir, const std::string &target,
                             const std::string &sourcePath,
                             const std::string &scenarioPath,
                             const std::vector<std::string> &artifacts,
                             const std::string &commandLine, bool ok) {
  json::Array arts;
  for (const std::string &a : artifacts) {
    arts.push_back(json::Object{
        {"path", a},
        {"type", artifactType(a)},
        {"sha256", neutrino::sha256OfFile(a)},
    });
  }

  json::Object root{
      {"tool", "neutrino-gen"},
      {"version", kToolVersion},
      // Pin the full language/artifact compatibility surface (): the same
      // envelope as `--version-json`, so a downstream consumer can reject a
      // stale tool/dialect/schema combination from the manifest alone (single
      // source: VersionInfo.h). manifest.json is run metadata, not part of
      // capability.lock.
      {"translatorVersion", neutrino::versionInfo("neutrino-gen")},
      {"target", target},
      {"command", commandLine},
      {"timestamp", isoNow()},
      {"ok", ok},
      {"diagnostics", "diagnostics.json"},
      {"source", json::Object{{"path", sourcePath},
                              {"sha256", neutrino::sha256OfFile(sourcePath)}}},
      {"scenario",
       json::Object{{"path", scenarioPath},
                    {"sha256", neutrino::sha256OfFile(scenarioPath)}}},
      {"artifacts", std::move(arts)},
  };

  SmallString<256> path(outDir);
  sys::path::append(path, "manifest.json");
  std::error_code ec;
  raw_fd_ostream os(path, ec);
  if (ec) {
    errs() << "warning: could not write manifest " << path << ": " << ec.message() << "\n";
    return;
  }
  os << formatv("{0:2}", json::Value(std::move(root))) << "\n";
}
