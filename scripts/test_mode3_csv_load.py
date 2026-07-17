#!/usr/bin/env python3
"""Mode3 CSV 加载回归测试 — matrix_mode=3、InfoBit[0..1]、CH1–2 比对护栏。"""

from __future__ import annotations

import csv
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.aggregate import case_from_csv_group
from analysis.sign_compare import compare_channels_for_mode, sim_value_to_bit
from csv_loader import infer_matrix_mode_from_path, load_test_csv
from protocol.codec import build_tx_frame, resolve_tx_matrix_mode


def main() -> None:
    path = ROOT / "data" / "mode3(1).csv"
    if not path.is_file():
        print(f"SKIP: {path} not found")
        return

    assert infer_matrix_mode_from_path(path) == 3
    assert infer_matrix_mode_from_path("model3.csv") == 3
    assert infer_matrix_mode_from_path("mode1.csv") == 1
    assert infer_matrix_mode_from_path("mode2.csv") == 2

    loaded = load_test_csv(path)
    assert loaded.matrix_mode == 3
    assert len(loaded.cases) == 7000, f"expected 7000 cases, got {len(loaded.cases)}"

    first = loaded.cases[0]
    assert first["mode"] == 3
    assert first["info_bits"] is not None
    assert len(first["info_bits"]) == 2
    for i in range(2):
        assert first["info_bits"][i] == sim_value_to_bit(first["sim_outputs"][i])

    with path.open(encoding="utf-8-sig") as f:
        first_row = next(csv.DictReader(f))
    expected_ib = [int(first_row[f"InfoBit[{i}]"]) for i in range(2)]
    assert first["info_bits"] == expected_ib

    # 文件名不含 mode3 时，表头仅 InfoBit[0..1] 仍应识别为 mode3
    with tempfile.TemporaryDirectory() as td:
        generic = Path(td) / "batch.csv"
        shutil.copy(path, generic)
        loaded_generic = load_test_csv(generic)
        assert loaded_generic.matrix_mode == 3
        assert len(loaded_generic.cases[0]["info_bits"]) == 2

    tc = case_from_csv_group(first)
    assert tc.mode == 3
    assert compare_channels_for_mode(tc.mode) == 2

    frame = build_tx_frame(tc.channels, resolve_tx_matrix_mode(0, 3))
    ch1_high = frame[1]
    assert (ch1_high >> 4) & 0x0F == 3, f"CH1 mode nibble should be 3, got {(ch1_high >> 4) & 0x0F}"
    for ch_idx in range(1, 12):
        high = frame[1 + ch_idx * 2]
        assert (high >> 4) & 0x0F == 0, f"CH{ch_idx + 1} high nibble should be 0"

    print("OK: mode3(1).csv → matrix_mode=3, InfoBit[0..1], compare CH1–2")


if __name__ == "__main__":
    main()
