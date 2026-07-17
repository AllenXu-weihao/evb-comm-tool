"""迭代次数公式冒烟测试。

本文件验证 EVB 协议中 RX 帧 byte0 与 iteration 的映射关系：
    iteration_count = RX_byte0 + 1

该公式是协议层的基础约定，单独测试可在不构造完整帧的情况下
快速发现 off-by-one 错误；同时覆盖 codec 纯函数与 parse_rx_frame
整条解析路径，避免重构 codec 时 silently 破坏语义。

Author: Xander
Date: 2026-06-30
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol.codec import iteration_from_rx_byte0, parse_rx_frame, RX_FRAME_LEN


def test_iteration_from_rx_byte0() -> None:
    """纯数学映射：iteration = byte0 + 1，不涉及帧结构。

    覆盖边界值（0x00 → 1）与典型值，防止 off-by-one 错误。
    """
    cases = [(0x00, 1), (0x01, 2), (0x02, 3), (0x0A, 11)]
    for byte0, expected in cases:
        assert iteration_from_rx_byte0(byte0) == expected, f"byte0=0x{byte0:02X}"


def test_parse_rx_frame_iteration() -> None:
    """完整解析路径：最小合法 RX 帧，仅 byte0 有意义，其余填 0。

    验证 parse_rx_frame 返回的 iteration 字段符合高层 API 语义，
    防止 codec 重构时破坏 byte0 → iteration 的约定。
    """
    for byte0, expected in [(0x00, 1), (0x0A, 11)]:
        frame = bytes([byte0] + [0x00] * (RX_FRAME_LEN - 1))
        parsed = parse_rx_frame(frame)
        assert parsed["iteration"] == expected


if __name__ == "__main__":
    test_iteration_from_rx_byte0()
    test_parse_rx_frame_iteration()
    print("OK: iteration formula smoke test passed")
