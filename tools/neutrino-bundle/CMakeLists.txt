add_llvm_executable(neutrino-bundle neutrino-bundle.cpp)

llvm_update_compile_flags(neutrino-bundle)
target_link_libraries(neutrino-bundle PRIVATE NeutrinoEmit NeutrinoTooling)

mlir_check_all_link_libraries(neutrino-bundle)
