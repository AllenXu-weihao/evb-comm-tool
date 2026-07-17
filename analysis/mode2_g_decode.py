"""Mode 2 InfoBit 解码：hardout0 × G → mod 2 → hardout2 (1×8) → InfoBit[0..3]。

G 解码流程（参考/实测行 InfoBit 导出；真值来自 CSV 仿真行）：

  1. hardout0[i] = (Out[i] < 0) ? 1 : 0，i = 0..7（负→1，零/正→0）

  2. hardout1 = hardout0 @ G（1×8 × 8×8，逐元素整数求和，尚未 mod 2）

  3. hardout2[i] = hardout1[i] mod 2（奇→1，偶→0），i = 0..7

  4. InfoBit[k] = hardout2[idx_k]，k = 0..3；idx = (3, 5, 6, 7)

索引约定：InfoBit 仅 4 元素（1×4）；hardout2 为 8 元素（1×8）。
  InfoBit[0]=hardout2[3], InfoBit[1]=hardout2[5], InfoBit[2]=hardout2[6], InfoBit[3]=hardout2[7]

hardout1 列求和（0-based，h = hardout0）：

  hardout1[3] = h[3] + h[7]
  hardout1[5] = h[5] + h[7]
  hardout1[6] = h[6] + h[7]
  hardout1[7] = h[7]

G 为 Polar/RM 风格 8×8 系统矩阵 MODE2_G_MATRIX（列 3/5/6/7 满足上式）。

导出约定（Mode2 双行/帧，14000 行 / 7000 帧）：

  - **仿真行** Out = Sim Out；InfoBit = CSV 测试集自带真值（`expected_info_bits` / `info_bits`）
  - **实测行** Out = 芯片实测 Out；InfoBit = G_decode(实测 Out[0..7])

  BER：G_decode(实测) vs CSV 真值；参考 BER = G_decode(Sim) vs CSV 真值
"""

from __future__ import annotations


def _chip_value_to_bit(value: float) -> int:
    """Out 硬判：模拟量 >= 0 → 0；< 0 → 1（与 sign_compare.chip_value_to_bit 相同）。"""
    return 1 if value < 0 else 0

MODE2_G_MATRIX: list[list[int]] = [
    [1, 0, 0, 0, 0, 0, 0, 0],
    [1, 1, 0, 0, 0, 0, 0, 0],
    [1, 0, 1, 0, 0, 0, 0, 0],
    [1, 1, 1, 1, 0, 0, 0, 0],
    [1, 0, 0, 0, 1, 0, 0, 0],
    [1, 1, 0, 0, 1, 1, 0, 0],
    [1, 0, 1, 0, 1, 0, 1, 0],
    [1, 1, 1, 1, 1, 1, 1, 1],
]

# hardout2 切片 [3,5,6,7] → InfoBit[0..3]
MODE2_INFOBIT_INDICES = (3, 5, 6, 7)


def mode2_hardout0(analogs_8: list[float]) -> list[int]:
    """Step 1 — 硬判决：Out0–7 负→1，零/正→0（同 chip_value_to_bit）。"""
    padded = list(analogs_8[:8]) + [0.0] * max(0, 8 - len(analogs_8))
    return [_chip_value_to_bit(v) for v in padded[:8]]


def hardout_from_analogs(analogs_8: list[float]) -> list[int]:
    """Alias for :func:`mode2_hardout0` (legacy name)."""
    return mode2_hardout0(analogs_8)


def mode2_hardout1(hardout0: list[int], g: list[list[int]] | None = None) -> list[int]:
    """Step 2 — 整数矩阵乘：hardout1 = hardout0 @ G（逐列求和，**未** mod 2）。

    每列 col 为 sum(hardout0[row] * G[row][col] for row in 0..7)。
    InfoBit 相关列在 mod2 前的典型关系见模块 docstring。
    """
    matrix = g if g is not None else MODE2_G_MATRIX
    return [
        sum(hardout0[row] * matrix[row][col] for row in range(8))
        for col in range(8)
    ]


def mode2_hardout2(hardout1: list[int]) -> list[int]:
    """Step 3 — mod 2：hardout2[i] = hardout1[i] % 2（奇→1，偶→0）。"""
    return [s % 2 for s in hardout1]


def mode2_decode_u(analogs_8: list[float], g: list[list[int]] | None = None) -> list[int]:
    """完整 G 解码，返回 8 位 hardout2 向量。"""
    hardout0 = mode2_hardout0(analogs_8)
    hardout1 = mode2_hardout1(hardout0, g)
    return mode2_hardout2(hardout1)


def mode2_decode_infobit(analogs_8: list[float], g: list[list[int]] | None = None) -> list[int]:
    """Step 4 — 取 hardout2[3,5,6,7]，映射为 InfoBit[0..3]。"""
    hardout0 = mode2_hardout0(analogs_8)
    hardout1 = mode2_hardout1(hardout0, g)
    hardout2 = mode2_hardout2(hardout1)
    return [hardout2[i] for i in MODE2_INFOBIT_INDICES]
