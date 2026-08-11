# core_flexible_binding

The canonical **late-binding** reference capability: participants whose runtime
binding is deferred (`to_be_bound`), an org-pair policy, and a cross-organization
slot binding-topology. It anchors several self-tests — `[32]` (slot fixture +
binding policy in the wire contract), `[33]` (participant views), `[38]` (slot
binding-topology: org → participant → slot), and the D8 editor-intelligence
`[45]`/`[46]`/`[47]` (symbols/hover/completions source).

## Contents

```
source/    core_flexible_binding.neu              # canonical source
scenario/  core_flexible_binding_happy_path.json  # happy-path scenario
generated/
  slot/    capability/operations/compensation/transcript + capability.lock
           + envelope.schema + binding-topology.json   # byte-compared by [32]/[38]
```

`source/` + `scenario/` are the trusted inputs; `generated/slot/` is tool-reproduced
(`neutrino-gen --target=slot`) and byte-compared, never hand-edited. The realized
binding manifest stays in the global `examples/binding-manifests/` area (it is a
reviewed realized-binding input, not generated output).
