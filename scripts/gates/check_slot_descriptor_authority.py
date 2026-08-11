#!/usr/bin/env python3
"""Slot-descriptor authority census ( M7 S0-C0).

PROBE/CENSUS ONLY. This gate grants NO retirement authority and proposes no
redesign: it records, mechanically and per field, WHERE each slot-descriptor
datum actually comes from in the committed generator, so the architect can rule
(S0-C3) on whether a single non-drifting authority partition exists.

WHAT IT DOES
  1. Enumerates every leaf field-address in the committed slot artifacts, unioned
     over the representative domains (so a conditionally-emitted artifact or a
     conditionally-emitted field is still seen).
  2. Joins each observed address against the declared AUTHORITY_TABLE below, whose
     every row is grounded in an exact `lib/slots/...:line` emitter citation.
  3. Fails closed when an observed field has no row (a new/renamed generator field
     cannot slip in unclassified) or when a declared row — conditional or not — is
     witnessed by NO domain (a field cannot silently disappear, and an unwitnessed
     declaration cannot be counted as an empirical field). Every counted row is an
     OBSERVATION; a reachable-but-unexercised emitter branch is recorded separately
     in `unexercisedEmitterBranches` as a finding.
  4. Resolves every `capability-spec` row's `sourcePath` against the REAL
     capability-spec instances that produced those artifacts, so an authority
     claim cannot be asserted without a path that actually exists.

THE EMPIRICAL RESULT THIS CENSUS RECORDS (do not "fix" it here)
  `emitSlotProject` (lib/slots/SlotTarget.cpp:24-27) takes `const Scenario &` —
  UNNAMED and UNUSED — and reads only `ingestSelfEmittedSpec(view, plan)`. No
  BackendProjectionGraph, no target profile, and no deploy-time coordinate is
  read anywhere in the slot renderer. So of the five taxonomy authorities, only
  TWO are observed:

      capability-spec  — the self-emitted spec (including its embedded
                         `lifecycle`, via lifecycleModelFromSpec)
      UNSOURCED        — literals/templates/computed defaults/receipts baked
                         into the emitters, each named with its `unsourcedKind`

  `finalized-projection`, `target-profile` and `deploy-coordinate` carry ZERO
  rows. That is a census FINDING, recorded verbatim in the inventory's
  `authorityTotals` and `unobservedAuthorities`; it is deliberately NOT smoothed
  into the proposed three-way split, which this slice does not adopt.

RATCHET
  The count of `UNSOURCED` rows may never INCREASE against the base revision's
  committed inventory — the census becomes standing pressure toward a single
  authority without itself authorizing any retirement. The first landing creates
  the baseline.

Usage:
  check_slot_descriptor_authority.py --write      # (re)bank the inventory
  check_slot_descriptor_authority.py              # verify committed == fresh
  check_slot_descriptor_authority.py --selftest   # non-vacuity mutations
"""
import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUTPUT = "docs/slot-descriptor-authority-inventory.json"
KIND = "neutrino.slot-descriptor-authority-inventory"
SCHEMA_VERSION = 1

# The closed authority taxonomy from the  census scope. The census reports
# which of these are actually OBSERVED; it does not require all to be populated.
AUTHORITIES = (
    "capability-spec",
    "finalized-projection",
    "target-profile",
    "deploy-coordinate",
    "UNSOURCED",
)

# Closed reason vocabulary for a datum with no single traceable source. Every
# UNSOURCED row MUST name one (never inferred, never silently defaulted).
UNSOURCED_KINDS = (
    "literal-constant",     # a constant baked into the emitter/template
    "computed-default",     # a fallback the emitter substitutes when spec is silent
    "computed-receipt",     # a hash over other artifacts (inherently cross-artifact)
    "overlay-literal",      # a constant injected by a build-profile overlay TU
    "mixed-literal-spec",   # literal prose whose payload interpolates spec names
)

# Representative committed domains: (slot artifact dir, the capability-spec that
# produced it). Unioned, so conditional emission is covered rather than assumed.
DOMAINS = (
    ("test/ir/domain/Inputs/core_flexible_binding/generated/slot",
     "test/ir/domain/Inputs/core_flexible_binding/generated/capability-spec/capability-spec.json"),
    ("test/ir/samples/Inputs/core_promo_campaign/generated/slot",
     "test/ir/samples/Inputs/core_promo_campaign/generated/capability-spec/capability-spec.json"),
    ("test/ir/pipeline/Inputs/core_sample_installment/generated/slot",
     "test/ir/pipeline/Inputs/core_sample_installment/generated/capability-spec/capability-spec.json"),
    ("test/ir/pipeline/Inputs/core_scheme_settlement/generated/slot",
     "test/ir/pipeline/Inputs/core_scheme_settlement/generated/capability-spec/capability-spec.json"),
)

# The seven artifacts. `conditional` names the emission predicate for the one
# artifact that is not always produced (proved by core_sample_installment, which
# declares no participants and therefore has no binding-topology.json).
ARTIFACTS = {
    "capability.json": None,
    "operations.json": None,
    "compensation.json": None,
    "transcript.json": None,
    "envelope.schema.json": None,
    "binding-topology.json": "spec.participants nonempty (GenSlotSpec.cpp:540-543)",
    "capability.lock": None,
}

# Object keys whose NAME is data, not schema — normalized to a grammar variable
# so the census row is stable across domains.
DYNAMIC_KEY_PARENTS = {
    ("capability.lock", "files"): "<name>",
    ("compensation.json", "compensable"): "<commitOp>",
}

