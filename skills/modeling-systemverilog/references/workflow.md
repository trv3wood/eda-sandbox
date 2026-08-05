# SystemVerilog 任务与验证

直接工作流：

```bash
eda-harness discover PROJECT
# 写 task.md 与 harness.yaml
eda-harness snapshot PROJECT
# Agent 直接读写工程
eda-harness verify PROJECT
```

典型 patch 配置：

```yaml
schema_version: 1
workspace: .
allowed_changes:
  - rtl/gpio.sv
  - dv/gpio_filter_test.sv
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

如果工程需要研发网或容器环境，命令数组可以直接以 `scripts/eda-run` 开头。Harness 不解析 RTL、不重建 filelist，也不推断验证命令。

Snapshot 记录修改前的已有 dirty state；最终 integrity gate 只检查 snapshot 后的增量。新增、删除、重命名和修改都必须匹配 snapshot 时锁定的 `allowed_changes`。
