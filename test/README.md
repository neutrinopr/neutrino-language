# test/

The translator **self-test suite** + fixtures. Trusted source (the expected behavior of the compiler).

## Contents

- **`neg_*.neu`** + `bad_scenario.json` — negative cases the frontend/verifier/scenario-loader must
  reject (bad compute, bad value, duplicate input, missing field, unexpected statement, illegal
  lifecycle / state-machine / protocol-native / external-observation constructs).
- **[ir/](ir)** — MLIR IR fixtures (verifier round-trips; see ir/README.md).
- **[conformance/](conformance)** — `.neu` language conformance corpus (`accepted/` + `rejected/`),
  pinning [docs/language/NEU_LANGUAGE_SPEC.md](../docs/language/NEU_LANGUAGE_SPEC.md) (self-test `[56]`).

## Verify

```
make test-fast      # fast tier: no-build validator smoke gate
make test           # full tier: build + complete self-test suite (also: ctest -L full)
make acceptance     # + backend checks (forge/docker)
```

Tiers + how to add a test: [docs/testing/TESTING.md](../docs/testing/TESTING.md).
