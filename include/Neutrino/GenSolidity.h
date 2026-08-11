#ifndef NEUTRINO_GENSOLIDITY_H
#define NEUTRINO_GENSOLIDITY_H

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/View.h"

#include <string>
#include <vector>

namespace neutrino {

// The Solidity coordination contract AND the Foundry test harness are both
// rendered from the canonical spec by GenSoliditySpec.h
// (generateSolidityContractFromSpec, WP6/; generateSolidityTestFromSpec,
// ) — the ProcedureView-based renderers are removed. This header now
// declares only the target's registry emit entry.

// Target-owned generator contract (): the `solidity` target's emit entry —
// writes foundry.toml, src/<Name>.sol, test/<Name>.t.sol; returns written
// paths. Matches the registry EmitFn; `solidity` is a value-lowering target
// (security-gated). See docs/backends/BACKEND_GENERATORS.md.
std::vector<std::string>
emitSolidityProject(const ProcedureView &view, const Scenario &scenario,
                    const std::string &outDir,
                    const CoordinationPlan &coordinationPlan);

} // namespace neutrino

#endif // NEUTRINO_GENSOLIDITY_H
