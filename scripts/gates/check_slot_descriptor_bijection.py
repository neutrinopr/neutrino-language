#!/usr/bin/env python3
"""Slot-descriptor authority BIJECTION ( M7 S0-C1).

Authorized by the architect S0-C3 verdict `S0-REVISE-PARTITION` (). This is
C1 MODELLING ONLY: it grants no deletion, no generator retirement, no
backend-private schema fork, no  reversal, and no  implementation. It
changes no generator behaviour — it models where every emitted field comes from.

RELATIONSHIP TO C0
  The C0 census (`check_slot_descriptor_authority.py`, merged) owns WHICH fields
  exist and proves each is witnessed by a committed domain. This gate IMPORTS that
  row set rather than re-deriving it, so the bijection can never drift from the
  observations: every C0 row must have exactly one C1 derivation, and a derivation
  may not exist for a field C0 does not witness.

THE REVISED AUTHORITY MODEL (from the S0-C3 ruling)
  semantic-input        the versioned capability/agreement spec — the SOLE
                        presently-observed semantic input authority.
  descriptor-contract   schema framing, closed literals, defaults, ordering,
                        canonicalization and receipt/hash algorithms, owned by ONE
                        versioned, target-neutral slot-descriptor contract. This is
                        CONTRACT OWNERSHIP: it is not a second semantic input, and
                        it is not permission to leave a row unowned.
  unresolved-decision   an explicitly named open adjudication. Permitted ONLY for
                        the exceptions the verdict named, each with a stated
                        question and options — never as a dumping ground.

  finalized-projection / target-profile / deploy-coordinate remain ZERO-ROW
  authorities. C1 must not populate them aspirationally: they become available only
  when an explicit typed input is actually wired AND mechanically witnessed.

C1 EXIT BAR ENFORCED HERE
  * zero unnamed residuals — every one of the C0 rows resolves to an owned contract
    item, a typed derivation from the semantic input, or a named unresolved decision;
  * one `source-or-contract-item -> transformation -> emitted-field` chain per row,
    each naming its canonical order and validation owner;
  * one-to-many / many-to-one relationships and cross-artifact invariants are
    explicit, and values that must agree SHARE ONE derivation id;
  * mutations bite for source substitution, ordering drift, duplicated independent
    derivation, and newly introduced target/deploy authority.

Usage:
  check_slot_descriptor_bijection.py --write     # (re)bank the bijection model
  check_slot_descriptor_bijection.py             # verify committed == fresh
  check_slot_descriptor_bijection.py --selftest  # non-vacuity mutations
  check_slot_descriptor_bijection.py --probe ID  # one tamper probe
"""
import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_slot_descriptor_authority as c0  # noqa: E402

REPO = c0.REPO
DEFAULT_OUTPUT = "docs/slot-descriptor-bijection.json"
KIND = "neutrino.slot-descriptor-bijection"
SCHEMA_VERSION = 1

# The revised C1 authority set. The three future authorities are declared so the
# model can PROVE they stay empty, not so rows may be filed under them.
AUTHORITIES = (
    "semantic-input",
    "descriptor-contract",
    "unresolved-decision",
)
FUTURE_AUTHORITIES = ("finalized-projection", "target-profile", "deploy-coordinate")

# Typed transformations. A derivation must name exactly one; `identity` means the
# emitted bytes are the source value verbatim.
TRANSFORMS = (
    "identity",              # emit the source value unchanged
    "constant",              # emit a contract-owned literal
    "prefix-compose",        # structural prefix/join over source values
    "project-field",         # take one named field from each source element
    "project-distinct",      # project, then de-duplicate preserving first appearance
    "filter-project",        # select source elements by predicate, then project
    "machine-vocabulary",    # project the lifecycle machine's operation names
    "predicate",             # reduce sources to a boolean
    "fallback-default",      # source value when present, else a contract default
    "template-interpolate",  # contract-owned template with source names spliced in
    "digest",                # content hash over named inputs
    "table-lookup",          # contract-owned table keyed by a source value
)

# Canonical orders (who decides element/key order).
ORDERS = (
    "source-order",          # first appearance in the source array
    "source-order-distinct",
    "machine-order",         # the lifecycle machine's transition order
    "contract-fixed",        # order frozen by the descriptor contract
    "lexicographic",
    "not-applicable",
)

# ---------------------------------------------------------------------------
# The versioned, target-neutral descriptor contract. Every constant, default,
# ordering rule, canonicalization rule and hash algorithm the emitters own lives
# here as an ITEM WITH AN IDENTITY, so "literal" is never a synonym for "unowned".
# ---------------------------------------------------------------------------
DESCRIPTOR_CONTRACT_VERSION = "neutrino.slot-descriptor-contract/1"

# The artifact set the capability lock is a receipt OVER. Adjudicated in C2 as a
# contract-owned named set; the model enforces the lock covers exactly these.
LOCK_WIRE_SET = ("capability.json", "compensation.json", "operations.json",
                 "transcript.json")
DESCRIPTOR_CONTRACT = {
    "artifact-kind-discriminators": {
        "owns": "the `kind` discriminator string of each descriptor artifact",
        "emitter": "lib/slots/GenSlotSpec.cpp:177,311,349,384,429,506",
        "rationale": "artifact identity is contract framing, not agreement content",
    },
    "envelope-schema-template": {
        "owns": "the frozen slot-operation envelope JSON-Schema — $schema/$id/title/"
                "description/type/additionalProperties/required and every property "
                "type declaration",
        "emitter": "lib/slots/GenSlotSpec.cpp:79-108",
        "rationale": "the wire envelope is a target-neutral interaction contract; "
                     "only its operation enum is projected from the agreement",
    },
    "envelope-correlation-rule": {
        "owns": "the conditional requiring correlationId for a fixed operation subset",
        "emitter": "lib/slots/GenSlotSpec.cpp:88",
        "rationale": "a contract rule over operation names",
        "adjudication": "envelope-hardcoded-op-subset",
    },
    "transcript-hashchain-policy": {
        "owns": "perEnvelope/chain/includesRejected/includesDiagnostics",
        "emitter": "lib/slots/GenSlotSpec.cpp:387-391",
        "rationale": "transcript integrity policy is contract-owned, not per-agreement",
    },
    "transcript-anchoring-policy": {
        "owns": "anchoring default/valueMovingCommit and the anchorRef records/via prose",
        "emitter": "lib/slots/GenSlotSpec.cpp:394-398",
        "rationale": "anchoring policy is contract-owned",
    },
    "operation-prose-table": {
        "owns": "the per-operation `maps` prose table",
        "emitter": "lib/slots/GenSlotSpec.cpp:286-306",
        "rationale": "human-facing description of each contract operation; the "
                     "emitter fails closed when the machine has an op with no entry "
                     "(:316-319), so the table is a total function over the vocabulary",
    },
    "compensation-prose": {
        "owns": "the compensable `how` description",
        "emitter": "lib/slots/GenSlotSpec.cpp:353",
        "rationale": "contract-owned description of the compensation mechanism",
    },
    "compensation-idempotency-template": {
        "owns": "the compensation idempotency key template",
        "emitter": "lib/slots/GenSlotSpec.cpp:364",
        "rationale": "key SHAPE is contract-owned; the procedure name is interpolated "
                     "from the semantic input",
    },
    "binding-topology-schema-version": {
        "owns": "the binding-topology schemaVersion integer",
        "emitter": "lib/slots/GenSlotSpec.cpp:430",
        "rationale": "artifact schema version is contract framing",
    },
    "binding-mode-literal": {
        "owns": 'the "to_be_bound" mode literal emitted inside the flexible-participant '
                "branch of capability.json",
        "emitter": "lib/slots/GenSlotSpec.cpp:200",
        "rationale": "in that branch the value is invariably the one literal — the "
                     "PRESENCE of the block is agreement-conditional, the VALUE is a "
                     "closed contract literal. Contrast binding-topology's "
                     "lateBindingMode, which is emitted unconditionally and IS a "
                     "two-valued predicate over the agreement",
    },
    "binding-assurance-default": {
        "owns": "the minAssurance fallback when the agreement declares none",
        "emitter": "lib/slots/GenSlotSpec.cpp:455-456",
        "rationale": "a contract-owned floor — static generation never claims above "
                     "the base assurance level",
    },
    "binding-evidence-profile-default": {
        "owns": "the per-slot evidenceProfile default",
        "emitter": "lib/slots/GenSlotSpec.cpp:468",
        "rationale": "contract-owned default; no agreement input exists for it today",
    },
    "capability-lock-algorithm": {
        "owns": "the lock hash construction: per-file sha256, lexicographic basename "
                "order, the newline-joined preimage, and the wire-file SET the lock "
                "covers (capability/operations/compensation/transcript)",
        "emitter": "lib/slots/GenSlotSpec.cpp:493-518,566-577",
        "rationale": "a receipt algorithm is contract-owned by the verdict's item 2",
        "adjudication": "lock-crossartifact-inputs",
    },
    "capability-identity-prefix": {
        "owns": "the `coordinate.` capability-identity namespace prefix and the "
                "`<capability>#<participant>` slot-id join",
        "emitter": "lib/slots/GenSlotSpec.cpp:451,528-529",
        "rationale": "identity namespacing is contract framing over an agreement value",
    },
    "transcript-anchor-chain": {
        "owns": "the anchorRef chain identifier",
        "emitter": "lib/slots/GenSlotSpec.cpp:396-398",
        "rationale": "PROVISIONAL — deploy-SHAPED but hardcoded; it is not a "
                     "deploy-coordinate input because nothing supplies it",
        "adjudication": "evm-anchor-hardcoded",
    },
}

