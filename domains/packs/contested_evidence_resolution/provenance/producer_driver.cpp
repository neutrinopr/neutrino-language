#include "Neutrino/CoordinationModelBuild.h"
#include "Neutrino/GenSolidity.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/SourceLoad.h"
#include "Neutrino/View.h"

#include "llvm/Support/Error.h"
#include "mlir/IR/MLIRContext.h"

#include <iostream>

int main(int argc, char **argv) {
  if (argc != 4)
    return 2;
  mlir::MLIRContext context;
  context.getOrLoadDialect<neutrino::NeutrinoDialect>();
  neutrino::LoadResult loaded = neutrino::loadModule(argv[1], context);
  if (loaded.status != neutrino::LoadStatus::Ok)
    return 3;
  neutrino::Scenario scenario = neutrino::loadScenario(argv[2]);
  neutrino::ProcedureOp procedure =
      neutrino::findProcedure(*loaded.module, scenario.procedure);
  if (!procedure)
    return 4;
  neutrino::ProcedureView view = neutrino::viewOf(procedure);
  llvm::Expected<neutrino::CoordinationModel> normalized =
      neutrino::normalizeModel(view);
  if (!normalized) {
    llvm::consumeError(normalized.takeError());
    return 5;
  }
  neutrino::CoordinationModel model = std::move(*normalized);
  for (const std::string &path :
       neutrino::emitSolidityProject(view, scenario, argv[3], model))
    std::cout << path << "\n";
  return 0;
}
