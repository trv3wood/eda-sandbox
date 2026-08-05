---
name: modeling-systemverilog
description: Implement and verify SystemVerilog interfaces, hierarchy, modules, and bounded RTL changes directly from a task, specifications, register maps, existing RTL, and available EDA tools. Use for new RTL or modifications that need syntax, elaboration, structural, lint, compile, and simulation validation without an intermediate handoff or generated scaffold.
---

# SystemVerilog 直接建模

让 Agent 直接理解任务并修改 RTL；让 harness 负责工具发现、任务基线、改动范围和验证结果。不要创建 canonical graph、RTL handoff、审批文件、隔离生成树或 edits.json。

## 工作流

1. 阅读 `references/workflow.md`，检查用户任务、规格、寄存器描述、filelist、宏/include、现有 RTL/DV 和原生构建命令。
2. 把目标、约束、兼容行为、允许修改范围和验收条件整理到 `task.md`。冲突或缺失语义必须引用原始位置向用户确认。
3. 运行 `eda-harness discover PROJECT`。根据工程实际选择 pyslang、Verilator、Surelog/UHDM、VCS 或项目原生工具，harness 不会自动替你选路。
4. 编写 `harness.yaml`，在首个代码修改前运行 `eda-harness snapshot PROJECT`。
5. 直接修改原工程。使用 AST/CST 或 elaborated 数据导航复杂结构；不得用 regex 代替失败的 SystemVerilog parser。
6. 迭代运行局部检查，最后用 `eda-harness verify PROJECT` 检查越界变化以及 syntax、elaboration、lint、compile 和 simulation。

## RTL 原则

- 尊重工程原有 filelist 顺序、`-f/-F` 语义、working directory、include 路径、defines 和代码生成边界。
- 修改已有 RTL 时先定位明确的语法节点和影响面；生成文件应通过工程原生 generator 更新，不手改派生产物。
- 接口、层次、时序、复位、寄存器副作用和验证 observable 只能来自任务与源资料，不能由相似命名猜测。
- 对 patch 任务在 `allowed_changes` 中收紧目录或文件；harness 的基线 diff 负责发现范围外新增、修改和删除。
- 工具缺失报告为 `blocked`，不能当作通过；不得削弱 lint、仿真或用户验收条件来获得绿色结果。

## 工具原则

- pyslang 用于源码级语法和位置；VCS/UHDM/Surelog 用于 elaboration 或结构问题；工具视图失败必须如实报告。
- 优先调用项目已有 lint/compile/simulation 命令，并将最终 argv 写进 `harness.yaml`。
- 不自动启动长时间商业 EDA 作业、下载大型镜像或改动原工程以外的系统配置。
