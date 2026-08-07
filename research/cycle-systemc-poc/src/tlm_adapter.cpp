#include "tlm_adapter.hpp"

#include <cstring>

namespace cycle_poc {

namespace {

const auto kAccessDelay = sc_core::sc_time(10, sc_core::SC_NS);

std::uint32_t load_word(const unsigned char* data) {
    std::uint32_t value = 0;
    std::memcpy(&value, data, sizeof(value));
    return value;
}

void store_word(unsigned char* data, std::uint32_t value) {
    std::memcpy(data, &value, sizeof(value));
}

}  // namespace

TlmModelAdapter::TlmModelAdapter(sc_core::sc_module_name name, IModel& model)
    : sc_core::sc_module(name), model_(model) {
    socket.register_b_transport(this, &TlmModelAdapter::b_transport);
}

void TlmModelAdapter::b_transport(tlm::tlm_generic_payload& trans,
                                  sc_core::sc_time& delay) {
    if (trans.get_data_ptr() == nullptr || trans.get_data_length() != 4 ||
        trans.get_streaming_width() < trans.get_data_length() ||
        trans.get_byte_enable_ptr() != nullptr) {
        trans.set_response_status(tlm::TLM_BURST_ERROR_RESPONSE);
        return;
    }

    const auto address = trans.get_address();
    const auto command = trans.get_command();
    auto* data = trans.get_data_ptr();
    const bool is_read = command == tlm::TLM_READ_COMMAND;
    const bool is_write = command == tlm::TLM_WRITE_COMMAND;
    if (!is_read && !is_write) {
        trans.set_response_status(tlm::TLM_COMMAND_ERROR_RESPONSE);
        return;
    }

    if (is_write && address == 0x00) {
        request_.samples.clear();
    } else if (is_write && address == 0x04) {
        const auto value = load_word(data);
        request_.scale = static_cast<std::uint16_t>(value);
        request_.bias = static_cast<std::uint16_t>(value >> 16);
    } else if (is_write && address == 0x08) {
        request_.samples.push_back(static_cast<std::uint16_t>(load_word(data)));
    } else if (is_write && address == 0x0c) {
        try {
            response_ = model_.run(request_);
        } catch (const std::exception&) {
            trans.set_response_status(tlm::TLM_GENERIC_ERROR_RESPONSE);
            return;
        }
    } else if (is_read && address == 0x10) {
        store_word(data, response_.value);
    } else if (is_read && address == 0x14) {
        store_word(data, static_cast<std::uint32_t>(response_.transactions));
    } else {
        trans.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
        return;
    }

    delay += kAccessDelay;
    trans.set_response_status(tlm::TLM_OK_RESPONSE);
}

}  // namespace cycle_poc
