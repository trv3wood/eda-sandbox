# EDA Harness 设计与命令

`src/eda_harness` 不生成 HDL/SystemC，也不解释设计语义。它只实现四项稳定能力：

1. 发现本机和项目可用的 EDA/构建能力。
2. 在任务修改前记录实际文件基线。
3. 检查本次增量是否越出声明范围。
4. 以 argv、cwd 和 timeout 可重复执行验证并保存日志。

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
`unverified`。报告额外按 capability 汇总候选工具。需要用户环境信息时由
`eda-tool-assistant` 提问，discover 不执行 `module avail/load` 或目录扫描。
Probe 失败的作用域是当前进程或沙盒，不能据此否定用户宿主 shell 中的工具。

### `snapshot ROOT --task task.md --config harness.yaml`

校验配置并把 workspace 当前内容写入 `.eda-harness/baseline.json`。Git 工程使用
tracked 与未忽略 untracked 文件；非 Git 工程使用递归摘要。已有 snapshot 不会被
隐式覆盖。

### `verify ROOT --task task.md --config harness.yaml`

先执行内置 integrity gate，再按配置顺序执行 checks。每个 check 的完整输出保存在
`.eda-harness/logs/<id>.log`，汇总写入 `.eda-harness/report.json`。

- 可执行文件不存在：`blocked`。
- 命令非零或超时：`failed`。
- 依赖没有通过：`blocked`。
- required 失败使总体失败；没有失败但存在 required blocked 时总体 blocked。
- optional 结果不改变总体状态。

### `status ROOT`

读取最近的 discovery、baseline 和 report，不执行命令。

## 配置接口

```yaml
schema_version: 1
workspace: .
allowed_changes: [rtl/**, dv/**]
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
- Snapshot 锁定允许路径，后续修改 harness.yaml 不能扩大本次任务范围。
- 报告不记录完整环境，避免把密钥和许可证地址写入任务目录。
- `scripts/eda-run` 只处理环境路由；实际项目参数由 skill/Agent 根据任务决定。
