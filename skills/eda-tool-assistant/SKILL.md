---
name: eda-tool-assistant
description: Discover, confirm, and configure EDA tool environments for RTL, SystemC/TLM, simulation, lint, synthesis, formal verification, FPGA, register generation, and waveform-debug tasks. Use when Codex needs to inventory available EDA tools, diagnose missing tool access, ask the user about commercial or remote environments, prepare an external toolchain.env, or turn discovered project commands into reproducible harness checks.
---

# EDA 工具环境助手

发现机器能安全确认的事实，向用户询问机器无法知道的环境信息，并生成最小、外置、可验证的工具配置。

## 工作流

1. 判断当前任务需要的能力，而不是要求所有 EDA 工具都可用。需要工具类别映射时阅读 `references/tool-catalog.md`。
2. 运行 `eda-harness discover PROJECT`，优先读取 `.eda-harness/discovery-summary.json`；只有诊断具体失败时才读取完整的 `discovery.json`。
3. 将结果区分为：
   - `usable`：安全版本 probe 已通过。
   - `unverified`：发现二进制，但为避免许可证副作用没有运行，或 probe 未证明任务可用。
   - `unavailable`：当前进程找不到工具。
   - `task-validated`：只有真实的项目 lint/compile/test 成功后才能使用此称呼。
4. 只针对当前任务缺少的能力询问用户。把已发现的候选工具放进问题，优先询问：研发网/远程节点、绝对路径、`module load` 名称、内部 wrapper、容器镜像、SDK 根目录、filelist/top 和项目原生验证命令。
5. 不询问或记录许可证服务器地址、token、密码或密钥；只确认相应环境是否已经由用户配置。
6. 按 `references/configuration.md` 在 `~/Work/<project>/toolchain.env` 准备白名单配置。项目仓库只记录通用示例，不写公司路径。
7. 在用户已激活的环境中重新运行 discover。商业工具仅做用户确认过的轻量 probe；长时间 elaboration、仿真、镜像拉取和安装动作必须先征得用户同意。
8. 将最终选定的项目命令以 argv 数组写入 `harness.yaml`，运行实际检查后更新能力结论。

## 询问策略

- 不要泛泛地问“有哪些 EDA 工具”。先说明任务缺少的能力以及本机已经找到的替代项。
- 每轮合并一至三个相关问题，例如 simulator + 激活方式 + 原生测试命令。
- 用户不知道路径时，建议他们在目标环境执行 `command -v TOOL`、`module list` 或内部标准环境脚本；不要自行递归扫描 `/opt`、网络盘或用户目录。
- 用户报告工具存在但当前不可访问时，将其标为 `user-reported`，不要伪装成 discover 已验证。
- Probe 失败只描述当前 Codex 进程或沙盒。若用户在宿主 shell 的版本命令成功，将宿主状态标为 `user-reported`，同时保留“Codex 环境可能需要授权或不同路由”的限制。

## 输出

给出精简能力矩阵、尚缺信息、建议的非敏感配置项、复现命令和验证限制。配置发生变化后重新 discover；只有真实项目命令通过后才宣布环境满足任务。
