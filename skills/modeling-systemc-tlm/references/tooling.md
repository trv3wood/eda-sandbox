# EDA 与 SystemC 工具使用

先运行 `eda-harness discover PROJECT`。它检查显式 toolchain 配置、PATH、Python 模块、SDK 环境、容器引擎和工程构建信号，但不会拉镜像、启动 elaboration 或验证许可证可用性。

`scripts/eda-run` 的角色保持简单：

- `agent`：本地 Python/uv 工具。
- `vcs`：研发网宿主机 VCS，继承当前许可证环境。
- `uhdm`：Surelog/UHDM 和直接 Python 查询。
- `rtl`：RTL lint、仿真和差分工具。
- `scc`：SystemC/minres-SCC 构建与测试。
- `rocky`：Rocky Linux 8 兼容性环境。

示例：

```bash
scripts/eda-run --work WORK vcs vcs -f PROJECT/rtl/top.f -top TOP
scripts/eda-run --work WORK uhdm eda-uhdm run \
  /workspace/design.uhdm /workspace/query.py --output-dir /workspace/query-output -- TOP
scripts/eda-run --work WORK scc \
  cmake -S /workspace/PROJECT/model -B /workspace/PROJECT/model/build
```

把最终选定的可重复命令直接写进 `harness.yaml`。工具缺失是 `blocked`，语法、编译、测试或比较失败是 `failed`。商业工具、长任务和大型镜像操作仍由用户明确启动。