# ---------------------------------------------------------------------------
# The contract's OWNED BYTES. A contract item that carries only prose cannot
# reject a changed artifact, so every `constant` chain freezes its value HERE and
# the contract becomes the authority: a committed artifact that no longer matches
# fails closed. Changing a value is then a deliberate, reviewable contract edit
# rather than silent drift. Bootstrapped once from the committed artifacts and
# verified to be domain-invariant (a value that differed per domain would not be
# a constant).
CONTRACT_CONSTANTS = {
    'binding-topology.json::kind':
        'neutrino.slot-binding-topology',
    'binding-topology.json::organizations[].participants[].slots[].evidenceProfile':
        None,
    'binding-topology.json::schemaVersion':
        1,
    'capability.json::backends[]':
        ['solidity', 'postgres'],
    'capability.json::declaredParticipants[].binding.mode':
        'to_be_bound',
    'capability.json::kind':
        'neutrino.slot-capability',
    'capability.lock::kind':
        'neutrino.capability-lock',
    'capability.lock::method':
        "lowercase-hex sha256 of concat(sorted(basename + ':' + sha256(file) + newline)) over the wire-contract files (capability/operations/compensation/transcript; envelope.schema.json excluded); decode hex to 32 bytes for EnvelopeHeader.schema_hash",
    'compensation.json::compensable.<commitOp>.how':
        'post the inverse of each committed leg',
    'compensation.json::kind':
        'neutrino.slot-compensation',
    'envelope.schema.json::$id':
        'neutrino.slot.envelope',
    'envelope.schema.json::$schema':
        'http://json-schema.org/draft-07/schema#',
    'envelope.schema.json::additionalProperties':
        False,
    'envelope.schema.json::allOf[].if.properties.operation.enum[]':
        ['COMMIT', 'REJECT', 'COMPENSATE'],
    'envelope.schema.json::allOf[].then.required[]':
        ['correlationId'],
    'envelope.schema.json::description':
        'Canonical envelope for one slot operation. Business-coordination operations only (not arbitrary RPC).',
    'envelope.schema.json::properties.anchorRef.properties.address.type':
        'string',
    'envelope.schema.json::properties.anchorRef.properties.chain.type':
        'string',
    'envelope.schema.json::properties.anchorRef.properties.commitmentHash.type':
        'string',
    'envelope.schema.json::properties.anchorRef.type':
        'object',
    'envelope.schema.json::properties.capability.type':
        'string',
    'envelope.schema.json::properties.capabilityVersion.type':
        'string',
    'envelope.schema.json::properties.correlationId.type':
        'string',
    'envelope.schema.json::properties.counterparty.type':
        'string',
    'envelope.schema.json::properties.diagnostics.items.properties.code.type':
        'string',
    'envelope.schema.json::properties.diagnostics.items.properties.message.type':
        'string',
    'envelope.schema.json::properties.diagnostics.items.properties.severity.type':
        'string',
    'envelope.schema.json::properties.diagnostics.items.required[]':
        ['severity', 'code', 'message'],
    'envelope.schema.json::properties.diagnostics.items.type':
        'object',
    'envelope.schema.json::properties.diagnostics.type':
        'array',
    'envelope.schema.json::properties.operation.type':
        'string',
    'envelope.schema.json::properties.operationId.type':
        'string',
    'envelope.schema.json::properties.participant.type':
        'string',
    'envelope.schema.json::properties.payload.type':
        'object',
    'envelope.schema.json::properties.payloadHash.type':
        'string',
    'envelope.schema.json::properties.previousTranscriptHash.type':
        'string',
    'envelope.schema.json::properties.sessionId.type':
        'string',
    'envelope.schema.json::properties.signature.type':
        'string',
    'envelope.schema.json::required[]':
        ['sessionId', 'operationId', 'operation', 'capability', 'capabilityVersion', 'participant', 'counterparty', 'payload', 'payloadHash', 'previousTranscriptHash', 'signature'],
    'envelope.schema.json::title':
        'Neutrino Slot Operation Envelope',
    'envelope.schema.json::type':
        'object',
    'operations.json::kind':
        'neutrino.slot-operations',
    'transcript.json::anchoring.anchorRef.chain':
        'evm',
    'transcript.json::anchoring.anchorRef.records':
        'commitmentHash of committed legs',
    'transcript.json::anchoring.anchorRef.via':
        'blockchain slot as coordinator-of-record',
    'transcript.json::anchoring.default':
        'per session close',
    'transcript.json::anchoring.valueMovingCommit':
        'optional per-commit anchor',
    'transcript.json::hashChain.chain':
        'previousTranscriptHash links each envelope to the prior one',
    'transcript.json::hashChain.includesDiagnostics':
        True,
    'transcript.json::hashChain.includesRejected':
        True,
    'transcript.json::hashChain.perEnvelope':
        'payloadHash = sha256(canonical(payload))',
    'transcript.json::kind':
        'neutrino.slot-transcript-policy',
}


# The contract's owned operation prose. Frozen per operation so a permuted or
# arbitrary mapping is rejected — cardinality alone proves nothing. PROPOSE is
# absent because it interpolates agreement values; it is DERIVED from the spec
# by the contract template instead (see _verify_contract_row).
OPERATION_PROSE = {
    'CLOSE':
        'reconciliation + final coordination status',
    'COMMIT':
        'assert_balanced + post the staged legs (replay-protected)',
    'COMPENSATE':
        'reverse the committed legs',
    'NEGOTIATE':
        'capability / attestation agreement',
    'OPEN':
        'initialize workflow key (status NEW)',
    'REJECT':
        'decline; no postings; recorded in transcript',
}

PROPOSE_TEMPLATE = "compute [{computes}]; stage [{entries}]"


# ---------------------------------------------------------------------------
# Named open adjudications. The verdict enumerates exactly these; each states the
# question and the admissible outcomes so "unresolved" is a decision record, not a
# silent gap. Every one must be referenced by at least one row or contract item.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# S0-C2 DECISION LEDGER. Each of the five decisions the S0-C3 verdict named is
# adjudicated here with an explicit outcome. `status` is one of:
#   resolved                  — settled within C1/C2 modelling authority and
#                               mechanically enforced below;
#   requires-generator-change — the only faithful resolutions need a generator or
#                               corpus change, which this checkpoint is NOT
#                               authorized to begin. Recorded with its consequence
#                               so the decision is made, not deferred silently.
# ---------------------------------------------------------------------------
DECISIONS = {
    "backends-overlay-authority": {
        "statusFrom": "overlay-identity-profile-equal",
        "question": "Who owns capability.json::backends[]? It was injected by a "
                    "different TU and absent from core-only builds, and because the "
                    "overlay was folded in BEFORE refreshSlotCapabilityLock it made "
                    "the hashed capability identity depend on the producer's build "
                    "profile.",
        "resolution": "RESOLVED BY REMOVAL (S0-C2R, architect ruling). Backend "
                      "availability is package/target discovery, not agreement "
                      "content, so it is no longer emitted into the descriptor at "
                      "all — not retained unhashed, and not profile-scoped. The "
                      "overlay TU is deleted and SlotTarget.cpp applies no "
                      "build-profile decoration. The status is not asserted here: "
                      "the predicate re-reads the real mutation/refresh ordering and "
                      "wire-set membership, and now finds no gated mutation at all.",
        "consequence": "was: build-profile-dependent capability identity/hash",
        "rows": [],
    },
    "evm-anchor-hardcoded": {
        "statusFrom": "anchor-owned-by-contract-constant",
        "question": "anchoring.anchorRef.chain is the only deploy-SHAPED value in any "
                    "artifact and it is a hardcoded constant.",
        "resolution": "RESOLVED as a descriptor-contract constant. It is NOT a "
                      "deploy-coordinate input: nothing supplies it, and the S0-C3 "
                      "verdict forbids populating that authority until a typed input "
                      "is wired AND witnessed. The contract owns the value and the "
                      "frozen-constant check enforces it. The field NAME remains "
                      "deploy-shaped; renaming is a generator change and is recorded "
                      "as cosmetic, not an authority question.",
        "rows": ["transcript.json::anchoring.anchorRef.chain"],
    },
    "crossorganization-duplicate-derivation": {
        "statusFrom": "crossorg-shares-one-derivation",
        "question": "crossOrganization is computed INDEPENDENTLY in two emitters "
                    "(GenSlotSpec.cpp:216 and :484-485) over the same source.",
        "resolution": "RESOLVED by giving both rows ONE typed derivation of record "
                      "(derivationGroup cross-organization, source participants[].org, "
                      "transformation predicate) and MECHANICALLY ENFORCING that the "
                      "two emitted values agree in every domain. The generator still "
                      "evaluates the predicate twice, but the model now has a single "
                      "derivation and a disagreement fails closed, which is what the "
                      "verdict required of a duplicated value.",
        "rows": ["capability.json::topology.crossOrganization",
                 "binding-topology.json::crossOrganization"],
    },
    "envelope-hardcoded-op-subset": {
        "statusFrom": "envelope-subset-reconciled",
        "question": "envelope allOf[].if...operation.enum[] is a hardcoded operation "
                    "subset while properties.operation.enum[] is projected from the "
                    "machine, so a renamed operation drifts silently.",
        "resolution": "RESOLVED as a contract constant WITH a reconciliation check: "
                      "the hardcoded subset must remain a strict subset of the "
                      "machine vocabulary in every domain. A machine that renames or "
                      "drops one of those operations now fails closed instead of "
                      "drifting. This is the second admissible option and needs no "
                      "generator change.",
        "rows": ["envelope.schema.json::allOf[].if.properties.operation.enum[]",
                 "envelope.schema.json::allOf[].then.required[]"],
    },
    "lock-crossartifact-inputs": {
        "statusFrom": "lock-receipts-bind-committed-bytes",
        "question": "capability.lock digests other artifacts, so the receipt is "
                    "structurally cross-artifact; its covered-file SET is also a "
                    "contract choice.",
        "resolution": "PARTIALLY RESOLVED. The lock is adjudicated a contract-owned "
                      "receipt over a NAMED artifact set, and the model now enforces "
                      "that the lock's file set equals the contract's declared wire "
                      "set and that capabilityHash reproduces the contract algorithm "
                      "over those inputs. What is NOT resolvable here: in 2 of 4 "
                      "committed domains the lock's per-file digests no longer match "
                      "the committed artifact bytes (the artifacts were reformatted "
                      "after the lock was written), so the committed receipts are "
                      "stale. Correcting that is a corpus regeneration, not a "
                      "modelling decision.",
        "consequence": "committed capability.lock receipts are stale in 2 of 4 domains",
        "rows": ["capability.lock::capabilityHash", "capability.lock::files.<name>"],
    },
}
UNRESOLVED_DECISIONS = DECISIONS  # name kept for the C1 report field


def _sem(source, transform, order, validator, note="", group=None, cardinality="1:1",
         emit="always"):
    """A row derived from the semantic input (the capability/agreement spec).

    `emit` names the per-element emission predicate: which source elements actually
    produce output. It is REQUIRED to be exact — a conditional row that merely says
    "some subset" cannot prove which elements must be emitted."""
    return {"authority": "semantic-input", "emitWhen": emit, "sourceRef": source,
            "contractItem": None, "transformation": transform,
            "canonicalOrder": order, "validationOwner": validator,
            "derivationGroup": group, "cardinality": cardinality, "note": note}


def _con(item, transform, order, validator, note="", group=None,
         cardinality="1:1", source=None, emit="always", mult="one"):
    """A row owned by the versioned descriptor contract. `mult` is how many times
    the field must appear per domain — validating only present occurrences would
    let a required one disappear."""
    return {"authority": "descriptor-contract", "emitWhen": emit, "sourceRef": source,
            "multiplicity": mult,
            "contractItem": item, "transformation": transform,
            "canonicalOrder": order, "validationOwner": validator,
            "derivationGroup": group, "cardinality": cardinality, "note": note}


_SPEC = "capability-spec"          # the versioned semantic input
_GEN = "slot-descriptor-generator"  # validation owner: the emitter itself
_LIFE = "lifecycle-model"           # validation owner: LifecycleModel invariants
_SCHEMA = "binding-topology-schema"  # docs/schemas/slot-binding-topology.schema.json


def _identity(order=ORDERS[5], group="capability-identity"):
    return _con("capability-identity-prefix", "prefix-compose", order, _GEN,
                group=group, source="procedure",
                note="contract-owned namespace over an agreement value")


