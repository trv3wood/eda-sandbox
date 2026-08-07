#include "model.hpp"

#include <stdexcept>

namespace cycle_poc {

namespace {

constexpr std::uint32_t kAccumulatorMask = 0xffffffffu;

void validate(const Request& request) {
    if (request.samples.empty())
        throw std::invalid_argument("事务至少需要一个 sample");
    if (request.samples.size() > 255)
        throw std::invalid_argument("sample 数量超过 RTL 8 位长度字段");
}

}  // namespace

std::uint32_t transform_sample(std::uint16_t sample,
                               std::uint16_t scale,
                               std::uint16_t bias) {
    return (static_cast<std::uint32_t>(sample) * scale + bias) &
           kAccumulatorMask;
}

CycleModelAdapter::CycleModelAdapter(std::uint64_t timeout_cycles)
    : timeout_cycles_(timeout_cycles) {}

Response CycleModelAdapter::run(const Request& request) {
    validate(request);
    std::uint32_t accumulator = 0;
    std::size_t accepted = 0;
    bool output_valid = false;
    last_cycle_count_ = 0;

    // 第一个周期接受 start；随后每周期最多接受一个 sample；最后一个周期完成输出握手。
    while (!output_valid) {
        if (++last_cycle_count_ > timeout_cycles_)
            throw std::runtime_error("cycle model transaction timeout");
        if (last_cycle_count_ == 1)
            continue;
        if (accepted < request.samples.size()) {
            accumulator += transform_sample(request.samples[accepted],
                                            request.scale, request.bias);
            ++accepted;
            if (accepted == request.samples.size())
                output_valid = true;
        }
    }

    ++last_cycle_count_;  // out_valid/out_ready 握手周期
    ++transactions_;
    return {accumulator, transactions_};
}

std::uint64_t CycleModelAdapter::last_cycle_count() const noexcept {
    return last_cycle_count_;
}

Response FunctionalModel::run(const Request& request) {
    validate(request);
    std::uint32_t accumulator = 0;
    for (const auto sample : request.samples)
        accumulator += transform_sample(sample, request.scale, request.bias);
    return {accumulator, ++transactions_};
}

}  // namespace cycle_poc

