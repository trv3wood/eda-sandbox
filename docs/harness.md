# EDA Harness 设计与命令

`src/eda_harness` 实现两项稳定能力：

1. 发现本机和项目可用的 EDA/构建能力。
2. 以 argv、cwd 和 timeout 可重复执行验证并保存日志。

## 命令

### `discover ROOT`

检查显式配置和 PATH 中的构建、RTL、仿真、综合、形式验证、FPGA、生成和调试工具，
以及 Python 模块、SystemC/SCC/厂商 SDK、environment modules、许可证环境存在性、
本地容器镜像和工程文件信号。结果写入
`.eda-harness/discovery.json`。报告只保存许可证环境变量是否存在，不保存值。

默认标准输出以及 `.eda-harness/discovery-summary.json` 只包含计数、通过 probe 的
工具、需要用户确认的工具、当前可用 capability、SDK/module/container 摘要和限制。
完整报告仍写入 `discovery.json`；`discover --full` 可将它打印到标准输出。

安全版本 probe 通过的工具为 `usable`；可能初始化许可证的商业工具只检查路径并标为
`unverified`。报告额外按 capability 汇总候选工具。
Probe 失败的作用域是当前进程或沙盒，不能据此否定用户宿主 shell 中的工具。

### `verify ROOT --task task.md --config harness.yaml`

按配置顺序执行 checks。每个 check 的完整输出保存在
`.eda-harness/logs/<id>.log`，汇总写入 `.eda-harness/report.json`。

- 可执行文件不存在：`blocked`。
- 命令非零或超时：`failed`。
- 依赖没有通过：`blocked`。
- required 失败使总体失败；没有失败但存在 required blocked 时总体 blocked。
- optional 结果不改变总体状态。

### `verify-cycle ROOT --config cycle-harness.yaml`

用于 RTL 到 Cycle-SystemC 的强差分验收，不读取 `task.md`。它校验结构化 EDA 证据和
模型独立性，从新运行目录执行 reference/model build 与 SystemC unit/elaboration，随后
用同一 stimulus 完成定向、至少 10×1,000-cycle 公开随机和至少 10×1,000-cycle 运行时
新种子差分。

Reference 和 model 必须输出标准 JSONL trace。Harness 自己校验连续 sample、采样
phase、observable 全集、位宽、二态值及逐样点一致性，并核对 stimulus 未被两侧修改。
结果写入 `.eda-harness/cycle-report.json`，运行产物位于
`.eda-harness/cycle-runs/`。完整 schema 见
`skills/cycle-systemc-modeling/references/cycle-harness.md`。

### `status ROOT`

读取最近的 discovery、普通 report 和 cycle report，不执行命令。

## 配置接口

```yaml
schema_version: 1
workspace: .
checks:
  - id: lint
    category: lint
    command: [verilator, --lint-only, -f, rtl/top.f]
    cwd: .
    timeout_seconds: 1800
    required: true
    depends_on: []
```

category 可为 `syntax`、`lint`、`build`、`test`、`differential` 或 `custom`。
命令必须是非空 argv 数组，不经 shell；cwd 必须位于 workspace 内。依赖只能指向
前面已经声明的 check，从而保持执行顺序确定。

## 安全和边界

- Harness 不自动选择后端、拉取镜像、运行许可证作业或修改工程源码。
- 报告不记录完整环境，避免把密钥和许可证地址写入任务目录。
- `scripts/eda-run` 只处理环境路由；实际项目参数由 skill/Agent 根据任务决定。
