# EVB 通信质量监测上位机 — 代码需求书（精简）

> **用途**：另一台 PC 上从零重建时的**规格索引与不变量清单**。  
> **权威细节**：以仓库现码为准；流程图与导出契约见 [软件工程视角与VibeCoding重建实验.md](软件工程视角与VibeCoding重建实验.md)；协议见 [PROTOCOL_UART.md](PROTOCOL_UART.md)；公式见 [SIM_TO_REAL.md](SIM_TO_REAL.md)。  
> **平台**：Windows 10/11，Python 3.10+

本文档**不再**与代码双份维护长流程图；实现以源码 + 上述三份文档为准。

---

## 1. 项目概述

| 项 | 说明 |
|----|------|
| 名称 | DAC 译码器测试工具（EVB 通信质量监测上位机） |
| 目标 | UART Sim-to-Real 批量测试、单帧联调、BER/迭代、三份测后 Excel |
| 规模 | 典型 7×1000=7000 帧；测前双行 14000；有重发则更多 |
| 窗口标题 | `DAC译码器测试工具` |

分层：`ui` → `comm` → `protocol`；旁路 `analysis` + `csv_loader`。见软件工程视角 §2。

---

## 2. 从零搭建清单

1. 创建 venv，安装 `requirements.txt`（含 openpyxl）  
2. 实现 `protocol/codec.py`：TX 25B / RX 17B、`raw_to_column_current`  
3. 实现 `protocol/validator.py`：CH1–8 raw ≥ 0x2FF  
4. 实现 `comm/serial_worker.py`：重试 + `RxAttempt` 列表  
5. 实现 `analysis/aggregate.py`：`CaseRecord` / `fill_measured`  
6. 实现 `csv_loader.py`：双行展开（`only_empty`）、`build_export_rows`  
7. 实现 `sign_compare` + SNR 聚合  
8. 实现三份 Excel：`result` / `ok` / `ber`  
9. 实现 GUI 编排 + `dataset_accuracy` 监测  
10. 对照 `scripts/test_mode2_rx_retry.py` 等冒烟通过  

课程切片顺序见软件工程视角「第二部分」。

---

## 3. 模块职责表

| 模块 | 必须提供 |
|------|----------|
| `protocol/codec` | `build_tx_frame`、`parse_rx_frame`、行/列电压换算 |
| `protocol/validator` | `RETRY_THRESHOLD=0x2FF`、`needs_retry` |
| `comm/serial_worker` | 连接、单发、批量、最多 5 次重发、每次 RX 入 `attempts` |
| `csv_loader` | `load_test_csv`、交错展开、`build_export_rows(exclude_comm_errors=)` |
| `analysis/aggregate` | `CaseRecord`、`AttemptRecord`、`fill_measured`、`analyze_by_snr` |
| `analysis/sign_compare` | 硬判、`ber_out_indices_for_mode`（1/2/3） |
| `analysis/report_export` | `filter_ber_error_rows`、样式写入 |
| `analysis/dataset_accuracy` | 仿真 CodeBit 快照比对 |
| `ui/main_window` | 串口、加载、运行全部、导出、监测入口 |
| `ui/chart_panel` | BER / 迭代图（可延迟加载） |
| `ui/perf_settings` | `EVB_UI_LITE` 等 |

---

## 4. 不变量（验收必测）

1. **收敛**：CH1–8 全部 raw ≥ 0x2FF 才停止重发  
2. **Out≈2.5**：对应 raw≈0，属未收敛 Attempt，可出现在 result，**不可**作为 ok/ber 成功行  
3. **最终失败帧**：ok 中 **仿真行 + Attempt 1..N 整套删除**（不是只删最后一次）  
4. **最终成功帧**：ok 只留 HC=Y 的 Attempt；ber 用该行 CodeBit vs 仿真  
5. **仿真 CodeBit**：展开/导出不得静默覆盖（`only_empty=True` + 监测）  
6. **Mode BER 下标**：1→`[0..3]`；2→`[3,5,6,7]`；3→`[0,1]`  
7. **I_col 公式**：`2.5 − raw×5/4096`（不用恒负的 −1.25 式做 bit）  
8. **源 CSV**：批量过程不就地覆盖；测后另存 `*_result_*`  

---

## 5. 数据与导出契约（摘要）

| 产物 | 口径 |
|------|------|
| `*_result_*.csv/xlsx` | 全量 Attempt |
| `*_ok.xlsx` | 去通信失败整套 + 去中间未收敛 Attempt |
| `*_ber.xlsx` | ok 中 CodeBit 不一致行 + 高亮 |

路径辅助：`csv_loader.post_test_excel_paths`。

---

## 6. 常量速查

| 常量 | 值 |
|------|-----|
| TX 长度 | 25 B（`0xAA` + 12×2） |
| RX 长度 | 17 B（iter + 8×2） |
| `RETRY_THRESHOLD` | 0x2FF |
| 默认最大重发 | 5（共 6 次 TX） |
| 波特率（常用） | 9600 8N1 |

---

## 7. 文档地图

| 文档 | 内容 |
|------|------|
| [软件工程视角…](软件工程视角与VibeCoding重建实验.md) | 架构 + mermaid + SE/课程 |
| [师傅带徒弟_代码故事.md](师傅带徒弟_代码故事.md) | 通俗：需求↔代码↔技术栈 |
| [软件使用手册.md](软件使用手册.md) | 操作说明 |
| [SIM_TO_REAL.md](SIM_TO_REAL.md) | 公式与 Mode |
| [PROTOCOL_UART.md](PROTOCOL_UART.md) | 帧格式 |
| [CODE_GUIDE.md](CODE_GUIDE.md) | 目录与冒烟 |
| PCB / 嘉立创 / AD / RRAM / 44×76 | 硬件文档（与上位机软件解耦） |

---

*精简版；与现码对齐：2026-07-09。长篇历史规格以 git 历史为准，不再维护双份。*
