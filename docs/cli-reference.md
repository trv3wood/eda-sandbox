# SystemC/TLM 命令行接口

本仓库提供一个命令行入口点，用于构建并验证一个 SystemC/TLM 模型：
`scripts/systemc-tlm-agent`。其主状态目录是一个建模 `PROJECT`（项目目录）。

## `systemc-tlm-agent`

实现位置：

- 入口点：`src/tlm_agent/cli.py`
- 提取：`src/tlm_agent/extractors.py`
- 合约与审批：`src/tlm_agent/workflow.py`
- 生成：`src/tlm_agent/generator.py`
- 验证：`src/tlm_agent/verifier.py`

### 项目布局

```text
PROJECT/
├── manifest.yaml
└── .systemc-agent/
    ├── graph/
    │   ├── manifest.json
    │   ├── document_tree.json
    │   ├── text_units.jsonl
    │   ├── spec_{entities,relationships}.jsonl
    │   ├── rtl_{entities,relationships}.jsonl
    │   ├── cross_source_relationships.jsonl
    │   └── {entities,relationships}.jsonl
    ├── contracts/{architecture,conflicts,approval}.yaml
    ├── model/
    └── verification/report.json.
```

`manifest.yaml` 用于区分待生成的模型与已有的验证源：

```yaml
name: ctrl
target_top: TopModule
reference_top: RefModule
documents: []
registers: []
rtl:
  - Prob001_controller_ref.sv
testbench:
  - Prob001_controller_test.sv
backend: local
```

`target_top` 是待生成的 DUT。`reference_top` 是已有的黄金 RTL 模块，供
所选 EDA 后端结构化 elaboration 使用。默认 VCS 后端接收
`eda_compile.filelists` 和追加在清单后的 `sources`，以及对应的 include
directory、define 和可选 `vcs_args`。没有 filelist 且未配置 `sources` 时，
才回退使用 `rtl`。

工业工程建议保留原始编译清单：

```yaml
eda_compile:
  working_directory: .
  filelists:
    - rtl/top.f
  sources:
    - rtl/extra_wrapper.sv
  include_dirs: []
  defines: []
  vcs_args:
    - -kdb
```

顶层 filelist 按声明顺序原样以 `-f` 交给EDA工具，`sources` 按声明顺序追加。
Agent递归解析 `-f/-F`、`-v` 和裸 `.v/.sv/.svp` 路径，仅用于输入摘要和源码
定位，不重建或重排filelist中的编译参数。VCS从 `working_directory`（默认项目根）
启动；`-f`内容中的相对路径按该目录解析，`-F`包含的清单内容按被包含清单目录解析。

语义 Spec 图默认关闭，功能合同可直接引用确定性 `text_units.jsonl` 中的
`txt-*` ID。需要细粒度语义实体时，再显式启用支持 OpenAI-compatible JSON
object 响应的 endpoint；返回内容会在本地通过完整 JSON Schema 和源跨度校验：

```yaml
graph:
  rtl_extraction:
    backend: vcs-vpi
    timeout_seconds: 1800
  spec_extraction:
    enabled: false
    provider: openai-compatible
    model: your-model
    base_url_env: SYSTEMC_TLM_LLM_BASE_URL
    api_key_env: SYSTEMC_TLM_LLM_API_KEY
    batch_max_chars: 24000
    response_format: json_object
```

`enabled: false` 时 extraction 将 Spec producer 标记为 skipped，不调用 LLM，
且 RTL EDA 门禁通过后可发布 ready graph。密钥和 endpoint 只从环境变量读取，不写入
项目产物。启用后，相同输入、prompt schema、模型和温度会命中
`.systemc-agent/tools/spec-llm-cache/` 的确定性缓存。

### 命令

#### `init`

创建 `manifest.yaml`。不执行提取、编译或生成操作。

```bash
scripts/systemc-tlm-agent init PROJECT \
  --name ctrl --top TopModule --reference-top RefModule \
  --eda-filelist rtl/top.f --backend local
```

`--docx`、`--xlsx`、`--rtl`、`--tb`、`--eda-filelist` 和 `--eda-source`
可重复指定。`--eda-source` 总是追加在全部filelist之后。RTL参数也可以命名为目录或
glob 模式；目录会递归发现 `.v`、`.sv` 和 `.svp`。旧版 manifest 中使用 `top`
而非 `target_top` 的写法仍然可读。

#### `extract`

解析 manifest 输入，计算源文件摘要，写入文档树、text units 和 pending graph，
并可选择运行 Spec 和配置的 RTL producer。

```bash
scripts/systemc-tlm-agent extract PROJECT
scripts/systemc-tlm-agent extract PROJECT --skip-tools
```

