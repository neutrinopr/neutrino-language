# Slot-Aware Artifact Contract (Phase 9)

Normative contract for what a **slot-ready** translator bundle must contain, so a
runtime/network slot can understand which coordination operations, commitments,
and compensation behavior a generated artifact supports.

**Implemented (Phase 12):** `neutrino-gen --target=slot` (capability
`generate.slot`, also a `neutrino-bundle` target) emits this subtree from the
procedure + value-model types. The committed slot fixtures are the generator's
output; `make test` check [11] diffs generated output against them.

This is the translator side only. The **Slot Operation Interface is owned by
`neutrino-network`**; this document targets the operation set it defines and is
the reconciliation point when the two are wired together (Phase 13). Slot fixtures
live under each domain's domain-major dir
[`examples/domains/<domain>/generated/slot/`](../../examples/domains) (); all
domains are migrated and the legacy `examples/slot/` container is retired.
`scripts/validate-slot-fixtures.sh` validates the fixtures (and still tolerates the
legacy path if a future domain lands there first).

## Slot subtree

A slot-ready bundle adds a `slot/` subtree alongside the existing per-target
artifacts:

```text
out/
  bundle.json
  slot/
    capability.json        capability descriptor: procedure, parties, ops, backends, value-model gaps
    operations.json        each op -> the generated artifact behavior it maps to
    compensation.json      what compensate means for this procedure/backends
    transcript.json        hash-chain + anchoring policy
    envelope.schema.json   the canonical operation envelope schema
    capability.lock        negotiation identity: per-file hashes + a rolled-up
                           capabilityHash (the Fabric EnvelopeHeader.schema_hash
                           bridge). Scope = the wire-contract files
                           (capability/operations/compensation/transcript);
                           envelope.schema.json is excluded (console/docs).
                           capabilityHash = lowercase hex of the 32-byte sha256 over
                           concat(sorted(basename + ':' + sha256(file) + newline));
                           decode the hex to 32 bytes for EnvelopeHeader.schema_hash.
    binding-topology.json  (D1b) the abstract organization -> participant -> slot
                           hierarchy with stable ids + late-binding metadata, for
                           Binding Manifest validation. Emitted ONLY when the source
                           declares participants. Advisory model metadata, NOT the
                           wire contract: EXCLUDED from capability.lock / capabilityHash,
                           so adding it never drifts an existing capability hash.
  solidity/ ...
  postgres/ ...
```

### `binding-topology.json` (D1b / Phase 22B)

The base `organization → participant → slot` model the rest of the system binds
against. Each declared participant gets one abstract coordination slot
(`slotId = <capability>#<participant>`) nested under its organization, carrying the
late-binding policy (`lateBindingMode`, `allowedRuntimes`, `minAssurance`,
`evidenceProfile`, optional `authorizedBinder`). A later **Binding Manifest** names
and validates an `(organizationId, participantId, slotId)` triple against this file;
an unknown name is rejected. It is **not** part of the negotiated wire contract, so
it is excluded from `capability.lock`/`capabilityHash` and is only emitted when the
source declares `participant`s (participant-free sources stay byte-stable). The
schema is [`schemas/slot-binding-topology.schema.json`](../schemas/slot-binding-topology.schema.json)
(fail-closed); `scripts/validators/validate_binding_topology.py` enforces it plus cross-refs
(slotId uniqueness/format, `crossOrganization` consistency, fixed-slot invariants).
Static generation never claims assurance above `A1`.

(`generate.slot` embeds the canonical envelope schema per bundle as
`slot/envelope.schema.json`; each domain's slot fixture carries its generated copy
under `examples/domains/<domain>/generated/slot/`.)

## Operation lifecycle

`OPEN → NEGOTIATE → PROPOSE → COMMIT | REJECT → (COMPENSATE) → CLOSE`

**Oracle-gated variant (M5 oracle S3, ).** When the spec carries an attestation policy, the machine
inserts an explicit M-of-N quorum gate before the post:

`… → PROPOSE → AWAIT_QUORUM → REACH_QUORUM → COMMIT | (TIMEOUT → ABORT|ESCALATE) → …`

with states `QUORUM_PENDING → QUORUM_MET | QUORUM_TIMEOUT`. The post (`COMMIT`) departs **only** from
`QUORUM_MET`, so `COMMIT` advertises `requiresPrior: REACH_QUORUM` and a leg can never fire on `< M`
(fail-closed by construction). On the deadline the machine takes the **declared** fallback: `abort` →
the aborted terminal, `escalate` → a `contested` terminal (`ESCALATED`). Because the envelope enum and
operation vocabulary are projected from the machine, these ops appear in the wire contract too; a
non-oracle spec keeps the exact `OPEN..CLOSE` machine (byte-identical artifacts).

Operation names are the reconciled Fabric Slot Operation Interface names
(`neutrino-network`). The transport-level `DISCOVER` message is **not** a capability
operation and is omitted from the capability/operations artifacts.

