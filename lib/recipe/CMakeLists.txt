# The generic, domain-blind, target-blind backend-idiom recipe runtime ( /
#  §8.1). A bottom-of-the-graph leaf like NeutrinoCodeText: it owns the
# recipe schema/validation, the FinalizedIdiomKey + typed invocation views, the
# provider ABI (RecipeRuntime.h), exact-key resolution, generic traversal, and
# the stable §3.7 diagnostics. It links ONLY MLIRSupport (llvm StringRef/Error);
# it MUST NOT link a backend, a target-node enum, a hook implementation, a
# domain/source header, or a target switch (§8.1). Backend recipe .td files +
# leaf hooks live in the backend packages, never here.
add_mlir_library(NeutrinoRecipe
  RecipeRuntime.cpp
  RecipeModule.cpp
  RecipeInterpreter.cpp
  RecipeExecutor.cpp
  RecipeProviderRegistry.cpp

  PARTIAL_SOURCES_INTENDED

  LINK_LIBS PUBLIC
  MLIRSupport
)