# Shared derivation groups: rows in the same group MUST agree and must ultimately
# share ONE derivation. Recording the group is what lets the model state the
# duplicated-recomputation problem precisely instead of hiding it.
DERIVATIONS = {
    "capability.json": {
        "kind": _con("artifact-kind-discriminators", "constant", "not-applicable", _GEN),
        "capability": _identity(),
        "capabilityVersion": _sem("specVersion", "identity", "not-applicable", _SPEC,
                                  group="capability-identity"),
        "procedure": _sem("procedure", "identity", "not-applicable", _SPEC,
                          group="capability-identity"),
        "trigger": _sem("trigger", "identity", "not-applicable", _SPEC),
        "parties[]": _sem("effects[].party.value", "project-distinct",
                          "source-order-distinct", _SPEC, cardinality="N:1"),
        "declaredParticipants[].name": _sem("participants[].name", "project-field",
                                            "source-order", _SPEC, cardinality="1:N"),
        "declaredParticipants[].role": _sem("participants[].role", "project-field",
                                            "source-order", _SPEC, cardinality="1:N"),
        "declaredParticipants[].org": _sem("participants[].org", "project-field",
                                           "source-order", _SPEC, cardinality="1:N",
                                           emit="value-nonempty"),
        "declaredParticipants[].capabilities[]": _sem(
            "participants[].capabilities[]", "project-field", "source-order", _SPEC,
            cardinality="1:N"),
        "declaredParticipants[].binding.mode": _con(
            "binding-mode-literal", "constant", "not-applicable", _GEN,
            group="late-binding-mode", cardinality="1:N",
            mult="per-flexible-participant",
            note="VALUE is the closed contract literal; PRESENCE is agreement-"
                 "conditional (emitted only for a flexible participant). The C0 census "
                 "records the presence predicate as the row's optionality"),
        "declaredParticipants[].binding.runtimes[]": _sem(
            "participants[].bindRuntimes[]", "project-field", "source-order", _SPEC,
            group="allowed-runtimes", cardinality="1:N", emit="participant-flexible"),
        "declaredParticipants[].binding.minAssurance": _sem(
            "participants[].bindMinAssurance", "identity", "not-applicable", _SPEC,
            group="declared-assurance", cardinality="1:N",
            emit="participant-flexible-and-value-nonempty"),
        "declaredParticipants[].binding.authorizedBinder": _sem(
            "participants[].org", "project-field", "not-applicable", _SPEC,
            group="authorized-binder", cardinality="1:N",
            emit="participant-flexible-and-value-nonempty"),
        "topology.organizations[]": _sem("participants[].org", "project-distinct",
                                         "source-order-distinct", _SPEC,
                                         group="organizations", cardinality="N:1",
                                         emit="value-nonempty"),
        "topology.crossOrganization": _sem(
            "participants[].org", "predicate", "not-applicable", _SPEC,
            group="cross-organization", cardinality="N:1",
            note="INDEPENDENTLY RECOMPUTED from binding-topology's copy — see the "
                 "crossorganization-duplicate-derivation adjudication"),
        "ledgerOwners[]": _sem("effects[].owner", "project-distinct",
                               "source-order-distinct", _SPEC, cardinality="N:1"),
        "operations[]": _sem("lifecycle", "machine-vocabulary", "machine-order", _LIFE,
                             group="operation-vocabulary", cardinality="1:N"),
        "computed[]": _sem("computes[].name", "project-field", "source-order", _SPEC,
                           cardinality="1:N"),
        "ledgers[]": _sem("effects[].ledger", "project-distinct",
                          "source-order-distinct", _SPEC, cardinality="N:1"),
        "evidenceInputs[]": _sem("inputs[type==evidence].name", "filter-project",
                                 "source-order", _SPEC, group="evidence-inputs",
                                 cardinality="1:N"),
        "partyTypedInputs[]": _sem("inputs[type==party].name", "filter-project",
                                   "source-order", _SPEC, cardinality="1:N"),
        "typedInputs[].name": _sem("inputs[].name", "project-field", "source-order",
                                   _SPEC, cardinality="1:N"),
        "typedInputs[].type": _sem("inputs[].type", "project-field", "source-order",
                                   _SPEC, cardinality="1:N"),
        "entries[].name": _sem("effects[].name", "project-field", "source-order", _SPEC,
                               group="ledger-entries", cardinality="1:N"),
        "entries[].kind": _sem("effects[].kind", "project-field", "source-order", _SPEC,
                               group="ledger-entries", cardinality="1:N"),
        "entries[].ledger": _sem("effects[].ledger", "project-field", "source-order",
                                 _SPEC, group="ledger-entries", cardinality="1:N"),
        "entries[].owner": _sem("effects[].owner", "project-field", "source-order",
                                _SPEC, group="ledger-entries", cardinality="1:N"),
        "entries[].participant": _sem("effects[].participant", "project-field",
                                      "source-order", _SPEC, group="ledger-entries",
                                      cardinality="1:N", emit="value-nonempty"),
        "entries[].party.input": _sem("effects[].party.value", "project-field",
                                      "source-order", _SPEC, group="ledger-entries",
                                      cardinality="1:N"),
        "entries[].amount.input": _sem("effects[].amount.value", "project-field",
                                       "source-order", _SPEC, group="ledger-entries",
                                       cardinality="1:N"),
        "entries[].currency.input": _sem("effects[].currency.value", "project-field",
                                         "source-order", _SPEC, group="ledger-entries",
                                         cardinality="1:N"),
        "entries[].idempotencyKey.input": _sem(
            "effects[].idempotencyKey.value", "project-field", "source-order", _SPEC,
            group="ledger-entries", cardinality="1:N"),
    },
    "operations.json": {
        "kind": _con("artifact-kind-discriminators", "constant", "not-applicable", _GEN),
        "capability": _identity(),
        "operations[].operation": _sem("lifecycle", "machine-vocabulary", "machine-order",
                                       _LIFE, group="operation-vocabulary",
                                       cardinality="1:N"),
        "operations[].requiresPrior": _sem("lifecycle", "machine-vocabulary",
                                           "machine-order", _LIFE,
                                           group="operation-vocabulary",
                                           cardinality="1:N"),
        "operations[].maps": _con("operation-prose-table", "table-lookup",
                                  "machine-order", _GEN, group="operation-vocabulary",
                                  source="lifecycle", cardinality="1:N",
                                  mult="per-operation",
                                  note="contract table keyed by the machine vocabulary; "
                                       "the PROPOSE entry interpolates compute/effect names"),
    },
    "compensation.json": {
        "kind": _con("artifact-kind-discriminators", "constant", "not-applicable", _GEN),
        "capability": _identity(),
        "compensable.<commitOp>.how": _con("compensation-prose", "constant",
                                           "not-applicable", _GEN),
        "compensable.<commitOp>.reverses[].entry": _sem(
            "effects[].name", "project-field", "source-order", _SPEC,
            group="ledger-entries", cardinality="1:N"),
        "compensable.<commitOp>.reverses[].ledger": _sem(
            "effects[].ledger", "project-field", "source-order", _SPEC,
            group="ledger-entries", cardinality="1:N"),
        "compensable.<commitOp>.reverses[].inverseOf": _sem(
            "effects[].kind", "project-field", "source-order", _SPEC,
            group="ledger-entries", cardinality="1:N"),
        "compensable.<commitOp>.idempotency": _con(
            "compensation-idempotency-template", "template-interpolate",
            "not-applicable", _GEN, source="procedure",
            note="contract-owned shape; the procedure name comes from the agreement"),
        "nonCompensable[]": _sem("lifecycle", "machine-vocabulary", "machine-order",
                                 _LIFE, group="operation-vocabulary", cardinality="1:N",
                                 note="the refusal set: machine ops minus the post and "
                                      "compensate effects — target-NEUTRAL"),
        "invariantAfterCompensation": _sem("invariants[kind==balanced]", "predicate",
                                           "not-applicable", _SPEC),
    },
    "transcript.json": {
        "kind": _con("artifact-kind-discriminators", "constant", "not-applicable", _GEN),
        "capability": _identity(),
        "hashChain.perEnvelope": _con("transcript-hashchain-policy", "constant",
                                      "not-applicable", _GEN),
        "hashChain.chain": _con("transcript-hashchain-policy", "constant",
                                "not-applicable", _GEN),
        "hashChain.includesRejected": _con("transcript-hashchain-policy", "constant",
                                           "not-applicable", _GEN),
        "hashChain.includesDiagnostics": _con("transcript-hashchain-policy", "constant",
                                              "not-applicable", _GEN),
        "anchoring.default": _con("transcript-anchoring-policy", "constant",
                                  "not-applicable", _GEN),
        "anchoring.valueMovingCommit": _con("transcript-anchoring-policy", "constant",
                                            "not-applicable", _GEN),
        "anchoring.anchorRef.chain": _con("transcript-anchor-chain", "constant",
                                          "not-applicable", _GEN,
                                          note="PROVISIONAL owner; deploy-shaped but "
                                               "supplied by nothing"),
        "anchoring.anchorRef.records": _con("transcript-anchoring-policy", "constant",
                                            "not-applicable", _GEN),
        "anchoring.anchorRef.via": _con("transcript-anchoring-policy", "constant",
                                        "not-applicable", _GEN),
        "evidence[]": _sem("inputs[type==evidence].name", "filter-project",
                           "source-order", _SPEC, group="evidence-inputs",
                           cardinality="1:N"),
    },
    "envelope.schema.json": {
        "properties.operation.enum[]": _sem("lifecycle", "machine-vocabulary",
                                            "machine-order", _LIFE,
                                            group="operation-vocabulary",
                                            cardinality="1:N"),
        "allOf[].if.properties.operation.enum[]": _con(
            "envelope-correlation-rule", "constant", "contract-fixed", _GEN,
            note="hardcoded op subset — under adjudication"),
        "allOf[].then.required[]": _con("envelope-correlation-rule", "constant",
                                        "contract-fixed", _GEN),
        # Every remaining envelope field is a constant of the ONE frozen template
        # (kEnvelopeSchema). The addresses are enumerated explicitly rather than
        # swept up by pattern, so a NEW template field still fails the bijection
        # completeness check instead of being silently absorbed.
        **{address: _con("envelope-schema-template", "constant", order, _GEN,
                         group="envelope-template")
           for address, order in (
               ("$schema", "not-applicable"),
               ("$id", "not-applicable"),
               ("title", "not-applicable"),
               ("description", "not-applicable"),
               ("type", "not-applicable"),
               ("additionalProperties", "not-applicable"),
               ("required[]", "contract-fixed"),
               ("properties.sessionId.type", "not-applicable"),
               ("properties.operationId.type", "not-applicable"),
               ("properties.operation.type", "not-applicable"),
               ("properties.correlationId.type", "not-applicable"),
               ("properties.capability.type", "not-applicable"),
               ("properties.capabilityVersion.type", "not-applicable"),
               ("properties.participant.type", "not-applicable"),
               ("properties.counterparty.type", "not-applicable"),
               ("properties.payload.type", "not-applicable"),
               ("properties.payloadHash.type", "not-applicable"),
               ("properties.previousTranscriptHash.type", "not-applicable"),
               ("properties.signature.type", "not-applicable"),
               ("properties.diagnostics.type", "not-applicable"),
               ("properties.diagnostics.items.type", "not-applicable"),
               ("properties.diagnostics.items.required[]", "contract-fixed"),
               ("properties.diagnostics.items.properties.severity.type",
                "not-applicable"),
               ("properties.diagnostics.items.properties.code.type", "not-applicable"),
               ("properties.diagnostics.items.properties.message.type",
                "not-applicable"),
               ("properties.anchorRef.type", "not-applicable"),
               ("properties.anchorRef.properties.chain.type", "not-applicable"),
               ("properties.anchorRef.properties.address.type", "not-applicable"),
               ("properties.anchorRef.properties.commitmentHash.type",
                "not-applicable"),
           )},
    },
    "binding-topology.json": {
        "kind": _con("artifact-kind-discriminators", "constant", "not-applicable", _GEN),
        "schemaVersion": _con("binding-topology-schema-version", "constant",
                              "not-applicable", _SCHEMA),
        "capability": _identity(),
        "capabilityVersion": _sem("specVersion", "identity", "not-applicable", _SPEC,
                                  group="capability-identity"),
        "procedure": _sem("procedure", "identity", "not-applicable", _SPEC,
                          group="capability-identity"),
        "organizations[].organizationId": _sem("participants[].org", "project-distinct",
                                               "source-order-distinct", _SCHEMA,
                                               group="organizations", cardinality="N:1"),
        "organizations[].participants[].participantId": _sem(
            "participants[].name", "project-field", "source-order", _SCHEMA,
            cardinality="1:N"),
        "organizations[].participants[].role": _sem(
            "participants[].role", "project-field", "source-order", _SCHEMA,
            cardinality="1:N"),
        "organizations[].participants[].slots[].slotId": _con(
            "capability-identity-prefix", "prefix-compose", "source-order", _SCHEMA,
            source="participants[].name", group="capability-identity",
            cardinality="1:N", mult="per-participant"),
        "organizations[].participants[].slots[].lateBindingMode": _sem(
            "participants[].binding", "predicate", "not-applicable", _SCHEMA,
            group="late-binding-mode", cardinality="1:N"),
        "organizations[].participants[].slots[].allowedRuntimes[]": _sem(
            "participants[].bindRuntimes[]", "project-field", "source-order", _SCHEMA,
            group="allowed-runtimes", cardinality="1:N"),
        "organizations[].participants[].slots[].minAssurance": _con(
            "binding-assurance-default", "fallback-default", "not-applicable", _SCHEMA,
            source="participants[].bindMinAssurance", group="effective-assurance",
            cardinality="1:N", mult="per-participant",
            note="agreement value when flexible and declared, else the contract floor"),
        "organizations[].participants[].slots[].evidenceProfile": _con(
            "binding-evidence-profile-default", "constant", "not-applicable", _SCHEMA,
            mult="per-participant"),
        "organizations[].participants[].slots[].authorizedBinder": _sem(
            "participants[].org", "project-field", "not-applicable", _SCHEMA,
            group="authorized-binder", cardinality="1:N",
            emit="participant-flexible-and-value-nonempty"),
        "crossOrganization": _sem(
            "participants[].org", "predicate", "not-applicable", _SCHEMA,
            group="cross-organization", cardinality="N:1",
            note="INDEPENDENTLY RECOMPUTED from capability.json's copy — see the "
                 "crossorganization-duplicate-derivation adjudication"),
    },
    "capability.lock": {
        "kind": _con("artifact-kind-discriminators", "constant", "not-applicable", _GEN),
        "capability": _identity(),
        "capabilityVersion": _sem("specVersion", "identity", "not-applicable", _SPEC,
                                  group="capability-identity"),
        "method": _con("capability-lock-algorithm", "constant", "not-applicable", _GEN),
        "capabilityHash": _con("capability-lock-algorithm", "digest", "lexicographic",
                               _GEN, group="lock-receipt", cardinality="N:1",
                               note="digest over the contract-named wire-artifact set"),
        "files.<name>": _con("capability-lock-algorithm", "digest", "lexicographic",
                             _GEN, group="lock-receipt", cardinality="N:1",
                             mult="per-wire-file"),
    },
}

