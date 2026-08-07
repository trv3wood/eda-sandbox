#include "model.hpp"

#include <chrono>
#include <cstdint>
#include <iostream>
#include <random>
#include <string_view>
#include <vector>

using Clock = std::chrono::steady_clock;

template <typename Model>
std::uint64_t measure(Model& model,
                      const std::vector<cycle_poc::Request>& requests) {
    std::uint32_t checksum = 0;
    const auto start = Clock::now();
    for (const auto& request : requests)
        checksum ^= model.run(request).value;
    const auto end = Clock::now();
    // 输出 checksum，避免优化器删除模型调用。
    if (checksum == 0xdeadbeefu)
        std::cerr << checksum;
    return std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
}

int main() {
    std::mt19937 random(0x5eedu);
    std::vector<cycle_poc::Request> requests(20000);
    for (auto& request : requests) {
        request.scale = static_cast<std::uint16_t>(random());
        request.bias = static_cast<std::uint16_t>(random());
        for (unsigned i = 0; i < 32; ++i)
            request.samples.push_back(static_cast<std::uint16_t>(random()));
    }

    // 单独实例避免事务计数相互污染；首轮为预热，不纳入五次测量。
    cycle_poc::CycleModelAdapter cycle_warmup;
    cycle_poc::FunctionalModel functional_warmup;
    measure(cycle_warmup, requests);
    measure(functional_warmup, requests);

    std::cout << "model,iteration,transactions,elapsed_ns\n";
    for (unsigned iteration = 0; iteration < 5; ++iteration) {
        cycle_poc::CycleModelAdapter cycle;
        cycle_poc::FunctionalModel functional;
        std::cout << "cycle," << iteration << ',' << requests.size() << ','
                  << measure(cycle, requests) << '\n';
        std::cout << "functional," << iteration << ',' << requests.size() << ','
                  << measure(functional, requests) << '\n';
    }
    return 0;
}

