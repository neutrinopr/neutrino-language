# Provisioning the Forge toolchain for the `requires-forge` rows ()

Nine CTest rows drive a real Foundry `forge`:

| row | launch route |
| --- | --- |
| `acceptance-solidity` | `run.sh` → `forge_test` (direct) |
| `acceptance-solidity-explicit-time` | `run.sh` → `forge_test` (direct) |
| `acceptance-solidity-reference` | `run.sh` → `forge_test` (direct) |
| `acceptance-oracle-coordination` | `run.sh` → `forge_test` (direct) |
| `acceptance-oracle-temporal` | `run.sh` → `forge_test` (direct) |
| `acceptance-compliant-transfer` | `run.sh` → `forge_test` (direct) + a Docker Postgres |
| `acceptance-curated-solidity` | `run.sh` → `test/curated/check_solidity_goldens.py` → `forge` |
| `acceptance-equivalence` | `run.sh` → `neutrino-equiv` → `/bin/sh` → `forge` |
| `acceptance-equivalence-scheme` | `run.sh` → `neutrino-equiv` → `/bin/sh` → `forge` |

plus `generalism-matrix-e2e` (through `neutrino-equiv`'s live adapters) and the two provisioning
rows described below.

## The macOS defect this provisioning exists for

A prebuilt Foundry release carries an **absolute** Mach-O load command for `libusb` under the
*default* Homebrew prefix:

```
$ otool -L "$(command -v forge)"
	…
	/usr/local/opt/libusb/lib/libusb-1.0.0.dylib (compatibility version 6.0.0, …)
```

On a machine whose Homebrew prefix is anything else (an Apple-silicon `/opt/homebrew`, a per-user
prefix, an offloaded prefix on external storage) `dyld` cannot resolve that path and forge dies
before it parses its own arguments:

```
dyld[…]: Library not loaded: /usr/local/opt/libusb/lib/libusb-1.0.0.dylib
Abort trap: 6
```

Every consuming row then fails **without measuring any conformance** — an infrastructure defect
wearing a conformance failure's clothes.

Three tempting "fixes" are forbidden and are not used here: a hand-created `/usr/local/opt/libusb`
symlink (machine-global, undocumented, needs root), `install_name_tool` surgery on the shipped
binary (mutates the pinned tool identity, breaks its signature), and an `export` in a shell profile
(invisible to CI and to anyone who runs bare `ctest`).

## The mechanism

One **declared tool identity**, derived in exactly one place and attached to the tests themselves.

* `scripts/gates/check_forge_toolchain.py` is the **single derivation authority**. Its
  `--print-library-path` yields the declared native-library prefix:
  `NEUTRINO_FORGE_LIBRARY_PATH` if set, else `$(brew --prefix libusb)/lib` on Darwin, else nothing
  (Linux forge resolves through the ordinary system loader). Nothing else may re-derive it — a fast
  check fails the build if a second `brew --prefix libusb` appears in cmake, the Makefile or the
  acceptance dispatcher.
* `cmake/NeutrinoForgeToolchain.cmake` runs that authority at configure time and publishes
  `FORGE`, `SOLC` and `FORGE_DYLD_LIBRARY_PATH` as the CTest **`ENVIRONMENT` property** of every
  `requires-forge` row. So a bare `ctest -L acceptance` carries the same identity as
  `make acceptance-suite`, with no shell-profile dependency. It is visible in
  `ctest --show-only=json-v1`.
* The value travels in the **neutral** `FORGE_DYLD_LIBRARY_PATH`, never in `DYLD_LIBRARY_PATH`.
  macOS SIP strips every `DYLD_*` variable from the environment of a protected process, so a
  `DYLD_LIBRARY_PATH` set by CTest is already gone by the time `/bin/bash run.sh` — let alone
  `neutrino-equiv` — runs.
* Each of the three routes that **directly spawns** forge re-materialises it as
  `DYLD_LIBRARY_PATH` at that spawn, and only there:
  `test/acceptance/run.sh:forge_test` (`env DYLD_LIBRARY_PATH=… forge test`),
  `test/curated/check_solidity_goldens.py:forge_env()` (the child `env=`), and
  `tools/neutrino-equiv/neutrino-equiv.cpp:forgeCmd()` (inlined into the `/bin/sh` command
  immediately before `exec`).

Nothing in a tracked file hard-codes a workstation path; the recorded paths live only in a machine
receipt.

## Clean setup from scratch (macOS)

```sh
# 1. The native dependency, from Homebrew — whatever prefix Homebrew uses on this machine.
brew install libusb
brew --prefix libusb                       # the derivation reads exactly this

# 2. Foundry, pinned into the repo-local prefix the Makefile/cmake look for first.
make setup-foundry                         # installs .foundry/bin/{forge,cast,anvil,chisel}
#    (an existing ~/.foundry install is equally fine: export FORGE=$HOME/.foundry/bin/forge)

# 3. solc.
pip3 install --user solc-select && solc-select install 0.8.35 && solc-select use 0.8.35
#    or: brew install solidity

# 4. Prove the closure resolves — this is the check every acceptance row runs first.
python3 scripts/gates/check_forge_toolchain.py --preflight
#    -> forge 1.7.1 ready (…); declared native library path: …/libusb/lib

# 5. Prove the guard bites (negative probe).
python3 scripts/gates/check_forge_toolchain.py --selftest

# 6. Record this machine.
make forge-toolchain-receipt               # writes docs/testing/forge-toolchain-receipts/…
make forge-toolchain-verify                # re-derives and compares

# 7. Configure + run. No env exports are needed; cmake supplies the identity.
make build BUILD_DIR=<dir>
ctest --test-dir <dir> -L requires-forge --output-on-failure
```

If Homebrew is not the provisioning route on some box, point the mechanism at whatever directory
holds the dependency — the mechanism is parameterized, not Homebrew-specific:

```sh
cmake -S . -B <dir> -DNEUTRINO_FORGE_LIBRARY_PATH=/path/to/dir/with/libusb-1.0.0.dylib …
# or, for a direct run.sh / make invocation:
NEUTRINO_FORGE_LIBRARY_PATH=/path/to/dir make acceptance-suite
```

`-DNEUTRINO_FORGE=/path/to/forge` and `-DNEUTRINO_SOLC=/path/to/solc` override the discovered
executables the same way.

## The preflight, and why it is not a skip

`test/acceptance/run.sh` distinguishes three states:

| state | outcome |
| --- | --- |
| forge is **absent** | `SKIP` (exit 77), or a hard failure under `NEUTRINO_REQUIRE_TOOLS` — unchanged |
| forge is present but its **native closure does not resolve** | `INFRASTRUCTURE` (exit **66**) before any render/compile/execute |
| forge runs | the row's actual conformance result |

The middle row is the whole point: a provisioning defect must never be reported as a backend
result, and must never be quietly skipped either. Its diagnostic names the binary, the declared
prefix, and every unresolved dependency.

## Receipts

`docs/testing/forge-toolchain-receipts/*.receipt.json` (schema:
`docs/schemas/forge-toolchain-receipt.schema.json`) record, per machine: OS/release/arch; the
forge path, version, upstream commit SHA and **binary digest**; every non-system Mach-O load
command with the prefix it actually resolves from and **its digest**; and the LLVM/MLIR and solc
coordinates. `--verify-receipt` re-derives on the current machine and fails on any drift — a silent
`foundryup` or a Homebrew `libusb` upgrade changes the tool identity and is caught rather than
absorbed. On a machine the receipt does not record it reports not-applicable (77), never a pass.

## Rows that enforce all of this

| row | what it proves |
| --- | --- |
| `forge-toolchain-probe` | the negative probe: with the declared dependency renamed inside a private copy of the closure, `--preflight` fails as infrastructure |
| `forge-toolchain-receipt-<machine>` | the recorded receipt still describes this machine |
| `fast-forge-toolchain-receipt` | (no build, no toolchain) receipt/schema structure, the single-derivation rule, every direct-spawn route re-materialising the loader variable, every `requires-forge` kind preflighting first, and every registered acceptance KIND having a `run.sh` case |
