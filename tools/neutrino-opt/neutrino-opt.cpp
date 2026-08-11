#include "mlir/IR/DialectRegistry.h"
#include "mlir/Tools/mlir-opt/MlirOptMain.h"

#include "Neutrino/L2Dialect.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/VersionInfo.h"

int main(int argc, char **argv) {
  if (neutrino::handleVersionFlag(argc, argv, "neutrino-opt"))
    return 0;
  mlir::DialectRegistry registry;
  registry.insert<neutrino::NeutrinoDialect, neutrino::l2::L2Dialect>();
  return mlir::asMainReturnCode(mlir::MlirOptMain(
      argc, argv, "neutrino-opt — Neutrino MLIR driver\n", registry));
}
