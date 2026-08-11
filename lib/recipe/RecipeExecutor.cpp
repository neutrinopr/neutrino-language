//===- RecipeExecutor.cpp - atomic top-level recipe execution -------------===//
//
// The single generic entrypoint owning the COMPLETE recipe lifecycle ( /
//  §3.6): target + schema-version check, exact-key resolution, session
// begin, generic interpretation, finish, and a BUFFERED render committed to the
// caller sink only on full success. Any failure before commit destroys the
// session and buffered bytes, so partial target output is never observable
// (§3.6 rules 7-9). The caller never manages the session or sees a half-render.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/RecipeModule.h"

#include "llvm/Support/raw_ostream.h"

#include <string>

using namespace llvm;

namespace neutrino {
namespace recipe {

namespace {
// Accumulates render bytes in memory; committed to the caller sink only if
// render succeeds.
class BufferingSink : public OutputSink {
public:
  void write(StringRef bytes) override { buffer += bytes.str(); }
  std::string buffer;
};
} // namespace

Expected<std::unique_ptr<OpaqueTargetArtifact>>
materializeRecipe(const RecipeModule &module,
                  const TargetRecipeProvider &provider,
                  const FinalizedInvocation &invocation) {
  if (module.schemaVersion != kSupportedSchemaVersion)
    return recipeError(RecipeDiagnostic::Version, module.target);
  if (provider.target() != module.target ||
      invocation.key.target != module.target)
    return recipeError(RecipeDiagnostic::TargetMismatch, invocation.key.target);

  // Resolve through the provider's generated exact-key resolver (§3.6 — the one
  // authoritative resolver), then hand that resolved handle to `begin` so the
  // session snapshots the input views for the actual recipe.
  auto handle = provider.resolve(invocation.key);
  if (!handle)
    return handle.takeError();
  int idx = (int)*handle;
  if (idx < 0 || idx >= (int)module.recipes.size())
    return recipeError(RecipeDiagnostic::ResolverZero, invocation.key.target);

  FinalizedInvocation resolved = invocation;
  resolved.recipe = *handle;

  auto session = provider.begin(resolved);
  if (!session)
    return session.takeError();

  auto roots = interpretRecipe(module, idx, provider, **session);
  if (!roots)
    return roots.takeError(); // session destroyed with the unique_ptr

  return provider.finish(std::move(*session), *roots);
}

Error executeRecipe(const RecipeModule &module,
                    const TargetRecipeProvider &provider,
                    const FinalizedInvocation &invocation, OutputSink &sink) {
  auto artifact = materializeRecipe(module, provider, invocation);
  if (!artifact)
    return artifact.takeError();
  // Buffer the render; commit to the caller sink only on success so a provider
  // that writes a prefix and then fails exposes nothing.
  BufferingSink buffered;
  if (Error e = provider.render(**artifact, buffered))
    return e; // buffered bytes discarded
  sink.write(buffered.buffer);
  return Error::success();
}

} // namespace recipe
} // namespace neutrino
