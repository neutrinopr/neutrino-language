# Demo quickstart (clean clone)

Validated on **macOS** (Apple Silicon / arm64) from a fresh, historyless
`neutrino-language` checkout. The four scripts below complete **PASS** with
only these steps — no primed worktree caches.

## Prerequisites

| tool | role | how it was resolved in this measurement |
|---|---|---|
| CMake ≥ 3.20, Ninja, C++17 clang | build | Homebrew |
| **LLVM/MLIR 15** development packages | link | Homebrew `llvm@15` (prefix used below) |
| Python 3 | validators / helpers | system / Homebrew |
| **solc** | compile generated Solidity | on `PATH` |
| **Foundry** (`anvil`, `cast`) | local chain | `~/.foundry/bin` |
| **libusb** (macOS only when Foundry was linked against it) | `cast`/`anvil` dyld | Homebrew `libusb` |

Linux (Ubuntu 22.04 style) substitutes: `apt install llvm-15-dev libmlir-15-dev`
and `LLVM_PREFIX=/usr/lib/llvm-15`.

### macOS Foundry + libusb

Hardened Foundry binaries may fail with
`Library not loaded: …/libusb-1.0.0.dylib`. Pass the library directory under a
**non-DYLD** name the scripts already honor:

```bash
# Example: Homebrew Cellar path (adjust to your install)
export NEUTRINO_FOUNDRY_DYLD_LIBRARY_PATH="$(brew --prefix libusb)/lib"
# or, if brew --prefix is not on PATH:
# export NEUTRINO_FOUNDRY_DYLD_LIBRARY_PATH=/path/to/Cellar/libusb/1.0.30/lib
```

The demo scripts copy that into `DYLD_LIBRARY_PATH` for their process. Setting
`DYLD_*` in the parent shell alone is often stripped by macOS before bash starts.

## Build the toolchain (from a clean clone)

```bash
git clone https://github.com/neutrinopr/neutrino-language.git
cd neutrino-language

# Point CMake at MLIR 15 (Homebrew example):
export LLVM_PREFIX="$(brew --prefix llvm@15 2>/dev/null || brew --prefix llvm)"
# Ubuntu example:
# export LLVM_PREFIX=/usr/lib/llvm-15

cmake -S . -B out -G Ninja \
  -DMLIR_DIR="$LLVM_PREFIX/lib/cmake/mlir" \
  -DLLVM_DIR="$LLVM_PREFIX/lib/cmake/llvm" \
  -DCMAKE_BUILD_TYPE=Release

# The frozen M6 CMake graph declares the Solidity generator but does not order
# its MLIR object consumers under parallel Ninja. Generate that declared build
# product first, then build the compiler.
ninja -C out solidity-emit-builders-inc
ninja -C out neutrino-gen
```

Binaries land at `out/tools/neutrino-gen/neutrino-gen`.

## Run the demos

From the repository root, with Foundry and `solc` on `PATH`:

```bash
export BIN_DIR="$PWD/out/tools/neutrino-gen"
# macOS + libusb only when needed:
# export NEUTRINO_FOUNDRY_DYLD_LIBRARY_PATH="$(brew --prefix libusb)/lib"

./demo/run_local_demo.sh            # Demo 1 — pipeline
./demo/run_agent_coordination.sh    # Demo 2 — two agents, no channel
./demo/run_kyc_paid_attestation.sh  # Demo 3 — KYC + keccak + local registry
./demo/run_authoring_demo.sh        # Demo 4 — untrusted authoring, verified compile
```

Each script exits 0 and prints `DEMO PASS` on success. Missing tools print a
clear `DEMO FAIL: missing …` line instead of a bare shell error.

### `CONTRACT_DIR` override ( AD5)

To drive the same harness against a **pre-generated** Solidity project (another
pipeline's emit, or a capture from this translator), set:

```bash
export CONTRACT_DIR=/path/to/neutrino-gen-layout   # must contain src/*.sol
./demo/run_local_demo.sh   # skips neutrino-gen; solc + deploy + beats unchanged
```

Bytecode-binding checks still run against this run's `solc` output. Consumer:
 AD5 (artifact-adapter first light — same demos, other emitter).

## What this does **not** claim

- Not a production deployment path.
- **No Docker entry path in this snapshot.** Build with the pinned LLVM/MLIR
  toolchain described above.
- Alignment language for standards is governed by `demo/STANDARDS.md` and the
  wording bars in `demo/DEMO.md` (no conformance claims against drafts).
