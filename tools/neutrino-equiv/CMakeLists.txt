add_llvm_executable(neutrino-equiv neutrino-equiv.cpp)

llvm_update_compile_flags(neutrino-equiv)
target_link_libraries(neutrino-equiv PRIVATE
  NeutrinoAnalysis
  NeutrinoFrontend
  NeutrinoSpecContract
  NeutrinoTargetCatalog
  NeutrinoTooling
  MLIRParser)

mlir_check_all_link_libraries(neutrino-equiv)