文档前端支持 DOCX/OOXML、Markdown 和 XLSX。默认
`graph.spec_extraction.enabled: false`，稳定的 `txt-*` text-unit ID 可直接作为
architecture 与合同证据。显式启用后，Spec producer 通过固定 JSON Schema 调用
OpenAI-compatible endpoint；每个实体和关系必须回链到 text unit
中的精确字符区间。SystemVerilog 不再使用文本或正则
发现模块：RTL 首先处于 `pending`。新项目默认由 VCS elaboration 和随包发布的
C/VPI 插件在仿真零时刻导出结构；旧项目可显式配置 `backend: uhdm` 使用原有
Surelog/UHDM 流程。只有退出状态、请求的 top、输入/原生工件/结构摘要全部校验
通过，`graph/manifest.json` 才会成为 `status: ready`；否则不能审批。
producer 不使用 Surelog 的 `-d uhdm` debug dump，避免把完整 UHDM tree 写入日志。
VCS 原生工件保留在 `tools/vcs-work/`，后端无关结构保留在
`tools/rtl-structure.json`。

`--skip-tools` 只登记输入并留下 `pending` 状态，适合随后在对应执行环境中分别执行：

```bash
scripts/eda-run --work WORK vcs eda-rtl-produce /workspace/PROJECT
# 可选：仅当 graph.spec_extraction.enabled: true
scripts/eda-run --work WORK agent eda-spec-produce /workspace/PROJECT
scripts/eda-run --work WORK agent \
  systemc-tlm-agent tools finalize /workspace/PROJECT
scripts/eda-run --work WORK agent \
  systemc-tlm-agent graph build /workspace/PROJECT
```

`eda_compile.filelists` 保留工程原始编译顺序，`sources` 是追加源；
`include_dirs`、`defines` 和可选 `vcs_args` 会传给 VCS producer。对于包含共享 primitive
目录的 IP，可用 `exclude_sources`（文件、目录或 glob 列表）排除与该 top 无关、
但依赖未被检出的模块。

#### `graph`

`graph build` 将规范 JSONL 转成 DuckDB 可查询的 Parquet；`graph index` 使用
固定 revision 的 multilingual-e5-small 创建 FAISS 索引，但不会自动下载模型。
`graph lookup/neighbors/path/search` 分别提供精确过滤、NetworkX 图遍历和向量
检索。Parquet 与 FAISS 均为可重建索引，不参与审批哈希。

```bash
pip install '.[graph]'   # DuckDB、NetworkX、OpenAI client
pip install '.[vector]'  # FAISS、sentence-transformers
hf download intfloat/multilingual-e5-small \
  --revision fd1525a9fd15316a2d503bf26ab031a61d056e98
```

运行时只从本地加载上述固定模型 revision，不会隐式访问网络。

`eda-uhdm run DATABASE QUERY.py --output-dir OUTPUT -- ARGS...` 在 UHDM 镜像中执行
Agent 编写的原生 Python API 查询，保存原始 stdout/stderr 和运行元数据。查询结果是探索信息，
不直接生成证据 ID，必须回到有定位的 RTL/规格证据确认。

合同中的 `evidence_ids` 只能引用规范图中带 `source_refs` 的实体。临时 EDA
查询和日志不能自行转换为证据 ID。

#### `architect`

创建八类合约框架，或验证已编辑的合约：

```bash
scripts/systemc-tlm-agent architect PROJECT
scripts/systemc-tlm-agent architect PROJECT --validate
```

八个类别分别是 `functional_intent`（功能意图）、`transaction_entry`（事务入口）、`input_domain`（输入域）、`algorithm_transform`（算法变换）、`data_flow`（数据流）、`state_concurrency`（状态与并发）、`boundaries_exceptions`（边界与异常）和 `observable_results`（可观察结果）。

验证检查类别状态、必填项、证据 ID 存在性、模型分区存在性以及未解决的冲突记录。这是一个结构性的门控检查；它并不证明引用的证据在语义上支持某个声明。

#### `approve`

要求指定的人类决策者并哈希所有受审批控制的产物：

```bash
scripts/systemc-tlm-agent approve PROJECT --approver NAME
```

此后任何 manifest、输入、规范图、架构或冲突的更改都会使审批失效。即使历史 approval
哈希仍匹配，只要当前 architecture/RTL EDA 门禁失败，也会被判为无效。

#### `generate`

从当前已审批的架构生成 C++17 SystemC/TLM 模型和测试源文件：

```bash
scripts/systemc-tlm-agent generate PROJECT
```

如果审批缺失、无效或已过期，生成操作将拒绝执行。

#### `verify`

配置、构建并测试生成的项目：

```bash
scripts/systemc-tlm-agent verify PROJECT --backend auto
```

后端选项为 `auto`、`local` 和 `podman`。验证级别必须分开报告：编译、CTest、合约导向的事务测试和 RTL 差分对比不可互换。

#### `run`

推进提取和架构阶段，然后在下一个强制性门控处停止：

```bash
scripts/systemc-tlm-agent run PROJECT --backend auto
```

退出码 `2` 表示工作流健康但暂停等待架构完成或审批。退出码 `1` 表示错误。

#### `status`

报告哪些产物存在、架构验证错误和审批有效性，不推进工作流：

```bash
scripts/systemc-tlm-agent status PROJECT
```
