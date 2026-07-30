# 开源 EDA 沙盒

工作流和图/规范工具通过本地 `uv` 环境运行；容器镜像只保留需要专用二进制
工具链的角色：

- `eda-uhdm`：Surelog 和 UHDM Python binding，生成原生数据库并运行
  Agent 编写的直接 Python 查询。
- `eda-scc`：SystemC/SCC 编译与验证；Conan 缓存只存在于 builder。
- `eda-enterprise`：Rocky Linux 8，用于 RHEL 系列兼容性检查。

先在宿主机运行 `uv sync`，再通过 `uv run` 或 `scripts/eda-run ... agent`
调用工作流。UHDM 镜像使用 conda-forge `surelog` 和 `uhdm` 二进制包。conda 包未携带可选的 Python wrapper，因此
wrapper 在临时 builder 中生成；Surelog 本身不再编译。商业 EDA 二进制和许可证
不会进入容器镜像，VCS producer 仅在研发网宿主环境运行。

## 构建与运行

使用 Docker：

```bash
uv sync --extra graph
uv run systemc-tlm-agent --help
docker compose build eda-uhdm
docker compose run --rm eda-uhdm scripts/regress.sh
```

使用 Podman（本环境推荐）：

```bash
uv sync --extra graph
uv run systemc-tlm-agent --help
podman-compose build eda-uhdm
podman-compose run --rm eda-uhdm scripts/regress.sh
```

SCC 构建耗时较长，通常从 GitHub Container Registry 拉取 CI 产物；它仅在
版本 tag 或手工 workflow dispatch 时构建。Surelog 和 RTL 工具来自二进制包；
UHDM 镜像只额外编译 Python wrapper。本地只构建当前需要的轻量目标：

```bash
podman-compose build eda-uhdm
```

不需要记忆容器参数时，可通过宿主机 wrapper 直接调用各角色：

```bash
scripts/eda-run uhdm surelog --version
scripts/eda-run --work "$PWD" vcs eda-rtl-produce /workspace/PROJECT
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
podman build -f Dockerfile.rocky8 -t eda-enterprise:local .
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
BuildKit/GHA cache，并强制单镜像小于 2 GiB。
`.github/workflows/rocky8-image.yml` 独立构建并测试
`ghcr.io/trv3wood/eda-enterprise`，避免 Rocky 兼容性构建拖慢 Ubuntu 矩阵。

## 适用范围

这是一个容器化的开源工具链冒烟测试环境，而非虚拟机。它不模拟宿主机内核、CentOS 7 用户空间、网络挂载或许可证服务器。最终的 CentOS 7 兼容性检查应使用真实的传统环境。

## SystemC TLM 建模 CLI

建模命令的职责、命令、产物和当前限制文档请参见
[`docs/cli-reference.md`](docs/cli-reference.md)。
新项目通过 VCS/VPI 访问已验证的 elaborated 结构；UHDM Python API 仅保留为
旧项目兼容和探索路径。canonical graph 仍只由固定、经过门禁的 exporter 生成。

提取阶段现在以 canonical property graph 为唯一事实源：DOCX/Markdown/XLSX
生成可定位的 text units，固定 schema 的 LLM producer 生成规范实体关系，
配置的 VCS/VPI 或兼容 UHDM 后端生成 RTL 实体关系，最后仅以唯一精确
名称/token 建立跨源边。
DuckDB/Parquet、NetworkX 和 FAISS 都是可重建的查询层，不参与审批哈希。配置、
产物和离线模型准备方式见
[`docs/cli-reference.md`](docs/cli-reference.md#graph)。
