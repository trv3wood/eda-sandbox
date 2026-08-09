#pragma once

#include <systemc>

class StreamAccumulatorSc final : public sc_core::sc_module {
public:
    sc_core::sc_in<bool> clk{"clk"};
    sc_core::sc_in<bool> reset_n{"reset_n"};
    sc_core::sc_in<bool> start{"start"};
    sc_core::sc_in<sc_dt::sc_uint<8>> length{"length"};
    sc_core::sc_in<bool> in_valid{"in_valid"};
    sc_core::sc_out<bool> in_ready{"in_ready"};
    sc_core::sc_in<sc_dt::sc_uint<32>> term{"term"};
    sc_core::sc_out<bool> out_valid{"out_valid"};
    sc_core::sc_in<bool> out_ready{"out_ready"};
    sc_core::sc_out<sc_dt::sc_uint<32>> result{"result"};

    SC_HAS_PROCESS(StreamAccumulatorSc);
    explicit StreamAccumulatorSc(sc_core::sc_module_name name);

private:
    void tick();
    void publish();

    bool active_{false};
    bool out_valid_{false};
    sc_dt::sc_uint<8> remaining_{0};
    sc_dt::sc_uint<32> accumulator_{0};
};