# Emitter branches that are REACHABLE IN CODE but exercised by NO committed
# domain. They are recorded as census FINDINGS, never as authority rows: a row
# nobody emits would be a declaration, not an observation, and counting it would
# make the S0-C3 authority totals partly speculative. Each entry states the
# evidence for the claim so the architect can weigh it.
UNEXERCISED_EMITTER_BRANCHES = [
    {
        "emitter": "lib/slots/GenSlotSpec.cpp:71-77",
        "branch": 'refJson emits { "literal": <value> } when the spec operand '
                  'kind == "literal"',
        "wouldProduce": [
            "capability.json::entries[].party.literal",
            "capability.json::entries[].amount.literal",
            "capability.json::entries[].currency.literal",
            "capability.json::entries[].idempotencyKey.literal",
        ],
        "evidence": "every effect operand in every committed capability-spec is "
                    'kind == "ref" (136 operands, 0 literal, whole-corpus scan); '
                    "no committed slot artifact contains a literal operand",
        "censusEffect": "not counted as authority rows — the observed authority "
                        "map contains no literal-operand field",
    },
]

# Ordering vocabulary (how an array's element order is determined).
ORDER_FIRST = "first-appearance"
ORDER_DISTINCT = "distinct-first-appearance"
ORDER_MACHINE = "lifecycle-machine-order"
ORDER_SORTED = "sorted"
ORDER_FIXED = "fixed-key-order"
ORDER_NA = "n/a"


def _spec(path, source, kind=None, opt="R", pred=None, order=ORDER_NA,
          invariant=None, note=""):
    """A capability-spec-authored row. `source` is a spec path that MUST resolve
    against at least one real capability-spec instance."""
    return {"authority": "capability-spec", "sourcePath": source,
            "unsourcedKind": kind, "optionality": opt, "optionalityPredicate": pred,
            "ordering": order, "invariant": invariant, "emitter": path, "note": note}


def _lit(path, kind, opt="R", pred=None, order=ORDER_NA, invariant=None, note=""):
    """An UNSOURCED row. `kind` names WHY there is no single traceable source."""
    return {"authority": "UNSOURCED", "sourcePath": None, "unsourcedKind": kind,
            "optionality": opt, "optionalityPredicate": pred, "ordering": order,
            "invariant": invariant, "emitter": path, "note": note}


_G = "lib/slots/GenSlotSpec.cpp"
_OVERLAY = "lib/slots/full/SlotBackendClaims.cpp"

# Identity note reused where the emitter prefixes a spec datum with a structural
# constant. The constant is a namespace, not a datum, so the row stays
# capability-spec-authored (contrast `mixed-literal-spec`, where the LITERAL is
# the payload and the spec only interpolates names into it).
_CAP_ID = 'cap = "coordinate." + spec.procedure (GenSlotSpec.cpp:528-529)'

