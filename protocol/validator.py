"""RX 17 字节帧合法性校验与硬件收敛判定。

Author: Xander
Date: 2026-06-30

本模块提供 A1 模式下 RX 帧的两层校验接口，判定逻辑与 EVB A1 规格一致：

硬件收敛（一次 TX 25 B / RX 17 B）：
  - TX：12 路 DAC；RX：byte0 迭代次数 + 8 路 12-bit ADC（大端 2 字节/路）。
    芯片内部可迭代多轮；PC 侧仅检查返回的 12-bit raw 是否达标。
  - 收敛条件：CH1–8 的 raw 均 ≥ RETRY_THRESHOLD（0x2FF）。
  - 未收敛：任一路 raw < 0x2FF → 上层应重发同一 TX 帧。
  - bit PASS/FAIL 见 analysis/sign_compare.py（CodeBit：Mode1 Out[0..3]，Mode2 [3,5,6,7]，Mode3 [0,1]）。

needs_retry 与 validate_rx_frame 的一致性：
  - 二者均检查前 CONVERGE_CHANNELS（8）路，阈值均为 RETRY_THRESHOLD。
  - raw 提取方式与 protocol.codec.parse_rx_frame 相同（大端 12-bit，& 0xFFF）。
  - validate_rx_frame(data) 在 UART/字节层校验长度并解析 raw；返回 (False, msg) 表示帧非法或未收敛。
  - needs_retry(outputs) 在已解析的 outputs 上判定；返回 True 等价于 validate_rx_frame 会失败。
  - 即：not needs_retry(outputs) ⟺ validate_rx_frame(rx_bytes) 在长度足够时返回 (True, "OK")。
  - 上层 comm 层（serial_worker）使用 needs_retry；validate_rx_frame 供字节流入口或独立校验场景。
"""

from __future__ import annotations

RETRY_THRESHOLD = 0x2FF  # 767 — CH1–8 ADC raw 须达到此值方视为收敛；Out≈2.5 对应 raw≈0，见 docs/SIM_TO_REAL.md / 软件工程视角
CONVERGE_CHANNELS = 8  # 回传 8 路均参与硬件收敛重试


def needs_retry(outputs: list[dict], threshold: int = RETRY_THRESHOLD) -> bool:
    """判定已解析 RX 是否需要重发（上层 retry 入口）。

    检查 outputs 前 CONVERGE_CHANNELS 路（CH1–8）的 ``raw`` 字段；
    任一路 ``raw < threshold`` 返回 True，全部达标返回 False。

    与 validate_rx_frame 逻辑互补：本函数 True ⟺ 后者在等长帧上会返回 False。
    """
    for o in outputs[:CONVERGE_CHANNELS]:
        if o["raw"] < threshold:
            return True
    return False


def validate_rx_frame(
    data: bytes,
    expected_len: int = 17,
    threshold: int = RETRY_THRESHOLD,
) -> tuple[bool, str]:
    """校验原始 RX 字节帧的长度与 CH1–8 收敛（UART/字节层入口）。

    Args:
        data: 原始 RX 字节流。
        expected_len: 期望帧长，默认 17 字节（A1 RX 帧）。
        threshold: 收敛阈值，默认 RETRY_THRESHOLD（0x2FF）。

    Returns:
        (True, "OK") 帧长足够且 CH1–8 raw 均 ≥ threshold；
        (False, msg) 帧长不足或未收敛（msg 含通道号或长度信息）。

    raw 解析与 parse_rx_frame 一致：byte[1+2i:3+2i] 大端 12-bit。
    与 needs_retry 判定范围相同，仅输入形态不同（bytes vs 已解析 outputs）。
    """
    if len(data) < expected_len:
        return False, f"帧长度不足: {len(data)}/{expected_len}"

    low_channels = []
    for i in range(CONVERGE_CHANNELS):
        raw = ((data[1 + i * 2] << 8) | data[2 + i * 2]) & 0xFFF
        if raw < threshold:
            low_channels.append(i + 1)

    if low_channels:
        return False, f"通道 {low_channels} 原始值 < 0x{threshold:03X}"

    return True, "OK"
