#include "stream_accumulator_sc.hpp"

StreamAccumulatorSc::StreamAccumulatorSc(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {
    SC_METHOD(tick);
    sensitive << clk.pos() << reset_n.neg();
    dont_initialize();
}

void StreamAccumulatorSc::publish() {
    in_ready.write(active_ && !out_valid_);
    out_valid.write(out_valid_);
    result.write(accumulator_);
}

void StreamAccumulatorSc::tick() {
    if (!reset_n.read()) {
        active_ = false;
        out_valid_ = false;
        remaining_ = 0;
        accumulator_ = 0;
        publish();
        return;
    }

    const bool was_active = active_;
    if (out_valid_ && out_ready.read()) {
        out_valid_ = false;
        active_ = false;
    }
    // 非阻塞赋值语义：同一沿上的 start 必须观察更新前的 active。
    if (start.read() && !was_active) {
        active_ = true;
        remaining_ = length.read();
        accumulator_ = 0;
    } else if (in_valid.read() && active_ && !out_valid_) {
        accumulator_ = accumulator_ + term.read();
        remaining_ = remaining_ - 1;
        if (remaining_ == 0)
            out_valid_ = true;
    }
    publish();
}
