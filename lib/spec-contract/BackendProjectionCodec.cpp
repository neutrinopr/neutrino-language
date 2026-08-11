#include "Neutrino/BackendProjectionCodec.h"

#include "Neutrino/JsonUtil.h"

#include "llvm/ADT/Twine.h"
#include "llvm/Support/JSON.h"

#include <cstdint>
#include <limits>
#include <type_traits>
#include <utility>
#include <vector>

namespace neutrino {
namespace projection {
namespace {

using llvm::StringRef;
namespace json = llvm::json;

constexpr StringRef kWireKind = "neutrino.finalized-projection/1";

llvm::Error codecError(const llvm::Twine &message) {
  return llvm::make_error<llvm::StringError>(message.str(),
                                             llvm::inconvertibleErrorCode());
}

std::string fieldPath(StringRef path, StringRef field) {
  return (llvm::Twine(path) + "." + field).str();
}

std::string indexPath(StringRef path, size_t index) {
  return (llvm::Twine(path) + "[" + llvm::Twine(index) + "]").str();
}

template <typename T> struct IsVector : std::false_type {};
template <typename T, typename Allocator>
struct IsVector<std::vector<T, Allocator>> : std::true_type {
  using Element = T;
};

template <typename T> struct EnumDecoder;

#define NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN(Type)                              \
  llvm::Expected<StringRef> encodeEnum(Type value, StringRef path) {           \
    switch (value) {
#define NEUTRINO_PROJECTION_WIRE_ENUM_VALUE(Type, Value)                       \
  case Type::Value:                                                            \
    return #Value;
#define NEUTRINO_PROJECTION_WIRE_ENUM_END(Type)                                \
  }                                                                            \
  return codecError(llvm::Twine(path) + ": unknown " #Type " enumerator");     \
  }
#define NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_END(Type)
#define NEUTRINO_PROJECTION_WIRE_NODE_FAMILY(Type, Name)
#define NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY(Type, Name)
#include "BackendProjectionCodecFields.inc"
#undef NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_ENUM_VALUE
#undef NEUTRINO_PROJECTION_WIRE_ENUM_END
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD
#undef NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_END
#undef NEUTRINO_PROJECTION_WIRE_NODE_FAMILY
#undef NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY

#define NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN(Type)                              \
  template <> struct EnumDecoder<Type> {                                       \
    static llvm::Expected<Type> decode(StringRef spelling, StringRef path) {
#define NEUTRINO_PROJECTION_WIRE_ENUM_VALUE(Type, Value)                       \
  if (spelling == #Value)                                                      \
    return Type::Value;
#define NEUTRINO_PROJECTION_WIRE_ENUM_END(Type)                                \
  return codecError(llvm::Twine(path) + ": unknown " #Type " spelling " +      \
                    spelling);                                                 \
  }                                                                            \
  }                                                                            \
  ;
#define NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_END(Type)
#define NEUTRINO_PROJECTION_WIRE_NODE_FAMILY(Type, Name)
#define NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY(Type, Name)
#include "BackendProjectionCodecFields.inc"
#undef NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_ENUM_VALUE
#undef NEUTRINO_PROJECTION_WIRE_ENUM_END
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD
#undef NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_END
#undef NEUTRINO_PROJECTION_WIRE_NODE_FAMILY
#undef NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY

template <typename T>
llvm::Expected<json::Object> encodeObject(const T &value, StringRef path);

template <typename T>
llvm::Expected<T> decodeObject(const json::Object &object, StringRef path);

#define NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_ENUM_VALUE(Type, Value)
#define NEUTRINO_PROJECTION_WIRE_ENUM_END(Type)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN(Type)                            \
  template <>                                                                  \
  llvm::Expected<json::Object> encodeObject<Type>(const Type &, StringRef);
#define NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_END(Type)
#define NEUTRINO_PROJECTION_WIRE_NODE_FAMILY(Type, Name)
#define NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY(Type, Name)
#include "BackendProjectionCodecFields.inc"
#undef NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_ENUM_VALUE
#undef NEUTRINO_PROJECTION_WIRE_ENUM_END
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD
#undef NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_END
#undef NEUTRINO_PROJECTION_WIRE_NODE_FAMILY
#undef NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY

#define NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_ENUM_VALUE(Type, Value)
#define NEUTRINO_PROJECTION_WIRE_ENUM_END(Type)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN(Type)                            \
  template <>                                                                  \
  llvm::Expected<Type> decodeObject<Type>(const json::Object &, StringRef);
#define NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_END(Type)
#define NEUTRINO_PROJECTION_WIRE_NODE_FAMILY(Type, Name)
#define NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY(Type, Name)
#include "BackendProjectionCodecFields.inc"
#undef NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_ENUM_VALUE
#undef NEUTRINO_PROJECTION_WIRE_ENUM_END
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD
#undef NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_END
#undef NEUTRINO_PROJECTION_WIRE_NODE_FAMILY
#undef NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY

template <typename T>
llvm::Expected<json::Value> encodeValue(const T &value, StringRef path) {
  if constexpr (std::is_same_v<T, std::string>) {
    return json::Value(value);
  } else if constexpr (std::is_same_v<T, bool>) {
    return json::Value(value);
  } else if constexpr (std::is_integral_v<T>) {
    if constexpr (std::is_unsigned_v<T>) {
      if (value > static_cast<T>(std::numeric_limits<int64_t>::max()))
        return codecError(llvm::Twine(path) + ": integer is out of range");
    }
    return json::Value(static_cast<int64_t>(value));
  } else if constexpr (std::is_enum_v<T>) {
    llvm::Expected<StringRef> spelling = encodeEnum(value, path);
    if (!spelling)
      return spelling.takeError();
    return json::Value(spelling->str());
  } else if constexpr (IsVector<T>::value) {
    json::Array array;
    for (size_t index = 0; index < value.size(); ++index) {
      std::string elementPath = indexPath(path, index);
      llvm::Expected<json::Value> encoded =
          encodeValue(value[index], elementPath);
      if (!encoded)
        return encoded.takeError();
      array.push_back(std::move(*encoded));
    }
    return json::Value(std::move(array));
  } else {
    llvm::Expected<json::Object> object = encodeObject(value, path);
    if (!object)
      return object.takeError();
    return json::Value(std::move(*object));
  }
}

template <typename T>
llvm::Expected<T> decodeValue(const json::Value &wire, StringRef path) {
  if constexpr (std::is_same_v<T, std::string>) {
    llvm::Optional<StringRef> value = wire.getAsString();
    if (!value)
      return codecError(llvm::Twine(path) + ": expected string");
    return value->str();
  } else if constexpr (std::is_same_v<T, bool>) {
    llvm::Optional<bool> value = wire.getAsBoolean();
    if (!value)
      return codecError(llvm::Twine(path) + ": expected bool");
    return *value;
  } else if constexpr (std::is_integral_v<T>) {
    llvm::Optional<int64_t> value = wire.getAsInteger();
    if (!value)
      return codecError(llvm::Twine(path) + ": expected integer");
    if constexpr (std::is_unsigned_v<T>) {
      if (*value < 0 ||
          static_cast<uint64_t>(*value) > std::numeric_limits<T>::max())
        return codecError(llvm::Twine(path) + ": integer is out of range");
    } else {
      if (*value < static_cast<int64_t>(std::numeric_limits<T>::min()) ||
          *value > static_cast<int64_t>(std::numeric_limits<T>::max()))
        return codecError(llvm::Twine(path) + ": integer is out of range");
    }
    return static_cast<T>(*value);
  } else if constexpr (std::is_enum_v<T>) {
    llvm::Optional<StringRef> spelling = wire.getAsString();
    if (!spelling)
      return codecError(llvm::Twine(path) + ": expected enum spelling");
    return EnumDecoder<T>::decode(*spelling, path);
  } else if constexpr (IsVector<T>::value) {
    const json::Array *array = wire.getAsArray();
    if (!array)
      return codecError(llvm::Twine(path) + ": expected array");
    T values;
    values.reserve(array->size());
    for (size_t index = 0; index < array->size(); ++index) {
      std::string elementPath = indexPath(path, index);
      llvm::Expected<typename IsVector<T>::Element> value =
          decodeValue<typename IsVector<T>::Element>((*array)[index],
                                                     elementPath);
      if (!value)
        return value.takeError();
      values.push_back(std::move(*value));
    }
    return values;
  } else {
    const json::Object *object = wire.getAsObject();
    if (!object)
      return codecError(llvm::Twine(path) + ": expected object");
    return decodeObject<T>(*object, path);
  }
}

#define NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_ENUM_VALUE(Type, Value)
#define NEUTRINO_PROJECTION_WIRE_ENUM_END(Type)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN(Type)                            \
  template <>                                                                  \
  llvm::Expected<json::Object> encodeObject<Type>(const Type &value,           \
                                                  StringRef path) {            \
    json::Object object;
#define NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD(Type, FieldType, Name)         \
  std::string path_##Name = fieldPath(path, #Name);                            \
  llvm::Expected<json::Value> encoded_##Name =                                 \
      encodeValue(value.Name, path_##Name);                                    \
  if (!encoded_##Name)                                                         \
    return encoded_##Name.takeError();                                         \
  object[#Name] = std::move(*encoded_##Name);
#define NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD(Type, FieldType, Name)         \
  if (value.Name) {                                                            \
    std::string path_##Name = fieldPath(path, #Name);                          \
    llvm::Expected<json::Value> encoded_##Name =                               \
        encodeValue(*value.Name, path_##Name);                                 \
    if (!encoded_##Name)                                                       \
      return encoded_##Name.takeError();                                       \
    object[#Name] = std::move(*encoded_##Name);                                \
  }
#define NEUTRINO_PROJECTION_WIRE_STRUCT_END(Type)                              \
  return object;                                                               \
  }
#define NEUTRINO_PROJECTION_WIRE_NODE_FAMILY(Type, Name)
#define NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY(Type, Name)
#include "BackendProjectionCodecFields.inc"
#undef NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_ENUM_VALUE
#undef NEUTRINO_PROJECTION_WIRE_ENUM_END
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD
#undef NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_END
#undef NEUTRINO_PROJECTION_WIRE_NODE_FAMILY
#undef NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY

#define NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_ENUM_VALUE(Type, Value)
#define NEUTRINO_PROJECTION_WIRE_ENUM_END(Type)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN(Type)                            \
  template <>                                                                  \
  llvm::Expected<Type> decodeObject<Type>(const json::Object &object,          \
                                          StringRef path) {                    \
    Type value;                                                                \
    size_t consumed = 0;
#define NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD(Type, FieldType, Name)         \
  const json::Value *wire_##Name = object.get(#Name);                          \
  if (!wire_##Name)                                                            \
    return codecError(llvm::Twine(fieldPath(path, #Name)) +                    \
                      ": required field is omitted");                          \
  ++consumed;                                                                  \
  llvm::Expected<FieldType> decoded_##Name =                                   \
      decodeValue<FieldType>(*wire_##Name, fieldPath(path, #Name));            \
  if (!decoded_##Name)                                                         \
    return decoded_##Name.takeError();                                         \
  value.Name = std::move(*decoded_##Name);
#define NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD(Type, FieldType, Name)         \
  if (const json::Value *wire_##Name = object.get(#Name)) {                    \
    ++consumed;                                                                \
    llvm::Expected<FieldType> decoded_##Name =                                 \
        decodeValue<FieldType>(*wire_##Name, fieldPath(path, #Name));          \
    if (!decoded_##Name)                                                       \
      return decoded_##Name.takeError();                                       \
    value.Name = std::move(*decoded_##Name);                                   \
  }
#define NEUTRINO_PROJECTION_WIRE_STRUCT_END(Type)                              \
  if (object.size() != consumed)                                               \
    return codecError(llvm::Twine(path) + ": unknown field");                  \
  return value;                                                                \
  }
#define NEUTRINO_PROJECTION_WIRE_NODE_FAMILY(Type, Name)
#define NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY(Type, Name)
#include "BackendProjectionCodecFields.inc"
#undef NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_ENUM_VALUE
#undef NEUTRINO_PROJECTION_WIRE_ENUM_END
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD
#undef NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_END
#undef NEUTRINO_PROJECTION_WIRE_NODE_FAMILY
#undef NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY

template <typename T>
llvm::Expected<json::Array> encodeArray(const std::vector<T> &values,
                                        StringRef path) {
  json::Array array;
  for (size_t index = 0; index < values.size(); ++index) {
    std::string elementPath = indexPath(path, index);
    llvm::Expected<json::Value> encoded =
        encodeValue(values[index], elementPath);
    if (!encoded)
      return encoded.takeError();
    array.push_back(std::move(*encoded));
  }
  return array;
}

template <typename T>
llvm::Expected<std::vector<T>> decodeArray(const json::Value &wire,
                                           StringRef path) {
  const json::Array *array = wire.getAsArray();
  if (!array)
    return codecError(llvm::Twine(path) + ": expected array");
  std::vector<T> values;
  values.reserve(array->size());
  for (size_t index = 0; index < array->size(); ++index) {
    std::string elementPath = indexPath(path, index);
    llvm::Expected<T> value = decodeValue<T>((*array)[index], elementPath);
    if (!value)
      return value.takeError();
    values.push_back(std::move(*value));
  }
  return values;
}

llvm::Expected<const json::Value *>
requiredValue(const json::Object &object, StringRef field, StringRef path) {
  if (const json::Value *value = object.get(field))
    return value;
  return codecError(llvm::Twine(fieldPath(path, field)) +
                    ": required field is omitted");
}

} // namespace

llvm::Expected<std::string>
encodeFinalizedProjection(const BackendProjectionGraph &graph) {
  if (graph.schemaVersion != kProjectionSchemaVersion)
    return codecError("finalized-projection: unsupported schemaVersion");
  BackendProjectionGraph ordered = graph;
  std::string diagnostic = verifyAndOrder(ordered);
  if (!diagnostic.empty())
    return codecError(llvm::Twine("finalized-projection: invalid graph: ") +
                      diagnostic);

  json::Object nodes;
#define NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_ENUM_VALUE(Type, Value)
#define NEUTRINO_PROJECTION_WIRE_ENUM_END(Type)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_END(Type)
#define NEUTRINO_PROJECTION_WIRE_NODE_FAMILY(Type, Name)                       \
  llvm::Expected<json::Array> encoded_##Name =                                 \
      encodeArray(ordered.Name, "$.nodes." #Name);                             \
  if (!encoded_##Name)                                                         \
    return encoded_##Name.takeError();                                         \
  nodes[#Name] = std::move(*encoded_##Name);
#define NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY(Type, Name)
#include "BackendProjectionCodecFields.inc"
#undef NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_ENUM_VALUE
#undef NEUTRINO_PROJECTION_WIRE_ENUM_END
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD
#undef NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_END
#undef NEUTRINO_PROJECTION_WIRE_NODE_FAMILY
#undef NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY

  llvm::Expected<json::Array> edges = encodeArray(ordered.edges, "$.edges");
  if (!edges)
    return edges.takeError();
  json::Object root{
      {"edges", std::move(*edges)},
      {"kind", kWireKind},
      {"nodes", std::move(nodes)},
      {"schemaVersion", ordered.schemaVersion},
  };
  return compactJson(json::Value(std::move(root)));
}

llvm::Expected<BackendProjectionGraph>
decodeFinalizedProjection(StringRef bytes) {
  llvm::Expected<json::Value> parsed = json::parse(bytes);
  if (!parsed)
    return parsed.takeError();
  const json::Object *root = parsed->getAsObject();
  if (!root)
    return codecError("finalized-projection: root must be an object");

  llvm::Expected<const json::Value *> kindWire =
      requiredValue(*root, "kind", "$");
  if (!kindWire)
    return kindWire.takeError();
  llvm::Expected<std::string> kind =
      decodeValue<std::string>(**kindWire, "$.kind");
  if (!kind)
    return kind.takeError();
  if (*kind != kWireKind)
    return codecError("finalized-projection: unknown kind");

  llvm::Expected<const json::Value *> versionWire =
      requiredValue(*root, "schemaVersion", "$");
  if (!versionWire)
    return versionWire.takeError();
  llvm::Expected<int> version =
      decodeValue<int>(**versionWire, "$.schemaVersion");
  if (!version)
    return version.takeError();
  if (*version != kProjectionSchemaVersion)
    return codecError("finalized-projection: unsupported schemaVersion");

  llvm::Expected<const json::Value *> nodesWire =
      requiredValue(*root, "nodes", "$");
  if (!nodesWire)
    return nodesWire.takeError();
  const json::Object *nodes = (*nodesWire)->getAsObject();
  if (!nodes)
    return codecError("$.nodes: expected object");

  BackendProjectionGraph graph;
  graph.schemaVersion = *version;
  size_t consumedFamilies = 0;
#define NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_ENUM_VALUE(Type, Value)
#define NEUTRINO_PROJECTION_WIRE_ENUM_END(Type)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN(Type)
#define NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD(Type, FieldType, Name)
#define NEUTRINO_PROJECTION_WIRE_STRUCT_END(Type)
#define NEUTRINO_PROJECTION_WIRE_NODE_FAMILY(Type, Name)                       \
  const json::Value *wire_##Name = nodes->get(#Name);                          \
  if (!wire_##Name)                                                            \
    return codecError("$.nodes." #Name ": required family is omitted");        \
  ++consumedFamilies;                                                          \
  llvm::Expected<std::vector<Type>> decoded_##Name =                           \
      decodeArray<Type>(*wire_##Name, "$.nodes." #Name);                       \
  if (!decoded_##Name)                                                         \
    return decoded_##Name.takeError();                                         \
  graph.Name = std::move(*decoded_##Name);
#define NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY(Type, Name)
#include "BackendProjectionCodecFields.inc"
#undef NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_ENUM_VALUE
#undef NEUTRINO_PROJECTION_WIRE_ENUM_END
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN
#undef NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD
#undef NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD
#undef NEUTRINO_PROJECTION_WIRE_STRUCT_END
#undef NEUTRINO_PROJECTION_WIRE_NODE_FAMILY
#undef NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY
  if (nodes->size() != consumedFamilies)
    return codecError("$.nodes: unknown family");

  llvm::Expected<const json::Value *> edgesWire =
      requiredValue(*root, "edges", "$");
  if (!edgesWire)
    return edgesWire.takeError();
  llvm::Expected<std::vector<ProjectionEdge>> edges =
      decodeArray<ProjectionEdge>(**edgesWire, "$.edges");
  if (!edges)
    return edges.takeError();
  graph.edges = std::move(*edges);

  if (root->size() != 4)
    return codecError("finalized-projection: unknown top-level field");
  std::string diagnostic = verifyAndOrder(graph);
  if (!diagnostic.empty())
    return codecError(llvm::Twine("finalized-projection: invalid graph: ") +
                      diagnostic);
  llvm::Expected<std::string> canonical = encodeFinalizedProjection(graph);
  if (!canonical)
    return canonical.takeError();
  if (bytes != *canonical)
    return codecError("finalized-projection: non-canonical encoding");
  return graph;
}

} // namespace projection
} // namespace neutrino
