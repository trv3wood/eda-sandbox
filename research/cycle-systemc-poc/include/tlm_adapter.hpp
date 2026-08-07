#pragma once

#include "model.hpp"

#include <systemc>
#include <tlm>
#include <tlm_utils/simple_target_socket.h>

namespace cycle_poc {

// 线协议：32 位小端字。写 0x00 清空，0x04 配置 scale/bias，0x08 追加 sample；
// 写 0x0c 执行，读 0x10 取得结果，读 0x14 取得事务计数低 32 位。
class TlmModelAdapter final : public sc_core::sc_module {
public:
    tlm_utils::simple_target_socket<TlmModelAdapter> socket{"socket"};

    TlmModelAdapter(sc_core::sc_module_name name, IModel& model);
    void b_transport(tlm::tlm_generic_payload& trans, sc_core::sc_time& delay);

private:
    IModel& model_;
    Request request_;
    Response response_;
};

}  // namespace cycle_poc

