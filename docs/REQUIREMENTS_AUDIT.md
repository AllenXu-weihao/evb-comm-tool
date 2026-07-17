# EVB 通信工具 — 需求符合性审计报告

> **审计日期**：2026-07-02  
> **用户决策确认**：2026-07-02  
> **需求文档**：`EVB通信工具_代码需求书.md`（位于 `c:\Users\15209\Desktop\`，不在本仓库内）  
> **代码库**：`evb-comm-tool`  
> **原则**：协议与公式以 `docs/PROTOCOL_UART.md`、`docs/SIM_TO_REAL.md`、`protocol/codec.py` 为准

---

## 一、审计摘要

| 指标 | 结果 |
|------|------|
| **总体符合率（估算）** | **~92%**（用户决策实施后） |
| **已解决（2026-07-02）** | I_col 公式、仿真 BER 曲线移除、动态 BER 分母、用例表浅色标注、Out/I_col 列扩展 |
| **剩余缺口** | 需求书不在 workspace（公式以用户确认的需求书为准）；SymbolPassed 独立列；GUI Match ✓/✗ 粒度 |

---

## 二、用户决策记录（2026-07-02 已实施）

| # | 议题 | 用户决定 | 实施 |
|---|------|----------|------|
| 1 | **I_col 公式** | 以**需求书**为准：`I_col = (raw/4096×5)×(−1.25)` | `protocol/codec.py`、`column_current_to_raw()` 逆变换；`docs/SIM_TO_REAL.md`、`docs/CODE_GUIDE.md`、`README.md` |
| 2 | **仿真 BER 曲线** | **移除**，仅保留实测 BER | `ui/chart_panel.py` 删除仿真曲线；`analysis/aggregate.py` 删除 `sim_channel_ber`；`report_export.py` SNR_Summary 精简 |
| 3 | **批量中断 BER 分母** | **动态**：`BER = error_bits / (4 × N_tested)` | `analysis/aggregate.py` `count_channel_error_bits()` 仅统计 `frame_was_tested()` 帧 |
| 4 | **用例表 UI 标注色** | 需求书浅色：`#fff3e0` 橙、`#fff9c4` 黄、浅蓝 `#e3f2fd` 实测行 | `ui/theme.py`、`ui/main_window.py` |
| 5 | **用例表列扩展** | 显示 Out1–4（仿真行）与 I_col1–4（实测行），误码单元格级黄色高亮 | `ui/main_window.py` 12 列用例表 |

> **说明**：`EVB通信工具_代码需求书.md` 不在本 workspace；用户已确认以需求书 §2.5 的 `(−1.25)` 公式为准，代码与文档已对齐，无需在本仓库修改需求书文件。

---

## 三、差距分析表（更新后）

| 需求项 | 状态 | 代码位置 | 备注 |
|--------|------|----------|------|
| **AA 协议 TX 25B / RX 17B** | OK | `protocol/codec.py` | — |
| **TX：V_row = (raw/4096)×4.096** | OK | `raw_to_row_voltage()` | — |
| **RX：I_col = (raw/4096×5)×(−1.25)** | OK | `raw_to_column_current()` | 用户确认需求书公式 |
| **收敛：CH1–4 raw ≥ 0x1FF，max 5 次重发** | OK | `protocol/validator.py`, `comm/serial_worker.py` | — |
| **BER 动态分母 4×N_tested** | OK | `analysis/aggregate.py` | 含未收敛已测帧计 4 error bits |
| **BER 图：实测曲线 + 对数 Y 轴** | OK | `ui/chart_panel.py` | 已移除仿真 BER 曲线 |
| **用例表 Out1–4 / I_col1–4 + 黄色误码** | OK | `ui/main_window.py` | — |
| **用例表浅色标注（橙/黄/浅蓝）** | OK | `ui/theme.py` | 用例表区域使用需求书 hex |
| **Excel 两 Sheet + 条件格式** | OK | `analysis/report_export.py` | — |
| **仿真 BER：Out_sim vs Out_ref** | N/A | — | 用户决定不展示仿真 BER |
| **Match_CH 显示 ✓/✗（GUI 用例表）** | Gap | `_format_match_status()` | 仍显示 `X/4` 文字 |
| **报告列 SymbolPassed** | Gap | `report_export.py` | 仅有 FramePassed |

---

## 四、本次已实施修复（用户决策批次）

| # | 文件 | 修改内容 |
|---|------|----------|
| 1 | `protocol/codec.py` | I_col 恢复需求书公式 `(raw/4096×5)×(−1.25)` 及逆变换 |
| 2 | `analysis/aggregate.py` | 动态 BER 分母；移除 `sim_channel_ber` / `count_sim_error_bits()` |
| 3 | `ui/chart_panel.py` | 仅实测 BER 曲线；标题注明动态分母 |
| 4 | `ui/main_window.py` | 用例表 12 列（Out1–4 + I_col1–4）；单元格级黄色误码高亮 |
| 5 | `ui/theme.py` | 用例表浅色标注常量（`#fff3e0` / `#fff9c4` / `#e3f2fd` / `#e8f5e9`） |
| 6 | `analysis/report_export.py` | SNR_Summary 移除仿真 BER 列，增加 `TestedFrames` |
| 7 | `docs/SIM_TO_REAL.md`, `docs/CODE_GUIDE.md`, `README.md` | 公式与 BER 口径文档同步 |

---

## 五、原存疑项 — 决议状态

| # | 原议题 | 决议 |
|---|--------|------|
| 1 | I_col 公式以哪份文档为准 | ✅ **需求书 `(−1.25)` 公式** |
| 2 | 仿真 BER / Out_ref | ✅ **不展示仿真 BER 曲线** |
| 3 | 批量中断 BER 分母 | ✅ **动态 `4×N_tested`** |
| 4 | 暗色主题 vs 浅色标注 | ✅ **用例表使用需求书浅色 hex** |
| 5 | 用例表 Out/I_col 列扩展 | ✅ **已扩展 12 列** |

---

## 六、关键模块符合性速查

```
协议层     protocol/codec.py, validator.py     ██████████ 100%
串口层     comm/serial_worker.py               ██████████ 100%
CSV 数据   csv_loader.py                       ██████████ 100%
符号比对   analysis/sign_compare.py            ██████████ 100%
SNR 聚合   analysis/aggregate.py               ██████████ 100%
报告导出   analysis/report_export.py           █████████░  90%
可视化     ui/chart_panel.py                   ██████████ 100%
主界面     ui/main_window.py                   █████████░  90%
粘贴解析   paste_parser.py                     ██████████ 100%
```

---

## 七、审查文件路径

| 类型 | 路径 |
|------|------|
| 需求书 | `c:\Users\15209\Desktop\EVB通信工具_代码需求书.md`（仓库外） |
| 本审计报告 | `docs/REQUIREMENTS_AUDIT.md` |
| 流程文档 | `docs/SIM_TO_REAL.md` |
| 代码指南 | `docs/CODE_GUIDE.md` |
| 协议文档 | `docs/PROTOCOL_UART.md` |
| 测试数据 | `data/testdata.csv` |

---

*审计人：自动化代码审查（2026-07-02）；用户决策实施（2026-07-02）*
