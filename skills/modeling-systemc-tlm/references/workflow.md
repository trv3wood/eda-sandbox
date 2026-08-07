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
# 语义抽取与证据（见下）：EDA 工具交叉验证理解，写 docs/EVIDENCE.md + docs/MODEL_ARCH.md
# Agent 直接实现模型并按需运行局部检查
eda-harness verify PROJECT --task task.md --config harness.yaml
```

## 语义抽取与证据阶段

在实现前/并行，对每个关键语义决策完成散步：

1. **定位**: RTL 源（`file:line`）+ spec 章节
2. **EDA 工具交叉验证**： 至少用一种工具验证理解（映射见 `tooling.md`）——仿真探针
  （`$display`/XMR/事务日志）、波形（FSDB/VPD + Verdi）、UHDM 查询。只读代码不算验证。
3. **记录**：写证据条目，汇总到项目 `docs/EVIDENCE.md`

完成后写两份文档：

- **`docs/EVIDENCE.md`** -- 每条决策的模板：

```
### <语义名>
- RTL 依据：`<file>.v:<line>` (<一句话>)
- spec 依据：<章节>
- EDA 证据：<场景>/<信号>/<观察值>；复现：<命令>
- 模型复刻：`<model 源码：行>`
- 验证：<单测 + 对拍场景>
```

- **`docs/MODEL_ARCH.md`(实现)**：function 切分、TLM 接口、数据流，映射到 RTL 模块

harness.yaml 可选加一条 `docs` check (category: `custom`) 让“两份文档存在”机器可查。

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