AUTHORITY_TABLE = {
    "capability.json": {
        "kind": _lit(f"{_G}:177", "literal-constant", note='"neutrino.slot-capability"'),
        "capability": _spec(f"{_G}:178", "procedure", note=_CAP_ID),
        "capabilityVersion": _spec(f"{_G}:179", "specVersion"),
        "procedure": _spec(f"{_G}:180", "procedure"),
        "trigger": _spec(f"{_G}:181-182", "trigger", opt="C",
                         pred="spec.trigger present"),
        "parties[]": _spec(f"{_G}:159,183", "effects[].party.value",
                           order=ORDER_DISTINCT,
                           note="the party OPERANDS of the legs, not the ledger owners"),
        "declaredParticipants[].name": _spec(f"{_G}:192", "participants[].name",
                                             opt="C", pred="spec.participants nonempty",
                                             order=ORDER_FIRST),
        "declaredParticipants[].role": _spec(f"{_G}:192", "participants[].role",
                                             opt="C", pred="spec.participants nonempty"),
        "declaredParticipants[].org": _spec(f"{_G}:193-196", "participants[].org",
                                            opt="C", pred="participant org nonempty"),
        "declaredParticipants[].capabilities[]": _spec(
            f"{_G}:198", "participants[].capabilities[]", opt="C",
            pred="spec.participants nonempty", order=ORDER_FIRST),
        "declaredParticipants[].binding.mode": _lit(
            f"{_G}:200", "literal-constant", opt="C",
            pred='participant binding == "to_be_bound" (isFlexible, :125-127)',
            note='constant "to_be_bound"'),
        "declaredParticipants[].binding.runtimes[]": _spec(
            f"{_G}:200", "participants[].bindRuntimes[]", opt="C",
            pred="participant isFlexible", order=ORDER_FIRST),
        "declaredParticipants[].binding.minAssurance": _spec(
            f"{_G}:201-203", "participants[].bindMinAssurance", opt="C",
            pred="participant isFlexible and bindMinAssurance nonempty"),
        "declaredParticipants[].binding.authorizedBinder": _spec(
            f"{_G}:204-205", "participants[].org", opt="C",
            pred="participant isFlexible and org nonempty",
            note="the binder is the participant's own declared org"),
        "topology.organizations[]": _spec(
            f"{_G}:215-216", "participants[].org", opt="C",
            pred="declared named orgs nonempty", order=ORDER_DISTINCT),
        "topology.crossOrganization": _spec(
            f"{_G}:216", "participants[].org", opt="C",
            pred="declared named orgs nonempty",
            invariant="== binding-topology.json::crossOrganization "
                      "(independently recomputed at GenSlotSpec.cpp:484-485)",
            note="computed: distinct named orgs > 1"),
        "ledgerOwners[]": _spec(f"{_G}:219", "effects[].owner", order=ORDER_DISTINCT),
        "operations[]": _spec(f"{_G}:222-223", "lifecycle", order=ORDER_MACHINE,
                              invariant="== operations.json::operations[].operation "
                                        "and == envelope.schema.json::"
                                        "properties.operation.enum[]",
                              note="projected via lifecycleModelFromSpec(spec)"
                                   ".operationNames() ()"),
        "computed[]": _spec(f"{_G}:224", "computes[].name", order=ORDER_FIRST),
        "ledgers[]": _spec(f"{_G}:225", "effects[].ledger", order=ORDER_DISTINCT),
        "evidenceInputs[]": _spec(f"{_G}:226", "inputs[type==evidence].name",
                                  order=ORDER_FIRST,
                                  invariant="== transcript.json::evidence[]"),
        "partyTypedInputs[]": _spec(f"{_G}:227", "inputs[type==party].name",
                                    order=ORDER_FIRST),
        "typedInputs[].name": _spec(f"{_G}:232", "inputs[].name", order=ORDER_FIRST),
        "typedInputs[].type": _spec(f"{_G}:233", "inputs[].type"),
        "entries[].name": _spec(f"{_G}:242", "effects[].name", order=ORDER_FIRST),
        "entries[].kind": _spec(f"{_G}:243", "effects[].kind"),
        "entries[].ledger": _spec(f"{_G}:244", "effects[].ledger"),
        "entries[].owner": _spec(f"{_G}:245", "effects[].owner"),
        "entries[].participant": _spec(f"{_G}:246-247", "effects[].participant",
                                       opt="C", pred="effect participant nonempty"),
        # The `{ "input": … }` operand shape. refJson (:71-77) can also emit
        # `{ "literal": … }`, but NO committed domain exercises that branch — see
        # UNEXERCISED_EMITTER_BRANCHES. It is recorded there as a finding rather
        # than carried here as an unwitnessed authority row.
        "entries[].party.input": _spec(f"{_G}:71-77,248", "effects[].party.value"),
        "entries[].amount.input": _spec(f"{_G}:71-77,249", "effects[].amount.value"),
        "entries[].currency.input": _spec(f"{_G}:71-77,250",
                                          "effects[].currency.value"),
        "entries[].idempotencyKey.input": _spec(
            f"{_G}:71-77,251", "effects[].idempotencyKey.value"),
    },
    "operations.json": {
        "kind": _lit(f"{_G}:311", "literal-constant", note='"neutrino.slot-operations"'),
        "capability": _spec(f"{_G}:312", "procedure", note=_CAP_ID),
        "operations[].operation": _spec(f"{_G}:263,314", "lifecycle",
                                        order=ORDER_MACHINE),
        "operations[].requiresPrior": _spec(
            f"{_G}:263,320", "lifecycle",
            note="nullable; LifecycleModel.requiresPrior(op)"),
        "operations[].maps": _lit(
            f"{_G}:286-306,289", "mixed-literal-spec",
            note="a literal prose table keyed by operation name; only the PROPOSE "
                 "row interpolates spec compute/effect names (:289). The emitter "
                 "throws when the machine has an op with no prose row (:316-319)"),
    },
    "compensation.json": {
        "kind": _lit(f"{_G}:349", "literal-constant",
                     note='"neutrino.slot-compensation"'),
        "capability": _spec(f"{_G}:350", "procedure", note=_CAP_ID),
        "compensable.<commitOp>.how": _lit(
            f"{_G}:353", "literal-constant",
            note='constant "post the inverse of each committed leg"'),
        "compensable.<commitOp>.reverses[].entry": _spec(
            f"{_G}:358", "effects[].name", order=ORDER_FIRST),
        "compensable.<commitOp>.reverses[].ledger": _spec(f"{_G}:359",
                                                          "effects[].ledger"),
        "compensable.<commitOp>.reverses[].inverseOf": _spec(f"{_G}:360",
                                                             "effects[].kind"),
        "compensable.<commitOp>.idempotency": _lit(
            f"{_G}:364", "mixed-literal-spec",
            note='literal template "<procedure>:<idempotency_key>:compensation"'),
        "nonCompensable[]": _spec(
            f"{_G}:341-345,368", "lifecycle", order=ORDER_MACHINE,
            note="machine ops minus the single post-effect and compensate-effect "
                 "ops; the emitter throws unless there is exactly one of each "
                 "(:333-339). This is the census's 'refusal set': it is "
                 "spec-lifecycle-derived and TARGET-NEUTRAL — no target profile "
                 "is read anywhere in the slot renderer"),
        "invariantAfterCompensation": _spec(
            f"{_G}:137-144,369-370", "invariants[kind==balanced]",
            note='"balanced" when the spec declares a balanced invariant, else "none"'),
    },
    "transcript.json": {
        "kind": _lit(f"{_G}:384", "literal-constant",
                     note='"neutrino.slot-transcript-policy"'),
        "capability": _spec(f"{_G}:385", "procedure", note=_CAP_ID),
        "hashChain.perEnvelope": _lit(f"{_G}:388", "literal-constant"),
        "hashChain.chain": _lit(f"{_G}:389-390", "literal-constant"),
        "hashChain.includesRejected": _lit(f"{_G}:390", "literal-constant",
                                           note="constant true"),
        "hashChain.includesDiagnostics": _lit(f"{_G}:391", "literal-constant",
                                              note="constant true"),
        "anchoring.default": _lit(f"{_G}:394", "literal-constant"),
        "anchoring.valueMovingCommit": _lit(f"{_G}:395", "literal-constant"),
        "anchoring.anchorRef.chain": _lit(
            f"{_G}:396-398", "literal-constant",
            note='constant "evm" — the only DEPLOY-SHAPED value in any artifact, '
                 "and it is hardcoded, not deploy-sourced. Census-relevant: this "
                 "is why the deploy-coordinate authority has zero rows"),
        "anchoring.anchorRef.records": _lit(f"{_G}:396-398", "literal-constant"),
        "anchoring.anchorRef.via": _lit(f"{_G}:396-398", "literal-constant"),
        "evidence[]": _spec(f"{_G}:400", "inputs[type==evidence].name",
                            order=ORDER_FIRST,
                            invariant="== capability.json::evidenceInputs[]"),
    },
    "envelope.schema.json": {
        # The whole document is the kEnvelopeSchema template (:79-108); only the
        # operation enum is projected from the machine (@OPS@, :94 + :117-123).
        "properties.operation.enum[]": _spec(
            f"{_G}:94,117-123", "lifecycle", order=ORDER_MACHINE,
            invariant="== capability.json::operations[]",
            note="the ONLY projected value in this artifact ()"),
        "allOf[].if.properties.operation.enum[]": _lit(
            f"{_G}:88", "literal-constant", order=ORDER_FIXED,
            note='constant ["COMMIT","REJECT","COMPENSATE"] — a HARDCODED op '
                 "subset that is NOT projected from the machine, unlike "
                 "properties.operation.enum[]. Latent drift if a machine renames "
                 "or drops one of these ops; recorded as a census finding"),
        "allOf[].then.required[]": _lit(f"{_G}:88-89", "literal-constant",
                                        order=ORDER_FIXED),
        "$schema": _lit(f"{_G}:80", "literal-constant"),
        "$id": _lit(f"{_G}:81", "literal-constant"),
        "title": _lit(f"{_G}:82", "literal-constant"),
        "description": _lit(f"{_G}:83", "literal-constant"),
        "type": _lit(f"{_G}:84", "literal-constant"),
        "additionalProperties": _lit(f"{_G}:85", "literal-constant"),
        "required[]": _lit(f"{_G}:86", "literal-constant", order=ORDER_FIXED),
        "properties.operation.type": _lit(f"{_G}:94", "literal-constant"),
        "properties.sessionId.type": _lit(f"{_G}:92", "literal-constant"),
        "properties.operationId.type": _lit(f"{_G}:93", "literal-constant"),
        "properties.correlationId.type": _lit(f"{_G}:95", "literal-constant"),
        "properties.capability.type": _lit(f"{_G}:96", "literal-constant"),
        "properties.capabilityVersion.type": _lit(f"{_G}:97", "literal-constant"),
        "properties.participant.type": _lit(f"{_G}:98", "literal-constant"),
        "properties.counterparty.type": _lit(f"{_G}:99", "literal-constant"),
        "properties.payload.type": _lit(f"{_G}:100", "literal-constant"),
        "properties.payloadHash.type": _lit(f"{_G}:101", "literal-constant"),
        "properties.previousTranscriptHash.type": _lit(f"{_G}:102",
                                                       "literal-constant"),
        "properties.signature.type": _lit(f"{_G}:103", "literal-constant"),
        "properties.diagnostics.type": _lit(f"{_G}:104", "literal-constant"),
        "properties.diagnostics.items.type": _lit(f"{_G}:104", "literal-constant"),
        "properties.diagnostics.items.required[]": _lit(f"{_G}:104",
                                                        "literal-constant",
                                                        order=ORDER_FIXED),
        "properties.diagnostics.items.properties.severity.type": _lit(
            f"{_G}:104", "literal-constant"),
        "properties.diagnostics.items.properties.code.type": _lit(
            f"{_G}:104", "literal-constant"),
        "properties.diagnostics.items.properties.message.type": _lit(
            f"{_G}:104", "literal-constant"),
        "properties.anchorRef.type": _lit(f"{_G}:105", "literal-constant"),
        "properties.anchorRef.properties.chain.type": _lit(f"{_G}:105",
                                                           "literal-constant"),
        "properties.anchorRef.properties.address.type": _lit(f"{_G}:105",
                                                             "literal-constant"),
        "properties.anchorRef.properties.commitmentHash.type": _lit(
            f"{_G}:105", "literal-constant"),
    },
    "binding-topology.json": {
        "kind": _lit(f"{_G}:429", "literal-constant",
                     note='"neutrino.slot-binding-topology"'),
        "schemaVersion": _lit(f"{_G}:430", "literal-constant", note="constant 1"),
        "capability": _spec(f"{_G}:431", "procedure", note=_CAP_ID),
        "capabilityVersion": _spec(f"{_G}:432", "specVersion"),
        "procedure": _spec(f"{_G}:433", "procedure"),
        "organizations[].organizationId": _spec(
            f"{_G}:407-415,438-439", "participants[].org", order=ORDER_FIRST,
            note="nullable: a participant with no declared org is a valid bucket "
                 "rendered with a null id"),
        "organizations[].participants[].participantId": _spec(
            f"{_G}:458", "participants[].name", order=ORDER_FIRST),
        "organizations[].participants[].role": _spec(f"{_G}:459",
                                                     "participants[].role"),
        "organizations[].participants[].slots[].slotId": _spec(
            f"{_G}:451,462", "participants[].name",
            note='cap + "#" + participant name'),
        "organizations[].participants[].slots[].lateBindingMode": _spec(
            f"{_G}:453,463", "participants[].binding",
            note='"to_be_bound" when isFlexible, else "fixed"'),
        "organizations[].participants[].slots[].allowedRuntimes[]": _spec(
            f"{_G}:464-465", "participants[].bindRuntimes[]", order=ORDER_FIRST,
            note="empty array when the participant is not flexible"),
        "organizations[].participants[].slots[].minAssurance": _spec(
            f"{_G}:455-456,466", "participants[].bindMinAssurance",
            kind="computed-default",
            note='falls back to the literal "A1" when the participant is not '
                 "flexible or declares no bindMinAssurance — a partially "
                 "unsourced field (static generation never claims above A1)"),
        "organizations[].participants[].slots[].evidenceProfile": _lit(
            f"{_G}:468", "literal-constant", note="constant null"),
        "organizations[].participants[].slots[].authorizedBinder": _spec(
            f"{_G}:470-472", "participants[].org", opt="C",
            pred="participant isFlexible and org nonempty"),
        "crossOrganization": _spec(
            f"{_G}:484-485", "participants[].org",
            invariant="== capability.json::topology.crossOrganization "
                      "(independently recomputed at GenSlotSpec.cpp:216)",
            note="computed: distinct NAMED orgs > 1"),
    },
    "capability.lock": {
        "kind": _lit(f"{_G}:506", "literal-constant",
                     note='"neutrino.capability-lock"'),
        "capability": _spec(f"{_G}:507", "procedure", note=_CAP_ID),
        "capabilityVersion": _spec(f"{_G}:508", "specVersion"),
        "method": _lit(f"{_G}:509-512", "literal-constant",
                       note="constant prose describing the hash construction"),
        "capabilityHash": _lit(
            f"{_G}:496-503,513", "computed-receipt",
            note="sha256 over concat(sorted(basename + ':' + sha256(content) + "
                 "newline)) of the WIRE subset only (capability/operations/"
                 "compensation/transcript); envelope.schema.json, "
                 "binding-topology.json and the lock itself are excluded "
                 "(:566-577). Structurally cross-artifact — a receipt cannot "
                 "belong to a single authority partition"),
        "files.<name>": _lit(f"{_G}:515-518", "computed-receipt",
                             order=ORDER_SORTED,
                             note="per-wire-file sha256, sorted by basename"),
    },
}


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _leaves(node, artifact, prefix=""):
    """Every leaf field-address under `node`.

    An array contributes ONE address per distinct element shape (`path[]`),
    whether it is empty or not — the field exists either way. An empty object is
    itself terminal. Object key order is not part of the address (it is recorded
    per row as an ordering rule instead).

    A key whose NAME is data (a wire filename, a lifecycle op) is replaced by its
    grammar variable HERE, at the point of descent, where the key boundary is
    exact — normalizing the flattened string instead would mis-split a key that
    itself contains a dot (`files."capability.json"`)."""
    out = set()
    if isinstance(node, dict):
        if not node:
            out.add(prefix)
            return out
        variable = DYNAMIC_KEY_PARENTS.get((artifact, prefix))
        for key, value in node.items():
            name = variable if variable else key
            out |= _leaves(value, artifact, f"{prefix}.{name}" if prefix else name)
    elif isinstance(node, list):
        if not node:
            out.add(f"{prefix}[]")
            return out
        for element in node:
            out |= _leaves(element, artifact, f"{prefix}[]")
    else:
        out.add(prefix)
    return out


