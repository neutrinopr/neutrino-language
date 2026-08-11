#ifndef NEUTRINO_MANIFEST_H
#define NEUTRINO_MANIFEST_H

#include <string>
#include <vector>

namespace neutrino {

// Per-run manifest + content hashing (T9 R1 /  — split out of the former
// kitchen-sink Backends.h). See docs/backends/BACKEND_GENERATORS.md.

// SHA-256 (lowercase hex) of a file's contents; "" if unreadable. Shared by the
// manifest writer and the agent bundle runner so hashes are computed
// identically.
std::string sha256OfFile(const std::string &path);

// Write manifest.json into outDir describing a generation run: source/scenario
// content hashes, target, generated artifacts + hashes, tool version, command,
// timestamp, success state.
void writeManifest(const std::string &outDir, const std::string &target,
                   const std::string &sourcePath,
                   const std::string &scenarioPath,
                   const std::vector<std::string> &artifacts,
                   const std::string &commandLine, bool ok);

} // namespace neutrino

#endif // NEUTRINO_MANIFEST_H
