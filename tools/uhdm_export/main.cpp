#include <uhdm/BaseClass.h>
#include <uhdm/Serializer.h>
#include <uhdm/enum_const.h>
#include <uhdm/ports.h>
#include <uhdm/ref_typespec.h>
#include <uhdm/typespec.h>
#include <uhdm/uhdm_types.h>
#include <uhdm/vpi_user.h>

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <string>
#include <string_view>
#include <vector>

namespace {

std::string Escape(std::string_view value) {
  std::string result;
  for (const unsigned char character : value) {
    switch (character) {
      case '"': result += "\\\""; break;
      case '\\': result += "\\\\"; break;
      case '\b': result += "\\b"; break;
      case '\f': result += "\\f"; break;
      case '\n': result += "\\n"; break;
      case '\r': result += "\\r"; break;
      case '\t': result += "\\t"; break;
      default:
        if (character < 0x20) {
          constexpr char digits[] = "0123456789abcdef";
          result += "\\u00";
          result += digits[character >> 4];
          result += digits[character & 0xf];
        } else {
          result += static_cast<char>(character);
        }
    }
  }
  return result;
}

const char* Direction(int32_t value) {
  switch (value) {
    case vpiInput: return "input";
    case vpiOutput: return "output";
    case vpiInout: return "inout";
    case vpiMixedIO: return "mixed";
    case vpiNoDirection: return "none";
    default: return "unknown";
  }
}

std::string Kind(const UHDM::BaseClass* object) {
  switch (object->UhdmType()) {
    case UHDM::uhdmmodule_inst: return "module";
    case UHDM::uhdmpackage: return "package";
    case UHDM::uhdmport: return "port";
    case UHDM::uhdmparameter: return "parameter";
    case UHDM::uhdmenum_typespec: return "enum";
    case UHDM::uhdmenum_const: return "enum-constant";
    case UHDM::uhdmalways: return "process";
    case UHDM::uhdminitial: return "process";
    case UHDM::uhdmcase_stmt: return "case";
    case UHDM::uhdmassign_stmt:
    case UHDM::uhdmassignment:
    case UHDM::uhdmcont_assign: return "assignment";
    default: break;
  }
  switch (object->VpiType()) {
    case vpiNet:
    case vpiReg:
    case vpiIntegerVar:
    case vpiRealVar:
    case vpiTimeVar:
    case vpiVariables: return "variable";
    default: return "";
  }
}

std::string ProcessType(const UHDM::BaseClass* object) {
  switch (object->UhdmType()) {
    case UHDM::uhdmalways: return "always";
    case UHDM::uhdminitial: return "initial";
    default: return "";
  }
}

const UHDM::BaseClass* OwningModule(const UHDM::BaseClass* object) {
  for (const UHDM::BaseClass* parent = object->VpiParent(); parent;
       parent = parent->VpiParent()) {
    if (parent->UhdmType() == UHDM::uhdmmodule_inst) return parent;
  }
  return nullptr;
}

void StringField(std::ostream& output, std::string_view name,
                 std::string_view value) {
  output << ",\"" << name << "\":\"" << Escape(value) << "\"";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc == 2 && std::string_view(argv[1]) == "--version") {
    std::cout << "uhdm-export schema 1, UHDM serializer "
              << UHDM::Serializer::kVersion << '\n';
    return 0;
  }
  if (argc != 3) {
    std::cerr << "Usage: uhdm-export INPUT.uhdm OUTPUT.json\n";
    return 2;
  }
  const std::filesystem::path input = argv[1];
  const std::filesystem::path output_path = argv[2];
  if (!std::filesystem::is_regular_file(input)) {
    std::cerr << "UHDM input does not exist: " << input << '\n';
    return 1;
  }

  UHDM::Serializer serializer;
  const auto designs = serializer.Restore(input);
  if (designs.empty()) {
    std::cerr << "UHDM input contains no design\n";
    return 1;
  }
  std::ofstream output(output_path);
  if (!output) {
    std::cerr << "Cannot open output: " << output_path << '\n';
    return 1;
  }

  output << "{\"schema_version\":1,\"format\":\"uhdm-json\","
         << "\"serializer_version\":" << UHDM::Serializer::kVersion
         << ",\"source\":\"" << Escape(input.string()) << "\",\"objects\":[";
  std::vector<const UHDM::BaseClass*> objects;
  for (const auto& entry : serializer.AllObjects()) objects.push_back(entry.first);
  std::sort(objects.begin(), objects.end(), [](const auto* lhs, const auto* rhs) {
    return lhs->UhdmId() < rhs->UhdmId();
  });
  bool first = true;
  for (const UHDM::BaseClass* object : objects) {
    const std::string kind = Kind(object);
    if (kind.empty()) continue;
    if (!first) output << ',';
    first = false;
    output << "{\"id\":" << object->UhdmId();
    StringField(output, "kind", kind);
    StringField(output, "name", object->VpiName());
    StringField(output, "definition", object->VpiDefName());
    if (const auto* parent = object->VpiParent()) {
      output << ",\"parent_id\":" << parent->UhdmId();
    } else {
      output << ",\"parent_id\":null";
    }
    if (const auto* module = OwningModule(object)) {
      StringField(
          output, "module",
          module->VpiName().empty() ? module->VpiDefName() : module->VpiName());
    } else if (kind == "module") {
      StringField(output, "module", object->VpiName());
    } else {
      StringField(output, "module", "");
    }
    StringField(output, "file", object->VpiFile());
    output << ",\"line\":" << object->VpiLineNo()
           << ",\"column\":" << object->VpiColumnNo()
           << ",\"end_line\":" << object->VpiEndLineNo()
           << ",\"end_column\":" << object->VpiEndColumnNo();
    if (const auto* port = object->Cast<const UHDM::ports*>()) {
      StringField(output, "direction", Direction(port->VpiDirection()));
      output << ",\"size\":" << port->VpiSize();
    }
    if (const auto* constant = object->Cast<const UHDM::enum_const*>()) {
      StringField(output, "value", constant->VpiValue());
      StringField(output, "decompile", constant->VpiDecompile());
      output << ",\"size\":" << constant->VpiSize();
    }
    const auto typespec_relation = object->GetByVpiType(vpiTypespec);
    const UHDM::BaseClass* typespec = std::get<0>(typespec_relation);
    if (const auto* reference = typespec
            ? typespec->Cast<const UHDM::ref_typespec*>()
            : nullptr) {
      if (reference->Actual_typespec()) typespec = reference->Actual_typespec();
    }
    if (typespec) {
      output << ",\"typespec_id\":" << typespec->UhdmId();
      StringField(
          output, "typespec_name",
          typespec->VpiName().empty() ? typespec->VpiDefName()
                                     : typespec->VpiName());
    }
    const std::string process_type = ProcessType(object);
    if (!process_type.empty()) StringField(output, "process_type", process_type);
    output << '}';
  }
  output << "]}\n";
  return output ? 0 : 1;
}
