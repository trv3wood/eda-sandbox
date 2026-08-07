# Cycle-Level SystemC PoC 架构

## 分层

```text
共享 Request/Response
        │
        ├── CycleModelAdapter ── 逐周期复刻 start/valid/ready/done
        │
        └── FunctionalModel ──── 单次函数调用保留事务语义
                    ▲
                    │ IModel::run
             TlmModelAdapter
                    ▲
                    │ b_transport + delay
               TLM initiator
```

`model_core` 只依赖 C++17。SystemC 和未来的 minres-SCC 能力隔离在
`TlmModelAdapter`，不会渗透进 functional core。

## 接口与数据流

- `Request`：一笔事务的 samples、scale 和 bias。
- `Response`：32 位累加结果与事务计数。
- `IModel::run`：Cycle 和 Functional 两种实现的唯一公共调用边界。
- `CycleModelAdapter`：用 start 周期、逐项接收周期、输出握手周期复刻延迟；设置
  timeout 防止模型永不完成。
- `FunctionalModel`：直接遍历 samples，不暴露内部 clock、remaining 或 out_valid。
- `TlmModelAdapter`：将 32 位小端访问解码为 clear/config/sample/execute/result/status，
  成功访问增加 10 ns annotated delay。

## RTL 映射

| RTL 概念 | Cycle adapter | Functional core |
|---|---|---|
| `active`, `remaining` | 循环状态和 accepted 索引 | 删除 |
| `in_valid && in_ready` | 每个 adapter 周期接收一个 sample | range-for 中的一次迭代 |
| `accumulator` | 32 位局部状态 | 32 位局部状态 |
| `out_valid && out_ready` | 显式增加完成握手周期 | 函数返回 |
| reset | 每次 `run` 初始化事务内部状态 | 每次 `run` 初始化局部状态 |

事务计数是 PoC adapter 的可见状态，不来自参考 RTL。真实模块替换时必须根据规格决定
是否保留、删除或改名。

## 验证边界

- 当前 `CycleModelAdapter` 是独立 C++ 语义基线，不是假称由 CIRCT 生成的 SystemC。
- CIRCT 可用后，生成模型必须接入相同 stimulus，并增加逐周期 CSV trace 比较。
- TLM contract 已在 SCC 容器的 SystemC SDK 中编译运行通过；宿主机仍未安装 SDK。
- 没有真实项目 RTL/spec 前，本架构只证明方法和接口可工作。
