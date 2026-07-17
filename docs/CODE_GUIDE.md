# EVB 通信工具 — 代码须知

面向需要在另一台 PC 上**理解或二次开发**本项目的工程师。无需阅读聊天历史即可上手。

| 文档 | 用途 |
|------|------|
| [软件使用手册.md](软件使用手册.md) | 操作人员 |
| [软件工程视角与VibeCoding重建实验.md](软件工程视角与VibeCoding重建实验.md) | 架构、流程图、导出契约、SE 学习 |
| [SIM_TO_REAL.md](SIM_TO_REAL.md) | 公式与 BER 通道 |
| [PROTOCOL_UART.md](PROTOCOL_UART.md) | UART / AA 帧 |
| [EVB通信工具_代码需求书.md](EVB通信工具_代码需求书.md) | 从零搭建清单与不变量摘要 |

---

## 1. 项目目的

PC 端通过 UART 与 EVB（Turbo 译码芯片评估板）通信，完成：

1. **Sim-to-Real 批量测试**：CSV 激励下发 → 采集 RX → CodeBit 比对 → BER / 迭代  
2. **单帧联调**：粘贴或手动收发  
3. **可视化与导出**：曲线 + 柱状图 + 测后 Excel（详见 `docs/批量测试可视化分析.md`）

核心语义：**硬件收敛（0x2FF）** 与 **误码（CodeBit）** 分离；见软件工程视角。

---

## 2. 目录结构

```
evb-comm-tool/
├── main.py
├── requirements.txt
├── setup.bat / run.bat / run_lite.bat / pack.bat
├── protocol/
│   ├── codec.py            # AA 编解码、物理量
│   └── validator.py        # 0x2FF 收敛
├── comm/
│   └── serial_worker.py    # QThread 收发、批量、多 Attempt
├── csv_loader.py           # 双行数据集、导出口径
├── paste_parser.py
├── analysis/
│   ├── aggregate.py        # CaseRecord、fill_measured、SNR
│   ├── sign_compare.py     # 硬判、模式 BER 下标
│   ├── report_export.py    # 样式 Excel、filter_ber_error_rows
│   ├── dataset_accuracy.py # 仿真 CodeBit 监测
│   └── mode2_g_decode.py   # Mode2 辅助解码（若启用）
├── ui/
│   ├── main_window.py
│   ├── workers.py          # QThread 后台任务
│   ├── chart_panel.py
│   ├── perf_settings.py    # EVB_UI_LITE 等
│   └── theme.py
├── data/
│   ├── 测试集/             # 源测试 CSV（加载用）
│   └── 测后数据集/         # 按日期 YYYY-MM-DD/ 存放 result/ok/ber
├── docs/                   # 本文档体系
└── scripts/                # 冒烟 / 迁移 / 验收脚本
```

---

## 3. 环境

- Python 3.10+（推荐 3.12+）
- Windows：`run.bat` / `setup.bat`
- 依赖见 `requirements.txt`（含 PyQt6、pyserial、matplotlib；Excel 需 openpyxl）

```cmd
run.bat
.\.venv\Scripts\python.exe -c "import protocol.codec; import ui.main_window; print('OK')"
```

弱机：`run_lite.bat`（`EVB_UI_LITE=1`）。

---

## 4. 关键模块速查

| 任务 | 入口 |
|------|------|
| 组帧 / 拆帧 / I_col | `protocol.codec` |
| 是否重发 | `protocol.validator.needs_retry` |
| 批量收发 | `comm.serial_worker.SerialWorker._do_send` |
| 写入 Attempt | `analysis.aggregate.fill_measured` |
| ①/② 导出行 | `csv_loader.TestCsvDataset.build_export_rows` |
| ③ 误码过滤 | `analysis.report_export.filter_ber_error_rows` |
| CodeBit 监测 | `analysis.dataset_accuracy` |
| 模式通道 | `sign_compare.ber_out_indices_for_mode` |

---

## 5. 设计决策（现码）

| 决策 | 原因 |
|------|------|
| 交错双行 + 多 Attempt | 仿真只读；重发可审计 |
| I_col = 2.5 − raw×5/4096 | 符号可硬判；Out≈2.5 ↔ raw≈0 |
| CH1–8 全部参与 0x2FF | 与硬件收敛一致 |
| BER 用仿真/实测 CodeBit | Mode 通道不同；InfoBit 在 Mode2 不参与 BER |
| 三份 Excel 契约 | 全量 / 成功口径 / 误码清单产品化 |
| 展开 `only_empty=True` | 禁止静默覆盖仿真 CodeBit |
| QThread + 后台导出 | 7000 帧不堵 UI |

过时说法（勿再采用）：「仅 CH1–4 收敛重试」「ok 只删最后一次失败 Attempt」「主产物是 error_rx.xlsx」。

---

## 6. 冒烟测试

```cmd
.venv\Scripts\python.exe scripts\test_mode2_rx_retry.py
.venv\Scripts\python.exe scripts\test_dataset_accuracy.py
.venv\Scripts\python.exe scripts\verify_sign_formula.py
.venv\Scripts\python.exe scripts\test_report_export.py
```

---

## 7. 相关文档

| 文档 | 内容 |
|------|------|
| [软件使用手册.md](软件使用手册.md) | 操作人员 |
| [师傅带徒弟_代码故事.md](师傅带徒弟_代码故事.md) | 需求↔模块↔技术栈，通俗入门 |
| [软件工程视角…](软件工程视角与VibeCoding重建实验.md) | 架构与流程图（首选） |
| [SIM_TO_REAL.md](SIM_TO_REAL.md) | 公式、Mode、导出摘要 |
| [PROTOCOL_UART.md](PROTOCOL_UART.md) | 帧格式 |
| [README.md](../README.md) | 安装总览 |
| [DISTRIBUTE.md](../DISTRIBUTE.md) | 打包 |

---

*与现码对齐：2026-07-09。*
