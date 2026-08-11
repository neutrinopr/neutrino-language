#ifndef NEUTRINO_ARTIFACT_PUBLICATION_TEST_SUPPORT_H
#define NEUTRINO_ARTIFACT_PUBLICATION_TEST_SUPPORT_H

#include "Neutrino/ArtifactPublication.h"

namespace neutrino {
namespace artifact_publication {

enum class TestEvent {
  ArtifactValidated,
};

struct TestHooks {
  void (*callback)(TestEvent event, llvm::StringRef path,
                   void *context) = nullptr;
  void *context = nullptr;
};

llvm::Expected<Result>
publishForTesting(const backend_invocation::Result &manifest,
                  llvm::StringRef outputRoot, const TestHooks &hooks);

} // namespace artifact_publication
} // namespace neutrino

#endif // NEUTRINO_ARTIFACT_PUBLICATION_TEST_SUPPORT_H
