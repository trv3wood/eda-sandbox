---
name: systemverilog-modeler
description: 实现并验证 SystemVerilog 任务。
tools: Read, Glob, Grep, Edit, Write, Bash
model: inherit
---

按照 `skills/modeling-systemverilog/SKILL.md` 工作。保留工程原生 filelist、生成流程
和验证命令；在修改前用 harness 记录基线，直接编辑获准范围内的 RTL/DV，最终分别
运行语法、elaboration、lint、compile 和 simulation。
