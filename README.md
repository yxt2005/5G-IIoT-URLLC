# 5G-IIoT-URLLC

面向工业 URLLC 场景的研究型通信仿真系统。

当前系统已经具备以下能力：
- 多 UE 业务到达生成
- 严格优先级队列与调度
- 同一时隙内的带宽切片服务
- InF 信道模型与 AMC 选择
- 重传机制与硬时延超时丢弃
- 包级明细导出与尝试级导出
- 按业务流、按 UE 的 KPI 汇总

## 项目介绍

本项目用于面向 5G 工业互联网场景的 URLLC 机制建模与仿真，当前重点覆盖以下链路：

- `Traffic`
  - 支持多业务流
  - 支持多 UE
  - 支持周期到达与泊松到达

- `Queue + Scheduler`
  - 按优先级维护队列
  - 使用严格优先级调度
  - 在单个时隙内对多个包进行带宽分配

- `Channel`
  - 支持简化 InF 信道建模
  - 支持 LOS/NLOS、路径损耗、阴影衰落、小尺度衰落
  - 支持 AMC 选择

- `Retransmission + Deadline`
  - 支持有限重传
  - 支持硬时延约束下的超时丢弃

- `Metrics`
  - 支持包级记录
  - 支持尝试级记录
  - 支持 per-flow / per-UE KPI 汇总

## 项目结构

```text
configs/                 配置文件
  default.yaml           默认实验配置
  regression/            回归用例配置

src/
  core/                  仿真主循环、类型、队列
  traffic/               业务到达生成
  channel/               信道模型与 AMC
  scheduler/             调度器
  utils/                 工具函数

experiments/
  run.py                 单次实验入口
  run_regression.py      回归实验入口

outputs/                 仿真输出目录
tests/                   单元测试
```

## 运行方法

运行默认配置：

```bash
python -m experiments.run --config configs/default.yaml
```

运行回归用例：

```bash
python -m experiments.run_regression --configs-dir configs/regression
```

运行测试：

```bash
pytest -q
```

## 结果位置

默认单次运行结果保存在：

```text
outputs/<timestamp>/
```

当前会输出以下文件：

- `metrics.json`
  - 总体指标
  - 时延、吞吐、成功率、失败率
  - 信道与 MCS 统计

- `kpis.json`
  - `per-flow` KPI
  - `per-UE` KPI
  - 公平性指标

- `packet_records.csv`
  - 包级汇总记录
  - 每个 packet 一行

- `attempts.csv`
  - 发送尝试级记录
  - 每次传输尝试一行

回归实验结果保存在：

```text
outputs/regression/<timestamp>/
```

## 当前支持的实验方向

当前配置已经可以支持以下类型的实验：

- 不同带宽占用比例 `bandwidth_fraction` 对吞吐和时延的影响
- 不同 UE 数量下的资源竞争行为
- 不同优先级业务在拥塞场景下的时延与 deadline miss 对比
- 不同距离配置下的链路质量变化
- AMC 与重传机制对成功率、吞吐和时延的影响

## 后续可扩展内容

后续可以在当前工程基础上继续扩展以下内容：

- 更细粒度资源分配
  - PRB 级建模
  - 最小带宽保底
  - 按优先级/按业务切片

- 更复杂信道模型
  - 多 UE 空间分布
  - 时间相关衰落
  - 更完整的 InF 子场景参数

- 更复杂调度算法
  - EDF
  - PF
  - Deadline-aware priority

- 更丰富的结果展示
  - 实验结果图
  - 时延 CDF / CCDF
  - 吞吐-可靠性折中图
  - 不同业务流 KPI 对比图
  - 项目模型示意图
  - 仿真流程图
