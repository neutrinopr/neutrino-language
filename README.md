# Neutrino Language

Neutrino is a small language and a deterministic compiler for **multi-party
coordination agreements**. You specify a coordination capability once in `.neu`
source; the compiler verifies it and generates executable realizations for
heterogeneous targets — today **Solidity/Foundry** and **PostgreSQL** — from one
canonical, machine-readable contract.

Fixed inputs produce fixed artifacts, every path emits machine-readable
diagnostics, and the generated realizations are checked to behave **equivalently
across backends**. That makes an agreement easy to run locally, audit in CI, and
trust across very different runtimes.

## Why

Multi-party agreements are usually reimplemented once per environment — a smart
contract here, a database procedure there — with no guarantee the two agree.
Neutrino inverts that:

- **One verified specification, many realizations.** Author and verify the
  agreement once; compile it to each target deterministically.
- **Cross-backend equivalence is checked, not assumed.** The same source and
  scenario are compiled to Solidity and PostgreSQL, and the two are compared for
  equivalent observable behavior.
- **Fail-closed by construction.** Unsupported syntax, invalid scenarios, and
  target-profile violations are rejected with stable diagnostic codes rather
  than silently degraded.
- **Everything is inspectable.** Canonical JSON contracts, hashes, manifests,
  and generated code are meant to be diffed and regenerated from source.

## How it works

```text
.neu source
  -> neutrino MLIR (registered dialect)
  -> verifier and analysis passes
  -> capability-spec.json        (canonical, target-neutral contract)
  -> Solidity / PostgreSQL projects  +  cross-backend equivalence report
```

A capability's semantic identity lives in the `capability-spec.json`. A separate
optional **scenario** supplies concrete test values and expected observable
behavior; it is not part of that identity.

## Cross-backend equivalence

The headline capability. From a single source/scenario pair, Neutrino renders
both backends and checks that they exhibit equivalent observable behavior:

```bash
make equivalence \
  EXAMPLE=test/ir/samples/Inputs/core_hybrid_compute_sample/source/core_hybrid_compute_sample.neu \
  SCENARIO=test/ir/samples/Inputs/core_hybrid_compute_sample/scenario/core_hybrid_compute_sample_happy_path.json
```

The same check is available directly as the `neutrino-equiv` tool.

## Try it in a few minutes (no compiler build)

You can see the core idea without building the native toolchain:

1. **One capability, two realizations — side by side.** Open the committed
   generated artifacts for a single domain pack and compare the two backends
   rendered from the *same* source:

   - Solidity: [`domains/packs/token_mint/pack/generated/solidity/src/`](domains/packs/token_mint/pack/generated/solidity/src/)
   - PostgreSQL: [`domains/packs/token_mint/pack/generated/postgres/`](domains/packs/token_mint/pack/generated/postgres/)

2. **Claim-honesty sweep** (pure shell, no build):

   ```bash
   bash demo/check_claims.sh
   ```

   This checks that the documentation does not overclaim relative to the
   artifacts. It is a wording/claim check — **not** a determinism proof; the
   behavioral and cross-backend equivalence checks run under the build path
   below.

3. **Run a demo build-free** (needs Foundry, not the compiler): the demo
   scripts accept a `CONTRACT_DIR` override that points at pre-generated
   contracts — see [`demo/QUICKSTART.md`](demo/QUICKSTART.md).

## Full path (with the compiler)

```bash
make build         # configure and build the native tools into out/ (LLVM/MLIR 15)
make test          # compiler self-test suite
make demo          # compile the default agreement and drive it end to end
make equivalence   # render both backends and compare
```

`make build` compiles against LLVM/MLIR 15 and takes longer than the quick path
above. The Makefile auto-detects LLVM via Homebrew or `llvm-config`; override
with `make build LLVM_PREFIX=/usr/lib/llvm-15`.

### Requirements

- **Compiler:** CMake 3.20+, Ninja, a C++17 compiler, LLVM/MLIR 15 dev files,
  Python 3.
