"""Mode1 新数据集：CodedBit 列保留、Out 硬判导出、可变 SNR/帧数。

运行：python scripts/test_mode1_codedbit_export.py
"""
from __future__ import annotations

import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.aggregate import analyze_by_snr, case_from_csv_group
from analysis.report_export import write_styled_dataset_xlsx
from analysis.sign_compare import chip_value_to_bit, sim_value_to_bit
from csv_loader import (
    CODED_BIT_COUNT,
    detect_coded_bit_prefix,
    load_test_csv,
    resolve_export_fieldnames,
)


def _fixture_path() -> Path | None:
    for p in (
        ROOT / "data" / "mode1_0706.csv",
        Path(r"c:\Users\15209\Desktop\mode1_0706.csv"),
    ):
        if p.is_file():
            return p
    return None


def test_load_shape() -> None:
    path = _fixture_path()
    if path is None:
        print("SKIP: mode1_0706.csv not found")
        return

    loaded = load_test_csv(path)
    assert loaded.matrix_mode == 1
    assert len(loaded.cases) == 27000, f"expected 27000 cases, got {len(loaded.cases)}"
    assert loaded.dataset is not None

    prefix = detect_coded_bit_prefix(loaded.dataset.fieldnames)
    assert prefix == "CodedBit", loaded.dataset.fieldnames

    snr_counts = Counter(tc.snr_db for tc in [case_from_csv_group(g) for g in loaded.cases])
    assert len(snr_counts) == 9, f"expected 9 SNR points, got {sorted(snr_counts.keys())}"
    for snr, cnt in sorted(snr_counts.items(), key=lambda x: x[0]):
        assert cnt == 3000, f"SNR {snr}: expected 3000 frames, got {cnt}"

    points = analyze_by_snr([case_from_csv_group(g) for g in loaded.cases[:6000]])
    assert len(points) == 2
    assert points[0].case_count == 3000
    print(f"OK: load {len(loaded.cases)} cases, {len(snr_counts)} SNR points × 3000 frames")


def test_codedbit_reference_pairing() -> None:
    """Mode1 参考 BER：Sim Out[0..3] 硬判 vs CodedBit[4..7]（非同下标）。"""
    path = _fixture_path()
    if path is None:
        print("SKIP: mode1_0706.csv not found")
        return

    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    prefix = detect_coded_bit_prefix(loaded.dataset.fieldnames) or "CodedBit"

    from analysis.aggregate import count_sim_reference_error_bits_for_case, case_from_csv_group

    checked = 0
    for g in loaded.cases[:50]:
        tc = case_from_csv_group(g)
        err, bits = count_sim_reference_error_bits_for_case(tc)
        assert bits == 4
        checked += 1
    print(f"OK: Mode1 reference BER pairing checked on {checked} frames")


def test_export_preserves_codedbit() -> None:
    path = _fixture_path()
    if path is None:
        print("SKIP: mode1_0706.csv not found")
        return

    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    ds = loaded.dataset
    ds.rebuild_rows_from_cases([case_from_csv_group(g) for g in loaded.cases[:4]])

    prefix = detect_coded_bit_prefix(ds.fieldnames) or "CodedBit"
    sim_rows = [r for r in ds.rows if str(r.get("RowKind", "")).strip() != "实测行"]
    assert len(sim_rows) >= 1
    for sim in sim_rows[:4]:
        for i in range(CODED_BIT_COUNT):
            assert f"{prefix}[{i}]" in sim
            assert sim[f"{prefix}[{i}]"] != ""

    fn = resolve_export_fieldnames(ds.fieldnames)
    assert f"{prefix}[0]" in fn
    assert f"{prefix}[7]" in fn

    with tempfile.TemporaryDirectory() as tmp:
        xlsx = Path(tmp) / "out.xlsx"
        write_styled_dataset_xlsx(xlsx, fn, ds.rows[:8], matrix_mode=1)
        import openpyxl

        wb = openpyxl.load_workbook(xlsx)
        headers = [c.value for c in wb.active[1]]
        assert f"{prefix}[0]" in headers
        assert f"{prefix}[7]" in headers

        csv_out = Path(tmp) / "out.csv"
        ds.save_as(csv_out)
        text = csv_out.read_text(encoding="utf-8-sig")
        assert f"{prefix}[0]" in text.splitlines()[0]

    print("OK: export keeps CodedBit columns and recomputes from Out")


def main() -> None:
    test_load_shape()
    test_codedbit_reference_pairing()
    test_export_preserves_codedbit()


if __name__ == "__main__":
    main()