# Rows whose values MUST agree across artifacts. Each names the group that has to
# resolve to ONE derivation, and whether it does so today.
# S0-C2: every cross-artifact invariant now carries a RESOLUTION. `sharing` is
# either `one-derivation` (a single derivation of record, with agreement enforced
# by _verify_shared_equalities) or `distinct-identities` (the semantics genuinely
# differ, so the contract says so instead of pretending the values must agree).
CROSS_ARTIFACT_INVARIANTS = [
    {"group": "capability-identity",
     "requirement": "the capability identity triple is byte-identical wherever emitted",
     "sharing": "one-derivation", "enforced": True,
     "rows": ["capability.json::capability", "operations.json::capability",
              "compensation.json::capability", "transcript.json::capability",
              "binding-topology.json::capability", "capability.lock::capability"]},
    {"group": "operation-vocabulary",
     "requirement": "the operation vocabulary agrees across capability, operations, "
                    "compensation and the envelope enum",
     "sharing": "one-derivation", "enforced": True,
     "rows": ["capability.json::operations[]",
              "operations.json::operations[].operation",
              "compensation.json::nonCompensable[]",
              "envelope.schema.json::properties.operation.enum[]"]},
    {"group": "evidence-inputs",
     "requirement": "capability.evidenceInputs[] == transcript.evidence[]",
     "sharing": "one-derivation", "enforced": True,
     "rows": ["capability.json::evidenceInputs[]", "transcript.json::evidence[]"]},
    {"group": "cross-organization",
     "requirement": "capability.topology.crossOrganization == "
                    "binding-topology.crossOrganization",
     "sharing": "one-derivation", "enforced": True,
     "resolution": "C2: one derivation of record; the two emitted copies are proved "
                   "equal in every domain, so the generator's duplicate evaluation "
                   "can no longer diverge silently",
     "rows": ["capability.json::topology.crossOrganization",
              "binding-topology.json::crossOrganization"]},
    {"group": "ledger-entries",
     "requirement": "capability.entries[] and compensation.reverses[] project the "
                    "same effect list in the same order",
     "sharing": "one-derivation", "enforced": True,
     "resolution": "C2: one derivation of record; the two projections are proved "
                   "equal in every domain despite running through separate emitter "
                   "loops",
     "rows": ["capability.json::entries[].name",
              "compensation.json::compensable.<commitOp>.reverses[].entry"]},
    {"group": "declared-assurance",
     "requirement": "capability.json reports the assurance the AGREEMENT declared, "
                    "and only for a flexible participant that declared one",
     "sharing": "distinct-identities", "enforced": True,
     "resolution": "C2: formerly grouped with the topology view and flagged as "
                   "unshared. The semantics genuinely differ, so the contract now "
                   "carries TWO identities instead of a false equality: this one is "
                   "the declared value.",
     "rows": ["capability.json::declaredParticipants[].binding.minAssurance"]},
    {"group": "effective-assurance",
     "requirement": "binding-topology reports the EFFECTIVE assurance — the declared "
                    "value when present, else the contract floor — for every "
                    "participant",
     "sharing": "distinct-identities", "enforced": True,
     "resolution": "C2: the counterpart identity. Distinct from declared-assurance "
                   "by design; asserting they must agree would have been wrong.",
     "rows": ["binding-topology.json::organizations[].participants[].slots[].minAssurance"]},
]


class BijectionError(Exception):
    pass


# Cross-artifact agreement rules adjudicated in C2. Each names two emitted
# addresses that a SHARED derivation requires to be equal in every domain, so a
# duplicated value cannot silently diverge.
SHARED_DERIVATION_EQUALITIES = [
    {"group": "cross-organization",
     "left": ("capability.json", "topology.crossOrganization"),
     "right": ("binding-topology.json", "crossOrganization")},
    {"group": "evidence-inputs",
     "left": ("capability.json", "evidenceInputs[]"),
     "right": ("transcript.json", "evidence[]")},
    {"group": "ledger-entries",
     "left": ("capability.json", "entries[].name"),
     "right": ("compensation.json", "compensable.<commitOp>.reverses[].entry")},
    {"group": "operation-vocabulary",
     "left": ("capability.json", "operations[]"),
     "right": ("envelope.schema.json", "properties.operation.enum[]")},
]


# --- Evidence binding the adjudicated overlay defect --------------------------
# The defect was never "a census row exists". It was: build-profile-conditional
# data entering the HASHED WIRE SET BEFORE the lock refresh, which made the
# capability identity differ between full and core-only profiles. The predicate
# therefore binds three facts — overlay/refresh ORDERING, WIRE-SET membership of
# the mutated artifact, and the resulting PROFILE EQUALITY of the lock identity —
# so a legitimate NON-DELETION fix (move the overlay after the refresh, or keep
# its data out of the hashed set) also reads as resolved, and a mere row deletion
# or rename does not.
# The decision-bearing statement is the overlay's MUTATION of an artifact's
# content — not the spelling of the artifact lookup that precedes it. Binding to
# the lookup would report a hazard even after the mutation had been moved past the
# lock refresh, which is exactly the failure this replaces.
_OVERLAY_MUTATION_RE = re.compile(
    r"\b\w+\s*(?:->\s*content|\.\s*content)\s*\.\s*insert\s*\(")
_LOCK_REFRESH = "refreshSlotCapabilityLock"


def _overlay_sources(repo):
    """{repo-relative path: text} for every slot source, so the evidence extractor
    can be driven against real statements — including moved ones — in a fixture."""
    out = {}
    root = os.path.join(repo, "lib", "slots")
    for dirpath, _dirs, names in os.walk(root):
        for name in sorted(names):
            if not name.endswith((".cpp", ".h")):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, repo).replace(os.sep, "/")
            with open(path, encoding="utf-8", errors="replace") as f:
                out[rel] = f.read()
    return out


def _overlay_identity_evidence(repo, sources=None, wire_set=None):
    """Evidence binding the adjudicated overlay defect.

    The defect was never "a census row exists". It was build-profile-conditional
    data entering the HASHED WIRE SET before the lock refresh, which made the
    capability identity differ between full and core-only profiles. Three facts are
    read from the real sources, and the conclusion is DERIVED from them — never
    supplied as a precomputed boolean:

      * ORDERING  — the offset of the overlay's actual content-mutation statement
                    versus the lock-refresh call;
      * WIRE-SET  — whether the artifact it mutates is inside the hashed set;
      * PROFILE   — the identity is profile-equal exactly when no gated mutation
                    lands in the hashed set ahead of the refresh.

    Either faithful non-deletion fix therefore reads as resolved: moving the
    mutation after the refresh, or keeping its artifact out of the hashed set.
    """
    sources = _overlay_sources(repo) if sources is None else sources
    wire_set = LOCK_WIRE_SET if wire_set is None else wire_set
    hazards = []
    for rel, text in sorted(sources.items()):
        if _LOCK_REFRESH not in text:
            continue
        # Only a build-profile-gated OVERLAY can make the identity differ; the
        # unconditional generator builds the artifacts fresh for every profile.
        if not ("NEUTRINO_CORE_ONLY" in text or "/full/" in rel):
            continue
        mutation = _OVERLAY_MUTATION_RE.search(text)
        if mutation is None:
            continue
        refresh_at = text.index(_LOCK_REFRESH)
        hashed = sorted(a for a in wire_set if f'"{a}"' in text)
        if mutation.start() < refresh_at and hashed:
            hazards.append({
                "source": rel,
                "hashedArtifacts": hashed,
                "mutationOffset": mutation.start(),
                "refreshOffset": refresh_at,
                "mutationBeforeRefresh": True,
            })
    return {
        "orderingHazards": hazards,
        "profileConditionalHashedFields": sorted({h["source"] for h in hazards}),
        "lockIdentityProfileEqual": not hazards,
    }


