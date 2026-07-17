"""EVB serial protocol frame encoder/decoder.



TX (PC → chip): 25 bytes = 0xAA + 12 × (2 bytes per DAC channel)

  线序（大端，见 docs/PROTOCOL_UART.md §4）：

    - 帧头 0xAA

    - 12 组 × 2 字节，每组 12-bit DAC（高 4 bit + 低 8 bit）

    - CH1 首字节高 4 bit = Mode（A1 批量测试固定 1）；低 4 bit = DAC[11:8]

    - CH1 次字节 = DAC[7:0]

    - CH2–12 首字节高 4 bit = 0（沿用模式，不改变芯片矩阵模式）



RX (chip → PC): 17 bytes = 1 byte iteration count + 8 × (2 bytes per ADC channel)

  线序（大端，见 docs/PROTOCOL_UART.md §5.1）：

    - byte0 = 迭代次数编码（非 Mode）；迭代次数 = byte0 + 1

    - 8 路 ADC，每路 2 字节：byte1 为高字节、byte2 为低字节

    - 每路首字节高 4 bit = Mode（硬件通常为 0 = 沿用，勿改芯片模式）

    - 低 12 bit = ADC 原始值：raw = (byte1 & 0x0F) << 8 | byte2

    - 等价于大端 16 bit 取低 12 bit：((byte1 << 8) | byte2) & 0x0FFF

    - 收敛判定：12-bit raw ≥ 0x2FF（CH1–8，见 is_recv_valid）

    - 列电流：I_col = ((raw/4096×5)−2.5)×(−1)（见 raw_to_column_current；中点 raw=2048 → 0）

"""



from __future__ import annotations



FRAME_HEADER = 0xAA

TX_FRAME_LEN = 25

RX_FRAME_LEN = 17



DAC_MAX = 0xFFF

DAC_MIN_VALID = 0x2FF  # 收敛阈值：12-bit raw 须 ≥ 0x2FF（回传 CH1–8）

MAX_RETRY = 5



TX_VOLTAGE_REF = 4.096  # 行电压满量程 (V)

TX_MID_VOLTAGE = 2.5  # testdata In[i] 相对此中点偏移 → 行电压

# RX 列电流（InfoBit 符号比对）：
#   I_col = ((XXX / 4096 × RX_CURRENT_SCALE) − RX_CURRENT_MID) × (−1)
#   XXX = 12-bit ADC raw；等价于 2.5 − (raw/4096×5)，但代码与文档采用上式显式形式。
# raw=2048 → I_col=0；raw<2048 为正、raw>2048 为负。
# 实测 bit 规则（chip_value_to_bit）：I_col<0→1，零或正→0；与 CSV InfoBit 比对。

RX_CURRENT_SCALE = 5.0
RX_CURRENT_MID = 2.5



MODE_LABELS: dict[int, str] = {

    0: "沿用",

    1: "矩阵模式1",

    2: "矩阵模式2",

    3: "矩阵模式3",

}





def _clamp12(value: int) -> int:

    return max(0, min(DAC_MAX, int(value)))





def raw_to_row_voltage(raw: int) -> float:

    """TX 12-bit DAC 码 → 忆阻器阵列行电压 (V)。



    公式：V_row = (raw / 4096) × 4.096

    """

    return (raw / 4096.0) * TX_VOLTAGE_REF





def row_voltage_to_raw(v_row: float) -> int:

    """行电压 (V) → 12-bit DAC 码。"""

    return max(0, min(DAC_MAX, round(v_row / TX_VOLTAGE_REF * 4096)))





def in_value_to_row_voltage(in_val: float) -> float:

    """testdata In[i] 归一化浮点 → 行电压 (V)。



    CSV 中 In[i] 为相对 2.5 V 中点的偏移，映射后 clamp 至 [0, 4.096] V。

    """

    v_row = TX_MID_VOLTAGE + in_val

    return max(0.0, min(TX_VOLTAGE_REF, v_row))





def raw_to_column_current(raw: int) -> float:

    """RX 12-bit ADC 码 → 列电流读数（供 InfoBit 符号比对）。



    公式：I_col = ((XXX / 4096 × RX_CURRENT_SCALE) − RX_CURRENT_MID) × (−1)

    XXX = 12-bit ADC raw。

    """

    return ((raw / 4096.0 * RX_CURRENT_SCALE) - RX_CURRENT_MID) * (-1.0)