def observed_addresses(repo):
    """{artifact: {address: [domains it was observed in]}} over every domain."""
    observed = {name: {} for name in ARTIFACTS}
    for slot_dir, _spec_path in DOMAINS:
        for artifact in ARTIFACTS:
            path = os.path.join(repo, slot_dir, artifact)
            if not os.path.exists(path):
                continue
            for address in _leaves(_read_json(path), artifact):
                observed[artifact].setdefault(address, []).append(slot_dir)
    return observed


# Sentinel for "this array exists but declares no elements here" — the remaining
# path is vacuously satisfied rather than falsified, since another domain may
# populate it. A path that is vacuous in EVERY domain still has to be structurally
# valid somewhere, which the caller enforces by requiring resolution in >= 1 spec
# where the array is non-empty.
_VACUOUS = object()


def _resolve_source_path(spec, path):
    """True when `path` is STRUCTURALLY valid against a real capability-spec.

    Grammar: dotted keys; `[]` iterates an array; `[key==value]` selects elements
    whose `key` equals `value`.

    A filter is checked STRUCTURALLY: the filter key must exist on some element
    (so `inputs[type==evidence]` proves `inputs[].type` is real), but the
    remaining path is then resolved against ALL elements. This deliberately keeps
    "no evidence input is declared in these domains" from being reported as a
    bogus path, while `inputs[type==evidence].noSuchKey` still fails."""
    nodes = [spec]
    for segment in path.split("."):
        key, filt = segment, None
        if key.endswith("]"):
            head, _, predicate = key[:-1].partition("[")
            key, filt = head, (predicate or "")
        nxt = []
        for node in nodes:
            if node is _VACUOUS:
                nxt.append(_VACUOUS)
                continue
            if not isinstance(node, dict) or key not in node:
                continue
            value = node[key]
            if filt is None:
                nxt.append(value)
                continue
            if not isinstance(value, list):
                return False
            if not value:
                nxt.append(_VACUOUS)
                continue
            if "==" in filt:
                fkey = filt.partition("==")[0]
                if not any(isinstance(e, dict) and fkey in e for e in value):
                    return False
            nxt.extend(value)
        if not nxt:
            return False
        nodes = nxt
    return True


