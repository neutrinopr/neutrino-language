# Neutrino Solidity backend clean-clone candidate

This directory is the mechanical  extraction proof. It materializes only
the files in `extraction-manifest.json`, regenerates all declared TableGen build
products, builds the real `neutrino-solidity-backend` protocol entry, and drives
it from the backend-free installed core.

Run:

```sh
python3 packaging/solidity/scripts/check_clean_clone.py \
  --core-prefix /path/to/core-only-install \
  --llvm-dir /path/to/llvm/lib/cmake/llvm \
  --receipt /tmp/solidity-extraction-receipt.json
```

The proof requires CMake, Ninja, LLVM/`llvm-tblgen` 15, Python 3, and Foundry.
It configures in a fresh temporary tree while an OS sandbox denies reads from
the translator checkout, builds and runs the focused generated-render test,
invokes `neutrino-gen`, `neutrino-bundle`, and `neutrino-equiv` through the
verified package catalog and protocol, binds their outputs to the dispatch
receipt, compares the resulting Solidity contract with the pinned monorepo
baseline, and runs the existing Foundry behavior test. Missing, duplicate,
tampered, disappeared, and protocol-incompatible package probes fail closed;
there is no core fallback.

The manifest classifies the exact target-blind projection consumer, protocol,
recipe runtime, and CodeText sources as the versioned
`neutrino.backend-source-runtime/1` dependency. The compiler-only projection
constructor is excluded. Its exact source/header identities and LLVM 15
dependency are frozen in
`packaging/shared/backend-source-runtime-v1.json`. Compiler-derived closures
are checked independently for the shared-runtime objects and each Solidity
target; the six Solidity-only headers cannot be absorbed into the shared
runtime. The contract explicitly marks the two header-only consumer APIs whose
closures appear in the package-private target rather than runtime objects. No
installed C++ ABI crosses the process boundary.

Core launches the package with the versioned
`neutrino.backend-startup/1` argument contract and a private absolute path to
the exact descriptor bytes it already verified. The package independently
recomputes the descriptor manifest identity before protocol negotiation.
Missing, malformed, and digest-mismatched startup descriptors fail before a
Hello frame; there is no environment or search-path fallback.

The receipt hashes every one of the 13 installed-core artifacts actually
copied and executed, records their canonical tree digest, and binds the
manifested source blobs to the exact Git commit/tree. A one-byte core-entry
mutation must fail before invocation. A declared CMake input is also mutated
to read the source checkout; both the declared-input audit and the checkout-
denying sandbox must reject it.

`licenseIdentity` remains `pending:`. This candidate must not be published
and  must not be declared complete until  resolves every license and
provenance row.
