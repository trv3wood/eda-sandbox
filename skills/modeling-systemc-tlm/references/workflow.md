# 直接建模工作流

项目本身是工作单元，harness 只增加三个轻量文件/目录：

```text
task.md
harness.yaml
.eda-harness/{discovery,baseline,report}.json
.eda-harness/logs/
```

推荐顺序：

```bash
eda-harness discover PROJECT
# 写 task.md 和 harness.yaml
eda-harness snapshot PROJECT --task task.md --config harness.yaml
# Agent 直接实现模型并按需运行局部检查
eda-harness verify PROJECT --task task.md --config harness.yaml
```

`task.md` 面向用户和 Agent，可自由组织，但应忠实包含目标、输入、允许范围、明确约束和验收条件。`harness.yaml` 只表达机器能验证的内容：

```yaml
schema_version: 1
workspace: .
allowed_changes: [model/**, tests/**]
checks:
  - id: configure
    category: build
    command: [cmake, -S, model, -B, model/build]
  - id: build
    category: build
    command: [cmake, --build, model/build, --parallel]
    depends_on: [configure]
  - id: test
    category: test
    command: [ctest, --test-dir, model/build, --output-on-failure]
    depends_on: [build]
```

命令必须是 argv 数组，`cwd` 相对 workspace，默认超时 1800 秒且 `required: true`。缺少 required 工具时总体为 `blocked`；命令失败或修改越界时总体为 `failed`。

Snapshot 记录任务开始时的实际文件内容，所以已有脏改动不会误算成本次变化。它锁定 `allowed_changes`；需要扩大范围时，应停止并明确开始新的任务基线，不能静默放宽配置。
