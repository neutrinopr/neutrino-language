# core_multi_pair_role

Demonstrates **per-pair scoping** of the role policy: when an org appears in two
different `allow … { … as … }` pairs, each leg's role is checked against *its*
coordinating pair — a valid multi-pair capability is not falsely rejected because
an unrelated pair requires a different role. The loosened "match any allowed role"
check still rejects a role no coordinating pair permits. Both behaviors are pinned
by self-test `[30]` (happy path passes; a `thief` role variant → exit 5,
`ok=false`).

## Contents

```
source/    core_multi_pair_role.neu              # canonical source
scenario/  core_multi_pair_role_happy_path.json  # valid multi-pair (passing) scenario
```

No committed `generated/` fixtures — `[30]` generates and checks the security
report from this source at test time (and mutates it for the negative case).
`source/` and `scenario/` are the trusted inputs.
