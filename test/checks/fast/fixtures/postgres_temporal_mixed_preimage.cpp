  for (const PlanEffect &pe : coordinationPlan.effects)
    if (pe.gateMode != PlanGateMode::TemporalSuppress)
      fail("attest.temporal.mixed",
           "effect '" + pe.name +
               "' is not gated on an accepted() policy, but the coordination "
               "has "
               "accepted() groups — a temporal per-policy PostgreSQL "
               "coordination "
               "must gate EVERY effect on accepted(); mixing per-policy and "
               "ordinary/unconditional effects is unsupported");
