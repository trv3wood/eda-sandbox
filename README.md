# 开源 EDA 沙盒

Ubuntu 24.04 工具链按职责拆成四个独立镜像：

- `eda-agent`：工作流、benchmark 和离线 JSON 查询；不含 EDA 编译器。
- `eda-uhdm`：Surelog 和 UHDM Python binding，负责语义数据库生成与查询。
- `eda-rtl`：Verilator 和 Yosys。
- `eda-scc`：SystemC/SCC 编译与验证；Conan 缓存只存在于 builder。
- `eda-enterprise`：Rocky Linux 8，用于 RHEL 系列兼容性检查。

Ubuntu agent 使用发行版 Python 3.12；UHDM 镜像使用同版本的 conda-forge
`surelog`、`uhdm` 和 Python binding 二进制包，不编译 Surelog。商业 EDA
工具有意排除。

## 构建与运行

使用 Docker：

```bash
docker compose build eda-agent eda-rtl
docker compose run --rm eda-agent scripts/regress.sh
docker compose run --rm eda-rtl scripts/regress.sh
```

使用 Podman（本环境推荐）：

```bash
podman-compose build eda-agent eda-rtl
podman-compose run --rm eda-agent scripts/regress.sh
podman-compose run --rm eda-rtl scripts/regress.sh
```

SCC 构建耗时较长，通常从 GitHub Container Registry 拉取 CI 产物；它仅在
版本 tag 或手工 workflow dispatch 时构建。Surelog/UHDM 和 RTL 镜像只解析
二进制包。本地只构建当前需要的轻量目标：

```bash
podman-compose build eda-agent
podman-compose build eda-rtl
```

如果只需要构建镜像，可以直接使用 Podman 的原生构建命令。这不需要 Docker 兼容的 API socket：

```bash
podman build -f Dockerfile.ubuntu --target agent -t eda-agent:local .
podman build -f Dockerfile.ubuntu --target rtl-tools -t eda-rtl:local .
podman build -f Dockerfile.rocky8 -t eda-enterprise:local .
podman run --rm -it -v "$PWD:/workspace" eda-agent:local
podman run --rm -it -v "$PWD:/workspace" eda-rtl:local
podman run --rm -it -v "$PWD:/workspace" eda-enterprise
```

当 `podman compose` 报告它正在执行 `docker-compose` 时，请避免使用它。该提供者需要运行中的无根 Podman API socket，是诸如 `failed to connect to the docker API` 等错误的根源。

如果确实希望继续使用该提供者，请先启动用户 socket，然后重试：

```bash
systemctl --user enable --now podman.socket
podman compose build
```

项目文件应放置在 `workspace/` 目录中。宿主机目录挂载在 `/workspace`，因此源代码的修改在容器退出后仍然保留。

`.github/workflows/ubuntu-images.yml` 构建 `linux/amd64` GHCR 镜像，复用
BuildKit/GHA cache，并强制单镜像小于 2 GiB（`eda-agent` 小于 500 MiB）。

## 适用范围

这是一个容器化的开源工具链冒烟测试环境，而非虚拟机。它不模拟宿主机内核、CentOS 7 用户空间、LSF、网络挂载、许可证服务器或 VCS、Verdi 等商业工具。最终的 CentOS 7 兼容性检查应使用真实的传统环境。

## SystemC TLM 技能基准测试

离线安全的 A/B 基准测试规划器、架构门控、评分聚合和报告工作流文档请参见
[`docs/systemc-tlm-benchmark.md`](docs/systemc-tlm-benchmark.md)。
两个命令行接口的职责、命令、产物和当前限制文档请参见
[`docs/cli-reference.md`](docs/cli-reference.md)。
