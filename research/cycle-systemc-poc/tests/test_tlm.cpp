#include "tlm_adapter.hpp"

#include <cassert>
#include <cstdint>
#include <cstring>

namespace {

tlm::tlm_response_status access(cycle_poc::TlmModelAdapter& adapter,
                                tlm::tlm_command command,
                                std::uint64_t address,
                                std::uint32_t& value,
                                unsigned length = 4) {
    tlm::tlm_generic_payload trans;
    trans.set_command(command);
    trans.set_address(address);
    trans.set_data_ptr(reinterpret_cast<unsigned char*>(&value));
    trans.set_data_length(length);
    trans.set_streaming_width(length);
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    adapter.b_transport(trans, delay);
    if (trans.is_response_ok())
        assert(delay == sc_core::sc_time(10, sc_core::SC_NS));
    return trans.get_response_status();
}

}  // namespace

int sc_main(int, char**) {
    cycle_poc::FunctionalModel model;
    cycle_poc::TlmModelAdapter adapter{"adapter", model};
    std::uint32_t value = 0;
    assert(access(adapter, tlm::TLM_WRITE_COMMAND, 0x00, value) ==
           tlm::TLM_OK_RESPONSE);
    value = (3u << 16) | 2u;
    assert(access(adapter, tlm::TLM_WRITE_COMMAND, 0x04, value) ==
           tlm::TLM_OK_RESPONSE);
    value = 5;
    assert(access(adapter, tlm::TLM_WRITE_COMMAND, 0x08, value) ==
           tlm::TLM_OK_RESPONSE);
    value = 7;
    assert(access(adapter, tlm::TLM_WRITE_COMMAND, 0x08, value) ==
           tlm::TLM_OK_RESPONSE);
    value = 1;
    assert(access(adapter, tlm::TLM_WRITE_COMMAND, 0x0c, value) ==
           tlm::TLM_OK_RESPONSE);
    value = 0;
    assert(access(adapter, tlm::TLM_READ_COMMAND, 0x10, value) ==
           tlm::TLM_OK_RESPONSE);
    assert(value == (5u * 2u + 3u) + (7u * 2u + 3u));
    assert(access(adapter, tlm::TLM_READ_COMMAND, 0xff, value) ==
           tlm::TLM_ADDRESS_ERROR_RESPONSE);
    assert(access(adapter, tlm::TLM_READ_COMMAND, 0x10, value, 2) ==
           tlm::TLM_BURST_ERROR_RESPONSE);
    return 0;
}
