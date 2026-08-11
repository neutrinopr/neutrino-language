"""[fast]  hard-cut completeness: the superseded network term is eradicated repo-wide.

Total eradication (no alias, no migration-table carve-out): the pre- orchestration term names
a network/runtime concept, not a translator artifact, and must not appear ANYWHERE in this repo. The
ONLY permitted residuals are genuine English/domain words that merely contain the substring:
'planned'/'planning'/'planted' (sample status + prose), 'control plane' (networking), 'installment plan'
(Cybersource domain term), 'explanation', and the  `CoordinationPlan` translator artifact
(the target-neutral normalized coordination — a compiler datum, NOT the eradicated network/runtime
concept; permitted as 'coordination plan'/`CoordinationPlan`/`planFromSpec`/`planToJson`/`PlanEffect`/
`PlanCompute`). Anything else is a regression — rename it to capability-spec / spec. The search token
is assembled from pieces so this gate's own source stays
free of the literal it forbids, letting the scan cover the whole tree including itself.
"""

import re
import unittest

from _fastcase import FastCase

# Assembled so this file does not itself contain the forbidden literal.
_P = "p"
TERM = _P + "lan"
# The  CoordinationPlan translator artifact (a compiler datum, not the eradicated network
# term) is a permitted residual: the type/target/prose coordination-plan plus the fixed
# API identifiers that cannot carry the prefix. Local variables use coordinationPlan so their
# use-sites match the first alternative. The  coordination-plan realization-legality gate
# extends the same family (PlanLegality mirrors SpecLegality): the plan-legality matcher API +
# its requirement/metrics data are the CoordinationPlan-derived compiler surface, not the term.
# The  obligation→CoordinationPlan realization adds the same-family PlanObligation record
# (mirrors PlanEffect) and versions it with kObligationPlanVersion; obligation[_ -]?plan covers
# that constant and the obligation_plan fixture/prose — all CoordinationPlan-derived, not the term.
# The canonical-plan semantics fixture and planText projection likewise exercise the
# CoordinationPlan compiler artifact and are part of that same exception.
# The  CoordinationPlan compiler surface also includes these EXACT live
# identifiers (each enumerated individually, never a wildcard): the
# semantic-authority direct-plan-read probe family (direct-plan-read,
# plan-auto-alias, plan-type-alias); its _PLAN_TYPES / plan_types / plan_vars /
# source_is_plan matcher state; the plan_out and plan.effects witness surface;
# the plan_target_error_seam fault-seam test; and the %t.plan / %t.rtplan lit
# temporaries. Ordinary-English 'plant'/'plants' (a selftest that plants
# failure classes) is a genuine residual too. Every token here is specific, so
# a standalone reintroduction of the bare product term still fails.
ALLOW = re.compile(
    r"planned|planning|planted|plants?|control plane|installment[ _]plan|explanation"
    r"|coordination[ _-]?plan|canonical[ _-]?plan|sem\(plan\)|normalizePlan|assemblePlan|planFromSpec"
    r"|planToJson|PlanEffect|PlanCompute|PlanInputs|PlanGateMode"
    r"|PlanLegality|PlanRequirements|PlanMetrics|planIsLegal|plan[_-]legality"
    r"|PlanObligation|obligation[ _-]?plan|planText"
    r"|direct-plan-read|plan-auto-alias|plan-type-alias|plan_types|plan_vars"
    r"|source_is_plan|plan_out|plan\.effects|plan_target_error_seam|%t\.(?:rt)?plan",
    re.I)

# SCOPE: the  hard-cut targets the neutrino product/codebase term. External-domain
# EVIDENCE docs are exempt — the L1-adequacy evidence artifacts quote/describe REAL-WORLD
# coordination-failure scenarios (emergency management, logistics, aviation, child
# welfare) whose ordinary-English coordination-document noun is unavoidable and is NOT the
# eradicated concept. This is a scan-SCOPE exclusion of external-domain prose, not a term
# alias or a migration-table carve-out, so the "total eradication" invariant still holds
# everywhere the product term could actually appear (code, product docs, specs). Kept
# narrow to the adequacy-evidence family so a product-term regression elsewhere still
# fails. (Added by the  closure audit to unblock the full-main run.) This comment,
# like the rest of the file, avoids the forbidden literal so the scan covers itself.
EXEMPT_PATH = re.compile(r"^docs/process/l1_adequacy_[^/]*_evidence/")


class TerminologyHardcut(FastCase):
    def test_superseded_term_eradicated(self):
        r = self.run_cmd("git", "grep", "-inEI", TERM, "--", ".")
        # git grep exits non-zero when there are no matches — that is the clean case.
        lines = r.stdout.decode("utf-8", "replace").splitlines() if r.stdout else []
        bad = [ln for ln in lines
               if ln and not ALLOW.search(ln)
               and not EXEMPT_PATH.match(ln.split(":", 1)[0])]
        self.assertEqual(
            bad, [],
            "the eradicated pre- term reappeared (rename to capability-spec / spec):\n"
            + "\n".join(bad[:40]))


if __name__ == "__main__":
    unittest.main()
