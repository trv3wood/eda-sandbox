# 任务能力与候选工具

根据任务选择最小能力集合；候选项不是等价性声明。

| 能力 | 常见候选工具 | 应向用户确认的项目输入 |
|---|---|---|
| SystemVerilog parse/lint | slang、Verilator、Surelog | language version、include、defines、filelist |
| 编译/elaboration/仿真 | VCS、Xcelium/xrun、Questa/vsim、Riviera、DSim、iverilog | top、filelist、working directory、test name |
| UHDM 导航 | Surelog、uhdm-lint、uhdm-hier、eda-uhdm | top、数据库位置、生成命令 |
| SystemC/TLM | C++、CMake、CTest、SystemC、minres-SCC、Conan | SDK 根目录、CMake package、C++ standard |
| ASIC 综合 | Yosys、Design Compiler、Genus | liberty、constraints、top、原生命令 |
| lint/CDC/RDC | Verilator、slang、SpyGlass | waiver、rule deck、clock/reset 约束 |
| 形式验证 | SymbiYosys、yosys-smtbmc、Boolector、Z3、JasperGold、VC Formal | property set、assumption、engine、timeout |
| FPGA | Vivado、Quartus | part、project/Tcl、constraints、top |
| 寄存器生成 | 项目 regtool、PeakRDL 或内部 generator | source of truth、生成目标、一致性命令 |
| 波形调试 | Verdi、DVE、GTKWave | dump 格式、层次、仿真生成命令 |
| 工程编排 | Make、Ninja、Bazel、FuseSoC、CMake | 原生 target、工作目录、环境初始化 |

商业工具的命令存在只代表 `unverified`。许可证、feature、编译选项和当前设计兼容性必须通过用户环境与项目命令确认。
