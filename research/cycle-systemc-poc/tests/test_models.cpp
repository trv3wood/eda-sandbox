#include "model.hpp"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>

using cycle_poc::CycleModelAdapter;
using cycle_poc::FunctionalModel;
using cycle_poc::Request;

int main() {
    CycleModelAdapter cycle;
    FunctionalModel functional;
    std::mt19937 random(0x5eedu);

    for (unsigned transaction = 0; transaction < 1000; ++transaction) {
        Request request;
        request.scale = static_cast<std::uint16_t>(random());
        request.bias = static_cast<std::uint16_t>(random());
        const auto length = 1u + random() % 64u;
        for (unsigned i = 0; i < length; ++i)
            request.samples.push_back(static_cast<std::uint16_t>(random()));

        const auto cycle_response = cycle.run(request);
        const auto functional_response = functional.run(request);
        assert(cycle_response == functional_response);
        assert(cycle.last_cycle_count() == request.samples.size() + 2);
    }

    bool rejected_empty = false;
    try {
        functional.run({});
    } catch (const std::invalid_argument&) {
        rejected_empty = true;
    }
    assert(rejected_empty);
    std::cout << "1000 transactions matched\n";
    return 0;
}