- **Deeper validation (optional):** `FileCheck`, `solc`, Foundry (`forge`),
  Docker/Colima for PostgreSQL integration, `clang-format`/`clang-tidy`.

## Demos

The [demo/](demo/) directory drives the compiled artifacts coordinating real
agents end to end on a local Ethereum chain (anvil). The scripts exercise the
Solidity backend:

- **`run_local_demo.sh`** — compile an agreement to Solidity, deploy it, and
  drive both an approved run and a policy-suppressed run against the same
  contract.
- **`run_agent_coordination.sh`** — two agents with no channel between them
  coordinate through the contract alone: refusal before attestation,
  adaptation, execution, replay refusal, and an audit from chain state.
- **`run_kyc_paid_attestation.sh`** — agents do real verification work on a
  document, post an unattributed on-chain checkpoint, and settle a fee via a
  scripted demo-ERC20 transfer, with agent registration and a chain-state audit.
- **`run_authoring_demo.sh`** — an untrusted candidate translation of a
  natural-language agreement is verified (and a deliberate imbalance refused),
  then driven through an on-chain pay-for-work path.

Start with [`demo/DEMO.md`](demo/DEMO.md) for the narrative,
[`demo/QUICKSTART.md`](demo/QUICKSTART.md) for the exact clean-clone commands,
and [`demo/STANDARDS.md`](demo/STANDARDS.md) for how the demos align with
Ethereum standards.

## The `.neu` language

`.neu` is a small procedure language for typed value movement and coordination
invariants:

```hcl
procedure core_sample_installment {
    trigger purchase_financed

    input merchant_id : party
    input principal   : money
    input subsidy_pct : decimal
    input currency    : currency

    compute subsidy = principal * subsidy_pct / 100

    debit merchant_subsidy {
        ledger = "acquirer.merchant_balance"
        party  = %merchant_id
        amount = %subsidy
        currency = %currency
    }

    assert balanced
}
```

The normative language contract is
[`docs/language/NEU_LANGUAGE_SPEC.md`](docs/language/NEU_LANGUAGE_SPEC.md); the
value model is [`docs/language/VALUE_MODEL.md`](docs/language/VALUE_MODEL.md).

## Reference

- **Generation targets** (`capability-spec`, `solidity`, `postgres`, `views`,
  `coverage`, `security`, and more) and the full backend inventory:
  [`docs/backends/BACKEND_TARGET_CATALOG.md`](docs/backends/BACKEND_TARGET_CATALOG.md).
- **Capability-spec contract:**
  [`docs/spec/CAPABILITY_SPEC.md`](docs/spec/CAPABILITY_SPEC.md).
- **Testing architecture** (fast / full / acceptance tiers, CTest, core-only
  graph): [`docs/testing/TESTING.md`](docs/testing/TESTING.md).
- **Compatibility surface:** the machine-readable manifest
  [`COMPATIBILITY.json`](COMPATIBILITY.json) records tool, dialect, schema, and
  artifact contract versions for consumers deciding whether a compiled artifact
  can be accepted.
- **Contributing & repository layout:** [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Security policy:** [`SECURITY.md`](SECURITY.md).

Every `neutrino-gen` run writes a `manifest.json` (inputs, hashes, artifact
paths, tool version, success state) and a `diagnostics.json` (stable codes,
ordered failure causes). Generation is deterministic and meant to be diffed and
regenerated.

## Scope

This repository is the Neutrino language and its compiler. The rendered backend
projects are coordination artifacts — they record workflow status, replay
protection, net positions, and generated tests — not wallets, fund-custody
systems, or authoritative settlement ledgers. Generated contracts are
experimental and have not been independently audited (see
[`SECURITY.md`](SECURITY.md)). Natural-language authoring appears only as
untrusted, user-side input to the compiler (see the authoring demo); it is not a
component of the compiler itself.

## License

Apache-2.0 — see [`LICENSE`](LICENSE). Third-party components are listed in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
