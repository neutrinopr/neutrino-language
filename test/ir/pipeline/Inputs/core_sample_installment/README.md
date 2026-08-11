# core_sample_installment

The **primary** sample domain — merchant-sponsored installment funding — and the
default Makefile fixture (`EXAMPLE`/`SCENARIO`). It exercises the full pipeline
(translate → all generators) and is one of the two R0 characterization goldens
(`[43]`, solidity + postgres byte-stable). Finance is only the sample; the
deliverable is the pipeline shape.

## Contents

```
source/    core_sample_installment.neu
scenario/  core_sample_installment_happy_path.json
generated/
  slot/ solidity/ postgres/ capability/ coverage/ security/   # byte-compared fixtures
README.md
```

`source/` + `scenario/` are the trusted inputs; everything under `generated/` is
tool-reproduced (`neutrino-gen --target=…`) and byte-compared by the self-tests
(`[11]`/`[13]`/`[32]` slot, `[14]` capability, `[16]` coverage, `[22]` security,
`[43]` solidity/postgres R0) — never hand-edited.
