# Backend Validation Hardening (Phase 11)

Target-native validators over the generated backend artifacts, emitting a
deterministic report in the agent-layer conventions — **before** any larger typed
backend IR (Phase 12 of the broader roadmap). Real execution checks (Foundry,
docker+psql) stay in `make solidity-test` / `make db-test`; this adds static /
parser validation on top.

```bash
make validate          # generate sol+pg for EXAMPLE/SCENARIO, then validate
```

Writes `build/validate/report/validation.json` and `diagnostics.json`.

## Checks

| backend | tool | mandatory | gate |
| --- | --- | --- | --- |
| Solidity | `solc --standard-json` | **yes** | a compile error fails `make validate` (exit non-zero) |
| Solidity | Slither (static analysis) | no | informational; findings recorded, never gates |
| PostgreSQL | libpg_query via `pglast` (parse) | no | parse errors recorded; do not gate |

`validation.json.ok` is true **iff every mandatory check passed**. Optional checks
report `skipped` when the tool isn't installed, `error` when present-but-broken,
and `pass`/`fail` otherwise — none of them affect `ok`.

## Report shape

```json
{
  "kind": "neutrino.validation-report",
  "ok": true,
  "checks": [
    {"backend": "solidity", "tool": "solc --standard-json", "mandatory": true, "status": "pass", "errors": 0, "warnings": 0},
    {"backend": "solidity", "tool": "slither", "mandatory": false, "status": "pass", "findings": 8},
    {"backend": "postgres", "tool": "libpg_query (pglast)", "mandatory": false, "status": "pass", "filesParsed": 3}
  ]
}
```

`diagnostics.json` carries `{ok, diagnostics:[{severity, code, message}]}` — the
same shape `neutrino-gen` emits — with `<backend>.validation_failed` codes
(`error` for mandatory failures, `warning` for optional).

## Enabling the optional validators

```bash
pip3 install --user slither-analyzer pglast      # then ensure the user bin is on PATH
```

Slither runs on an isolated copy of the generated contract with the solc
framework forced, so it never invokes `forge`. `pglast` wraps `libpg_query` and
parses `schema.sql` / `procedure.sql` / `reconciliation.sql`.

## CI / agent guidance

- **Mandatory for CI:** `make validate` (the `solc --standard-json` gate). It is
  part of `make acceptance`.
- **Optional / advisory:** Slither + `pglast` — run where installed; surface
  findings, don't block.
- **No rewrite:** this phase deliberately does **not** move to Yul or a typed
  backend IR. If Slither/libpg_query surface a recurring real problem, that is the
  signal to revisit the typed-model work — not before.