# --- S0-C2 status predicates -------------------------------------------------
# A decision's status is DERIVED from C0/C1 evidence already present, never
# asserted. Each predicate is small and explicit; this is deliberately not a
# general decision framework.
def _decision_status(name, predicate, rows, repo, census, derivations_by_address,
                     sources=None):
    """Return "resolved"/"requires-generator-change" from existing evidence."""
    if predicate == "overlay-identity-profile-equal":
        # Bound to the defect, not to a row: resolved exactly when no
        # profile-conditional data reaches the hashed wire set before the lock
        # refresh, so the capability identity is equal across build profiles.
        # Deleting or renaming the census row changes nothing here on its own.
        evidence = _overlay_identity_evidence(repo, sources=sources)
        return ("resolved" if evidence["lockIdentityProfileEqual"]
                else "requires-generator-change")
    if predicate == "anchor-owned-by-contract-constant":
        row = derivations_by_address.get("transcript.json::anchoring.anchorRef.chain")
        owned = bool(row) and row["authority"] == "descriptor-contract" and (
            "transcript.json::anchoring.anchorRef.chain" in CONTRACT_CONSTANTS)
        return "resolved" if owned else "requires-generator-change"
    if predicate == "crossorg-shares-one-derivation":
        groups = {derivations_by_address.get(a, {}).get("derivationGroup")
                  for a in rows}
        enforced = any(r["group"] == "cross-organization"
                       for r in SHARED_DERIVATION_EQUALITIES)
        return ("resolved" if len(groups) == 1 and None not in groups and enforced
                else "requires-generator-change")
    if predicate == "envelope-subset-reconciled":
        # Resolved when the reconciliation check finds no problem on the corpus.
        return "resolved" if not _verify_envelope_subset(repo) else \
            "requires-generator-change"
    if predicate == "lock-receipts-bind-committed-bytes":
        return ("resolved" if not _lock_digest_findings(repo)
                and not _verify_lock_wire_set(repo) else "requires-generator-change")
    raise BijectionError(f"unknown status predicate {predicate!r}")


def _verify_shared_equalities(repo):
    """A value with ONE derivation of record must be emitted identically wherever
    it appears. The generator may still compute it more than once; this proves the
    copies agree, which is what the S0-C3 verdict required of duplicated values."""
    problems = []
    for rule in SHARED_DERIVATION_EQUALITIES:
        for slot_dir, _spec in c0.DOMAINS:
            values = {}
            for side in ("left", "right"):
                artifact, address = rule[side]
                path = os.path.join(repo, slot_dir, artifact)
                if not os.path.exists(path):
                    values = None
                    break
                with open(path, encoding="utf-8") as f:
                    values[side] = _emitted_values(json.load(f), address)
            if not values:
                continue
            if values["left"] != values["right"]:
                problems.append(
                    f"shared derivation {rule['group']!r} disagrees in {slot_dir}: "
                    f"{rule['left'][0]}::{rule['left'][1]} = {values['left'][:4]}… "
                    f"!= {rule['right'][0]}::{rule['right'][1]} = "
                    f"{values['right'][:4]}…")
    return problems


_ENVELOPE_SUBSET_OVERRIDE = "unset"


def _verify_envelope_subset(repo):
    """C2 adjudication: the envelope's hardcoded correlation op-subset must remain a
    strict subset of the machine vocabulary, so a renamed/dropped operation fails
    closed instead of drifting."""
    problems = []
    for slot_dir, _spec in c0.DOMAINS:
        env = os.path.join(repo, slot_dir, "envelope.schema.json")
        ops = os.path.join(repo, slot_dir, "operations.json")
        if not (os.path.exists(env) and os.path.exists(ops)):
            continue
        with open(env, encoding="utf-8") as f:
            subset = _emitted_values(
                json.load(f), "allOf[].if.properties.operation.enum[]")
        if _ENVELOPE_SUBSET_OVERRIDE != "unset":
            with open(ops, encoding="utf-8") as f:
                subset = (_ENVELOPE_SUBSET_OVERRIDE
                          if _ENVELOPE_SUBSET_OVERRIDE is not None
                          else [o["operation"] for o in json.load(f)["operations"]])
        with open(ops, encoding="utf-8") as f:
            vocab = [o["operation"] for o in json.load(f)["operations"]]
        missing = [op for op in subset if op not in vocab]
        if missing:
            problems.append(
                f"envelope correlation subset does not reconcile with the machine "
                f"vocabulary in {slot_dir}: {missing} absent from {vocab}")
        elif not set(subset) < set(vocab):
            # STRICT subset: the correlation rule singles out a PROPER subset of
            # the vocabulary. Equality would mean the rule carries no information
            # and would silently become vacuous.
            problems.append(
                f"envelope correlation subset must be a STRICT subset of the "
                f"machine vocabulary in {slot_dir}: {sorted(subset)} vs "
                f"{sorted(vocab)}")
    return problems


def _verify_lock_wire_set(repo):
    """C2 adjudication: the lock is a receipt over a contract-NAMED artifact set."""
    problems = []
    for slot_dir, _spec in c0.DOMAINS:
        lock_path = os.path.join(repo, slot_dir, "capability.lock")
        if not os.path.exists(lock_path):
            continue
        with open(lock_path, encoding="utf-8") as f:
            files = sorted(json.load(f).get("files", {}))
        if files != sorted(LOCK_WIRE_SET):
            problems.append(
                f"capability.lock covers {files} in {slot_dir}, not the contract's "
                f"named wire set {sorted(LOCK_WIRE_SET)}")
    return problems


def _lock_digest_findings(repo):
    """The committed capability.lock digests vs the committed artifact bytes.

    The lock's capabilityHash is internally consistent (verified as a chain), but
    in some domains its per-file digests no longer match the bytes on disk — the
    artifacts were reformatted after the lock was written. Recorded as evidence
    rather than asserted away; it is material to the lock-crossartifact-inputs
    adjudication."""
    out = []
    for slot_dir, _spec in c0.DOMAINS:
        lock_path = os.path.join(repo, slot_dir, "capability.lock")
        if not os.path.exists(lock_path):
            continue
        with open(lock_path, encoding="utf-8") as f:
            lock = json.load(f)
        stale = []
        for name, digest in sorted(lock.get("files", {}).items()):
            path = os.path.join(repo, slot_dir, name)
            if not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != digest:
                    stale.append(name)
        if stale:
            out.append({"domain": slot_dir, "staleFileDigests": stale})
    return out


# ---------------------------------------------------------------------------
# Mechanical verification. A declared chain is worthless unless it is EVALUATED:
# for every semantic-input derivation whose transformation is mechanically
# evaluable, apply it to the real capability-spec and compare against the bytes the
# generator actually emitted. This is what makes source substitution and ordering
# drift bite — a chain that no longer reproduces the artifact is not a bijection.
# ---------------------------------------------------------------------------
EVALUABLE = {"identity", "project-field", "project-distinct", "filter-project",
             "machine-vocabulary"}


def _spec_values(spec, path):
    """Evaluate a sourceRef path over a capability-spec, returning the ordered list
    of leaf values it selects (mirrors the C0 grammar: dotted keys, `[]`, and
    `[key==value]` filters)."""
    nodes = [spec]
    for segment in path.split("."):
        key, filt = segment, None
        if key.endswith("]"):
            head, _, predicate = key[:-1].partition("[")
            key, filt = head, (predicate or "")
        nxt = []
        for node in nodes:
            if not isinstance(node, dict) or key not in node:
                continue
            value = node[key]
            if filt is None:
                nxt.append(value)
                continue
            if not isinstance(value, list):
                return None
            for element in value:
                if "==" in filt:
                    fkey, _, fval = filt.partition("==")
                    if not isinstance(element, dict) or element.get(fkey) != fval:
                        continue
                nxt.append(element)
        nodes = nxt
    return nodes


def _emitted_values(doc, address):
    """Collect the emitted values at a C0 field-address, in document order."""
    out = []

    def walk(node, remaining):
        if not remaining:
            out.append(node)
            return
        head, _, rest = remaining.partition(".")
        if head.endswith("[]"):
            key = head[:-2]
            if not isinstance(node, dict) or key not in node:
                return
            seq = node[key]
            if not isinstance(seq, list):
                return
            for element in seq:
                walk(element, rest)
            return
        if not isinstance(node, dict):
            return
        if head.startswith("<") and head.endswith(">"):
            # A grammar variable stands for a data-valued key; visit every key.
            for value in node.values():
                walk(value, rest)
            return
        if head not in node:
            return
        walk(node[head], rest)

    walk(doc, address)
    # A terminal `x[]` address collects the array itself; flatten one level.
    flat = []
    for value in out:
        if isinstance(value, list):
            flat.extend(value)
        else:
            flat.append(value)
    return flat


# Per-element emission predicates. A conditional row must say EXACTLY which source
# elements produce output; "some ordered subset" is not a derivation, because it
# accepts an arbitrary wrong omission that happens to preserve order.
PREDICATES = ("always", "value-nonempty", "participant-flexible",
              "participant-flexible-and-value-nonempty")


def _emits(predicate, element, value):
    empty = value in (None, "", [], {})
    flexible = isinstance(element, dict) and element.get("binding") == "to_be_bound"
    if predicate == "always":
        return True
    if predicate == "value-nonempty":
        return not empty
    if predicate == "participant-flexible":
        return flexible
    if predicate == "participant-flexible-and-value-nonempty":
        return flexible and not empty
    raise BijectionError(f"unknown emission predicate {predicate!r}")


def _split_source(source):
    """Split a sourceRef into (container-path, leaf-path). The container is
    everything up to and including the last `[]`/filter segment; the leaf is the
    path evaluated inside each element. A source with no array segment has no
    container and yields a single value."""
    segments = source.split(".")
    for i, seg in enumerate(segments):
        if seg.endswith("]"):
            # Split at the FIRST array segment: a per-element emission predicate
            # applies to that element (e.g. a participant), not to members of a
            # nested leaf array (e.g. its runtimes).
            return ".".join(segments[:i + 1]), ".".join(segments[i + 1:])
    return None, source


def _leaf(node, path):
    if not path:
        return node
    for key in path.split("."):
        listy = key.endswith("[]")
        if listy:
            key = key[:-2]
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
        if listy and not isinstance(node, list):
            return None
    return node


def _projected_pairs(spec, source):
    """[(source-element, projected-value)] for a sourceRef, preserving order. The
    element is kept so a per-element emission predicate can be evaluated."""
    container, leaf = _split_source(source)
    if container is None:
        return [(spec, _leaf(spec, leaf))]
    elements = _spec_values(spec, container)
    if elements is None:
        return None
    return [(e, _leaf(e, leaf)) for e in elements]


