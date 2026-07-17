"""芯片符号判决与 CSV 实测行 InfoBit 回填链路冒烟测试。

本冒烟测试验证芯片符号判决与 CSV 实测行 InfoBit 回填链路：

1）chip_value_to_bit() 遵循 ≥0→0 / <0→1 判决规则；
2）apply_bit_compare() 正确生成 chip_bits；
3）Dataset.update_measured() 将 chip_bits 写回实测行的 InfoBit[0..3]；
4）save_as() 能正确持久化字段。

覆盖逻辑层、数据模型层与文件 IO 层，属于端到端基础校验。

Author: Xander
Date: 2026-06-30
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.aggregate import CaseRecord, apply_bit_compare
from analysis.sign_compare import chip_value_to_bit
from csv_loader import load_test_csv


def test_chip_value_to_bit() -> None:
    """逻辑层：验证 chip_value_to_bit 符号判决规则（≥0→0，<0→1）。"""
    # 负值 → bit 1
    assert chip_value_to_bit(-0.5) == 1
    # 正值 → bit 0
    assert chip_value_to_bit(0.5) == 0
    # 边界值 0.0 归入 ≥0，→ bit 0
    assert chip_value_to_bit(0.0) == 0
    print("ok: chip_value_to_bit mapping")


def test_csv_measured_infobit() -> None:
    """端到端：apply_bit_compare → update_measured → save_as 全链路。"""
    # --- 准备：加载 CSV 测试夹具（文件 IO 层入口）---
    path = ROOT / "data" / "mode1.csv"
    if not path.is_file():
        path = ROOT / "data" / "testdata.csv"
    if not path.is_file():
        print("skip: no CSV fixture")
        return

    loaded = load_test_csv(path)
    assert loaded.dataset is not None

    # --- 数据模型层：构造含实测电流与期望 InfoBit 的用例记录 ---
    tc = CaseRecord(
        name="test",
        mode=1,
        channels=[2500] * 12,
        info_bits=[1, 0, 1, 0],
        actual_currents=[0.2, -0.2, 0.3, -0.1, 0.0, 0.0, 0.0, 0.0],
        iteration_count=5,
        rx_hex="05 FF",
        hardware_converged=True,
        success=True,
    )

    # --- 逻辑层：apply_bit_compare 将 CH1–4 实测电流转为 chip_bits ---
    apply_bit_compare(tc)
    # 期望 [0,1,0,1]：0.2→0, -0.2→1, 0.3→0, -0.1→1
    assert tc.chip_bits == [0, 1, 0, 1]

    # --- 数据模型层：update_measured 将 chip_bits 回填至实测行 InfoBit[0..3] ---
    loaded.dataset.update_measured(0, tc)
    row = loaded.dataset.rows[loaded.dataset.meas_row_index(0)]
    assert row["InfoBit[0]"] == "0"
    assert row["InfoBit[1]"] == "1"
    assert row["InfoBit[2]"] == "0"
    assert row["InfoBit[3]"] == "1"

    # --- 文件 IO 层：save_as 持久化后 CSV 仍含 InfoBit 列 ---
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.csv"
        loaded.dataset.save_as(out)
        text = out.read_text(encoding="utf-8-sig")
        assert "InfoBit[0]" in text

    print("ok: CSV measured row InfoBit export")


if __name__ == "__main__":
    test_chip_value_to_bit()
    test_csv_measured_infobit()
