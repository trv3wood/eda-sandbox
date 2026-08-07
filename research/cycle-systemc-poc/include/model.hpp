#pragma once

#include <cstdint>
#include <vector>

namespace cycle_poc {

struct Request {
    std::vector<std::uint16_t> samples;
    std::uint16_t scale{1};
    std::uint16_t bias{0};
};

struct Response {
    std::uint32_t value{0};
    std::uint64_t transactions{0};

    bool operator==(const Response& other) const {
        return value == other.value && transactions == other.transactions;
    }
};

class IModel {
public:
    virtual ~IModel() = default;
    virtual Response run(const Request& request) = 0;
};

// 软件复刻 RTL 的逐周期 valid/ready 行为，供共享测试驱动。
class CycleModelAdapter final : public IModel {
public:
    explicit CycleModelAdapter(std::uint64_t timeout_cycles = 100000);
    Response run(const Request& request) override;
    std::uint64_t last_cycle_count() const noexcept;

private:
    std::uint64_t timeout_cycles_;
    std::uint64_t transactions_{0};
    std::uint64_t last_cycle_count_{0};
};

// 去掉内部时钟、流水寄存器和握手，仅保留事务可见语义。
class FunctionalModel final : public IModel {
public:
    Response run(const Request& request) override;

private:
    std::uint64_t transactions_{0};
};

std::uint32_t transform_sample(std::uint16_t sample,
                               std::uint16_t scale,
                               std::uint16_t bias);

}  // namespace cycle_poc