def _source_paths_resolve(repo):
    """{sourcePath: True/False} — resolvable in at least one real spec."""
    specs = []
    for _slot_dir, spec_path in DOMAINS:
        path = os.path.join(repo, spec_path)
        if os.path.exists(path):
            specs.append(_read_json(path))
    resolved = {}
    for artifact, rows in AUTHORITY_TABLE.items():
        for _address, row in rows.items():
            source = row.get("sourcePath")
            if not source:
                continue
            resolved.setdefault(
                source, any(_resolve_source_path(s, source) for s in specs))
    return resolved


def generate(repo=REPO):
    """Build the census. Raises SlotCensusError on any classification gap."""
    observed = observed_addresses(repo)
    resolvable = _source_paths_resolve(repo)

    problems, rows = [], []
    for artifact in sorted(ARTIFACTS):
        table = AUTHORITY_TABLE.get(artifact, {})
        seen = observed[artifact]
        # (1) every OBSERVED field must be classified — nothing slips in.
        for address in sorted(seen):
            if address not in table:
                problems.append(
                    f"{artifact}::{address} is emitted but has no authority row "
                    "— classify it (never infer, never blanket-default)")
        # (2) EVERY declared row must be WITNESSED at least once across the union.
        # `optionality: C` means "not present in every domain" — never "possibly
        # present in none". An unwitnessed row would be a declaration rather than
        # an observation, and counting it would make the authority totals partly
        # speculative; a reachable-but-unexercised emitter branch belongs in
        # UNEXERCISED_EMITTER_BRANCHES instead. This is also what gives the
        # field-disappearance guarantee its teeth for CONDITIONAL fields: drop the
        # emitter branch behind one and its row loses its last witness.
        for address, row in sorted(table.items()):
            if address not in seen:
                qualifier = ("declared R (always present)"
                             if row["optionality"] != "C" else
                             f"declared C ({row['optionalityPredicate']})")
                problems.append(
                    f"{artifact}::{address} is {qualifier} but is witnessed by NO "
                    "committed domain — either the emitter dropped it, or it is a "
                    "reachable-but-unexercised branch that belongs in "
                    "UNEXERCISED_EMITTER_BRANCHES, not in the authority rows")
            # (3) an authority claim needs a path that actually exists.
            source = row.get("sourcePath")
            if source and not resolvable.get(source):
                problems.append(
                    f"{artifact}::{address} claims sourcePath '{source}', which "
                    "resolves against no committed capability-spec")
            if row["authority"] == "UNSOURCED" and not row["unsourcedKind"]:
                problems.append(
                    f"{artifact}::{address} is UNSOURCED but names no reason")
            if row["unsourcedKind"] and row["unsourcedKind"] not in UNSOURCED_KINDS:
                problems.append(
                    f"{artifact}::{address} has unknown unsourcedKind "
                    f"'{row['unsourcedKind']}'")
            if not row["emitter"]:
                problems.append(f"{artifact}::{address} cites no emitter")
            rows.append({
                "artifact": artifact,
                "fieldAddress": f"{artifact}::{address}",
                "authority": row["authority"],
                "sourcePath": source,
                "unsourcedKind": row["unsourcedKind"],
                "optionality": row["optionality"],
                "optionalityPredicate": row["optionalityPredicate"],
                "ordering": row["ordering"],
                "invariant": row["invariant"],
                "emitter": row["emitter"],
                "observedIn": sorted(seen.get(address, [])),
                "note": row["note"],
            })
    if problems:
        raise SlotCensusError("; ".join(problems))

    totals = {name: 0 for name in AUTHORITIES}
    for row in rows:
        totals[row["authority"]] += 1
    unsourced_kinds = {}
    partial = 0
    for row in rows:
        if row["unsourcedKind"]:
            unsourced_kinds[row["unsourcedKind"]] = (
                unsourced_kinds.get(row["unsourcedKind"], 0) + 1)
            if row["authority"] != "UNSOURCED":
                partial += 1

    return {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "documentId": "urn:neutrino:document:slot-descriptor-authority-v1",
        "checkpoint": "S0-C0",
        "note": "PROBE/CENSUS ONLY — grants no retirement authority and adopts "
                "no partition. Records where each slot-descriptor field actually "
                "comes from in the committed generator.",
        "sourceRevision": _censused_material_digest(repo),
        "domains": [slot for slot, _spec in DOMAINS],
        "artifacts": {name: {"conditional": ARTIFACTS[name]} for name in sorted(ARTIFACTS)},
        "authorityTotals": totals,
        "unobservedAuthorities": sorted(a for a in AUTHORITIES if totals[a] == 0),
        "unsourcedKindTotals": dict(sorted(unsourced_kinds.items())),
        "partiallyUnsourcedRows": partial,
        "unexercisedEmitterBranches": UNEXERCISED_EMITTER_BRANCHES,
        "totals": {"fields": len(rows)},
        "fields": rows,
    }


