---
name: modeling-systemc-tlm
description: Implement and verify loosely timed SystemC TLM-2.0 models directly from a modeling task, specifications, register maps, RTL, and available EDA tools. Use for SystemC/TLM model creation, refinement, compilation, contract testing, and RTL differential validation without an intermediate architecture DSL or generated scaffold.
---

# SystemC/TLM 直接建模

让 Agent 负责理解任务和实现模型，让程序只负责环境发现、改动审计和验证。不要创建证据图、八类合同、handoff、审批文件或生成器输入。

## 工作流

1. 阅读 `references/workflow.md` 和 `references/tooling.md`，检查用户任务、规格、寄存器表、RTL、测试和已有构建系统。
2. 将用户目标、范围、约束和验收条件忠实整理到 `task.md`；不确定的设计语义必须回到原始资料或询问用户，不得自行发明。
3. 运行 `eda-harness discover PROJECT`，根据报告选择本地、研发网或容器工具。报告只是建议，不能替代任务相关判断。
   缺少任务所需工具或激活信息时，使用 `eda-tool-assistant` 向用户确认并准备外置配置。
4. 若任务需要改代码或运行多项验收，建立一次最小 `harness.yaml`：只声明允许修改范围和最终选定的项目验证命令；然后在首个代码改动前运行 `eda-harness snapshot PROJECT`。只做环境盘点时不需要它。
5. **语义抽取与证据**:对每个关键语义决策（寄存器副作用、影子配置、寻址、仲裁...），定位 RTL 源 (`file:line`) 与spec 章节，并用 EDA 工具交叉验证理解 (见 `references/tooling.md` 的工具映射)--仿真弹奏、波形或查询至少用一种，**不能只靠读代码**。完成架构与功能推理后，在项目 `docs/` 写两份审计文档：
   - `EVIDENCE.md` ：juece -> RTL 依据 -> EDA 工具证据 -> 模型复刻位置 -> 复现命令；
   - `MODEL_ARCH.md` (实现)：function 切分、接口、数据流、映射到 RTL 模块。
   证据不足的决策不得宣称已理解。
6. 实现或修改模型和测试
7. 迭代运行目标检查；完成时运行 `(.venv) eda-harness verify PROJECT`，分别报告通过、失败和因工具缺失而阻塞的层级。

## 建模原则

- 默认使用 loosely timed TLM-2.0、`b_transport` 和 delay annotation；只有任务明确要求时才提高时序精度。
- 按事务和功能责任划分组件，不照搬 RTL 模块、信号、握手或流水寄存器。
- 明确实现任务所涉及的寄存器副作用、队列、仲裁、背压、异常、中断、完成条件和可观察时延。
- 每个关键语义决策必须同时具备 **RTL/规格依据** 与 **EDA 工具验证证据**（见工作流第 5 步）；
   `docs/EVIDENCE.md`（证据）与 `docs/MODEL_ARCH.md`（实现）是审计物。
- 将 minres-SCC 依赖隔离在 adapter 后，核心模型尽可能可用标准 SystemC 测试。
- 测试通过公开事务接口驱动模型。没有共享 stimulus 与 normalization/comparison adapter 时，不得宣称 RTL 等价。
- 不为通过验证而削弱用户已有测试或验收条件。

## 工具策略

- `scripts/eda-run` 只用于本仓库维护的 UHDM、RTL、SCC 等专用环境。商业工具和工程原生命令直接按项目既有方式调用。
- UHDM 查询使用官方 Python binding 和薄 `eda-uhdm` runner，查询结果用于导航和交叉检查，不替代 Spec/RTL 原文。
- 不自动拉取大型镜像、重编 minres-SCC 或启动长时间商业 EDA 作业；给出准确命令让用户决定。
