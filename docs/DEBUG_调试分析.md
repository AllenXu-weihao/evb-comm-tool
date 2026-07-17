# EVB 通信工具 — 调试 / 分析备忘

面向排查 **测后 CSV / Excel 中 `Out[]` 十进制** 与 **PC 侧重发** 是否一致、以及串口抓包与表内数值如何互证的工程师。实现以 `protocol/codec.py`、`protocol/validator.py`、`comm/serial_worker.py` 为准。

相关文档：[SIM_TO_REAL.md](SIM_TO_REAL.md)（批量流程）、[PROTOCOL_UART.md](PROTOCOL_UART.md)（帧格式）、[CODE_GUIDE.md](CODE_GUIDE.md)（代码索引）。

> **2026-07-17**：串口助手单帧不成功 / 硬件配置分层排查 → 见 [PROTOCOL_UART.md §12](PROTOCOL_UART.md#12-硬件--串口配置排查串口助手单帧不成功)（9600 8N1、A1 黄金帧、回环自检、上位机交叉验证）。

---

## 回传序列重发判别与测后表十进制含义

### 1. RX 17 字节帧结构

芯片 → PC 固定 **17 B**：

| 偏移 | 长度 | 含义 |
|------|------|------|
| byte0 | 1 | 迭代次数编码；**迭代次数 = byte0 + 1**（非 Mode） |
| byte1–16 | 16 | **8 路 ADC**，每路 **2 字节大端** 12-bit raw（`0x000`–`0xFFF`） |

解析：`raw_i = ((data[1+2i] << 8) | data[2+2i]) & 0xFFF`，`i = 0..7` 对应 CH1–CH8。首字节高 4 bit 为 Mode nibble（硬件多为 0），**与 raw 合并时仍取完整 12 bit**（见 `parse_rx_frame`）。

### 2. 列电流公式（`Out[]` 十进制来源）

测后表 **实测行** 的 `Out[0..7]` 不是线上 hex，而是换算后的列电流 **I_col (V)**：

```
I_col = ((raw / 4096 × 5) − 2.5) × (−1)
      = 2.5 − raw × 5 / 4096
```

代码：`protocol.codec.raw_to_column_current()`。

| raw (12-bit) | I_col (V) | 说明 |
|--------------|-----------|------|
| 0 | **+2.500** | 读数偏高、远离零点 |
| 511 (`0x1FF`) | **+1.876** | 收敛阈值边界 |
| 2048 | **0.000** | 电学中点 |
| 4095 | **−2.499** | 负向饱和侧 |

符号判决（BER）：**I_col ≥ 0 → bit 0；I_col < 0 → bit 1**（`chip_value_to_bit`）。

### 3. 重发判别：看 raw，不看十进制 `Out`

PC **硬件收敛**判定在 **12-bit raw** 上完成，**不是**在 `Out[]` 浮点上直接比较阈值。

| 项目 | 规则 |
|------|------|
| 检查通道 | **仅 CH1–CH4**（`Out[0..3]` 对应 raw）；**CH5–CH8 不参与**重发 |
| 阈值 | `RETRY_THRESHOLD = 0x1FF`（十进制 **511**） |
| 未收敛 | 前 4 路 **任一路** `raw < 0x1FF` → **重发同一 TX 25 B** |
| 已收敛 | CH1–4 **全部** `raw ≥ 0x1FF` → 停止重发，写入测后行 |
| 次数上限 | 默认最多 **5 次重发**（共 **6 次** TX 机会）；超时 / 帧长不足同理重试 |

代码：`protocol.validator.needs_retry()`、`comm.serial_worker._do_send()`。

**与十进制的对应关系**（仅 CH1–4）：`raw < 511` ⟺ `I_col > 1.876 V`；收敛时 CH1–4 的 `Out[i]` **均 ≤ ~1.876 V**（仍可为正，尚未过零）。

```
未收敛示例：CH1 raw=0x0A0 (160) → Out[0] ≈ +2.30 V → 触发重发
收敛示例：  CH1 raw=0x917 (2327) → Out[0] ≈ +0.34 V → 不因此路重发
```

### 4. Mode 2 额外重发（列电流过高）

Mode 1/3 仅受 §3 约束。 **Mode 2 批量**在 §3 之外增加：

| 项目 | 规则 |
|------|------|
| 条件 | **8 路任意一路** 解析后 `I_col > 2.2` V |
| 动作 | 重发同一 TX |
| 上限 | 最多 **5 次收发**（含首次；`MODE2_RX_MAX_ATTEMPTS`） |
| 记录 | 每次尝试写入 CSV `Attempt` 列（1, 2, …）；BER 统计仍取**最后一次** |

代码：`needs_mode2_high_rx_retry()`。阈值 `2.2` 高于 §3 边界 `1.876`，用于剔除异常偏高的模拟读数。

### 4b. Mode 2 额外重发（列电流绝对值过低）

Mode 2 **批量 / 单帧**在 §3、§4 之外增加：

| 项目 | 规则 |
|------|------|
| 条件 | **8 路任意一路** 解析后 **\|I_col\| < 0.06** V（严格小于，不含 0.06） |
| 动作 | 重发同一 TX |
| 上限 | 最多 **5 次收发**（含首次；`MODE2_RX_MAX_ATTEMPTS`） |
| 记录 | 每次尝试写入 CSV `Attempt` 列；BER 统计仍取**最后一次** |

代码：`needs_mode2_low_abs_rx_retry()`。用于剔除接近零点的读数，避免符号判决不稳定。

### 5. `RecvHex` 与 raw 的对应

| 字段 | 含义 |
|------|------|
| `RecvHex` | 当次 RX **17 字节** 空格分隔大写 hex（`format_hex(rx_frame)`） |
| 与 `Out[]` | 同一帧：byte0 → `IterNum`；byte1–16 按 §1 拆 8×raw → §2 公式得 `Out[0..7]` |
| 手工验算 | 取 CHk 两个字节，算 `raw` → 代入公式，应等于表中 `Out[k-1]`（浮点误差 ±0.001 内） |

**示例**（CH1 字节对 `09 17`）：

```
raw = 0x917 = 2327
I_col = 2.5 − 2327×5/4096 ≈ +0.341 V
```

若 `RecvHex` 中某路字节对很小（如 `00 00`–`01 FF`），对应 raw < 511，**必触发 §3 重发**（在重试预算内）。

### 6. 为何测后表常见 `Out ≈ +2.5`

| 现象 | 原因 |
|------|------|
| 实测行 `Out[0..3]` 接近 **+2.5** | 对应 **raw ≈ 0**：芯片列电流读数仍在正向高端，**未硬件收敛** |
| 同一帧多行 `Attempt=1,2,…` | §3 或 §4 触发的中间尝试；浅紫 / 多行表示发生过重发 |
| 最终行仍 ≈ +2.5 | 6 次 TX 后仍 `raw < 0x1FF`：工具**仍用最后一次 RX** 写表并做 bit 比对，`HardwareConverged=N` |
| 与仿真 `Out` 差很大 | 仿真行是 MATLAB 参考；未收敛实测 raw 靠近 0 时十进制天然落在 **+2.5** 附近，**不代表公式错误** |

**调试顺序建议**：先看 `RecvHex` 中 CH1–4 四组字节是否均 ≥ `01 FF`；再查 `Out[0..3]` 是否均 ≤ ~1.876；Mode 2 再查是否有路 > 2.2 或 \|Out[i]\| < 0.06。

### 7. 代码索引

| 职责 | 模块 |
|------|------|
| raw ↔ I_col | `protocol.codec.raw_to_column_current` |
| CH1–4 raw ≥ 0x1FF | `protocol.validator.needs_retry` |
| Mode 2 I_col > 2.2 | `protocol.validator.needs_mode2_high_rx_retry` |
| Mode 2 \|I_col\| < 0.06 | `protocol.validator.needs_mode2_low_abs_rx_retry` |
| 收发与重试循环 | `comm.serial_worker.SerialWorker._do_send` |
| 写回 `Out[]` / `RecvHex` | `analysis.aggregate.fill_measured`、`csv_loader` |

验证脚本：`scripts/verify_sign_formula.py`（公式与样例行）、`scripts/test_mode2_rx_retry.py`（Mode 2 高超限 / 低绝对值重发）。

---

## 裁决模式（Mode 1 / 2 / 3 批量重发）

PC 侧在每次 TX→RX 后按模式决定是否**重发同一 TX 帧**。Mode 1 与 Mode 3 规则相同；Mode 2 在相同硬件收敛规则之上增加列电流门限。

### Mode 1 / Mode 3

| 项目 | 规则 |
|------|------|
| 检查通道 | **CH1–CH4**（`Out[0..3]` 对应 ADC raw）；CH5–CH8 不参与 |
| 未收敛 | 任一路 **raw < 0x1FF**（511）→ 重发 |
| 已收敛 | CH1–4 **全部 raw ≥ 0x1FF** → 停止重发 |
| 次数上限 | 默认 **5 次重发**（共 **6 次** TX 机会，含首次） |
| BER 比对 | **CH1–4**（Mode3 仅 **CH1–2**）`chip_value_to_bit(I_col)` vs CSV **InfoBit** |
| InfoBit 真值 | CSV 仿真行 **InfoBit[0..3]**（Mode3 为 `[0..1]`） |
| CodedBit 导出 | 仿真行：`CodedBit[i]` = `Out[i]` 硬判（<0→1，≥0→0）；实测行：对**实测 Out** 同样硬判 |

代码：`needs_retry()`、`SerialWorker._do_send()`（非 Mode2 批量时 `max_attempts = max_retries + 1`）。

### Mode 2

在 Mode 1 硬件收敛规则 **之外**，批量测试还检查：

| 条件 | 规则 | 动作 |
|------|------|------|
| 硬件未收敛 | CH1–4 任一路 raw < 0x1FF | 重发（与 Mode1 相同） |
| 列电流过高 | **8 路任意** `I_col > 2.2` V | 重发 |
| 列电流过低 | **8 路任意** `\|I_col\| < 0.06` V（严格小于） | 重发 |
| 次数上限 | 最多 **5 次收发**（含首次；`MODE2_RX_MAX_ATTEMPTS`） | 仍用**最后一次** RX 写表与 BER |

**InfoBit / BER（Mode2 专用）**

- CSV 仿真行 **InfoBit** = MATLAB 真值（列保留，**不参与 BER**）
- 实测 **InfoBit 导出** = `G_decode(实测 Out[0..7])`（列保留，**不参与 BER**）
- **实测 BER** = `chip_value_to_bit(实测 Out[i])` vs `chip_value_to_bit(Sim Out[i])`，**仅 i ∈ {3,5,6,7}**
- **无参考 BER 曲线**（Mode2 图表仅实测 BER）
- **CodedBit 导出**：仿真/实测行对 **Out[0..7]** 做符号硬判（8 路均导出；BER 仅用 Out[3,5,6,7]）

代码：`needs_mode2_high_rx_retry()`、`needs_mode2_low_abs_rx_retry()`、`mode2_coded_bits_from_outputs()`。

### CodedBit vs InfoBit（新数据集）

| 列 | 来源 |
|----|------|
| **InfoBit[0..3]** | CSV 给定（列保留；Mode2 实测行 G 解码导出，**BER 不用**） |
| **CodedBit[0..7]** | 导出时由 **Out[0..7]** 计算：Out < 0 → 1，Out ≥ 0 → 0（Mode2 BER 仅用 `[3,5,6,7]`） |

BER 图表：Mode1/3 按 **CodeBit 比对**；Mode2 按 **Out[3,5,6,7] CodeBit**（实测 vs Sim）。SNR 聚合 `analyze_by_snr()` 按 CSV 中实际 **EbNo_dB** 分组；**图表分母** 每 SNR 至多 **1000 帧**（`FRAMES_PER_SNR`，见 `docs/批量测试可视化分析.md` §2.6）。
