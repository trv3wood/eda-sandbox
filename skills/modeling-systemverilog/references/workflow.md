# SystemVerilog 任务与验证

直接工作流：

```bash
eda-harness discover PROJECT
# 写 task.md 与 harness.yaml
# Agent 直接读写工程
eda-harness verify PROJECT
```

典型 patch 配置：

```yaml
schema_version: 1
workspace: .
checks:
  - id: lint
    category: lint
    command: [verilator, --lint-only, -f, rtl/top.f, --top-module, gpio]
  - id: compile
    category: build
    command: [make, compile]
  - id: gpio-filter-test
    category: test
    command: [make, test, TEST=gpio_filter]
    depends_on: [compile]
```

本仓库维护的专用容器环境可以通过 `scripts/eda-run` 调用；研发网、商业工具和工程原生 wrapper 直接使用项目提供的命令。Harness 不解析 RTL、不重建 filelist，也不推断验证命令。
