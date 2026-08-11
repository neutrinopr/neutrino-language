# core_scheme_settlement

The **second sample domain** (generality check) — a scheme net-settlement
capability, used to prove the toolchain is not specific to the primary
merchant-installment example. It is the Makefile `EXAMPLE2`/`SCENARIO2` and drives
the self-test generality slice and `make equivalence-scheme`.

**M2 language-evolution promotion ():** upgraded from a bare procedure to the
participant / org / org-pair-policy / leg-participant form, with the
`SettlementBank` slot late-bound (`binding = "to_be_bound"`). Derived from
`neutrino-strategy/09-debates/m2-language-evolution-examples.md` (Example 2). Now
carries committed `slot`, `security`, and `postgres` fixtures and is pinned by
self-test `[50]`.

## Contents

```
source/    core_scheme_settlement.neu              # participant/org/allow/leg-participant form
scenario/  core_scheme_settlement_happy_path.json  # happy-path scenario
generated/
  slot/      capability.json + capability.lock + binding-topology.json
             (one to_be_bound slot: #SettlementBank [swift,jvm]/A2/bankco)
             + operations/compensation/transcript + envelope.schema
  security/  security.json   (ok=true; the A2 binding is a trustBoundary advisory)
  postgres/  schema.sql + procedure.sql + reconciliation.sql + run_db_test.sh
```

The realized **binding manifest** (one binding for the SettlementBank slot) lives
in `examples/binding-manifests/core_scheme_settlement.binding.json` and is validated
against the generated topology by `scripts/validators/validate_binding_manifest.py`.

`source/` + `scenario/` are the trusted inputs; everything under `generated/` is
tool-reproduced (`neutrino-gen --target=…`) and byte-compared, never hand-edited.

## Gaps (documented, not encoded as unsupported syntax)

- **SWIFT / ISO 20022 message semantics** (`pacs.008`, `pacs.009`, `pacs.002`) are
  lower-layer / domain-dialect / translation-map concerns — not core `.neu` flow
  statements. See `docs/domains/DOMAIN_DIALECT.md` / `docs/domains/LOWER_LAYER.md`.
- **External observation / receipts / runtime evidence** remain network/agents work.
- **Source-level lifecycle / state-machine syntax** is not in core `.neu` yet (the
  security pass reports `state: n/a`).
- The M2 note's Example 2 omitted the `bankco`↔`treasuryco` org-pair policy; it is
  added here because the topology gate requires every co-occurring org pair to be
  permitted.
