# 开源 EDA 沙盒

本仓库为相同的 EDA 实验提供了几个小型容器环境：

- `eda-fast`：Ubuntu 24.04，用于快速开发和发行版软件包。
- `eda-scc`：Ubuntu 24.04，包含与 `eda-fast` 相同的快速工具链，外加已编译的 SCC/SystemC 前缀。
- `eda-agent`：Ubuntu 24.04，基于 eda-scc，包含用于智能体（agent）使用的文档处理 Python 库。
- `eda-enterprise`：Rocky Linux 8，用于 RHEL 系列兼容性检查。

容器使用预构建的 conda-forge 软件包来提供 Surelog 和 UHDM，而非在镜像中编译这些 C++ 项目。主 `eda` 环境使用 Python 3.10。Surelog 1.84 目前仅有 Python 3.11/3.12 的 Linux conda 构建版本，因此安装在独立的环境中，通过 `surelog` 包装器暴露使用。商业 EDA 工具被有意排除在外。

## 构建与运行

使用 Docker：

```bash
docker compose build
docker compose run --rm eda-fast bash scripts/regress.sh
docker compose run --rm eda-scc bash scripts/regress.sh
docker compose run --rm eda-enterprise bash scripts/regress.sh
```

使用 Podman（本环境推荐）：

```bash
podman-compose build
podman-compose run --rm eda-fast bash scripts/regress.sh
podman-compose run --rm eda-scc bash scripts/regress.sh
podman-compose run --rm eda-enterprise bash scripts/regress.sh
```

`eda-fast` 目标仅安装预构建软件包。`eda-scc` 目标额外增加了一个构建阶段，该阶段会检出固定版本的 SCC 发行版 `2026.05` 并使用 Conan 和 CMake 进行构建，与 SCC 官方的 Ubuntu 24.04 测试镜像保持一致。
仅在需要 SCC 时才构建它：

```bash
podman-compose build eda-fast
podman-compose build eda-scc
```

如果只需要构建镜像，可以直接使用 Podman 的原生构建命令。这不需要 Docker 兼容的 API socket：

```bash
podman build -f Dockerfile.ubuntu -t eda-fast:local .
podman build -f Dockerfile.ubuntu --target scc -t eda-scc:local .
podman build -f Dockerfile.rocky8 -t eda-enterprise:local .
podman run --rm -it -v "$PWD:/workspace" eda-fast
podman run --rm -it -v "$PWD:/workspace" eda-scc
podman run --rm -it -v "$PWD:/workspace" eda-enterprise
```

当 `podman compose` 报告它正在执行 `docker-compose` 时，请避免使用它。该提供者需要运行中的无根 Podman API socket，是诸如 `failed to connect to the docker API` 等错误的根源。

如果确实希望继续使用该提供者，请先启动用户 socket，然后重试：

```bash
systemctl --user enable --now podman.socket
podman compose build
```

项目文件应放置在 `workspace/` 目录中。宿主机目录挂载在 `/workspace`，因此源代码的修改在容器退出后仍然保留。

conda-forge 环境包含 Python 3.10、CMake、Ninja、UHDM 库、Verilator 和 Yosys。独立的 Surelog 环境仅包含 Surelog 1.84 和 Python 3.11，专门用于预构建的 Surelog 软件包。请勿安装 PyPI 上无关的名为 `surelog` 的软件包；容器使用的是 CHIPS Alliance 的 Surelog 可执行文件。

## 适用范围

这是一个容器化的开源工具链冒烟测试环境，而非虚拟机。它不模拟宿主机内核、CentOS 7 用户空间、LSF、网络挂载、许可证服务器或 VCS、Verdi 等商业工具。最终的 CentOS 7 兼容性检查应使用真实的传统环境。

## SystemC TLM 技能基准测试

离线安全的 A/B 基准测试规划器、架构门控、评分聚合和报告工作流文档请参见
[`docs/systemc-tlm-benchmark.md`](docs/systemc-tlm-benchmark.md)。
两个命令行接口的职责、命令、产物和当前限制文档请参见
[`docs/cli-reference.md`](docs/cli-reference.md)。
