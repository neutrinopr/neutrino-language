# core_role_constrained

Demonstrates the **per-org-pair role policy**: `allow "A" with "B" { "A" as "roleA"; "B" as "roleB" }` hard-gates the role each side's actors must take. The happy-path source satisfies the constraint (sponsor/merchant roles match), so it passes the security gate and lowers; self-test `[30]` also derives a violating variant in-test (wrong role → exit 5, `ok=false`).

## Contents

```
source/    core_role_constrained.neu              # canonical source
scenario/  core_role_constrained_happy_path.json  # satisfied (passing) scenario
```

No committed `generated/` fixtures — `[30]` generates and checks the security report from this source at test time (and mutates it for the negative case). `source/` and `scenario/` are the trusted inputs.
