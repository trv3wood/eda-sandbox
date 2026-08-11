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
3. slang、yosys、verilator 等开源工具的 syntax/lint/compile 检查。
4. UHDM/Surelog 仅在已有 UHDM 输入、需要开源可移植查询，或作为额外交叉检查时使用。

首次商业命令在用户允许范围内执行。命令失败时记录实际后端、日志和未覆盖能力；不得
静默切换到覆盖更弱的后端。
