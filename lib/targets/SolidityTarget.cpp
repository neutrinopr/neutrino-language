//===- SolidityTarget.cpp - Solidity target emit entry ------------------===//
//
// The `solidity` target's registry emit entry (emitSolidityProject). Both the
// coordination contract AND the Foundry test harness are rendered from the
// CANONICAL SPEC (the frozen contract, ) by GenSoliditySpec.cpp — this TU
// just emits the spec, folds the scenario once into the TestRealization (),
// and writes the project files. It owns no contract/test rendering itself.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CoordinationPlanBuild.h"
#include "Neutrino/GenSolidity.h"
#include "Neutrino/GenSoliditySpec.h"
#include "Neutrino/GenSpec.h"

#include "llvm/Support/Error.h"

#include "llvm/Support/JSON.h"

#include <filesystem>
#include <fstream>

using namespace neutrino;

std::vector<std::string> neutrino::emitSolidityProject(
    const ProcedureView &view, const Scenario &scenario,
    const std::string &outDir, const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(fs::path(outDir) / "src");
  fs::create_directories(fs::path(outDir) / "test");

  std::string name = view.pascalName();

  // The contract (WP6/) AND the Foundry test harness () are both
  // rendered from the CANONICAL SPEC (the frozen contract, ), not
  // ProcedureView — the spec is emitted here and re-parsed so both renderers
  // consume exactly the external contract (generateSolidityContractFromSpec /
  // generateSolidityTestFromSpec touch no View.h and re-parse no expression
  // text). The test harness single-sources its structural shape from the SAME
  // spec as the contract (so they cannot drift) and folds the scenario once
  // into the TestRealization artifact (WP2/) for values.
  // The shared adapter emits + re-parses our OWN spec and fails closed (abort,
  // not a user diagnostic) if it does not parse to an object — an internal
  // invariant, off the  throw ratchet ().
  neutrino::SelfEmittedSpec spec =
      neutrino::ingestSelfEmittedSpec(view, coordinationPlan);
  const llvm::json::Object *specObj = &spec.object();

  std::vector<SoliditySourceFile> sources =
      generateSoliditySourcesFromSpec(coordinationPlan);
  std::vector<std::pair<std::string, std::string>> files = {
      // optimizer + via_ir: procedures with many inputs/legs otherwise hit the
      // legacy codegen "stack too deep".
      {(fs::path(outDir) / "foundry.toml").string(),
       "[profile.default]\nsrc = \"src\"\ntest = \"test\"\nout = \"out\"\nlibs "
       "= []\n"
       "optimizer = true\nvia_ir = true\n"
       "# Generated artifacts; run with: forge test --use <solc 0.8.x>\n"},
      {(fs::path(outDir) / sources.front().path).string(),
       sources.front().content},
      {(fs::path(outDir) / "test" / (name + ".t.sol")).string(),
       generateSolidityTestFromSpec(*specObj,
                                    realize(view, scenario, coordinationPlan),
                                    coordinationPlan)},
  };

  for (size_t i = 1; i < sources.size(); ++i)
    files.push_back(
        {(fs::path(outDir) / sources[i].path).string(), sources[i].content});

  std::vector<std::string> written;
  for (auto &f : files) {
    std::ofstream os(f.first);
    os << f.second;
    written.push_back(f.first);
  }
  return written;
}
