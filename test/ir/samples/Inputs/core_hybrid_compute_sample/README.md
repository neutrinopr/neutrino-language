# core_hybrid_compute_sample

The strategy [] M3 sample as **current-valid** translator artifacts (issue ) — the
**fourth coverage class** beyond the three strategy  samples: a **deterministic EVM core
slot** coordinates **async conventional adapters** for storage, compute, oracle verification,
and settlement.

## Flow

A Requester funds a bounty escrowed by the EVM core; a storage adapter observes the input and
the core locks the job for one processor (mutex); a compute worker produces an output to
destination storage; an oracle verifies the output against the input hash and submits
proof/earmark evidence; the core completes the job, releases the mutex, and settles the
processor — fail-closed if verification is not admitted.

- **L1** [`source/core_hybrid_compute_sample.neu`](source/core_hybrid_compute_sample.neu) — real
  procedure-oriented `.neu`: the balanced bounty escrow (Requester funds `requester.bounty`,
  the EVM core holds `core.escrow`). The **Demand + Supply + neutral Verification triad** is
  first-class and bound: `Requester` (demand, fixed) + six `to_be_bound` slots — **EvmCore**
  (orchestration, `evm`), **Processor** (supply, `jvm`), **Verifier** (neutral verification,
  `jvm`), **SourceStorage** / **DestStorage** / **ComputeWorker** (conventional adapters,
  `jvm`). The EVM core is **deterministic orchestration state, not the universal source of
  truth**, and the conventional slots realize on `jvm` — distinct from the EVM core, never
  pretending to be EVM. No pseudo `capability`/`domain_semantics`/`lifecycle`/`mlir_modeling` syntax.
- **L2** [`examples/l2-domain-semantics/core_hybrid_compute_sample.l2.json`](../../l2-domain-semantics/core_hybrid_compute_sample.l2.json)
  — declares the async-observation evidence requirements **`input_hash` / `compute_output` /
  `verification_proof`**, parameters **`bounty_amount` / `verification_timeout` /
  `mutex_lease`**, and structured invariants `verification_before_settlement` /
  `escrow_conserved` with `lease_expired` / `verification_failed` / `settlement_reversal`
  failure modes. Async storage/EVM observations are modelled as evidence-bearing concepts.
- **L3** [`core_hybrid_compute_sample.l3.binding.json`](../../binding-manifests/core_hybrid_compute_sample.l3.binding.json)
  — binds the **EVM core slot concretely** (`backendProfile evm.v1`, the bounty/SLA/verifier-fee
  parameters) and the **conventional `jvm` slots deferred** (`deferred: true`) — Processor,
  Verifier (with `verifier_attestation`/`verification_proof` evidence refs), and the storage/
  compute adapters. A deferred binding has not pinned its concrete runtime/profile, so it is
  exempt from the `backendProfile`-family check — that is how the hybrid binds an `evm` core and
  defers `jvm` adapters in one manifest (a *concrete* `jvm` binding under `evm.v1` still fails
  `NEU-3002`). Validation **status: `deferred`**.

## Boundary: M3 declares, M4 runs

L2 only **declares** the evidence-bearing transitions and the EVM core is deterministic
orchestration **state**, not a runtime. **M4 owns** runtime storage/compute/oracle observation,
execution, and evidence admission (`neutrino-/`, `neutrino-network/`);
there is no real runtime here. The Solidity EVM-core contract is a future-profile build target
(`neutrino-solidity-samples`), not committed/compiled in this sample.

## Validation

Pinned by self-test `[70]`: L1 lowers (7 participants, 4 `to_be_bound` slots); the L2 sidecar
validates; the evidence set is distinct from the strategy  samples; the L3 manifest validates
**status `deferred`** (EVM core concrete + async adapters deferred); and targeted negatives fail
closed — missing EVM core binding (`NEU-1004`), orphan async adapter binding (`NEU-1003`),
settlement-slot assurance degradation (`NEU-2001`), plus L2 malformed evidence (`L2-1001`) and
undeclared parameter (`L2-1008`). The L2 positive + negatives also run in the fast tier
(`make test-fast`); L3 is full-tier (needs the generated binding-topology). Registered in the M3
sample portfolio ([`docs/domains/M3_SAMPLE_PORTFOLIO.md`](../../../docs/domains/M3_SAMPLE_PORTFOLIO.md), ).

[]: internal-tracker/neutrino-
