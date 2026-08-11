add_llvm_executable(neutrino-opt neutrino-opt.cpp)

llvm_update_compile_flags(neutrino-opt)
# MLIROptLib transitively brings MLIRIR/MLIRParser/MLIRSupport.
target_link_libraries(neutrino-opt
  PRIVATE
  NeutrinoDialect
  NeutrinoL2
  MLIROptLib
)

mlir_check_all_link_libraries(neutrino-opt)