def _censused_material_digest(repo):
    """A CONTENT digest over the censused material — the slot generator plus the
    committed artifacts and specs it emits.

    Deliberately NOT a git revision. A revision identifies the commit that last
    touched those paths, so any commit that CHANGES them invalidates the bank it
    is committing: the recorded SHA is stale the moment the commit exists, and
    amending to fix it mints a new SHA again. Content-addressing has the semantics
    actually wanted — it changes when the censused material changes, and not
    merely because a commit happened."""
    entries = []
    roots = ["lib/slots"]
    roots += [slot for slot, _spec in DOMAINS]
    files = []
    for root in roots:
        base = os.path.join(repo, root)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, names in os.walk(base):
            for name in sorted(names):
                if name.endswith((".pyc", ".o")):
                    continue
                files.append(os.path.join(dirpath, name))
    for _slot, spec in DOMAINS:
        path = os.path.join(repo, spec)
        if os.path.exists(path):
            files.append(path)
    for path in sorted(set(files)):
        rel = os.path.relpath(path, repo).replace(os.sep, "/")
        with open(path, "rb") as f:
            entries.append(f"{rel}:{hashlib.sha256(f.read()).hexdigest()}")
    return "sha256:" + hashlib.sha256("\n".join(entries).encode()).hexdigest()


