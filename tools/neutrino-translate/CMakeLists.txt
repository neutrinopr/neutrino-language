add_llvm_executable(neutrino-translate neutrino-translate.cpp)

llvm_update_compile_flags(neutrino-translate)
# NeutrinoFrontend (the .neu parser) PUBLIC-links NeutrinoDialect -> MLIRIR/MLIRSupport.
target_link_libraries(neutrino-translate PRIVATE NeutrinoFrontend)

mlir_check_all_link_libraries(neutrino-translate)
