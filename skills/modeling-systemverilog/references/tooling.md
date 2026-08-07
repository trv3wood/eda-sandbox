# SystemVerilog 工具后端选择

`eda-harness discover PROJECT` 只盘点候选工具、环境变量和工程线索，不能证明许可证、
项目 wrapper 或商业数据库接口可用。工具选择由任务所需能力与项目既有流程决定，不按
厂商名称猜测。

在 `task.md` 记录：

```text
工具后端：<工程原生命令/厂商与产品>
覆盖能力：<syntax/elaboration/lint/simulation/waveform/query>
选择依据：<许可证、既有脚本、目标平台>
复现命令：<最终 argv 或 wrapper>
不可替代项：<例如完整 elaboration、特定 lint rule>
允许降级：<明确列出；未列出即不允许>
```

优先级：

1. 复用项目已有的 filelist、defines、编译/elaboration、仿真和 lint 命令。
2. 使用已有许可证的 VCS、Xcelium 或 Questa 完成语义编译、elaboration 与仿真；用
   项目既有的 SpyGlass、Jasper/相关 lint 流或 Questa Lint 完成质量检查。
3. UHDM/Surelog 仅在已有 UHDM 输入、需要开源可移植查询，或作为额外交叉检查时使用。
   商业工具的内部数据库不应假定能导入、导出或替代 UHDM。
4. verible、verilator 等开源工具只能作为它们实际运行的 syntax/lint/compile 检查。

Rocky 8 无容器环境下，不能使用 `eda-uhdm` 不构成阻塞；只要项目已有商业命令覆盖任务
验收，直接使用这些命令。若验收明确依赖 `.uhdm`、UHDM Python API 或既有 UHDM 查询脚本，
则应报告为独立需求，向用户确认二进制分发或脚本改写，不能用商业仿真器假装等价。

首次商业命令在用户允许范围内执行。命令失败时记录实际后端、日志和未覆盖能力；不得
静默切换到覆盖更弱的后端。
