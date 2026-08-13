---
name: modeling-systemverilog
description: Implement and verify SystemVerilog interfaces, hierarchy, modules, and bounded RTL changes from a task, specifications, register maps, existing RTL, and available EDA tools. Use for new RTL or modifications that need syntax, elaboration, structural, lint, compile, and simulation validation.
---

# SystemVerilog 编码增强

让 Agent 直接理解任务并编写、修改 RTL；让 harness 负责工具发现、任务基线、改动范围和验证结果。

## 工作流

1. 阅读 `references/workflow.md` 和 `references/tooling.md`，检查用户任务、规格、寄存器描述、filelist、宏/include、现有 RTL/DV 和原生构建命令。
2. 把目标、约束、兼容行为、允许修改范围和验收条件整理到 `task.md`。冲突或缺失语义必须引用原始位置向用户确认。
3. 运行 `eda-harness discover PROJECT`。按 `references/tooling.md` 的能力矩阵选择工程原生、商业或开源工具，并在 `task.md` 固化后端、命令、理由及禁止降级项；harness 不会自动替你选路。
   缺少任务所需工具或激活信息时，使用 `eda-tool-assistant` 向用户确认并准备外置配置。
4. 若任务需要改代码或运行多项验收，建立一次最小 `harness.yaml`，记录最终选定的项目验证命令。只做环境盘点时不需要它。
5. 直接修改原工程。使用 AST/CST 或 elaborated 数据导航复杂结构。
6. 迭代运行局部检查，最后用 `eda-harness verify PROJECT` 检查越界变化以及 syntax、elaboration、lint、compile 和 simulation。

## RTL 原则

- 尊重工程原有 filelist 顺序、`-f/-F` 语义、working directory、include 路径、defines 和代码生成边界。
- 修改已有 RTL 时先定位明确的语法节点和影响面；生成文件应通过工程原生 generator 更新，不手改派生产物。
- 接口、层次、时序、复位、寄存器副作用和验证 observable 只能来自任务与源资料，不能由相似命名猜测。
- 工具缺失报告为 `blocked`，不能当作通过；不得削弱 lint、仿真或用户验收条件来获得绿色结果。

## 工具原则

- 工具视图失败必须如实报告。
- 优先调用项目已有 lint/compile/simulation 命令。商业工具可覆盖的编译、elaboration、仿真或 lint 不以 UHDM 为前置条件；UHDM 仅是可选的开源查询后端。
- 不得将商业工具失败静默降级为 UHDM、verible、verilator 或文本搜索；这些工具只能声明它们实际覆盖的检查。需要可重复验收时，将最终 argv 和选定后端记录在任务的 `harness.yaml` 与 `task.md` 中。
- 不自动启动长时间商业 EDA 作业、下载大型镜像或改动原工程以外的系统配置。
