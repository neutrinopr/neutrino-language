#include "Neutrino/ArtifactPublication.h"

#include "ArtifactPublicationTestSupport.h"
#include "Neutrino/BackendProtocol.h"
#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/Support/Error.h"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <set>
#include <string>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <utility>
#include <vector>

namespace neutrino {
namespace artifact_publication {
namespace {

using llvm::StringRef;

class OwnedFd {
public:
  OwnedFd() = default;
  explicit OwnedFd(int descriptor) : Descriptor(descriptor) {}
  OwnedFd(const OwnedFd &) = delete;
  OwnedFd &operator=(const OwnedFd &) = delete;
  OwnedFd(OwnedFd &&other) noexcept
      : Descriptor(std::exchange(other.Descriptor, -1)) {}
  OwnedFd &operator=(OwnedFd &&other) noexcept {
    if (this != &other) {
      reset();
      Descriptor = std::exchange(other.Descriptor, -1);
    }
    return *this;
  }
  ~OwnedFd() { reset(); }

  int get() const { return Descriptor; }

private:
  void reset() {
    if (Descriptor >= 0)
      (void)::close(Descriptor);
    Descriptor = -1;
  }

  int Descriptor = -1;
};

llvm::Error publicationError(StringRef code, const llvm::Twine &diagnostic) {
  return llvm::make_error<llvm::StringError>(
      (llvm::Twine(code) + ":write:" + diagnostic).str(),
      llvm::inconvertibleErrorCode());
}

llvm::Error systemError(StringRef operation, StringRef path, int error) {
  return publicationError("E_PATH", llvm::Twine(operation) + " '" + path +
                                        "': " + std::strerror(error));
}

bool validDigest(StringRef digest) {
  if (!digest.consume_front("sha256:") || digest.size() != 64)
    return false;
  return llvm::all_of(digest, [](char value) {
    return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
  });
}

llvm::Expected<llvm::SmallVector<std::string, 8>>
splitRelativePath(StringRef path) {
  if (llvm::Error error = backend_protocol::validateArtifactPath(path))
    return std::move(error);
  llvm::SmallVector<std::string, 8> components;
  while (!path.empty()) {
    std::pair<StringRef, StringRef> split = path.split('/');
    components.push_back(split.first.str());
    path = split.second;
  }
  return components;
}

llvm::Expected<OwnedFd> duplicateFd(int descriptor) {
  int duplicate = ::fcntl(descriptor, F_DUPFD_CLOEXEC, 0);
  if (duplicate < 0)
    return systemError("duplicate directory", "", errno);
  return OwnedFd(duplicate);
}

llvm::Expected<OwnedFd> openOutputRoot(StringRef path) {
  if (path.empty() || path.contains('\0'))
    return publicationError("E_PATH", "output root is empty or contains NUL");

  // Open the caller-spelled root ONCE and keep that descriptor as the
  // publication root; every descendant operation is fd-relative from it.
  //
  // There is deliberately no lstat/realpath pre-check. Any check performed on a
  // PATH and then re-resolved is a check/use race: the final component could be
  // replaced with a symlink between the check and the resolution, and the later
  // traversal would then safely open the wrong destination. Opening once
  // removes the window entirely -- the fd IS the checked object, so nothing can
  // be swapped underneath it afterwards.
  //
  // O_NOFOLLOW applies only to the FINAL component, which is exactly the
  // distinction needed: ancestors may legitimately resolve through symlinks (on
  // macOS TMPDIR resolves via /var -> private/var, so every tempfile.mkdtemp()
  // path does), while the root the caller named may not itself be a symlink and
  // so cannot redirect the publication.
  std::string spelled = path.str();
  int rootFd =
      ::open(spelled.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (rootFd < 0) {
    if (errno == ELOOP || errno == EMLINK)
      return publicationError("E_PATH", "output root is a symbolic link");
    return systemError("open output root", path, errno);
  }
  return OwnedFd(rootFd);
}

struct Identity {
  dev_t device = 0;
  ino_t inode = 0;
};

llvm::Expected<Identity> descriptorIdentity(int descriptor,
                                            StringRef description) {
  struct stat status {};
  if (::fstat(descriptor, &status) != 0)
    return systemError("inspect descriptor", description, errno);
  return Identity{status.st_dev, status.st_ino};
}

llvm::Expected<OwnedFd>
walkDirectories(int root, llvm::ArrayRef<std::string> components, bool create) {
  llvm::Expected<OwnedFd> duplicate = duplicateFd(root);
  if (!duplicate)
    return duplicate.takeError();
  OwnedFd current = std::move(*duplicate);
  for (const std::string &component : components) {
    if (create && ::mkdirat(current.get(), component.c_str(), 0755) != 0 &&
        errno != EEXIST)
      return systemError("create output directory", component, errno);
    int next = ::openat(current.get(), component.c_str(),
                        O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (next < 0)
      return systemError("open output directory", component, errno);
    current = OwnedFd(next);
  }
  return current;
}

llvm::Error writeAll(int descriptor, StringRef bytes) {
  while (!bytes.empty()) {
    ssize_t written = ::write(descriptor, bytes.data(), bytes.size());
    if (written < 0) {
      if (errno == EINTR)
        continue;
      return systemError("write published artifact", "", errno);
    }
    if (written == 0)
      return publicationError("E_PATH",
                              "published artifact write made no progress");
    bytes = bytes.drop_front(static_cast<size_t>(written));
  }
  return llvm::Error::success();
}

llvm::Error syncFd(int descriptor, StringRef description) {
  if (::fsync(descriptor) != 0)
    return systemError("sync", description, errno);
  return llvm::Error::success();
}

void runHook(const TestHooks &hooks, TestEvent event, StringRef path) {
  if (hooks.callback)
    hooks.callback(event, path, hooks.context);
}

llvm::Error verifyOpenArtifact(int descriptor,
                               const backend_invocation::Artifact &artifact) {
  if (::lseek(descriptor, 0, SEEK_SET) < 0)
    return systemError("seek published artifact", artifact.path, errno);
  std::string bytes;
  bytes.resize(artifact.bytes.size());
  size_t offset = 0;
  while (offset != bytes.size()) {
    ssize_t count =
        ::read(descriptor, bytes.data() + offset, bytes.size() - offset);
    if (count < 0) {
      if (errno == EINTR)
        continue;
      return systemError("read published artifact", artifact.path, errno);
    }
    if (count == 0)
      break;
    offset += static_cast<size_t>(count);
  }
  bytes.resize(offset);
  if (bytes != artifact.bytes ||
      "sha256:" + sha256Hex(bytes) != artifact.sha256)
    return publicationError("E_ARTIFACT_DIGEST",
                            "published artifact bytes changed");
  return llvm::Error::success();
}

llvm::Error visiblePathsRetained(llvm::Error error) {
  return publicationError(
      "E_PATH",
      llvm::Twine("publication stopped; visible paths are retained: ") +
          llvm::toString(std::move(error)));
}

} // namespace

static llvm::Expected<Result>
publishImpl(const backend_invocation::Result &manifest, StringRef outputRoot,
            const TestHooks &hooks) {
  struct Pending {
    const backend_invocation::Artifact *artifact = nullptr;
    llvm::SmallVector<std::string, 8> components;
  };
  struct Published {
    const backend_invocation::Artifact *artifact = nullptr;
    llvm::SmallVector<std::string, 8> components;
    OwnedFd file;
    std::string leaf;
    Identity identity;
  };

  std::vector<Pending> pending;
  pending.reserve(manifest.artifacts.size());
  if (manifest.requestId == 0 || manifest.targetIdentity.empty() ||
      !validDigest(manifest.receiptDigest))
    return publicationError("E_PROTOCOL",
                            "verified manifest metadata is malformed");
  std::set<std::string> paths;
  for (const backend_invocation::Artifact &artifact : manifest.artifacts) {
    llvm::Expected<llvm::SmallVector<std::string, 8>> components =
        splitRelativePath(artifact.path);
    if (!components)
      return components.takeError();
    if (!paths.insert(artifact.path).second)
      return publicationError("E_PATH", "artifact path is duplicated");
    if (!validDigest(artifact.sha256) ||
        artifact.sha256 != "sha256:" + sha256Hex(artifact.bytes))
      return publicationError("E_ARTIFACT_DIGEST",
                              "artifact digest does not match bytes");
    pending.push_back({&artifact, std::move(*components)});
  }
  std::sort(pending.begin(), pending.end(),
            [](const Pending &left, const Pending &right) {
              return left.artifact->path < right.artifact->path;
            });

  llvm::Expected<OwnedFd> root = openOutputRoot(outputRoot);
  if (!root)
    return root.takeError();
  std::vector<Published> published;
  for (const Pending &entry : pending) {
    llvm::ArrayRef<std::string> parents(entry.components);
    parents = parents.drop_back();
    llvm::Expected<OwnedFd> parent =
        walkDirectories(root->get(), parents, true);
    if (!parent)
      return visiblePathsRetained(parent.takeError());
    const std::string &leaf = entry.components.back();
    int descriptor =
        ::openat(parent->get(), leaf.c_str(),
                 O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (descriptor < 0)
      return visiblePathsRetained(
          systemError("publish artifact", entry.artifact->path, errno));
    OwnedFd output(descriptor);
    llvm::Expected<Identity> identity =
        descriptorIdentity(output.get(), entry.artifact->path);
    if (!identity)
      return visiblePathsRetained(identity.takeError());
    published.push_back(
        {entry.artifact, entry.components, std::move(output), leaf, *identity});
    Published &created = published.back();
    if (llvm::Error error = writeAll(created.file.get(), entry.artifact->bytes))
      return visiblePathsRetained(std::move(error));
    if (::fchmod(created.file.get(), 0444) != 0)
      return visiblePathsRetained(
          systemError("set artifact permissions", entry.artifact->path, errno));
    if (llvm::Error error = syncFd(created.file.get(), entry.artifact->path))
      return visiblePathsRetained(std::move(error));
    if (llvm::Error error =
            verifyOpenArtifact(created.file.get(), *entry.artifact))
      return visiblePathsRetained(std::move(error));
    runHook(hooks, TestEvent::ArtifactValidated, entry.artifact->path);
    if (llvm::Error error = syncFd(parent->get(), entry.artifact->path))
      return visiblePathsRetained(std::move(error));
  }

  for (const Published &entry : published) {
    llvm::ArrayRef<std::string> parents(entry.components);
    parents = parents.drop_back();
    llvm::Expected<OwnedFd> visibleParent =
        walkDirectories(root->get(), parents, false);
    if (!visibleParent)
      return visiblePathsRetained(visibleParent.takeError());
    int visibleDescriptor = ::openat(visibleParent->get(), entry.leaf.c_str(),
                                     O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (visibleDescriptor < 0)
      return visiblePathsRetained(systemError("reopen published artifact",
                                              entry.artifact->path, errno));
    OwnedFd visible(visibleDescriptor);
    llvm::Expected<Identity> visibleIdentity =
        descriptorIdentity(visible.get(), entry.artifact->path);
    if (!visibleIdentity)
      return visiblePathsRetained(visibleIdentity.takeError());
    if (visibleIdentity->device != entry.identity.device ||
        visibleIdentity->inode != entry.identity.inode)
      return visiblePathsRetained(
          publicationError("E_PATH", "published artifact identity changed"));
    if (llvm::Error error = verifyOpenArtifact(visible.get(), *entry.artifact))
      return visiblePathsRetained(std::move(error));
  }
  if (llvm::Error error = syncFd(root->get(), outputRoot))
    return visiblePathsRetained(std::move(error));

  Result result;
  result.requestId = manifest.requestId;
  result.targetIdentity = manifest.targetIdentity;
  result.receiptDigest = manifest.receiptDigest;
  for (const Pending &entry : pending)
    result.artifacts.push_back(
        {entry.artifact->path, entry.artifact->sha256,
         static_cast<uint64_t>(entry.artifact->bytes.size())});
  return result;
}

llvm::Expected<Result> publish(const backend_invocation::Result &manifest,
                               StringRef outputRoot) {
  return publishImpl(manifest, outputRoot, {});
}

llvm::Expected<PublishedArtifact>
publishCoreArtifact(StringRef path, StringRef bytes, StringRef outputRoot) {
  std::vector<CoreArtifact> artifacts{{path.str(), bytes.str()}};
  llvm::Expected<std::vector<PublishedArtifact>> published =
      publishCoreArtifacts(artifacts, outputRoot);
  if (!published)
    return published.takeError();
  if (published->size() != 1)
    return publicationError("E_PROTOCOL",
                            "core metadata publication cardinality changed");
  return std::move(published->front());
}

llvm::Expected<std::vector<PublishedArtifact>>
publishCoreArtifacts(llvm::ArrayRef<CoreArtifact> artifacts,
                     StringRef outputRoot) {
  backend_invocation::Result input;
  input.requestId = 1;
  input.targetIdentity = "neutrino-core-artifacts";
  std::string receiptPreimage;
  for (const CoreArtifact &artifact : artifacts) {
    input.artifacts.push_back(
        {artifact.path, artifact.bytes, "sha256:" + sha256Hex(artifact.bytes)});
    receiptPreimage += artifact.path;
    receiptPreimage.push_back('\0');
    receiptPreimage += artifact.bytes;
    receiptPreimage.push_back('\0');
  }
  input.receiptDigest = "sha256:" + sha256Hex(receiptPreimage);
  llvm::Expected<Result> published = publishImpl(input, outputRoot, {});
  if (!published)
    return published.takeError();
  return std::move(published->artifacts);
}

llvm::Expected<Result>
publishForTesting(const backend_invocation::Result &manifest,
                  StringRef outputRoot, const TestHooks &hooks) {
  return publishImpl(manifest, outputRoot, hooks);
}

} // namespace artifact_publication
} // namespace neutrino