def _expected_occurrences(kind, spec, repo, slot_dir):
    """How many times a contract-owned field must appear in one domain."""
    if kind == "one":
        return 1
    participants = spec.get("participants", []) or []
    if kind == "per-participant":
        return len(participants)
    if kind == "per-flexible-participant":
        return len([p for p in participants
                    if isinstance(p, dict) and p.get("binding") == "to_be_bound"])
    if kind == "per-operation":
        ops_path = os.path.join(repo, slot_dir, "operations.json")
        if not os.path.exists(ops_path):
            return None
        with open(ops_path, encoding="utf-8") as f:
            return len(json.load(f)["operations"])
    if kind == "per-wire-file":
        lock_path = os.path.join(repo, slot_dir, "capability.lock")
        if not os.path.exists(lock_path):
            return None
        with open(lock_path, encoding="utf-8") as f:
            return len(json.load(f).get("files", {}))
    if kind == "unchecked":
        return None
    raise BijectionError(f"unknown multiplicity {kind!r}")


def _verify_contract_row(repo, artifact, address, d):
    """Evaluate a descriptor-contract chain against the emitted bytes.

    `constant` compares against the contract's frozen value; `digest` recomputes
    the receipt; the remaining contract transforms are rule-checked. A contract row
    that owns bytes it cannot reproduce is an ownership catalogue, not a bijection."""
    full = f"{artifact}::{address}"
    for slot_dir, spec_path in c0.DOMAINS:
        art = os.path.join(repo, slot_dir, artifact)
        spec_file = os.path.join(repo, spec_path)
        if not (os.path.exists(art) and os.path.exists(spec_file)):
            continue
        with open(art, encoding="utf-8") as f:
            doc = json.load(f)
        with open(spec_file, encoding="utf-8") as f:
            spec = json.load(f)
        emitted = _emitted_values(doc, address)

        # A contract-owned field must appear the EXACT number of times the contract
        # requires. Validating only when present would let a required or conditional
        # occurrence disappear silently.
        expected_n = _expected_occurrences(d.get("multiplicity", "one"), spec,
                                           repo, slot_dir)
        if expected_n is not None and not address.endswith("[]"):
            if len(emitted) != expected_n:
                return (f"{full} must be emitted {expected_n}x in {slot_dir} "
                        f"(multiplicity {d.get('multiplicity', 'one')!r}) but appears "
                        f"{len(emitted)}x")
        elif expected_n is not None and address.endswith("[]"):
            if expected_n > 0 and not emitted:
                return (f"{full} is a contract-owned list that must be emitted in "
                        f"{slot_dir} but is absent")
        if not emitted:
            continue

        if d["transformation"] == "constant":
            if full not in CONTRACT_CONSTANTS:
                return (f"{full} is a contract-owned constant but the contract "
                        "carries no value for it — prose cannot reject a changed byte")
            expected = CONTRACT_CONSTANTS[full]
            if address.endswith("[]"):
                if emitted != expected:
                    return (f"{full} does not match its contract value in {slot_dir}: "
                            f"emitted {emitted!r} != contract {expected!r}")
            else:
                for value in emitted:
                    if value != expected:
                        return (f"{full} does not match its contract value in "
                                f"{slot_dir}: emitted {value!r} != contract "
                                f"{expected!r}")
            continue

        if d["transformation"] == "prefix-compose":
            procedure = spec.get("procedure", "")
            capability = "coordinate." + procedure
            if address.endswith("slotId"):
                names = [p.get("name") for p in spec.get("participants", [])]
                expected = [f"{capability}#{n}" for n in names]
                if emitted != expected:
                    return (f"{full} does not reproduce the contract slot-id join in "
                            f"{slot_dir}: {emitted[:3]}… != {expected[:3]}…")
            else:
                for value in emitted:
                    if value != capability:
                        return (f"{full} does not reproduce the contract identity "
                                f"prefix in {slot_dir}: {value!r} != {capability!r}")
            continue

        if d["transformation"] == "digest":
            # The receipt algorithm is verified for INTERNAL consistency: the
            # capabilityHash must be the contract's sha256 over the lock's own
            # sorted `<basename>:<sha256>\n` preimage. That bites a misdeclared
            # algorithm. It is deliberately NOT claimed that the per-file digests
            # match the committed artifact bytes — they do not, and that
            # discrepancy is recorded as a finding rather than asserted away
            # (see lockDigestFindings / the lock-crossartifact-inputs adjudication).
            lock_path = os.path.join(repo, slot_dir, "capability.lock")
            if not os.path.exists(lock_path):
                continue
            with open(lock_path, encoding="utf-8") as f:
                lock = json.load(f)
            files = lock.get("files", {})
            if address == "files.<name>":
                if sorted(emitted) != sorted(files.values()):
                    return (f"{full} does not enumerate the lock's own file digests "
                            f"in {slot_dir}")
            else:
                preimage = "".join(f"{n}:{files[n]}\n" for n in sorted(files))
                expected = hashlib.sha256(preimage.encode()).hexdigest()
                if emitted[0] != expected:
                    return (f"{full} does not reproduce the contract receipt "
                            f"algorithm over the lock's own inputs in {slot_dir}")
            continue

        if d["transformation"] == "fallback-default":
            pairs = _projected_pairs(spec, d["sourceRef"])
            if pairs is None:
                return f"{full}: sourceRef does not evaluate in {slot_dir}"
            expected = []
            for element, value in pairs:
                flexible = (isinstance(element, dict)
                            and element.get("binding") == "to_be_bound")
                expected.append(value if (flexible and value) else "A1")
            if emitted != expected:
                return (f"{full} does not reproduce the contract fallback in "
                        f"{slot_dir}: {emitted!r} != {expected!r}")
            continue

        if d["transformation"] == "template-interpolate":
            procedure = spec.get("procedure", "")
            expected = f"{procedure}:<idempotency_key>:compensation"
            for value in emitted:
                if value != expected:
                    return (f"{full} does not reproduce the contract template in "
                            f"{slot_dir}: {value!r} != {expected!r}")
            continue

        if d["transformation"] == "table-lookup":
            ops_path = os.path.join(repo, slot_dir, "operations.json")
            if not os.path.exists(ops_path):
                continue
            with open(ops_path, encoding="utf-8") as f:
                entries = json.load(f)["operations"]
            # Totality over the vocabulary, AND the exact prose per operation: a
            # permuted or arbitrary mapping must be rejected, so each operation's
            # value is compared against the contract table (or, for PROPOSE, against
            # the contract template applied to this agreement).
            computes = [c["name"] for c in _spec_values(spec, "computes[]") or []
                        if isinstance(c, dict)]
            effects = [f"{e.get('kind')} {e.get('name')}"
                       for e in _spec_values(spec, "effects[]") or []
                       if isinstance(e, dict)]
            for entry in entries:
                op, value = entry["operation"], entry["maps"]
                if op == "PROPOSE":
                    expected = PROPOSE_TEMPLATE.format(
                        computes=", ".join(computes), entries=", ".join(effects))
                elif op in OPERATION_PROSE:
                    expected = OPERATION_PROSE[op]
                else:
                    return (f"{full}: operation {op!r} has no contract prose entry in "
                            f"{slot_dir} — the table must be total over the vocabulary")
                if value != expected:
                    return (f"{full}: operation {op!r} does not match the contract "
                            f"table in {slot_dir}: emitted {value!r} != contract "
                            f"{expected!r}")
            continue

    return None


def _verify_derivation(repo, artifact, address, d, predicate="always"):
    """Evaluate a declared chain against the committed data.

    Semantic rows apply their sourceRef and per-element emission predicate and must
    reproduce the emitted sequence EXACTLY — including expected absence. Contract
    rows are evaluated by _verify_contract_row. Only genuinely unevaluable
    transformations (a boolean predicate over the whole spec) are skipped, and they
    are skipped explicitly rather than by falling through."""
    if d["authority"] == "descriptor-contract":
        return _verify_contract_row(repo, artifact, address, d)
    if d["transformation"] not in EVALUABLE:
        return None
    source = d["sourceRef"]
    for slot_dir, spec_path in c0.DOMAINS:
        art = os.path.join(repo, slot_dir, artifact)
        spec_file = os.path.join(repo, spec_path)
        if not (os.path.exists(art) and os.path.exists(spec_file)):
            continue
        with open(art, encoding="utf-8") as f:
            doc = json.load(f)
        with open(spec_file, encoding="utf-8") as f:
            spec = json.load(f)
        emitted = _emitted_values(doc, address)

        if d["transformation"] == "machine-vocabulary":
            ops_path = os.path.join(repo, slot_dir, "operations.json")
            if not os.path.exists(ops_path):
                continue
            with open(ops_path, encoding="utf-8") as f:
                machine = [o["operation"] for o in json.load(f).get("operations", [])]
            if d["canonicalOrder"] != "machine-order":
                return (f"{artifact}::{address} projects the lifecycle vocabulary but "
                        f"declares canonicalOrder {d['canonicalOrder']!r}")
            if address in ("operations[]", "properties.operation.enum[]",
                           "operations[].operation") and emitted != machine:
                return (f"{artifact}::{address} does not reproduce the machine "
                        f"vocabulary in {slot_dir}")
            continue

        pairs = _projected_pairs(spec, source)
        if pairs is None:
            return (f"{artifact}::{address} sourceRef {source!r} does not evaluate "
                    f"against the capability-spec in {slot_dir}")
        expected = []
        for element, value in pairs:
            if not _emits(predicate, element, value):
                continue
            if isinstance(value, list):
                expected.extend(value)
            else:
                expected.append(value)
        if d["transformation"] == "project-distinct":
            seen, deduped = set(), []
            for v in expected:
                if v not in seen:
                    seen.add(v)
                    deduped.append(v)
            expected = deduped
        expected = [v for v in expected
                    if isinstance(v, (str, int, float, bool)) or v is None]
        if not expected and not emitted:
            continue
        if expected != emitted:
            return (f"{artifact}::{address} declared chain {source} "
                    f"--{d['transformation']}/{predicate}--> does not reproduce the "
                    f"emitted values in {slot_dir}: emitted {emitted[:4]}… != "
                    f"expected {expected[:4]}…")
    return None


