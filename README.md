# 开源 EDA 沙盒

Ubuntu 24.04 工具链按职责拆成四个独立镜像：

- `eda-agent`：工作流和离线 JSON 查询；不含 EDA 编译器。
- `eda-uhdm`：Surelog 和 UHDM Python binding，生成原生数据库并运行
  Agent 编写的直接 Python 查询。
- `eda-rtl`：Verilator 和 Yosys。
- `eda-scc`：SystemC/SCC 编译与验证；Conan 缓存只存在于 builder。
- `eda-enterprise`：Rocky Linux 8，用于 RHEL 系列兼容性检查。

Ubuntu agent 使用发行版 Python 3.12；UHDM 镜像使用同版本的 conda-forge
`surelog` 和 `uhdm` 二进制包。conda 包未携带可选的 Python wrapper，因此
wrapper 在临时 builder 中生成；Surelog 本身不再编译。商业 EDA 工具有意排除。

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
版本 tag 或手工 workflow dispatch 时构建。Surelog 和 RTL 工具来自二进制包；
UHDM 镜像只额外编译 Python wrapper。本地只构建当前需要的轻量目标：

```bash
podman-compose build eda-agent
podman-compose build eda-rtl
```

不需要记忆容器参数时，可通过宿主机 wrapper 直接调用各角色：

```bash
scripts/eda-run rtl verilator --version
scripts/eda-run uhdm surelog --version
scripts/eda-run --work "$PWD" uhdm \
  eda-uhdm run /workspace/design.uhdm /workspace/query.py \
  --output-dir /workspace/query-output
scripts/eda-run scc --shell
scripts/eda-run rocky --shell
```

默认使用 `ghcr.io/trv3wood/eda-*:main`、挂载当前目录并保持宿主 UID，且不会
自动拉取新镜像。可通过 `--image`、`--tag`、`--work` 或 `EDA_*_IMAGE`
环境变量覆盖；完整参数见 `scripts/eda-run --help`。

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
`.github/workflows/rocky8-image.yml` 独立构建并测试
`ghcr.io/trv3wood/eda-enterprise`，避免 Rocky 兼容性构建拖慢 Ubuntu 矩阵。

## 适用范围

这是一个容器化的开源工具链冒烟测试环境，而非虚拟机。它不模拟宿主机内核、CentOS 7 用户空间、网络挂载或许可证服务器。最终的 CentOS 7 兼容性检查应使用真实的传统环境。

## SystemC TLM 建模 CLI

建模命令的职责、命令、产物和当前限制文档请参见
[`docs/cli-reference.md`](docs/cli-reference.md)。
Agent 直接访问 UHDM Python API 与离线 Yosys/Verilator 查询的边界见
[`docs/agent-eda-query.md`](docs/agent-eda-query.md)。
