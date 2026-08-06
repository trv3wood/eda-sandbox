# 安全配置方法

把机器特定配置放在仓库外，例如：

```bash
mkdir -p "$HOME/Work/my-project"
cp env/toolchain.env.example "$HOME/Work/my-project/toolchain.env"
export EDA_HARNESS_TOOLCHAIN_CONFIG="$HOME/Work/my-project/toolchain.env"
```

配置文件只接受 harness 注册表中的 `EDA_TOOL_*` 和 SDK 路径变量：

```text
EDA_TOOL_VCS=/tools/vcs/bin/vcs
EDA_TOOL_XRUN=/tools/xcelium/bin/xrun
EDA_TOOL_VSIM=/tools/questa/bin/vsim
EDA_TOOL_VERILATOR=/usr/bin/verilator
EDA_SYSTEMC_HOME=/tools/systemc
EDA_SCC_HOME=/tools/scc
```

每个 `EDA_TOOL_*` 值是单个可执行文件路径，不是 shell 命令，也不附带参数。许可证环境由用户或标准环境脚本管理，不写进该文件。

## Environment Modules

Harness 只报告 `MODULESHOME`、`MODULEPATH`、`LMOD_CMD` 和已加载 module 数量，不自动执行 `module avail/load`。优先让用户进入标准激活 shell：

```bash
module load <用户确认的模块>
eda-harness discover PROJECT
```

只有用户明确要求长期 wrapper 时，才在 `~/Work/<project>/bin/` 创建任务专用脚本；脚本只加载用户确认的 module 并 `exec` 工具，不嵌入许可证或凭据。

## Codex 沙盒与宿主机差异

`probe_status: failed` 只表示当前执行环境中的轻量命令失败。容器 runtime、用户 socket、网络盘和许可证环境尤其可能被沙盒隔离。若用户在宿主 shell 中确认厂商工具版本成功：

- 把宿主工具标为 `user-reported`，不要标为 unavailable。
- 保留当前 Codex 环境的失败日志，说明自动执行可能需要授权或 `scripts/eda-run` 路由。
- 需要运行镜像或商业任务时再请求用户批准，不以版本成功推断实际任务可用。

## 验证层级

1. 路径或 PATH 命中：`available`。
2. 无副作用版本 probe 通过：`usable`。
3. 商业工具由用户确认环境已激活：`user-reported`，仍不是自动验证。
4. 项目 lint/compile/test 命令成功：`task-validated`。

把第四层命令写入 `harness.yaml`，而不是添加新的全局自动路由规则。
