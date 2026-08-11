# Per-Participant Narrowed Views (Trust lane — T5)

**Status:** translator emission (`neutrino-gen --target=views`). Source:
`neutrino-strategy/09-debates/verification-trust-model-implementation-spec.md`
(Translator track step 4 / per-slot views). See the contract
[`TRUST_LATE_BINDING_CONTRACT.md`](TRUST_LATE_BINDING_CONTRACT.md).

A slot implementer should see **only the slice it is responsible for**, not the
whole agreement. For each declared participant the translator emits one narrowed
view **projected from the canonical capability spec** (M5 ) — the capability
identity, the spec's coordination operations, the inputs *its own* legs require,
the counterparties its org may coordinate with, its binding policy, and the legs
it must produce evidence for, each carrying its **spec-path + DSL source
provenance**. **No view leaks another participant's obligations.**

## Generate

```bash
make views
# or (no --scenario: views are a spec/kernel projection, scenario-independent):
neutrino-gen --target=views <source.neu|.mlir> -o <dir>
# writes <dir>/<participant>.json per declared participant (+ manifest/diagnostics)
```

A source with **no declared participants** emits no view files (additive — nothing
else changes).

`views` is **security-gated** like `slot`/`solidity`/`postgres`: the translator
refuses to emit narrowed views for a capability the Capability Security Pass finds
hard violations in (exit `5`), so an agent never receives an implementation
contract for a capability already known to be invalid. Run `--target=security` for
details, or pass `--allow-insecure` to override.

## Shape

```jsonc
{
  "kind": "neutrino.participant-view",
  "schemaVersion": "0.2.0",
  "procedure": "core_flexible_binding",
  "dslVersion": "1.0.0",

  // Capability identity (M5 ): which capability/spec this view narrows. The
  // hash is a function of source ALONE (scenario-independent) and equals the
  // spec's identity.capabilityHash — so a view can be tied to its capability.
  "capability": { "capabilityHash": "160870a8…", "specVersion": "1.0.0" },

  // Participant + slot identity. slotId matches the slot / binding-topology id
  // (coordinate.<procedure>#<participant>).
  "participant": { "name": "Sponsor", "role": "sponsor", "org": "sponsorco",
                   "slotId": "coordinate.core_flexible_binding#Sponsor" },

  // PROJECTED from the canonical lifecycle machine (), not invented here.
  "visibleOperations": ["OPEN", "NEGOTIATE", "PROPOSE", "COMMIT", "REJECT", "COMPENSATE", "CLOSE"],

  // The declared inputs THIS participant's legs need (declaration order), each
  // with its spec path + DSL source location — the D11 provenance chain (source
  // -> spec -> view). A leg referencing a compute surfaces the compute's
  // underlying declared inputs, resolved transitively.
  "requiredInputs": [
    { "name": "offer_id", "type": "string", "specPath": "inputs[0]", "source": { "line": 40, "column": 1 } },
    { "name": "sponsor_id", "type": "party", "specPath": "inputs[1]", "source": { "line": 41, "column": 1 } }
  ],

  // Orgs this participant's org may coordinate with (from `allow`), + any role
  // required of that counterparty.
  "permittedCounterparties": [ { "org": "acme", "role": "merchant" } ],

  // Present only for a to_be_bound participant (see BINDING_POLICY.md).
  "binding": { "mode": "to_be_bound", "runtimes": ["evm", "jvm"], "minAssurance": "A2", "authorizedBinder": "sponsorco" },

  // The legs this participant authorizes — i.e. must produce evidence for, each
  // with its spec path + source (why the obligation is here, traceable to DSL).
  "evidenceObligations": [
    { "leg": "sponsor_commitment", "kind": "debit", "ledger": "sponsor.commitment", "specPath": "effects[0]", "source": { "line": 46, "column": 1 } }
  ],

  // The artifact this view derives from + the spec contract it was projected
  // under, so a consumer () can verify a view came from a compatible spec.
  "provenance": { "derivedFrom": "capability-spec.json", "specContract": { "kind": "neutrino.capability-spec", "schemaVersion": 1 } }
}
```

## Derived from the canonical spec (M5 )

Views **project from the capability spec/kernel**, they don't re-derive
coordination semantics: `capabilityHash` and `visibleOperations` come from the
[spec](../spec/CAPABILITY_SPEC.md) (via `capabilityHashOf` and the shared
[lifecycle machine](../../include/Neutrino/Lifecycle.h), ), and every
`requiredInput` / `evidenceObligation` carries the **spec path + DSL source**
that back it — the D11 chain *source → spec path → view*. `--target=views` needs
no `--scenario` and its output is **byte-identical with or without one**: changing
only a scenario/test never changes capability-level view semantics. Self-test
`[82]` regenerates every committed view fixture and cross-checks its
`capabilityHash`, `visibleOperations`, `specContract`, and per-field `source`
against the domain's `capability-spec.json` — so a view cannot invent a field, operation, or
obligation the spec does not carry.

`scripts/validators/validate_participant_view.py` (schema:
[`participant-view.schema.json`](../schemas/participant-view.schema.json)) is what a
consumer / **** runs: it mirrors the schema and enforces the beyond-schema
invariant a JSON-Schema can't — given the referenced capability-spec (`--spec`), the view's
`capabilityHash` matches, `specContract` matches the spec's kind/schemaVersion,
`visibleOperations` are the spec's lifecycle ops, and every `specPath` resolves in
the spec with matching source. Its codes come from the shared
[diagnostic taxonomy](../language/DIAGNOSTIC_TAXONOMY.md) (`view.*`, ); every committed
view is validated + cross-checked in the fast tier (`[fast/12]`) and `[82]`.

A view is validated **against the spec it was projected from** (regenerated
together), so `specContract.schemaVersion` matches by construction. Validating a
view against a *different* spec version intentionally reports
`view.contract_mismatch` — that is version skew being caught, not a false
negative: a view and its spec are a versioned pair. `source` is a line-oriented
DSL location (column is always `1`) and is **exactly the spec's `sourceMap`
source** for that `specPath` — `[82]` pins them equal, so a view's provenance is
as accurate as the spec's (the authority), never independently derived.

## Narrowing rules (self-test `[33]`)

- `requiredInputs` / `evidenceObligations` include **only** the legs whose
  `participant` is this one; another participant's leg never appears.
  `requiredInputs` resolves compute dependencies transitively, so a leg paying a
  computed `amount` surfaces the inputs that compute derives from.
- `permittedCounterparties` is derived per-org from the `allow` policy, so a
  participant sees the *other* side of each pair it is in (and the role required of
  it), not the whole topology.
- `binding` appears only for a `to_be_bound` participant.

## Downstream

These narrowed views are advisory implementation contracts: an Agents (T2)
workflow can present a participant its slice (operations, inputs, counterparties,
binding policy, evidence obligations) without parsing the whole global agreement.