class SlotCensusError(Exception):
    pass


def _validate(report):
    if report["kind"] != KIND:
        raise SlotCensusError("wrong inventory kind")
    if report["totals"]["fields"] != len(report["fields"]):
        raise SlotCensusError("field total does not match the row set")
    addresses = [row["fieldAddress"] for row in report["fields"]]
    if len(set(addresses)) != len(addresses):
        raise SlotCensusError("duplicate field addresses in the inventory")
    for row in report["fields"]:
        if row["authority"] not in AUTHORITIES:
            raise SlotCensusError(f"unknown authority {row['authority']}")


def _validate_nonincrease(report, base):
    """Ratchet: the UNSOURCED row count may never grow. The census is standing
    pressure toward a single authority; it authorizes no retirement itself."""
    if not base:
        return
    now = report["authorityTotals"]["UNSOURCED"]
    was = base.get("authorityTotals", {}).get("UNSOURCED")
    if was is not None and now > was:
        raise SlotCensusError(
            f"UNSOURCED rows increased {was} -> {now}; a new unsourced datum "
            "needs an explicit ruling, not a re-bank")


def _load_base(repo, base_ref, output_rel):
    try:
        out = subprocess.run(
            ["git", "-C", repo, "show", f"{base_ref}:{output_rel}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout else None
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# Non-vacuity selftest. Two REQUIRED properties, each with a biting mutation.
# --------------------------------------------------------------------------

def _selftest_no_disappear(repo):
    """(i) A field can neither DISAPPEAR nor slip in unclassified.

    Mutation A: drop a declared row while the field is still emitted -> the
    observed field is unclassified and generate() must fail.
    Mutation B: declare a mandatory row nothing emits -> generate() must fail."""
    failures = []
    saved = copy.deepcopy(AUTHORITY_TABLE)
    try:
        victim = "kind"
        del AUTHORITY_TABLE["capability.json"][victim]
        try:
            generate(repo)
            failures.append(
                "dropping the capability.json::kind row did not fail — an "
                "emitted field could vanish from the census")
        except SlotCensusError:
            pass
    finally:
        AUTHORITY_TABLE["capability.json"] = saved["capability.json"]

    try:
        AUTHORITY_TABLE["capability.json"]["phantomField"] = _lit(
            f"{_G}:0", "literal-constant")
        try:
            generate(repo)
            failures.append(
                "a mandatory row that nothing emits did not fail — a stale "
                "census row could outlive its field")
        except SlotCensusError:
            pass
    finally:
        AUTHORITY_TABLE["capability.json"] = saved["capability.json"]

    # A CONDITIONAL row gets the same protection: `C` means "absent in some
    # domains", never "absent everywhere". Declaring a conditional field that no
    # committed domain witnesses must fail, or an unwitnessed declaration could be
    # counted as an empirical field and inflate the authority totals.
    try:
        AUTHORITY_TABLE["capability.json"]["phantomConditional"] = _lit(
            f"{_G}:0", "literal-constant", opt="C", pred="never true in any domain")
        try:
            generate(repo)
            failures.append(
                "a CONDITIONAL row witnessed by no domain did not fail — an "
                "unwitnessed declaration could be counted as an empirical field")
        except SlotCensusError:
            pass
    finally:
        AUTHORITY_TABLE["capability.json"] = saved["capability.json"]

    # Removing a WITNESSED CONDITIONAL field's row must bite exactly as a
    # mandatory one does: the field is still emitted by some domain, so it would
    # otherwise slip out of the census unclassified. `trigger` is present in some
    # domains and absent in others, which is precisely the conditional shape.
    try:
        victim = "trigger"
        assert AUTHORITY_TABLE["capability.json"][victim]["optionality"] == "C"
        del AUTHORITY_TABLE["capability.json"][victim]
        try:
            generate(repo)
            failures.append(
                "dropping the WITNESSED CONDITIONAL capability.json::trigger row "
                "did not fail — a conditionally-emitted field could vanish from "
                "the census")
        except SlotCensusError:
            pass
    finally:
        AUTHORITY_TABLE["capability.json"] = saved["capability.json"]
    return failures


def _selftest_no_blanket_classification(repo):
    """(ii) A field cannot be blanket-classified by function/file.

    Mutation C: relabel every compensation.json row to one stub capability-spec
    authority -> the stub sourcePath resolves against no real spec, so generate()
    must fail. Mutation D: an UNSOURCED row with no named reason must fail."""
    failures = []
    saved = copy.deepcopy(AUTHORITY_TABLE)
    try:
        for address in AUTHORITY_TABLE["compensation.json"]:
            AUTHORITY_TABLE["compensation.json"][address] = _spec(
                f"{_G}:328-373", "wholeFileIsSpecAuthored")
        try:
            generate(repo)
            failures.append(
                "blanket-relabelling every compensation.json field to one stub "
                "authority did not fail — authority could be assigned wholesale "
                "by file rather than per field")
        except SlotCensusError:
            pass
    finally:
        AUTHORITY_TABLE["compensation.json"] = saved["compensation.json"]

    try:
        AUTHORITY_TABLE["transcript.json"]["kind"] = {
            **saved["transcript.json"]["kind"], "unsourcedKind": None}
        try:
            generate(repo)
            failures.append(
                "an UNSOURCED row naming no reason did not fail — an unsourced "
                "datum could hide without being named")
        except SlotCensusError:
            pass
    finally:
        AUTHORITY_TABLE["transcript.json"] = saved["transcript.json"]

    try:
        AUTHORITY_TABLE["capability.json"]["capabilityVersion"] = _spec(
            f"{_G}:179", "noSuchSpecKey")
        try:
            generate(repo)
            failures.append(
                "a sourcePath resolving against no committed spec did not fail "
                "— an authority claim could be asserted without evidence")
        except SlotCensusError:
            pass
    finally:
        AUTHORITY_TABLE["capability.json"] = saved["capability.json"]
    return failures


def selftest(repo=REPO):
    report = generate(repo)
    _validate(report)
    failures = []

    # Floors: a wrong dir / eroded corpus must not pass on zero work.
    if len(report["fields"]) < 100:
        failures.append(
            f"only {len(report['fields'])} fields censused; the committed "
            "artifacts carry far more (eroded corpus or wrong dir?)")
    if len(report["domains"]) < 4:
        failures.append("fewer than 4 representative domains")
    for artifact in ARTIFACTS:
        if not any(r["artifact"] == artifact for r in report["fields"]):
            failures.append(f"{artifact} contributed no census rows")

    # The recorded empirical result must stay recorded, not silently smoothed.
    if report["authorityTotals"]["capability-spec"] < 1:
        failures.append("no capability-spec rows — the census lost its one "
                        "observed structured authority")
    if report["authorityTotals"]["UNSOURCED"] < 1:
        failures.append("no UNSOURCED rows — literals cannot have vanished")

    failures += _selftest_no_disappear(repo)
    failures += _selftest_no_blanket_classification(repo)

    if failures:
        print("slot-descriptor-authority SELFTEST FAILED:", file=sys.stderr)
        for f in failures:
            print("  " + f, file=sys.stderr)
        return 1
    print(
        f"slot-descriptor-authority selftest OK ({len(report['fields'])} fields "
        f"across {len(ARTIFACTS)} artifacts; a field can neither disappear nor "
        f"slip in unclassified, and authority cannot be assigned wholesale by "
        f"file — stub/unresolvable/unnamed classifications all bite)")
    return 0


# The  tamper probes: each drives ONE of the two required non-vacuity
# properties into its failing state and must be observed to fail.
PROBES = {
    "field-disappearance": (
        "drop a declared row while the field is still emitted",
        lambda: AUTHORITY_TABLE["capability.json"].pop("kind")),
    "blanket-classification": (
        "relabel every compensation.json field to one stub authority",
        lambda: AUTHORITY_TABLE["compensation.json"].update(
            {address: _spec(f"{_G}:328-373", "wholeFileIsSpecAuthored")
             for address in AUTHORITY_TABLE["compensation.json"]})),
    "unwitnessed-declaration": (
        "declare a conditional row that no committed domain witnesses",
        lambda: AUTHORITY_TABLE["capability.json"].update(
            {"phantomConditional": _lit(f"{_G}:0", "literal-constant", opt="C",
                                        pred="never true in any domain")})),
}


def probe(name, repo=REPO):
    """Run one tamper probe: mutate, then require generate() to fail closed."""
    if name not in PROBES:
        print(f"unknown probe '{name}'", file=sys.stderr)
        return 2
    description, mutate = PROBES[name]
    saved = copy.deepcopy(AUTHORITY_TABLE)
    try:
        mutate()
        try:
            generate(repo)
        except SlotCensusError:
            print(f"probe-failed-as-expected:{name} ({description})")
            return 1
        print(f"probe-DID-NOT-BITE:{name} ({description}) — the census would "
              f"accept the tampered classification", file=sys.stderr)
        return 0
    finally:
        AUTHORITY_TABLE.clear()
        AUTHORITY_TABLE.update(saved)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe", help="run one tamper probe and fail closed")
    args = parser.parse_args()
    try:
        if args.probe:
            return probe(args.probe)
        if args.selftest:
            return selftest()
        report = generate()
        _validate(report)
        _validate_nonincrease(report, _load_base(REPO, args.base_ref, args.output))
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        output = os.path.join(REPO, args.output)
        if args.write:
            os.makedirs(os.path.dirname(output), exist_ok=True)
            with open(output, "w", encoding="utf-8") as f:
                f.write(payload)
            print(f"wrote {args.output}: {len(report['fields'])} fields")
            return 0
        try:
            committed = open(output, encoding="utf-8").read()
        except OSError as exc:
            raise SlotCensusError(f"committed inventory missing: {exc}")
        if committed != payload:
            raise SlotCensusError("committed inventory is stale; rerun --write")
        totals = report["authorityTotals"]
        print(
            f"slot-descriptor-authority: PASS ({len(report['fields'])} fields; "
            f"capability-spec={totals['capability-spec']}, "
            f"UNSOURCED={totals['UNSOURCED']}, "
            f"unobserved authorities: {', '.join(report['unobservedAuthorities'])})")
        return 0
    except (SlotCensusError, OSError, ValueError) as exc:
        print(f"slot-descriptor-authority: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
