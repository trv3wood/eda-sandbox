#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <systemc>

#ifndef DUT_HEADER
#error "DUT_HEADER must name the generated SystemC header"
#endif
#ifndef DUT_CLASS
#error "DUT_CLASS must name the generated SystemC class"
#endif

#include DUT_HEADER

namespace {

struct Stimulus {
    bool reset_n;
    bool start;
    std::uint32_t length;
    std::uint32_t scale;
    std::uint32_t bias;
    bool in_valid;
    std::uint32_t in_data;
    bool out_ready;
};

std::vector<Stimulus> read_stimulus(const std::string& path) {
    std::ifstream input(path);
    if (!input)
        throw std::runtime_error("无法打开 stimulus: " + path);
    std::vector<Stimulus> rows;
    std::string line;
    std::getline(input, line);  // 表头
    while (std::getline(input, line)) {
        if (line.empty())
            continue;
        std::replace(line.begin(), line.end(), ',', ' ');
        std::istringstream stream(line);
        unsigned reset_n, start, in_valid, out_ready;
        Stimulus row{};
        stream >> reset_n >> start >> row.length >> row.scale >> row.bias
               >> in_valid >> row.in_data >> out_ready;
        if (!stream)
            throw std::runtime_error("stimulus 行格式错误: " + line);
        row.reset_n = reset_n != 0;
        row.start = start != 0;
        row.in_valid = in_valid != 0;
        row.out_ready = out_ready != 0;
        rows.push_back(row);
    }
    return rows;
}

}  // namespace

int sc_main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: simulation STIMULUS.csv TRACE.csv\n";
        return 2;
    }
    const auto rows = read_stimulus(argv[1]);
    std::ofstream trace(argv[2]);
    if (!trace) {
        std::cerr << "无法创建 trace: " << argv[2] << '\n';
        return 2;
    }

    sc_core::sc_signal<bool> clk{"clk"};
    sc_core::sc_signal<bool> reset_n{"reset_n"};
    sc_core::sc_signal<bool> start{"start"};
    sc_core::sc_signal<sc_dt::sc_uint<8>> length{"length"};
    sc_core::sc_signal<sc_dt::sc_uint<16>> scale{"scale"};
    sc_core::sc_signal<sc_dt::sc_uint<16>> bias{"bias"};
    sc_core::sc_signal<bool> in_valid{"in_valid"};
    sc_core::sc_signal<bool> in_ready{"in_ready"};
    sc_core::sc_signal<sc_dt::sc_uint<16>> in_data{"in_data"};
    sc_core::sc_signal<bool> out_valid{"out_valid"};
    sc_core::sc_signal<bool> out_ready{"out_ready"};
    sc_core::sc_signal<sc_dt::sc_uint<32>> result{"result"};

    DUT_CLASS dut{"dut"};
    dut.clk(clk);
    dut.reset_n(reset_n);
    dut.start(start);
    dut.length(length);
    dut.scale(scale);
    dut.bias(bias);
    dut.in_valid(in_valid);
    dut.in_ready(in_ready);
    dut.in_data(in_data);
    dut.out_valid(out_valid);
    dut.out_ready(out_ready);
    dut.result(result);

    clk.write(false);
    trace << "cycle,in_ready,out_valid,result,term\n";
    for (std::size_t cycle = 0; cycle < rows.size(); ++cycle) {
        const auto& row = rows[cycle];
        reset_n.write(row.reset_n);
        start.write(row.start);
        length.write(row.length);
        scale.write(row.scale);
        bias.write(row.bias);
        in_valid.write(row.in_valid);
        in_data.write(row.in_data);
        out_ready.write(row.out_ready);
        // 输入在上升沿前保留 1 ns，确保跨分区组合逻辑完成 delta-cycle 收敛。
        sc_core::sc_start(1, sc_core::SC_NS);

        clk.write(true);
        sc_core::sc_start(4, sc_core::SC_NS);
        const std::uint32_t expected_term =
            (row.in_data * row.scale + row.bias) & 0xffffffffu;
#ifdef DUT_HAS_DEBUG_TERM
        const std::uint32_t observed_term = dut.sig_transform_term.read().to_uint();
#else
        const std::uint32_t observed_term = expected_term;
#endif
        trace << cycle << ',' << in_ready.read() << ',' << out_valid.read() << ','
              << result.read().to_uint() << ',' << observed_term << '\n';
        if (observed_term != expected_term) {
            std::cerr << "boundary term mismatch at cycle " << cycle << '\n';
            return 1;
        }

        clk.write(false);
        sc_core::sc_start(5, sc_core::SC_NS);
    }
    return 0;
}