> **Projected from the spec, not invented here (M5 WP3, ).** The operation
> vocabulary and the compensable/non-compensable partition are **derived from the
> canonical lifecycle machine** ([`Lifecycle.h`](../../include/Neutrino/Lifecycle.h)) —
> the single machine the [capability spec](CAPABILITY_SPEC.md)'s `lifecycle` and the
> slot artifacts both serialize. GenSlot no longer hand-lists these; a slot can't
> advertise or compensate an operation the spec's lifecycle doesn't define (self-test
> `[80]` cross-checks every slot lifecycle surface against `capability-spec.json`). Because the
> lifecycle is source-derived, **`--target=slot` needs no `--scenario`** (like the
> spec) and its output is byte-identical with or without one. WP3 unifies the
> **spec and slot** onto this one machine; the Solidity on-chain surface
> (`attest`/`execute`/`Reconciled`) still emits its own copy and joins the same
> model at **** (the spec's lifecycle-projection fixture already proves it can).

- **OPEN** — open a slot session for a workflow key. No prior.
- **NEGOTIATE** — agree the capability/terms (maps to the attestation gate).
- **PROPOSE** — stage the value-moving spec (compute + staged debit/credit legs).
- **COMMIT** — apply it (balanced post, replay-protected). Must reference a prior
  `PROPOSE` via `correlationId`.
- **REJECT** — decline a proposal; no postings; recorded in the transcript.
- **COMPENSATE** — reverse a prior `COMMIT` (references it via `correlationId`).
- **CLOSE** — reconcile and finalize; no prior required.

## Envelope

Every operation is an envelope conforming to `envelope.schema.json`. Always-required
fields: `sessionId`, `operationId`, `operation`, `capability`, `capabilityVersion`,
`participant`, `counterparty`, `payload`, `payloadHash`, `previousTranscriptHash`,
`signature`. `correlationId` is **required only for `COMMIT` / `REJECT` /
`COMPENSATE`** (the operationId of the prior `PROPOSE`/`COMMIT`) and is absent on
`OPEN`/`CLOSE` — the schema encodes this with a conditional (`allOf`/`if`/`then`).
Optional: `diagnostics`, `anchorRef`.

Note: `envelope.schema.json` is a console/docs artifact, not the Fabric wire
contract; the runtime produces transcripts in its own protobuf `EnvelopeHeader`
format and references this capability via `capability_name` + `capability_version` +
`schema_hash` (the `capabilityHash` in `capability.lock`).

This is a **business-coordination** envelope, not a generic RPC call — payloads
carry offer terms, postings, computed values, and evidence references, keyed to a
procedure capability.

## Design decisions (the debate's open questions, settled for this phase)

- **Format:** Markdown + JSON Schema now; Protobuf only if/when `neutrino-network`
  requires it.
- **COMMIT requires PROPOSE:** yes — value-moving `COMMIT`/`REJECT`/`COMPENSATE`
  must reference a prior `PROPOSE` (`correlationId`). `OPEN`/`CLOSE` are
  unilateral.
- **Anchoring:** per **session close** by default; value-moving `commit` may also
  anchor. The blockchain slot is **coordinator-of-record / anchor**, never the
  business source of truth.
- **Compensation:** the interface only defines that `compensate` exists; *what*
  it reverses is domain/backend-specific (`compensation.json`).
- **Transcript:** the hash chain **includes rejected proposals and diagnostics**,
  so the audit trail is complete.
- **Identity (mock phase):** typed party ids (`role:id`) + local fixture signing
  keys. Real key/DID model is deferred.

## Artifact → operation mapping

The generated coordination artifacts already contain everything the operations
need; Phase 9 names the mapping (full per-domain detail in each
`operations.json`):

| operation | Solidity coordination contract | PostgreSQL procedure |
| --- | --- | --- |
| OPEN | initialize workflow key (status NEW) | reserve idempotency key |
| NEGOTIATE | attestation gate | (precondition check) |
| PROPOSE | compute + staged debit/credit checkpoints | staged postings |
| COMMIT | `assert_balanced` + post, replay-protected | atomic posting, replay-safe |
| REJECT | gate decline (no postings) | no postings |
| COMPENSATE | reversing checkpoint (net → 0) | reversing posting |
| CLOSE | net positions + final status + events | reconciliation |

## Gaps handed to Phase 10 (value model)

Phase 9 is implementable as a contract today, but slot envelopes need typed
values that the IR does not model yet:

- **money** — postings/`computed` are integer minor units; envelopes need typed
  money + currency (not bare ints).
- **parties** — `participant`/`counterparty` are `role:id` strings; signatures
  and permissions need typed party identities.
- **time** — only if a business operation becomes time-dependent.
- **evidence** — `evidence`/`anchorRef` need hashable typed references, not
  free-form strings.

These are the explicit inputs to Phase 10; Phase 12 (`generate.slot`) builds on
both.

## Validate the fixtures

```bash
scripts/validate-slot-fixtures.sh
```

Checks every domain has the required `slot/` files and that each
`envelope.example.json` validates against `envelope.schema.json`.
