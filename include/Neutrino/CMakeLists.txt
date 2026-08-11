set(LLVM_TARGET_DEFINITIONS NeutrinoOps.td)
mlir_tablegen(NeutrinoDialect.h.inc -gen-dialect-decls -dialect=neutrino)
mlir_tablegen(NeutrinoDialect.cpp.inc -gen-dialect-defs -dialect=neutrino)
mlir_tablegen(NeutrinoTypes.h.inc -gen-typedef-decls -typedefs-dialect=neutrino)
mlir_tablegen(NeutrinoTypes.cpp.inc -gen-typedef-defs -typedefs-dialect=neutrino)
mlir_tablegen(NeutrinoAttrs.h.inc -gen-attrdef-decls -attrdefs-dialect=neutrino)
mlir_tablegen(NeutrinoAttrs.cpp.inc -gen-attrdef-defs -attrdefs-dialect=neutrino)
mlir_tablegen(NeutrinoOps.h.inc -gen-op-decls)
mlir_tablegen(NeutrinoOps.cpp.inc -gen-op-defs)
add_public_tablegen_target(NeutrinoOpsIncGen)

# The generic L2 domain-semantics meta-model dialect (). Ordinary MLIR
# tablegen backends only — no custom generator.
set(LLVM_TARGET_DEFINITIONS L2Ops.td)
mlir_tablegen(L2Dialect.h.inc -gen-dialect-decls -dialect=l2)
mlir_tablegen(L2Dialect.cpp.inc -gen-dialect-defs -dialect=l2)
mlir_tablegen(L2Ops.h.inc -gen-op-decls)
mlir_tablegen(L2Ops.cpp.inc -gen-op-defs)
add_public_tablegen_target(NeutrinoL2IncGen)

# One aggregate so `compile-db` (and any generated-header prep) pulls EVERY
# dialect's generated headers — a new dialect adds itself here, not to each
# consumer, so clang-tidy can never miss a fresh *.inc again.
add_custom_target(NeutrinoIncGen DEPENDS NeutrinoOpsIncGen NeutrinoL2IncGen)