def generate(repo=REPO):
    """Build the bijection over the C0 census rows. Fails closed on any gap."""
    census = c0.generate(repo)
    observed = {row["fieldAddress"] for row in census["fields"]}

    problems, rows = [], []
    declared = set()
    for artifact, table in DERIVATIONS.items():
        for address, d in table.items():
            declared.add(f"{artifact}::{address}")

    # (1) BIJECTION: exactly one derivation per witnessed field, and none extra.
    for address in sorted(observed - declared):
        problems.append(
            f"{address} is a witnessed field with NO derivation — C1 requires a "
            "source-or-contract-item -> transformation -> field chain for every row")
    for address in sorted(declared - observed):
        problems.append(
            f"{address} has a derivation but is not a witnessed C0 field — the "
            "bijection may not model fields the census does not observe")

    census_by_address = {row["fieldAddress"]: row for row in census["fields"]}
    for artifact, table in DERIVATIONS.items():
        for address, d in sorted(table.items()):
            full = f"{artifact}::{address}"
            # (2) every row names a typed transformation, order and validator.
            if d["transformation"] not in TRANSFORMS:
                problems.append(f"{full}: unknown transformation "
                                f"{d['transformation']!r}")
            if d["canonicalOrder"] not in ORDERS:
                problems.append(f"{full}: unknown canonicalOrder "
                                f"{d['canonicalOrder']!r}")
            if not d["validationOwner"]:
                problems.append(f"{full}: no validation owner")
            if d["authority"] not in AUTHORITIES:
                problems.append(f"{full}: authority {d['authority']!r} is outside the "
                                "revised C1 model")
            # (3) FUTURE AUTHORITIES STAY EMPTY unless a typed input is witnessed.
            if d["authority"] in FUTURE_AUTHORITIES:
                problems.append(
                    f"{full}: claims the {d['authority']} authority, which must stay "
                    "zero-row until an explicit typed input is wired AND mechanically "
                    "witnessed — C1 may not populate it aspirationally")
            # (4) ownership is real: a semantic row needs a spec path that the C0
            # census already resolved; a contract row needs a registered item.
            if d["authority"] == "semantic-input":
                if not d["sourceRef"]:
                    problems.append(f"{full}: semantic-input row with no sourceRef")
                if d["contractItem"]:
                    problems.append(f"{full}: semantic-input row also claims a "
                                    "contract item — ownership must be singular")
            elif d["authority"] == "descriptor-contract":
                if d["contractItem"] not in DESCRIPTOR_CONTRACT:
                    problems.append(
                        f"{full}: contract item {d['contractItem']!r} is not registered "
                        "in the versioned descriptor contract")
                if d["transformation"] == "identity":
                    problems.append(
                        f"{full}: a contract-owned row cannot be an identity of a "
                        "semantic value — that would be a disguised semantic input")
            # (5) the C0 row must agree that a semantic row had a resolvable path.
            c0row = census_by_address.get(full)
            if c0row and d["authority"] == "semantic-input":
                if c0row["authority"] != "capability-spec":
                    problems.append(
                        f"{full}: modelled as semantic-input but C0 observed it as "
                        f"{c0row['authority']} — the bijection contradicts the census")

            # (5b) EVALUATE the chain against committed data — a declared
            # source/order that no longer reproduces the emitted bytes is not a
            # bijection. This is what makes source substitution and ordering drift
            # bite rather than merely being re-labelled.
            if d.get("emitWhen") not in PREDICATES:
                problems.append(f"{full}: unknown emission predicate "
                                f"{d.get('emitWhen')!r}")
            failure = _verify_derivation(repo, artifact, address, d,
                                         predicate=d.get("emitWhen", "always"))
            if failure:
                problems.append(failure)

            rows.append({
                "fieldAddress": full,
                "artifact": artifact,
                "authority": d["authority"],
                "sourceRef": d["sourceRef"],
                "contractItem": d["contractItem"],
                "transformation": d["transformation"],
                "canonicalOrder": d["canonicalOrder"],
                "validationOwner": d["validationOwner"],
                "derivationGroup": d["derivationGroup"],
                "emitWhen": d.get("emitWhen", "always"),
                "multiplicity": d.get("multiplicity"),
                "cardinality": d["cardinality"],
                "note": d["note"],
            })

    # (6) every registered contract item and adjudication must be USED.
    by_address = {r["fieldAddress"]: r for r in rows}
    used_items = {r["contractItem"] for r in rows if r["contractItem"]}
    for item in sorted(set(DESCRIPTOR_CONTRACT) - used_items):
        problems.append(f"contract item {item!r} is registered but owns no row")
    derived_status = {}
    for _name, _d in DECISIONS.items():
        derived_status[_name] = _decision_status(
            _name, _d.get("statusFrom"), _d.get("rows", []), repo, census,
            by_address)

    # C2: every decision must carry a closed-vocabulary status, name rows that
    # actually exist, and — when it is not resolved — state its consequence. A
    # decision cannot be quietly dropped or left statusless.
    for name, decision in sorted(DECISIONS.items()):
        if derived_status[name] not in ("resolved", "requires-generator-change"):
            problems.append(f"decision {name!r} has unknown status "
                            f"{derived_status[name]!r}")
        if derived_status[name] != "resolved" and not decision.get("consequence"):
            problems.append(f"decision {name!r} is unresolved but states no "
                            "consequence")
        if not decision.get("resolution"):
            problems.append(f"decision {name!r} records no adjudication")
        for address in decision.get("rows", []):
            if address not in by_address:
                problems.append(f"decision {name!r} names {address}, which has no "
                                "derivation")
    for item, spec_ in sorted(DESCRIPTOR_CONTRACT.items()):
        ref = spec_.get("adjudication")
        if ref and ref not in DECISIONS:
            problems.append(f"contract item {item!r} references unknown decision "
                            f"{ref!r}")

    # (7) every invariant group must name rows that actually exist, AND every row
    # the invariant covers must still carry that group. Dropping the group from one
    # copy of a duplicated value is exactly how independent recomputation creeps
    # back in, so it fails closed rather than silently un-linking the pair.
    groups = {r["derivationGroup"] for r in rows if r["derivationGroup"]}
    for inv in CROSS_ARTIFACT_INVARIANTS:
        if inv["group"] not in groups:
            problems.append(
                f"invariant group {inv['group']!r} matches no derivation row")
        for address in inv.get("rows", []):
            row = by_address.get(address)
            if row is None:
                problems.append(
                    f"invariant {inv['group']!r} names {address}, which has no "
                    "derivation")
            elif row["derivationGroup"] != inv["group"]:
                problems.append(
                    f"{address} must carry derivationGroup {inv['group']!r} (the "
                    f"values are required to agree) but carries "
                    f"{row['derivationGroup']!r} — dropping the shared group would "
                    "permit independent recomputation")

    # S0-C2R: the committed receipts must bind the committed bytes. This was a
    # recorded finding while the corpus was stale; with the receipts regenerated it
    # becomes an enforced guarantee, so a one-byte artifact change fails closed.
    for finding in _lock_digest_findings(repo):
        problems.append(
            f"capability.lock in {finding['domain']} does not bind the committed "
            f"bytes of {finding['staleFileDigests']} — the receipt is stale")

    problems += _verify_shared_equalities(repo)
    problems += _verify_envelope_subset(repo)
    problems += _verify_lock_wire_set(repo)

    if problems:
        raise BijectionError("; ".join(problems))

    totals = {a: 0 for a in AUTHORITIES}
    for r in rows:
        totals[r["authority"]] += 1
    return {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "documentId": "urn:neutrino:document:slot-descriptor-authority-v1",
        "checkpoint": "S0-C1",
        "verdict": "authorized by S0-C3 S0-REVISE-PARTITION; C1 MODELLING ONLY — "
                   "grants no deletion, generator retirement, schema fork,  "
                   "reversal or  implementation",
        "censusRevision": census["sourceRevision"],
        "censusRows": census["totals"]["fields"],
        "descriptorContractVersion": DESCRIPTOR_CONTRACT_VERSION,
        "authorityTotals": totals,
        "futureAuthorities": {a: 0 for a in FUTURE_AUTHORITIES},
        "unnamedResiduals": 0,
        "lockDigestFindings": _lock_digest_findings(repo),
        "descriptorContract": DESCRIPTOR_CONTRACT,
        "decisions": {name: {**d, "status": derived_status[name],
                             "statusDerivedFrom": d.get("statusFrom")}
                      for name, d in sorted(DECISIONS.items())},
        # The PUBLIC residual/REVISE exit: exactly the decisions that are still
        # open. The full five-entry ledger stays above for the record.
        "residualDecisions": sorted(
            name for name in DECISIONS if derived_status[name] != "resolved"),
        "crossArtifactInvariants": CROSS_ARTIFACT_INVARIANTS,
        "checkpointC2": {
            "decisionsTotal": len(DECISIONS),
            "decisionsResolved": len(
                [n for n in DECISIONS if derived_status[n] == "resolved"]),
            "decisionsRequiringGeneratorChange": sorted(
                n for n in DECISIONS if derived_status[n] != "resolved"),
            "invariantsTotal": len(CROSS_ARTIFACT_INVARIANTS),
            "invariantsUnresolved": len(
                [i for i in CROSS_ARTIFACT_INVARIANTS if not i.get("enforced")]),
            "sharedDerivationEqualitiesEnforced": len(SHARED_DERIVATION_EQUALITIES),
            # The exit condition the S0-C2 scope defines: S0-BIJECTION-CONFIRMED is
            # available only with ZERO open decisions and ZERO unresolved invariants.
            "bijectionConfirmable": (
                all(v == "resolved" for v in derived_status.values())
                and all(i.get("enforced") for i in CROSS_ARTIFACT_INVARIANTS)),
        },
        "totals": {"derivations": len(rows)},
        "derivations": sorted(rows, key=lambda r: r["fieldAddress"]),
    }


# --------------------------------------------------------------------------
# Non-vacuity: the four mutations the C1 exit bar names.
# --------------------------------------------------------------------------
PROBES = {
    "source-substitution": (
        "repoint a semantic row at a different spec path",
        lambda: DERIVATIONS["capability.json"].__setitem__(
            "procedure", _sem("specVersion", "identity", "not-applicable", _SPEC))),
    "ordering-drift": (
        "change a projected array's canonical order",
        lambda: DERIVATIONS["capability.json"].__setitem__(
            "operations[]", _sem("lifecycle", "machine-vocabulary", "lexicographic",
                                 _LIFE, group="operation-vocabulary"))),
    "duplicated-independent-derivation": (
        "drop the shared derivation group from one copy of a duplicated value",
        lambda: DERIVATIONS["binding-topology.json"].__setitem__(
            "crossOrganization", _sem("participants[].org", "predicate",
                                      "not-applicable", _SCHEMA))),
    "contract-literal-drift": (
        "change a contract-owned literal so the frozen contract no longer matches "
        "the emitted bytes",
        lambda: CONTRACT_CONSTANTS.__setitem__(
            "capability.json::kind", "neutrino.changed-kind")),
    "conditional-element-omission": (
        "weaken a conditional row's emission predicate so an element that MUST be "
        "emitted may be silently omitted",
        lambda: DERIVATIONS["capability.json"].__setitem__(
            "declaredParticipants[].name",
            _sem("participants[].name", "project-field", "source-order", _SPEC,
                 cardinality="1:N", emit="participant-flexible"))),
    "contract-occurrence-loss": (
        "declare a per-collection contract field as single-occurrence so a lost "
        "required occurrence would pass unnoticed",
        lambda: DERIVATIONS["binding-topology.json"].__setitem__(
            "organizations[].participants[].slots[].evidenceProfile",
            _con("binding-evidence-profile-default", "constant", "not-applicable",
                 _SCHEMA, mult="one"))),
    "table-value-permutation": (
        "permute the contract's operation prose so a wrong mapping value would pass",
        lambda: OPERATION_PROSE.__setitem__(
            "COMMIT", OPERATION_PROSE["CLOSE"])),
    "shared-derivation-disagreement": (
        "point one side of a shared derivation at a different emitted address so the "
        "two copies of a duplicated value would be allowed to diverge",
        lambda: SHARED_DERIVATION_EQUALITIES.__setitem__(
            0, {"group": "cross-organization",
                "left": ("capability.json", "topology.crossOrganization"),
                "right": ("binding-topology.json", "procedure")})),
    "envelope-subset-drift": (
        "declare a correlation subset the machine vocabulary does not contain, "
        "reaching the reconciliation check rather than the frozen-constant check",
        lambda: globals().__setitem__("_ENVELOPE_SUBSET_OVERRIDE",
                                      ["COMMIT", "REJECT", "NOT_AN_OPERATION"])),
    "envelope-subset-not-strict": (
        "declare a correlation subset equal to the whole vocabulary, making the "
        "rule vacuous",
        lambda: globals().__setitem__("_ENVELOPE_SUBSET_OVERRIDE", None)),
    "lock-wire-set-drift": (
        "declare a lock wire set the committed receipts do not cover",
        lambda: globals().__setitem__(
            "LOCK_WIRE_SET", ("capability.json", "operations.json"))),
    "new-target-authority": (
        "introduce a target/deploy authority without a witnessed typed input",
        lambda: DERIVATIONS["transcript.json"].__setitem__(
            "anchoring.anchorRef.chain",
            {"authority": "deploy-coordinate", "sourceRef": "deployment.chain",
             "contractItem": None, "transformation": "identity",
             "canonicalOrder": "not-applicable", "validationOwner": "deploy",
             "derivationGroup": None, "cardinality": "1:1", "note": ""})),
}


