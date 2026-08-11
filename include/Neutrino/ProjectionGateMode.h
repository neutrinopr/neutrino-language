#ifndef NEUTRINO_PROJECTION_GATE_MODE_H
#define NEUTRINO_PROJECTION_GATE_MODE_H

namespace neutrino {

// Closed target-neutral gate disposition carried by the finalized projection.
// This small wire-facing type is intentionally independent of CoordinationPlan
// so an external backend can consume a verified projection without importing
// the compiler's plan representation.
enum class PlanGateMode { None, AtomicRefuse, TemporalSuppress };

} // namespace neutrino

#endif // NEUTRINO_PROJECTION_GATE_MODE_H
