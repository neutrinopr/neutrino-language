#include "Neutrino/BackendInvoker.h"

#include "Neutrino/BackendProjectionCodec.h"
#include "Neutrino/BackendStartup.h"
#include "Neutrino/JsonUtil.h"
#include "Neutrino/VersionInfo.h"

#include "llvm/ADT/ScopeExit.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/FileSystem.h"
#include "llvm/Support/Path.h"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <poll.h>
#if defined(__APPLE__)
#include <spawn.h>
#endif
#include <signal.h>
#include <string>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#if defined(__linux__)
#include <sys/syscall.h>
#endif
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <utility>

extern char **environ;

namespace neutrino {
namespace backend_invocation {
namespace {

using Clock = std::chrono::steady_clock;
using backend_protocol::Direction;
using backend_protocol::Frame;
using backend_protocol::Session;
using backend_protocol::SessionState;

llvm::Error invocationError(llvm::StringRef code,
                            const llvm::Twine &diagnostic) {
  return llvm::make_error<llvm::StringError>(
      (llvm::Twine(code) + ":invoke:" + diagnostic).str(),
      llvm::inconvertibleErrorCode());
}

llvm::Error systemError(llvm::StringRef operation, int errorNumber = errno) {
  return invocationError("E_PROCESS", llvm::Twine(operation) + ": " +
                                          std::strerror(errorNumber));
}

int remainingMilliseconds(Clock::time_point deadline);

llvm::Error writeAll(int descriptor, llvm::StringRef bytes,
                     Clock::time_point deadline) {
  while (!bytes.empty()) {
    int timeout = remainingMilliseconds(deadline);
    if (timeout == 0)
      return invocationError("E_TIMEOUT", "backend protocol write timed out");
    pollfd ready{descriptor, POLLOUT, 0};
    int polled = ::poll(&ready, 1, timeout);
    if (polled < 0) {
      if (errno == EINTR)
        continue;
      return systemError("polling backend protocol output");
    }
    if (polled == 0)
      return invocationError("E_TIMEOUT", "backend protocol write timed out");
    ssize_t written =
        ::send(descriptor, bytes.data(), bytes.size(), MSG_NOSIGNAL);
    if (written < 0) {
      if (errno == EINTR)
        continue;
      if (errno == EAGAIN || errno == EWOULDBLOCK)
        continue;
      return systemError("writing backend protocol stream");
    }
    if (written == 0)
      return invocationError("E_PROCESS_EXIT",
                             "backend closed its protocol stream");
    bytes = bytes.drop_front(static_cast<size_t>(written));
  }
  return llvm::Error::success();
}

llvm::Error sendFrame(int descriptor, const Frame &frame,
                      Clock::time_point deadline) {
  llvm::Expected<std::string> wire = backend_protocol::encodeFrame(frame);
  if (!wire)
    return wire.takeError();
  return writeAll(descriptor, *wire, deadline);
}

enum class ReadKind { Frame, Timeout, Eof };

struct ReadResult {
  ReadKind kind = ReadKind::Eof;
  Frame frame;
};

int remainingMilliseconds(Clock::time_point deadline) {
  auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
      deadline - Clock::now());
  if (remaining.count() <= 0)
    return 0;
  return static_cast<int>(
      std::min<int64_t>(remaining.count(), std::numeric_limits<int>::max()));
}

llvm::Expected<ReadKind> readExact(int descriptor, char *bytes, size_t size,
                                   Clock::time_point deadline) {
  size_t offset = 0;
  while (offset < size) {
    int timeout = remainingMilliseconds(deadline);
    if (timeout == 0)
      return ReadKind::Timeout;
    pollfd ready{descriptor, POLLIN, 0};
    int polled = ::poll(&ready, 1, timeout);
    if (polled < 0) {
      if (errno == EINTR)
        continue;
      return systemError("polling backend protocol stream");
    }
    if (polled == 0)
      return ReadKind::Timeout;
    ssize_t count = ::recv(descriptor, bytes + offset, size - offset, 0);
    if (count < 0) {
      if (errno == EINTR)
        continue;
      return systemError("reading backend protocol stream");
    }
    if (count == 0)
      return ReadKind::Eof;
    offset += static_cast<size_t>(count);
  }
  return ReadKind::Frame;
}

llvm::Expected<ReadResult> readFrame(int descriptor,
                                     Clock::time_point deadline) {
  std::string wire(8, '\0');
  llvm::Expected<ReadKind> header =
      readExact(descriptor, wire.data(), wire.size(), deadline);
  if (!header)
    return header.takeError();
  if (*header != ReadKind::Frame)
    return ReadResult{*header, {}};

  const auto *raw = reinterpret_cast<const unsigned char *>(wire.data());
  uint32_t payloadLength = (static_cast<uint32_t>(raw[0]) << 24) |
                           (static_cast<uint32_t>(raw[1]) << 16) |
                           (static_cast<uint32_t>(raw[2]) << 8) |
                           static_cast<uint32_t>(raw[3]);
  if (payloadLength > backend_protocol::kMaximumFramePayload)
    return invocationError("E_FRAME_LIMIT",
                           "backend frame payload exceeds 64 MiB");
  size_t oldSize = wire.size();
  wire.resize(oldSize + payloadLength);
  llvm::Expected<ReadKind> payload =
      readExact(descriptor, wire.data() + oldSize, payloadLength, deadline);
  if (!payload)
    return payload.takeError();
  if (*payload == ReadKind::Timeout)
    return ReadResult{ReadKind::Timeout, {}};
  if (*payload == ReadKind::Eof)
    return invocationError("E_PROTOCOL", "backend stream ended inside a frame");

  llvm::Expected<std::vector<Frame>> decoded =
      backend_protocol::decodeFrames(wire);
  if (!decoded)
    return decoded.takeError();
  if (decoded->size() != 1)
    return invocationError("E_PROTOCOL",
                           "one backend read decoded multiple frames");
  return ReadResult{ReadKind::Frame, std::move(decoded->front())};
}

void removeStagingDirectory(llvm::StringRef path) {
  if (path.empty())
    return;
  (void)::chmod(path.str().c_str(), 0700);
  (void)llvm::sys::fs::remove_directories(path);
}

void reapAfterKill(pid_t pid, std::chrono::milliseconds bound) {
  if (pid <= 0)
    return;
  (void)::kill(pid, SIGKILL);
  Clock::time_point deadline = Clock::now() + bound;
  while (Clock::now() < deadline) {
    pid_t waited = ::waitpid(pid, nullptr, WNOHANG);
    if (waited == pid || (waited < 0 && errno == ECHILD))
      return;
    if (waited < 0 && errno != EINTR)
      return;
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  std::thread([pid] {
    while (::waitpid(pid, nullptr, 0) < 0 && errno == EINTR) {
    }
  }).detach();
}

struct ChildProcess {
  pid_t pid = -1;
  int protocol = -1;
  std::string stagingDirectory;

  ~ChildProcess() {
    if (protocol >= 0)
      ::close(protocol);
    reapAfterKill(pid, std::chrono::milliseconds(250));
    if (!stagingDirectory.empty())
      removeStagingDirectory(stagingDirectory);
  }

  ChildProcess(const ChildProcess &) = delete;
  ChildProcess &operator=(const ChildProcess &) = delete;
  ChildProcess() = default;
  ChildProcess(ChildProcess &&other)
      : pid(std::exchange(other.pid, -1)),
        protocol(std::exchange(other.protocol, -1)),
        stagingDirectory(std::exchange(other.stagingDirectory, {})) {}
  ChildProcess &operator=(ChildProcess &&other) {
    if (this == &other)
      return *this;
    if (protocol >= 0)
      ::close(protocol);
    reapAfterKill(pid, std::chrono::milliseconds(250));
    if (!stagingDirectory.empty())
      removeStagingDirectory(stagingDirectory);
    pid = std::exchange(other.pid, -1);
    protocol = std::exchange(other.protocol, -1);
    stagingDirectory = std::exchange(other.stagingDirectory, {});
    return *this;
  }
};

#if !defined(__APPLE__)
void closeChildDescriptorsFrom(int first) {
#if defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__NetBSD__)
  ::closefrom(first);
#elif defined(__linux__) && defined(SYS_close_range)
  if (::syscall(SYS_close_range, static_cast<unsigned int>(first), ~0u, 0) == 0)
    return;
#endif
  rlimit limit{};
  int last = 65536;
  if (::getrlimit(RLIMIT_NOFILE, &limit) == 0 &&
      limit.rlim_cur != RLIM_INFINITY)
    last = static_cast<int>(
        std::min<rlim_t>(limit.rlim_cur, std::numeric_limits<int>::max()));
  for (int descriptor = first; descriptor < last; ++descriptor)
    (void)::close(descriptor);
}
#endif

llvm::Error writeFile(int descriptor, llvm::StringRef bytes) {
  while (!bytes.empty()) {
    ssize_t written = ::write(descriptor, bytes.data(), bytes.size());
    if (written < 0) {
      if (errno == EINTR)
        continue;
      return systemError("staging verified backend entry");
    }
    bytes = bytes.drop_front(static_cast<size_t>(written));
  }
  return llvm::Error::success();
}

llvm::Expected<ChildProcess>
launchVerifiedEntry(const backend_package::VerifiedPackage &package) {
  std::string directoryTemplate = "/tmp/neutrino-backend.XXXXXX";
  char *directory = ::mkdtemp(directoryTemplate.data());
  if (!directory)
    return systemError("creating private backend staging directory");
  std::string directoryPath = directory;
  auto cleanup =
      llvm::make_scope_exit([&] { removeStagingDirectory(directoryPath); });
  std::string entryPath;
  for (const backend_package::VerifiedClosureEntry &entry : package.closure()) {
    llvm::SmallString<256> stagedPath(directoryPath);
    llvm::sys::path::append(stagedPath, entry.manifest.path);
    llvm::SmallString<256> parent(stagedPath);
    llvm::sys::path::remove_filename(parent);
    if (std::error_code error = llvm::sys::fs::create_directories(parent))
      return invocationError("E_PROCESS",
                             llvm::Twine("creating staged closure path: ") +
                                 error.message());
    const bool executable =
        entry.manifest.path == package.entry().manifest.path;
    int staged =
        ::open(stagedPath.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW,
               executable ? 0500 : 0400);
    if (staged < 0)
      return systemError("opening private staged closure entry");
    llvm::Error stagedWrite = writeFile(staged, entry.file->bytes());
    int closeError = ::close(staged);
    if (stagedWrite)
      return std::move(stagedWrite);
    if (closeError != 0)
      return systemError("closing private staged closure entry");
    if (executable)
      entryPath = stagedPath.str().str();
  }
  if (entryPath.empty())
    return invocationError("E_PACKAGE_BINDING",
                           "verified package has no staged executable entry");

  llvm::SmallString<256> descriptorPath(directoryPath);
  llvm::sys::path::append(descriptorPath, backend_package::kDescriptorFileName);
  int stagedDescriptor = ::open(descriptorPath.c_str(),
                                O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0400);
  if (stagedDescriptor < 0)
    return systemError("opening private staged package descriptor");
  llvm::Error descriptorWrite =
      writeFile(stagedDescriptor, package.descriptorFile().bytes());
  int descriptorCloseError = ::close(stagedDescriptor);
  if (descriptorWrite)
    return std::move(descriptorWrite);
  if (descriptorCloseError != 0)
    return systemError("closing private staged package descriptor");

  if (::chmod(directoryPath.c_str(), 0500) != 0)
    return systemError("sealing private backend staging directory");

  int protocolPair[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_STREAM, 0, protocolPair) != 0)
    return systemError("creating backend protocol socket");
  auto closeSockets = llvm::make_scope_exit([&] {
    if (protocolPair[0] >= 0)
      ::close(protocolPair[0]);
    if (protocolPair[1] >= 0)
      ::close(protocolPair[1]);
  });

  char argumentZero[] = "neutrino-backend";
  std::string contractArgument =
      (backend_startup::kContractArgument + backend_startup::kContractIdentity)
          .str();
  std::string descriptorArgument =
      (backend_startup::kDescriptorArgument + descriptorPath).str();
  char *arguments[] = {argumentZero, contractArgument.data(),
                       descriptorArgument.data(), nullptr};
  pid_t pid = -1;
#if defined(__APPLE__)
  posix_spawn_file_actions_t actions;
  posix_spawnattr_t attributes;
  bool actionsInitialized = false;
  bool attributesInitialized = false;
  int spawnError = ::posix_spawn_file_actions_init(&actions);
  if (spawnError == 0) {
    actionsInitialized = true;
    spawnError = ::posix_spawnattr_init(&attributes);
  }
  if (spawnError == 0)
    attributesInitialized = true;
  if (spawnError == 0)
    spawnError = ::posix_spawn_file_actions_adddup2(&actions, protocolPair[1],
                                                    STDIN_FILENO);
  if (spawnError == 0)
    spawnError = ::posix_spawn_file_actions_adddup2(&actions, protocolPair[1],
                                                    STDOUT_FILENO);
  if (spawnError == 0)
    spawnError = ::posix_spawn_file_actions_addopen(&actions, STDERR_FILENO,
                                                    "/dev/null", O_WRONLY, 0);
  if (spawnError == 0)
    spawnError =
        ::posix_spawnattr_setflags(&attributes, POSIX_SPAWN_CLOEXEC_DEFAULT);
  if (spawnError == 0)
    spawnError = ::posix_spawn(&pid, entryPath.c_str(), &actions, &attributes,
                               arguments, environ);
  if (actionsInitialized)
    ::posix_spawn_file_actions_destroy(&actions);
  if (attributesInitialized)
    ::posix_spawnattr_destroy(&attributes);
  if (spawnError != 0)
    return systemError("executing verified backend entry", spawnError);
  ::close(protocolPair[1]);
  protocolPair[1] = -1;
#else
  int execPipe[2] = {-1, -1};
  if (::pipe(execPipe) != 0)
    return systemError("creating backend exec-status pipe");
  auto closeExecPipe = llvm::make_scope_exit([&] {
    if (execPipe[0] >= 0)
      ::close(execPipe[0]);
    if (execPipe[1] >= 0)
      ::close(execPipe[1]);
  });
  if (::fcntl(execPipe[1], F_SETFD, FD_CLOEXEC) != 0)
    return systemError("marking backend exec-status pipe close-on-exec");

  pid = ::fork();
  if (pid < 0)
    return systemError("forking backend process");
  if (pid == 0) {
    if (::dup2(protocolPair[1], STDIN_FILENO) < 0 ||
        ::dup2(protocolPair[1], STDOUT_FILENO) < 0) {
      int childError = errno;
      (void)::write(execPipe[1], &childError, sizeof(childError));
      _exit(126);
    }
    if (execPipe[1] != 3 && ::dup2(execPipe[1], 3) < 0)
      _exit(126);
    if (::fcntl(3, F_SETFD, FD_CLOEXEC) != 0)
      _exit(126);
    int devNull = ::open("/dev/null", O_WRONLY);
    if (devNull >= 0) {
      (void)::dup2(devNull, STDERR_FILENO);
      ::close(devNull);
    }
    closeChildDescriptorsFrom(4);
    ::execve(entryPath.c_str(), arguments, environ);
    int childError = errno;
    (void)::write(3, &childError, sizeof(childError));
    _exit(127);
  }

  ::close(protocolPair[1]);
  protocolPair[1] = -1;
  ::close(execPipe[1]);
  execPipe[1] = -1;
  int childError = 0;
  ssize_t statusRead;
  do {
    statusRead = ::read(execPipe[0], &childError, sizeof(childError));
  } while (statusRead < 0 && errno == EINTR);
  if (statusRead < 0) {
    ::kill(pid, SIGKILL);
    (void)::waitpid(pid, nullptr, 0);
    return systemError("reading backend exec status");
  }
  if (statusRead != 0) {
    (void)::waitpid(pid, nullptr, 0);
    return systemError("executing verified backend entry", childError);
  }

  ::close(execPipe[0]);
  execPipe[0] = -1;
#endif
  cleanup.release();

  ChildProcess child;
  child.pid = pid;
  child.protocol = protocolPair[0];
  child.stagingDirectory = directoryPath;
  protocolPair[0] = -1;
  int flags = ::fcntl(child.protocol, F_GETFL);
  if (flags < 0 || ::fcntl(child.protocol, F_SETFL, flags | O_NONBLOCK) != 0) {
    reapAfterKill(child.pid, std::chrono::milliseconds(250));
    child.pid = -1;
    return systemError("making backend protocol stream nonblocking");
  }
  return std::move(child);
}

llvm::Expected<int> waitForExit(ChildProcess &child,
                                Clock::time_point deadline) {
  while (true) {
    int status = 0;
    pid_t waited = ::waitpid(child.pid, &status, WNOHANG);
    if (waited == child.pid) {
      child.pid = -1;
      return status;
    }
    if (waited < 0) {
      if (errno == EINTR)
        continue;
      return systemError("waiting for backend process");
    }
    if (Clock::now() >= deadline)
      return invocationError("E_TIMEOUT", "backend did not exit after Goodbye");
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
}

llvm::Error requireCleanExit(int status) {
  if (WIFEXITED(status) && WEXITSTATUS(status) == 0)
    return llvm::Error::success();
  if (WIFEXITED(status))
    return invocationError("E_PROCESS_EXIT",
                           llvm::Twine("backend exited with status ") +
                               llvm::Twine(WEXITSTATUS(status)));
  if (WIFSIGNALED(status))
    return invocationError("E_PROCESS_EXIT",
                           llvm::Twine("backend terminated by signal ") +
                               llvm::Twine(WTERMSIG(status)));
  return invocationError("E_PROCESS_EXIT",
                         "backend exited without a terminal status");
}

llvm::Error
checkCapabilities(const backend_package::VerifiedPackage &package,
                  const backend_protocol::Capabilities &capabilities) {
  const backend_package::Descriptor &descriptor = package.descriptor();
  if (capabilities.protocolMajor != descriptor.protocolMajor ||
      capabilities.protocolMinorSelected != descriptor.protocolMinor)
    return invocationError("E_VERSION",
                           "negotiated protocol does not match descriptor");
  if (capabilities.apiVersion != descriptor.apiVersion)
    return invocationError("E_VERSION",
                           "backend API version does not match descriptor");
  if (capabilities.targetIdentity != descriptor.targetIdentity ||
      capabilities.targetProfileIdentity != descriptor.targetProfileIdentity)
    return invocationError("E_PACKAGE_BINDING",
                           "backend identity does not match descriptor");
  if (capabilities.projectionSchemaMin !=
          descriptor.compatibilityBounds.projectionSchema.min ||
      capabilities.projectionSchemaMax !=
          descriptor.compatibilityBounds.projectionSchema.max)
    return invocationError(
        "E_VERSION",
        "backend projection schema range does not match descriptor");
  if (capabilities.manifestDigest != descriptor.manifestDigest)
    return invocationError("E_PACKAGE_BINDING",
                           "backend manifest digest does not match descriptor");
  if (capabilities.features != descriptor.capabilities ||
      capabilities.licenseIdentity != descriptor.licenseIdentity)
    return invocationError("E_PACKAGE_BINDING",
                           "backend capabilities do not match descriptor");
  return llvm::Error::success();
}

llvm::Error peerError(const backend_protocol::ErrorMessage &message) {
  return invocationError(message.code,
                         llvm::Twine(message.stage) + ":" + message.diagnostic);
}

llvm::Error consumeOutgoing(Session &session, const Frame &frame) {
  return session.consume(Direction::CoreToBackend, frame);
}

llvm::Expected<Frame> receiveFrame(ChildProcess &child, Session &session,
                                   Clock::time_point deadline, bool &timedOut) {
  llvm::Expected<ReadResult> received = readFrame(child.protocol, deadline);
  if (!received)
    return received.takeError();
  if (received->kind == ReadKind::Timeout) {
    timedOut = true;
    return invocationError("E_TIMEOUT", "backend response timed out");
  }
  if (received->kind == ReadKind::Eof) {
    llvm::Expected<int> status =
        waitForExit(child, Clock::now() + std::chrono::milliseconds(100));
    if (!status)
      return status.takeError();
    if (llvm::Error error = requireCleanExit(*status))
      return std::move(error);
    return invocationError("E_PROCESS_EXIT",
                           "backend exited before completing the protocol");
  }
  if (llvm::Error error =
          session.consume(Direction::BackendToCore, received->frame))
    return std::move(error);
  return std::move(received->frame);
}

llvm::Error sendGoodbye(ChildProcess &child, Session &session,
                        Clock::time_point deadline) {
  llvm::Expected<Frame> goodbye = backend_protocol::encodeGoodbye();
  if (!goodbye)
    return goodbye.takeError();
  if (llvm::Error error = consumeOutgoing(session, *goodbye))
    return error;
  if (llvm::Error error = sendFrame(child.protocol, *goodbye, deadline))
    return error;
  if (::shutdown(child.protocol, SHUT_WR) != 0)
    return systemError("closing backend protocol input");
  return session.finish();
}

} // namespace

std::string coreIdentity() {
  return (llvm::Twine("neutrino-core|protocol=") +
          llvm::Twine(backend_protocol::kProtocolMajor) + "." +
          llvm::Twine(backend_protocol::kProtocolMinor) + "|tool=" +
          kToolVersion + "|git=" + kGitSha + "|build=" + kBuildTarget)
      .str();
}

llvm::Expected<Result> invoke(const backend_package::VerifiedPackage &package,
                              const projection::BackendProjectionGraph &graph,
                              const InvocationOptions &options) {
  if (options.requestId == 0)
    return invocationError("E_PROTOCOL", "requestId must be nonzero");
  if (options.outputSpec.maxArtifacts == 0 ||
      options.outputSpec.maxTotalBytes == 0)
    return invocationError("E_OUTPUT_LIMIT", "output limits must be nonzero");
  if (options.timeout.count() <= 0 || options.cancellationGrace.count() <= 0)
    return invocationError("E_TIMEOUT",
                           "invocation deadlines must be positive");

  llvm::Expected<std::string> projectionBytes =
      projection::encodeFinalizedProjection(graph);
  if (!projectionBytes)
    return projectionBytes.takeError();
  llvm::Expected<ChildProcess> launched = launchVerifiedEntry(package);
  if (!launched)
    return launched.takeError();
  ChildProcess child = std::move(*launched);
  Session session;
  Clock::time_point deadline = Clock::now() + options.timeout;

  backend_protocol::Hello hello{backend_protocol::kProtocolMajor,
                                backend_protocol::kProtocolMinor,
                                options.coreIdentity};
  llvm::Expected<Frame> helloFrame = backend_protocol::encodeHello(hello);
  if (!helloFrame)
    return helloFrame.takeError();
  if (llvm::Error error = consumeOutgoing(session, *helloFrame))
    return std::move(error);
  if (llvm::Error error = sendFrame(child.protocol, *helloFrame, deadline))
    return std::move(error);

  bool timedOut = false;
  llvm::Expected<Frame> capabilitiesFrame =
      receiveFrame(child, session, deadline, timedOut);
  if (!capabilitiesFrame)
    return capabilitiesFrame.takeError();
  if (llvm::Optional<backend_protocol::ErrorMessage> error =
          session.takePeerError())
    return peerError(*error);
  llvm::Optional<backend_protocol::Capabilities> capabilities =
      session.negotiatedCapabilities();
  if (!capabilities)
    return invocationError("E_PROTOCOL",
                           "backend did not complete the handshake");
  if (llvm::Error error = checkCapabilities(package, *capabilities))
    return std::move(error);

  backend_protocol::Emit emit;
  emit.requestId = options.requestId;
  emit.artifactEncoding = "neutrino.finalized-projection/1";
  emit.artifactByteLen = projectionBytes->size();
  emit.artifactDigest = "sha256:" + sha256Hex(*projectionBytes);
  emit.targetProfileIdentity = package.descriptor().targetProfileIdentity;
  emit.outputSpec = options.outputSpec;
  llvm::Expected<std::vector<Frame>> emitFrames =
      backend_protocol::encodeEmit(emit, *projectionBytes);
  if (!emitFrames)
    return emitFrames.takeError();
  for (const Frame &frame : *emitFrames) {
    if (llvm::Error error = consumeOutgoing(session, frame))
      return std::move(error);
    if (llvm::Error error = sendFrame(child.protocol, frame, deadline))
      return std::move(error);
  }

  llvm::Optional<backend_protocol::CompletedEmission> completed;
  while (!completed) {
    llvm::Expected<Frame> frame =
        receiveFrame(child, session, deadline, timedOut);
    if (!frame) {
      if (!timedOut || session.state() != SessionState::Emitting)
        return frame.takeError();
      llvm::consumeError(frame.takeError());
      llvm::Expected<Frame> cancel =
          backend_protocol::encodeCancel({options.requestId});
      if (!cancel)
        return cancel.takeError();
      Clock::time_point graceDeadline =
          Clock::now() + options.cancellationGrace;
      if (llvm::Error error = consumeOutgoing(session, *cancel))
        return std::move(error);
      if (llvm::Error error = sendFrame(child.protocol, *cancel, graceDeadline))
        return std::move(error);
      bool graceTimedOut = false;
      llvm::Expected<Frame> cancelled =
          receiveFrame(child, session, graceDeadline, graceTimedOut);
      if (!cancelled) {
        llvm::consumeError(cancelled.takeError());
        return invocationError(
            "E_TIMEOUT", graceTimedOut
                             ? "backend ignored cancellation after timeout"
                             : "backend failed during cancellation");
      }
      if (session.state() != SessionState::Ready)
        return invocationError("E_PROTOCOL",
                               "backend did not acknowledge cancellation");
      if (llvm::Error error = sendGoodbye(child, session, graceDeadline))
        return std::move(error);
      llvm::Expected<int> status = waitForExit(child, graceDeadline);
      if (!status)
        return status.takeError();
      if (llvm::Error error = requireCleanExit(*status))
        return std::move(error);
      return invocationError("E_TIMEOUT",
                             "backend invocation timed out and was cancelled");
    }
    if (llvm::Optional<backend_protocol::ErrorMessage> error =
            session.takePeerError()) {
      llvm::Error reported = peerError(*error);
      Clock::time_point exitDeadline = Clock::now() + options.cancellationGrace;
      if (llvm::Error goodbyeError =
              sendGoodbye(child, session, exitDeadline)) {
        llvm::consumeError(std::move(reported));
        return std::move(goodbyeError);
      }
      llvm::Expected<int> status = waitForExit(child, exitDeadline);
      if (!status) {
        llvm::consumeError(std::move(reported));
        return status.takeError();
      }
      if (llvm::Error exitError = requireCleanExit(*status)) {
        llvm::consumeError(std::move(reported));
        return std::move(exitError);
      }
      return std::move(reported);
    }
    completed = session.takeCompletedEmission();
  }

  Clock::time_point exitDeadline = Clock::now() + options.cancellationGrace;
  if (llvm::Error error = sendGoodbye(child, session, exitDeadline))
    return std::move(error);
  llvm::Expected<int> status = waitForExit(child, exitDeadline);
  if (!status)
    return status.takeError();
  if (llvm::Error error = requireCleanExit(*status))
    return std::move(error);

  Result result;
  result.requestId = completed->requestId;
  result.coreIdentity = options.coreIdentity;
  result.targetIdentity = package.descriptor().targetIdentity;
  result.targetProfileIdentity = package.descriptor().targetProfileIdentity;
  result.packageManifestDigest = package.descriptor().manifestDigest;
  result.projectionEncoding = emit.artifactEncoding;
  result.projectionByteLen = emit.artifactByteLen;
  result.projectionDigest = emit.artifactDigest;
  result.receiptDigest = completed->receiptDigest;
  for (backend_protocol::CompletedArtifact &artifact : completed->artifacts)
    result.artifacts.push_back({std::move(artifact.path),
                                std::move(artifact.bytes),
                                std::move(artifact.sha256)});
  return result;
}

} // namespace backend_invocation
} // namespace neutrino