def probe(name, repo=REPO):
    if name not in PROBES:
        print(f"unknown probe '{name}'", file=sys.stderr)
        return 2
    description, mutate = PROBES[name]
    saved = copy.deepcopy(DERIVATIONS)
    saved_constants = copy.deepcopy(CONTRACT_CONSTANTS)
    saved_prose = copy.deepcopy(OPERATION_PROSE)
    saved_shared = copy.deepcopy(SHARED_DERIVATION_EQUALITIES)
    saved_wire = LOCK_WIRE_SET
    try:
        mutate()
        try:
            generate(repo)
        except BijectionError:
            print(f"probe-failed-as-expected:{name} ({description})")
            return 1
        print(f"probe-DID-NOT-BITE:{name} ({description})", file=sys.stderr)
        return 0
    finally:
        DERIVATIONS.clear()
        DERIVATIONS.update(saved)
        CONTRACT_CONSTANTS.clear()
        CONTRACT_CONSTANTS.update(saved_constants)
        OPERATION_PROSE.clear()
        OPERATION_PROSE.update(saved_prose)
        SHARED_DERIVATION_EQUALITIES[:] = saved_shared
        globals()['LOCK_WIRE_SET'] = saved_wire


def _ordering_drift_detected(repo):
    """Ordering drift must be caught by VALUE, not just by the declared label: an
    array declared `machine-order` whose emitted order is not the machine's order
    is a real drift. Compares the committed capability.json operations against the
    operations.json machine order."""
    for slot_dir, _spec_path in c0.DOMAINS:
        cap = os.path.join(repo, slot_dir, "capability.json")
        ops = os.path.join(repo, slot_dir, "operations.json")
        if not (os.path.exists(cap) and os.path.exists(ops)):
            continue
        with open(cap, encoding="utf-8") as f:
            vocab = json.load(f).get("operations", [])
        with open(ops, encoding="utf-8") as f:
            machine = [o["operation"] for o in json.load(f).get("operations", [])]
        if vocab != machine:
            return slot_dir
    return None


def selftest(repo=REPO):
    report = generate(repo)
    failures = []
    if report["totals"]["derivations"] != report["censusRows"]:
        failures.append(
            f"bijection covers {report['totals']['derivations']} rows but the census "
            f"witnesses {report['censusRows']} — C1 requires one chain per row")
    if report["authorityTotals"]["unresolved-decision"] != 0:
        failures.append("rows filed directly under unresolved-decision; a residual "
                        "must be an owned contract item plus a named adjudication")
    if any(v for v in report["futureAuthorities"].values()):
        failures.append("a future authority gained rows")
    if report["unnamedResiduals"] != 0:
        failures.append("unnamed residuals remain")
    if len(report["decisions"]) < 5:
        failures.append("the five verdict-named adjudications are not all recorded")
    # The public exit must expose EXACTLY the derived residuals — no more, no less.
    expected_residual = sorted(
        n for n, d in report["decisions"].items() if d["status"] != "resolved")
    if report["residualDecisions"] != expected_residual:
        failures.append(
            f"public residual exit {report['residualDecisions']} does not match the "
            f"derived residuals {expected_residual}")
    # Every status must be DERIVED, never asserted.
    for name, d in report["decisions"].items():
        if not d.get("statusDerivedFrom"):
            failures.append(f"decision {name} has an asserted, not derived, status")

    # The overlay decision must track the DEFECT (mutation/refresh ordering and
    # hashed-wire-set membership), never the presence of a census row. The fixture
    # below MOVES THE REAL OVERLAY STATEMENT and invokes the REAL evidence
    # extractor — no precomputed conclusion is injected.
    _real_sources = _overlay_sources(repo)
    _overlay_rel = next(
        (rel for rel in _real_sources
         if rel.endswith("SlotBackendClaims.cpp")), None)
    if _overlay_rel is None:
        # The overlay is DELETED in the retired state, so the fixture recovers its
        # real statements from the last revision that carried them. The extractor
        # is still the real one and the statements are still the real ones — the
        # discriminating power of the fixture must not depend on the defect still
        # being present in the working tree.
        _overlay_rel = "lib/slots/full/SlotBackendClaims.cpp"
        _proc = subprocess.run(
            ["git", "-C", repo, "log", "-1", "--format=%H", "--", _overlay_rel],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        _rev = (_proc.stdout or "").strip()
        _text = ""
        if _rev:
            _blob = subprocess.run(
                ["git", "-C", repo, "show", f"{_rev}^:{_overlay_rel}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            _text = _blob.stdout or ""
        if not _text:
            failures.append(
                "overlay evidence fixture unavailable: the retired overlay source "
                "could not be recovered from history")
    else:
        _text = _real_sources[_overlay_rel]
    if _text:

        def _statement_span(text, start):
            """The full statement containing `start`, from its line beginning
            through the semicolon that terminates it."""
            begin = text.rfind("\n", 0, start) + 1
            end = text.index(";", start) + 1
            while end < len(text) and text[end] == "\n":
                end += 1
            return begin, end

        _mut = _OVERLAY_MUTATION_RE.search(_text)
        _ref = _text.index(_LOCK_REFRESH)
        _ms, _me = _statement_span(_text, _mut.start())
        _rs, _re_ = _statement_span(_text, _ref)
        if not (_me <= _rs):
            failures.append(
                "overlay fixture expected the mutation to precede the refresh")
        else:
            _moved = (_text[:_ms] + _text[_me:_rs]
                      + _text[_rs:_re_] + _text[_ms:_me] + _text[_re_:])
            _excluded = _text.replace('"capability.json"', '"binding-topology.json"')
            _row = {"fields": [{"fieldAddress": "capability.json::backends[]"}]}
            _cases = (
                ("mutation BEFORE refresh, artifact in wire set", _text,
                 "requires-generator-change"),
                ("mutation AFTER refresh, row retained", _moved, "resolved"),
                ("mutation before refresh, artifact OUTSIDE wire set", _excluded,
                 "resolved"),
            )
            for _desc, _variant, _want in _cases:
                _sources = dict(_real_sources)
                _sources[_overlay_rel] = _variant
                _ev = _overlay_identity_evidence(repo, sources=_sources)
                _got = ("resolved" if _ev["lockIdentityProfileEqual"]
                        else "requires-generator-change")
                if _got != _want:
                    failures.append(
                        f"overlay evidence wrong for [{_desc}]: got {_got!r}, "
                        f"expected {_want!r} (hazards={_ev['orderingHazards']})")
                # ROW-INDEPENDENCE: with the evidence fixed, deleting or renaming
                # the census row must not move the decision.
                for _census in (_row, {"fields": []},
                                {"fields": [{"fieldAddress":
                                             "capability.json::renamedBackends[]"}]}):
                    _status = _decision_status(
                        "backends-overlay-authority",
                        "overlay-identity-profile-equal", [], repo, _census, {},
                        sources=_sources)
                    if _status != _want:
                        failures.append(
                            f"census-row presence changed the overlay decision for "
                            f"[{_desc}]: {_status!r} != {_want!r}")

    drift = _ordering_drift_detected(repo)
    if drift:
        failures.append(f"declared machine-order does not match emitted order in {drift}")

    for name in PROBES:
        saved = copy.deepcopy(DERIVATIONS)
        saved_constants = copy.deepcopy(CONTRACT_CONSTANTS)
        saved_prose = copy.deepcopy(OPERATION_PROSE)
        saved_shared = copy.deepcopy(SHARED_DERIVATION_EQUALITIES)
        saved_wire = LOCK_WIRE_SET
        try:
            PROBES[name][1]()
            try:
                generate(repo)
                failures.append(f"mutation {name!r} did not bite")
            except BijectionError:
                pass
        finally:
            DERIVATIONS.clear()
            DERIVATIONS.update(saved)
            CONTRACT_CONSTANTS.clear()
            CONTRACT_CONSTANTS.update(saved_constants)
            OPERATION_PROSE.clear()
            OPERATION_PROSE.update(saved_prose)
            SHARED_DERIVATION_EQUALITIES[:] = saved_shared
            globals()['LOCK_WIRE_SET'] = saved_wire

    if failures:
        print("slot-descriptor-bijection SELFTEST FAILED:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        return 1
    print(f"slot-descriptor-bijection selftest OK "
          f"({report['totals']['derivations']} derivations, one per witnessed census "
          f"row; zero unnamed residuals; future authorities empty; source-substitution, "
          f"ordering-drift, duplicated-independent-derivation and new-target-authority "
          f"all bite)")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe")
    args = parser.parse_args()
    try:
        if args.probe:
            return probe(args.probe)
        if args.selftest:
            return selftest()
        report = generate()
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        output = os.path.join(REPO, args.output)
        if args.write:
            os.makedirs(os.path.dirname(output), exist_ok=True)
            with open(output, "w", encoding="utf-8") as f:
                f.write(payload)
            print(f"wrote {args.output}: {len(report['derivations'])} derivations")
            return 0
        try:
            committed = open(output, encoding="utf-8").read()
        except OSError as exc:
            raise BijectionError(f"committed bijection missing: {exc}")
        if committed != payload:
            raise BijectionError("committed bijection is stale; rerun --write")
        t = report["authorityTotals"]
        print(f"slot-descriptor-bijection: PASS ({report['totals']['derivations']} "
              f"derivations; semantic-input={t['semantic-input']}, "
              f"descriptor-contract={t['descriptor-contract']}, "
              f"unnamed residuals=0, "
              f"open residuals={len(report['residualDecisions'])})")
        return 0
    except (BijectionError, c0.SlotCensusError, OSError, ValueError) as exc:
        print(f"slot-descriptor-bijection: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