def column_current_to_raw(i_col: float) -> int:

    """列电流 → 12-bit ADC 码（raw_to_column_current 的逆变换）。



    由 I_col = ((raw/4096×S)−M)×(−1) 得 raw = (M − I_col) / S × 4096。

    """

    raw = round((RX_CURRENT_MID - i_col) / RX_CURRENT_SCALE * 4096.0)

    return max(0, min(DAC_MAX, raw))





def format_adc_bytes_hex(raw: int, mode_nibble: int = 0) -> str:

    """仿真参考：12-bit ADC 码 → RX 帧中该路 2 字节 hex（大端）。"""

    val = _clamp12(raw)

    high = (mode_nibble << 4) | ((val >> 8) & 0x0F)

    low = val & 0xFF

    return f"{high:02X} {low:02X}"





def raw_to_tx_voltage(raw: int) -> float:

    """兼容旧名：等同 raw_to_row_voltage。"""

    return raw_to_row_voltage(raw)





def tx_raw_to_delta_v(raw: int) -> float:

    """已弃用：旧 ΔV 相对 2.5 V 偏移，请改用 raw_to_row_voltage。"""

    return raw_to_row_voltage(raw) - TX_MID_VOLTAGE





def build_tx_frame(channels: list[int], mode: int = 1) -> bytes:

    """组 25 字节 TX 帧：AA + 12 组 × 2 B。



    CH1 高字节高 4 bit = Mode（A1 批量固定 1）；CH2–12 高 4 bit = 0（沿用）。

    每组 12-bit DAC：high = (mode_nibble << 4) | DAC[11:8], low = DAC[7:0]。

    """

    if len(channels) != 12:

        raise ValueError(f"Expected 12 channels, got {len(channels)}")



    matrix_mode = mode & 0x03

    frame = bytearray(TX_FRAME_LEN)

    frame[0] = FRAME_HEADER



    for i, raw in enumerate(channels):

        val = _clamp12(raw)

        mode_nibble = matrix_mode if i == 0 else 0

        high_byte = (mode_nibble << 4) | ((val >> 8) & 0x0F)

        low_byte = val & 0xFF

        frame[1 + i * 2] = high_byte

        frame[2 + i * 2] = low_byte



    return bytes(frame)





def iteration_from_rx_byte0(b: int) -> int:
    """RX byte0 → 芯片迭代次数：hex2dec(byte0) + 1。"""
    return (b & 0xFF) + 1


def parse_rx_frame(data: bytes) -> dict:

    """解析 17 字节 RX：byte0→迭代次数(byte0+1) + 8×12-bit ADC（大端 2 字节/路）。"""

    if len(data) < RX_FRAME_LEN:

        raise ValueError(f"RX frame too short: {len(data)} bytes (need {RX_FRAME_LEN})")



    iteration = iteration_from_rx_byte0(data[0])

    outputs: list[dict] = []



    for i in range(8):

        high = data[1 + i * 2]

        low = data[2 + i * 2]

        raw = ((high << 8) | low) & 0xFFF

        current = raw_to_column_current(raw)

        outputs.append({"raw": raw, "current": current, "voltage": current})



    return {"iteration": iteration, "outputs": outputs}





def is_recv_valid(dacs: list[int], threshold: int = DAC_MIN_VALID, num_channels: int = 8) -> bool:

    """前 num_channels 路 raw 均 ≥ threshold 视为硬件收敛（默认检 CH1–8）。"""

    check = dacs[:num_channels]

    return bool(check) and all(int(d) >= threshold for d in check)





def decode_tx_frame(data: bytes) -> dict:

    """Decode 25-byte TX frame (AA + 12×2 B) into per-channel fields.



    CH1 high nibble = Mode; CH2–12 high nibble 0 = 沿用.

    Each channel: 12-bit dac_raw = (high_byte & 0x0F) << 8 | low_byte.

    """

    if len(data) < TX_FRAME_LEN:

        raise ValueError(f"TX frame too short: {len(data)} bytes (need {TX_FRAME_LEN})")



    header = data[0]

    channels: list[dict] = []

    frame_mode = 0



    for i in range(12):

        high = data[1 + i * 2]

        low = data[2 + i * 2]

        mode_nibble = (high >> 4) & 0x0F

        dac_hi = high & 0x0F

        dac_raw = (dac_hi << 8) | low

        if i == 0:

            frame_mode = mode_nibble & 0x03



        channels.append(

            {

                "index": i + 1,

                "bytes_hex": f"{high:02X} {low:02X}",

                "mode_nibble": mode_nibble,

                "mode_label": MODE_LABELS.get(mode_nibble & 0x03, f"?{mode_nibble}")

                if i == 0

                else "沿用",

                "dac_raw": dac_raw,

                "row_voltage": raw_to_row_voltage(dac_raw),

            }

        )



    return {

        "header": header,

        "header_ok": header == FRAME_HEADER,

        "mode": frame_mode,

        "mode_label": MODE_LABELS.get(frame_mode, f"?{frame_mode}"),

        "channels": channels,

        "raw_hex": format_hex(data),

    }





