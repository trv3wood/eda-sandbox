---
name: cycle-systemc-modeling
description: Build and verify an independent, input-driven cycle-accurate SystemC model from RTL. Use when reset, state, FIFO/RAM latency, handshake, arbitration, protocol timing, or per-cycle outputs must match RTL; reject trace predictors, runner-embedded DUT behavior, absolute-cycle specialization, and loosely timed TLM models.
---

# Cycle-SystemC 建模

这是角色编排与工程纪律，不定义项目专用验证格式。源文件、依赖、构建和公开验证入口由项目
`CMakeLists.txt` 与 CTest 维护；`.eda-harness` 只保存 `$eda-tool-assistant` 的工具发现结果。

## Git 隔离与冻结

大型设计的各角色必须在隔离的 Git 工作目录中工作；agent 可以在自己的阶段分支提交，但不得
直接合并或改写集成分支。协调者在完成规定门禁后，创建冻结 tag 并负责将阶段结果集成。先运行
`git worktree --help`（或等价能力探测）选择下列模式，不得假定目标 Git 版本支持 worktree：

1. **`git worktree` 模式**：支持 `git worktree` 时，以同一仓库的独立 worktree 承载各角色；
   每个 worktree 检出独立阶段分支，禁止两个角色共用目录或分支。
2. **旧 Git 回退模式**：不支持 `git worktree` 时，从同一只读基线建立每个
   角色的独立 clone，并在 clone 内创建独立阶段分支。不得通过复制未提交目录、共享 `.git` 或
   复用构建目录模拟隔离。

Harness、Architecture 与每次获准返工的 Model 阶段完成后，协调者只在该阶段门禁通过时创建
不可变冻结 tag（例如 `cycle/harness-frozen`、`cycle/architecture-frozen`、
`cycle/model-frozen`）。下游角色从指定冻结 tag 新建自己的阶段分支；只读角色检出该 tag 后不
产生提交。Diagnosis 仅提交或传递定位结果，Acceptance 只在独立 checkout/clone 中执行隐藏
验证；二者均不得修改候选模型。所有 build、trace 与差分产物按角色和阶段分目录，不能在不同
工作目录间共享可写中间产物。

## Agent 角色分工
由不同 agent 顺序完成下列角色；不得让同一 agent 兼任互相制约的角色。各阶段只交付代码、
配置、机器结果和 agent 交接消息，不写 evidence、architecture、coverage 或迭代说明文档。

1. **Harness Agent**：恢复 RTL closure，建立 reference、BFM、公开 stimulus、trace comparator
   和 CTest 公开门禁；调用 `$eda-tool-assistant` 发现当前任务所需工具。先证明 RTL baseline
   可复现，再冻结 oracle、stimulus 和公开测试。它不得创建或实现 SystemC DUT，也不得依据
   候选模型调整 reference。
2. **Architecture Agent**：只读冻结的 harness/RTL，分解大型设计并初始化可编译 SystemC/C++
   工程。CDC、FIFO/RAM、握手和关键 FSM 按时序边界建模；纯组合算法可按功能域合并。它负责
   CMake、模块接口、端口、clock/reset process、独立 runner 空壳和模块测试目标，但不得实现
   DUT 行为。Runner 只能解析、驱动、clock/delta 和序列化。完成后冻结工程结构和接口。
3. **Model Agent**：使用全新会话，只读冻结 harness/RTL 和工程接口，只实现 DUT 与模块单元
   测试。它可以编译并运行内部测试，但不得运行 RTL 差分、读取 reference trace 或根据首个
   失配拟合行为。DUT 只能由输入、配置和显式状态推导；禁止 seed、scenario、sample、绝对
   cycle、reference trace 或测试 payload 特化。
4. **Diagnosis Agent**：Model Agent 停止后运行项目 CTest 公开差分，结合 RTL 定位首个失配的
   状态、NBA、CDC、RAM 或协议根因，只反馈实现缺陷，不直接修改模型。行为缺陷退回 Model
   Agent；模块接口或边界缺陷退回 Architecture Agent。公开迭代只使用冻结的公开测试。
5. **Acceptance Agent**：公开差分通过且模型冻结后，用全新会话复核边界，再使用 Model Agent
   不可见的 generator/seeds 做隐藏 payload、地址、timing、ACK/NACK、stall/stretch、reset
   和 idle-shift metamorphic 差分。

Model Agent 不得修改冻结 harness；Diagnosis Agent 不得修改候选模型；Acceptance Agent 不把
隐藏失败反馈给 Architecture/Model Agent继续拟合。公开 CTest 通过仅称 `regression-passed`；
独立性、隐藏与 metamorphic 差分全部通过后才称 `cycle-equivalent`。

旧 `cycle-harness.yaml` 与 `eda-harness verify-cycle` 仅为兼容入口，已弃用；新项目不得生成或
依赖它们。
