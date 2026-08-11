add_llvm_executable(neutrino-emit neutrino-emit.cpp)

llvm_update_compile_flags(neutrino-emit)
# NeutrinoFrontend (parser) PUBLIC-links NeutrinoDialect -> MLIRIR/MLIRSupport; MLIRParser for .mlir.
target_link_libraries(neutrino-emit PRIVATE NeutrinoFrontend NeutrinoAnalysis NeutrinoDomainSemantics MLIRParser)

mlir_check_all_link_libraries(neutrino-emit)