def decode_rx_frame(data: bytes) -> dict:

    """解码 17 字节 RX：迭代次数 + 8 路列电流；converged 看 CH1–8 raw ≥ 0x2FF。"""

    if len(data) < RX_FRAME_LEN:

        raise ValueError(f"RX frame too short: {len(data)} bytes (need {RX_FRAME_LEN})")



    iteration = iteration_from_rx_byte0(data[0])

    outputs: list[dict] = []

    raws: list[int] = []



    for i in range(8):

        high = data[1 + i * 2]

        low = data[2 + i * 2]

        mode_nibble = (high >> 4) & 0x0F

        adc_raw = ((high << 8) | low) & 0xFFF

        i_col = raw_to_column_current(adc_raw)

        raws.append(adc_raw)

        outputs.append(

            {

                "index": i + 1,

                "bytes_hex": f"{high:02X} {low:02X}",

                "mode_nibble": mode_nibble,

                "raw": adc_raw,

                "current": i_col,

                "sign": "+" if i_col >= 0 else "-",

                "valid": adc_raw >= DAC_MIN_VALID,

                "judged": i < 4,

            }

        )



    return {

        "iteration": iteration,

        "outputs": outputs,

        "converged": is_recv_valid(raws),

        "raw_hex": format_hex(data),

    }





def format_tx_decode(data: bytes) -> str:

    """Human-readable TX decode for logs / GUI."""

    d = decode_tx_frame(data)

    lines = [

        f"【发送 {TX_FRAME_LEN}B】{d['raw_hex']}",

        f"  帧头 0x{d['header']:02X} {'(AA ✓)' if d['header_ok'] else '(非 AA ✗)'}",

        f"  矩阵模式 {d['mode']} ({d['mode_label']}) — 编码于 CH1 高字节高 4 bit",

        "",

    ]

    for ch in d["channels"]:

        prefix = f"Mode={ch['mode_label']}, " if ch["index"] == 1 else ""

        lines.append(

            f"  CH{ch['index']:2d}  {ch['bytes_hex']}  "

            f"{prefix}DAC=0x{ch['dac_raw']:03X}({ch['dac_raw']:4d})  "

            f"V_row={ch['row_voltage']:.4f} V"

        )

    return "\n".join(lines)





def format_rx_decode(data: bytes) -> str:

    """Human-readable RX decode for logs / GUI."""

    d = decode_rx_frame(data)

    conv = "已收敛 ✓" if d["converged"] else f"未收敛 ✗ (需 raw≥0x{DAC_MIN_VALID:03X})"

    lines = [

        f"【接收 {RX_FRAME_LEN}B】{d['raw_hex']}",

        f"  迭代次数 {d['iteration']}  |  {conv}",

        "",

    ]

    for ch in d["outputs"]:

        if ch.get("judged", True):

            valid_mark = "✓" if ch["valid"] else "✗"

        else:

            valid_mark = "参考"

        lines.append(

            f"  CH{ch['index']}  {ch['bytes_hex']}  "

            f"ADC=0x{ch['raw']:03X}({ch['raw']:4d})  "

            f"I_col={ch['current']:+.6f}  符号{ch['sign']}  {valid_mark}"

        )

    return "\n".join(lines)





def format_hex(data: bytes, sep: str = " ") -> str:

    """Format bytes as uppercase hex string."""

    return sep.join(f"{b:02X}" for b in data)





def parse_cmd(value: str | int) -> int:

    """Parse a byte value from decimal or hex string (legacy CSV / UI)."""

    if isinstance(value, int):

        return value & 0xFF

    text = str(value).strip()

    if text.lower().startswith("0x"):

        return int(text, 16) & 0xFF

    return int(text) & 0xFF





def parse_mode(value: str | int) -> int:

    """Parse matrix mode 0–3 for CH1 high nibble."""

    return parse_cmd(value) & 0x03





def resolve_tx_matrix_mode(mode: int, default_matrix_mode: int = 1) -> int:

    """Resolve CH1 high nibble for TX encoding.



    Explicit 1/2/3 select that matrix mode. Nibble 0 (沿用) maps to

    ``default_matrix_mode`` — e.g. mode-2 batch testing treats AA 0X as mode 2.

    """

    n = parse_mode(mode)

    if n == 0:

        return parse_mode(default_matrix_mode)

    return n

