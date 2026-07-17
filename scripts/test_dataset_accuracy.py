"""数据集准确性与 CodeBit BER 口径回归测试。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.aggregate import (
    CaseRecord,
    count_measured_error_bits,
    count_sim_reference_error_bits,
    count_sim_reference_error_bits_for_case,
    sim_coded_bits_for_ber,
    meas_coded_bits_for_ber,
)
from analysis.dataset_accuracy import check_dataset_rows
from analysis.sign_compare import chip_value_to_bit, compare_frame
from csv_loader import (
    ROW_KIND_MEASURED,
    ROW_KIND_SIM,
    STANDARD_FIELDNAMES,
    resolve_export_fieldnames,
    _sim_csv_row_from_case,
    _attempt_to_csv_row,
)


def test_ber_uses_codedbit_not_infobit() -> None:
    tc = CaseRecord(
        name="t",
        mode=1,
        channels=[2500] * 12,
        # InfoBit 故意与 CodeBit 相反，若误用 InfoBit 会算错
        info_bits=[1, 1, 1, 1],
        coded_bits=[0, 0, 0, 0, 0, 0, 0, 0],
        sim_outputs=[0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        success=True,
        hardware_converged=True,
        actual_currents=[0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        rx_hex="AA",
        iteration_count=1,
    )
    assert sim_coded_bits_for_ber(tc) == [0, 0, 0, 0]
    assert meas_coded_bits_for_ber(tc) == [0, 0, 0, 0]
    assert count_measured_error_bits(tc) == 0

    tc2 = CaseRecord(
        name="t2",
        mode=1,
        channels=[2500] * 12,
        info_bits=[0, 0, 0, 0],
        coded_bits=[0, 0, 0, 0, 0, 0, 0, 0],
        sim_outputs=[0.5] * 8,
        success=True,
        hardware_converged=True,
        actual_currents=[-0.5, -0.5, -0.5, -0.5, 0.5, 0.5, 0.5, 0.5],
        rx_hex="BB",
        iteration_count=1,
    )
    assert count_measured_error_bits(tc2) == 4


def test_sim_codedbit_preserved_on_export() -> None:
    fn = resolve_export_fieldnames(["CodedBit[0]"])
    assert "CodedBit[0]" in fn
    tc = CaseRecord(
        name="s",
        mode=2,
        channels=[2500] * 12,
        sim_outputs=[0.5] * 8,  # 硬判全 0
        coded_bits=[1, 1, 1, 1, 1, 1, 1, 1],  # 测试集给定全 1
        info_bits=[0, 1, 0, 1],
        snr_db=0.0,
        frame_idx=1,
    )
    sim = _sim_csv_row_from_case(tc, fn)
    for i in range(8):
        assert sim[f"CodedBit[{i}]"] == "1", f"sim CodeBit[{i}] overwritten"


def test_legacy_expand_preserves_codedbit() -> None:
    """单行→双行展开不得用 Out 硬判覆盖测试集 CodeBit（监测误报根因）。"""
    from csv_loader import build_interleaved_rows_from_legacy

    old_fn = [
        "EbNo_dB",
        "FrameIdx",
        *[f"In[{i}]" for i in range(12)],
        *[f"Out[{i}]" for i in range(8)],
        *[f"CodedBit[{i}]" for i in range(8)],
        *[f"InfoBit[{i}]" for i in range(4)],
        "IterNum",
    ]
    # Out 全正 → 硬判 0；CodedBit 故意全 1（与硬判不一致）
    sim = {k: "" for k in old_fn}
    sim.update(
        {
            "EbNo_dB": "0",
            "FrameIdx": "8",
            **{f"Out[{i}]": "0.5" for i in range(8)},
            **{f"CodedBit[{i}]": "1" for i in range(8)},
        }
    )
    fn, rows, _ = build_interleaved_rows_from_legacy([sim], old_fn)
    assert rows[0]["RowKind"] == ROW_KIND_SIM
    for i in range(8):
        assert rows[0][f"CodedBit[{i}]"] == "1", (
            f"expand overwrote CodedBit[{i}] with Out hard decision"
        )
    assert "CodedBit[0]" in fn


def test_meas_infobit_empty_codedbit_hard() -> None:
    fn = resolve_export_fieldnames(["CodedBit[0]"])
    sim = {k: "" for k in fn}
    sim["RowKind"] = ROW_KIND_SIM
    currents = [0.5, -0.5, 0.5, -0.5, 0.5, -0.5, 0.5, -0.5]
    row = _attempt_to_csv_row(sim, fn, 1, "01 02", 1, currents, [], mode=2, hardware_converged=True)
    for i in range(4):
        assert row.get(f"InfoBit[{i}]", "") == ""
    for i, c in enumerate(currents):
        assert row[f"CodedBit[{i}]"] == str(chip_value_to_bit(c))


def test_accuracy_check_flags_meas_infobit() -> None:
    fn = resolve_export_fieldnames(["CodedBit[0]"])
    rows = [
        {k: "" for k in fn},
        {k: "" for k in fn},
    ]
    rows[0].update({"RowKind": ROW_KIND_SIM, "EbNo_dB": "0", "FrameIdx": "1", "Out[0]": "0.5", "CodedBit[0]": "0"})
    rows[1].update(
        {
            "RowKind": ROW_KIND_MEASURED,
            "Attempt": "1",
            "EbNo_dB": "0",
            "FrameIdx": "1",
            "Out[0]": "0.5",
            "CodedBit[0]": "0",
            "InfoBit[0]": "1",  # 应空
        }
    )
    for i in range(1, 8):
        rows[0][f"Out[{i}]"] = "0.5"
        rows[0][f"CodedBit[{i}]"] = "0"
        rows[1][f"Out[{i}]"] = "0.5"
        rows[1][f"CodedBit[{i}]"] = "0"
    rep = check_dataset_rows(rows, fn, mode=1)
    assert any("InfoBit" in i.field for i in rep.issues)


def test_sim_codedbit_tamper_detected() -> None:
    from analysis.dataset_accuracy import (
        build_source_sim_coded_map,
        check_export_rows_against_source,
        tamper_issues_only,
    )

    fn = resolve_export_fieldnames(["CodedBit[0]"])
    src_sim = {k: "" for k in fn}
    src_sim.update(
        {
            "RowKind": ROW_KIND_SIM,
            "EbNo_dB": "1",
            "FrameIdx": "7",
            **{f"Out[{i}]": "0.5" for i in range(8)},
            **{f"CodedBit[{i}]": "1" for i in range(8)},
        }
    )
    snap = build_source_sim_coded_map([src_sim])
    assert ("1", "7") in snap

    post_sim = dict(src_sim)
    post_sim["CodedBit[3]"] = "0"  # 非法改写
    post_meas = {k: "" for k in fn}
    post_meas.update(
        {
            "RowKind": ROW_KIND_MEASURED,
            "Attempt": "1",
            "EbNo_dB": "1",
            "FrameIdx": "7",
            **{f"Out[{i}]": "0.5" for i in range(8)},
            **{f"CodedBit[{i}]": "0" for i in range(8)},
        }
    )
    rep = check_export_rows_against_source(
        [post_sim, post_meas], fn, snap, mode=2
    )
    tampers = tamper_issues_only(rep)
    assert len(tampers) == 1
    assert "CodedBit[3]" in tampers[0].field


def test_compare_frame_mode1_codedbit() -> None:
    r = compare_frame(
        [0.5, 0.5, 0.5, 0.5, 0, 0, 0, 0],
        [0, 0, 0, 0],
        sim_outputs=[0.5] * 8,
        mode=1,
    )
    assert r["channel_errors"] == 0
    assert r["passed"]


def test_reference_ber_out_vs_specified_codedbit() -> None:
    """参考 BER = Sim Out 硬判 vs 指定 CodeBit（Mode1 交叉下标；Mode2 同下标）。"""
    tc_match = CaseRecord(
        name="match",
        mode=1,
        channels=[2500] * 12,
        sim_outputs=[0.1, -0.1, 0.2, -0.2, 0, 0, 0, 0],
        coded_bits=[0, 0, 0, 0, 0, 1, 0, 1],
    )
    err, bits = count_sim_reference_error_bits_for_case(tc_match)
    assert bits == 4
    assert err == 0

    tc_mismatch = CaseRecord(
        name="mismatch",
        mode=2,
        channels=[2500] * 12,
        sim_outputs=[0.1, 0.0, 0.0, -0.2, 0.0, 0.3, -0.4, 0.0],
        coded_bits=[1, 0, 0, 0, 0, 1, 1, 0],
    )
    err2, bits2 = count_sim_reference_error_bits_for_case(tc_mismatch)
    assert bits2 == 4
    assert err2 == 2
    ref_err, ref_bits, n_ref = count_sim_reference_error_bits([tc_match, tc_mismatch])
    assert n_ref == 2
    assert ref_bits == 8
    assert ref_err == 2


def test_reference_ber_mode3() -> None:
    """Mode3 参考/实测 BER：Out[0,1] 硬判 vs CodeBit[0,1]（同下标）。"""
    from analysis.sign_compare import ber_channel_pairs_for_mode

    assert ber_channel_pairs_for_mode(3) == ((0, 0), (1, 1))

    tc_match = CaseRecord(
        name="m3_match",
        mode=3,
        channels=[2500] * 12,
        sim_outputs=[0.5, -0.5, 0, 0, 0, 0, 0, 0],
        coded_bits=[0, 1, 0, 0, 0, 0, 0, 0],
        actual_currents=[0.5, -0.5, 0, 0, 0, 0, 0, 0],
        hardware_converged=True,
        rx_hex="aa",
        iteration_count=1,
    )
    assert sim_coded_bits_for_ber(tc_match) == [0, 1]
    assert meas_coded_bits_for_ber(tc_match) == [0, 1]
    assert count_measured_error_bits(tc_match) == 0
    err, bits = count_sim_reference_error_bits_for_case(tc_match)
    assert bits == 2 and err == 0

    tc_err = CaseRecord(
        name="m3_err",
        mode=3,
        channels=[2500] * 12,
        sim_outputs=[0.5, 0.5, 0, 0, 0, 0, 0, 0],
        coded_bits=[0, 0, 0, 0, 0, 0, 0, 0],
        actual_currents=[-0.5, 0.5, 0, 0, 0, 0, 0, 0],
        hardware_converged=True,
        rx_hex="bb",
        iteration_count=1,
    )
    assert count_measured_error_bits(tc_err) == 1


def test_trim_ok_rows_for_chart() -> None:
    """图表裁剪：每 SNR 按 FrameIdx 只保留前 FRAMES_PER_SNR 帧。"""
    from analysis.aggregate import FRAMES_PER_SNR
    from csv_loader import ROW_KIND_MEASURED, ROW_KIND_SIM, trim_ok_rows_for_chart

    rows: list[dict[str, str]] = []
    for snr in (0.0, 1.0):
        for fi in range(1, FRAMES_PER_SNR + 501):
            sim = {
                "RowKind": ROW_KIND_SIM,
                "EbNo_dB": f"{snr:g}",
                "FrameIdx": str(fi),
            }
            meas = {
                "RowKind": ROW_KIND_MEASURED,
                "EbNo_dB": f"{snr:g}",
                "FrameIdx": str(fi),
            }
            rows.extend([sim, meas])
    assert len(rows) == 2 * 2 * (FRAMES_PER_SNR + 500)
    trimmed = trim_ok_rows_for_chart(rows)
    assert len(trimmed) == 2 * 2 * FRAMES_PER_SNR
    for snr in (0.0, 1.0):
        fis = [
            int(r["FrameIdx"])
            for r in trimmed
            if r["RowKind"] == ROW_KIND_SIM and r["EbNo_dB"] == f"{snr:g}"
        ]
        assert len(fis) == FRAMES_PER_SNR
        assert fis[0] == 1
        assert fis[-1] == FRAMES_PER_SNR
        assert FRAMES_PER_SNR + 1 not in fis


def test_analyze_by_snr_caps_chart_at_1000() -> None:
    """图表聚合：每 SNR 仅前 FRAMES_PER_SNR 帧计入 BER / 迭代均值。"""
    from analysis.aggregate import FRAMES_PER_SNR, analyze_by_snr, ok_chart_frame_attempts

    cases = []
    for fi in range(1, 1501):
        cases.append(
            CaseRecord(
                name=f"f{fi}",
                mode=1,
                channels=[2500] * 12,
                sim_outputs=[0.5] * 8,
                coded_bits=[0] * 8,
                iter_ref=10,
                snr_db=0.0,
                frame_idx=fi,
                success=True,
                hardware_converged=True,
                actual_currents=[0.5] * 8,
                rx_hex="aa",
                iteration_count=20,
            )
        )
    pairs = ok_chart_frame_attempts(cases=cases)
    assert len(pairs) == FRAMES_PER_SNR
    points = analyze_by_snr(cases)
    assert len(points) == 1
    p = points[0]
    assert p.tested_count == FRAMES_PER_SNR
    assert p.channel_bits == FRAMES_PER_SNR * 4
    assert p.meas_iter_sum == 20 * FRAMES_PER_SNR
    assert p.ref_iter_sum == 10 * FRAMES_PER_SNR
    assert p.avg_iterations == 20.0
    assert p.avg_ref_iterations == 10.0


def test_analyze_by_snr_custom_cap() -> None:
    """图表聚合：max_per_snr 可配置（如 1300）。"""
    from analysis.aggregate import analyze_by_snr, ok_chart_frame_attempts

    cap = 1300
    cases = []
    for fi in range(1, 1501):
        cases.append(
            CaseRecord(
                name=f"f{fi}",
                mode=1,
                channels=[2500] * 12,
                sim_outputs=[0.5] * 8,
                coded_bits=[0] * 8,
                iter_ref=10,
                snr_db=0.0,
                frame_idx=fi,
                success=True,
                hardware_converged=True,
                actual_currents=[0.5] * 8,
                rx_hex="aa",
                iteration_count=20,
            )
        )
    pairs = ok_chart_frame_attempts(cases=cases, max_per_snr=cap)
    assert len(pairs) == cap
    points = analyze_by_snr(cases, max_per_snr=cap)
    assert points[0].tested_count == cap


def test_ok_frame_attempt_record_prefers_last_pass() -> None:
    """末次无误码 Attempt 优先于更晚的误码收敛 Attempt。"""
    from analysis.aggregate import AttemptRecord, CaseRecord, ok_frame_attempt_record

    tc = CaseRecord(
        name="mix",
        mode=1,
        channels=[2500] * 12,
        coded_bits=[0] * 8,
        sim_outputs=[0.1] * 8,
        attempt_records=[
            AttemptRecord(
                attempt=1,
                rx_hex="aa",
                iteration_count=1,
                actual_currents=[0.1] * 8,
                actual_raws=[0x300] * 8,
                chip_bits=[0] * 4,
                channel_results=[],
                match_count=4,
                channel_errors=0,
                passed=True,
                hardware_converged=True,
            ),
            AttemptRecord(
                attempt=2,
                rx_hex="bb",
                iteration_count=2,
                actual_currents=[-0.1] * 8,
                actual_raws=[0x300] * 8,
                chip_bits=[1] * 4,
                channel_results=[],
                match_count=0,
                channel_errors=4,
                passed=False,
                hardware_converged=True,
            ),
        ],
        hardware_converged=True,
        success=True,
    )
    ar = ok_frame_attempt_record(tc)
    assert ar is not None
    assert ar.attempt == 1


def test_batch_snr_cap_guard() -> None:
    from comm.batch_snr_cap import BatchSnrCapGuard

    g = BatchSnrCapGuard(cap=3, enabled=True)
    assert not g.is_snr_full(0.0)
    assert g.record_converged_frame(0.0) is False
    assert g.record_converged_frame(0.0) is False
    assert g.record_converged_frame(0.0) is True
    assert g.is_snr_full(0.0)
    assert g.consume_snr_completed() == 0.0


def main() -> None:
    test_ber_uses_codedbit_not_infobit()
    test_sim_codedbit_preserved_on_export()
    test_legacy_expand_preserves_codedbit()
    test_meas_infobit_empty_codedbit_hard()
    test_accuracy_check_flags_meas_infobit()
    test_sim_codedbit_tamper_detected()
    test_compare_frame_mode1_codedbit()
    test_reference_ber_out_vs_specified_codedbit()
    test_reference_ber_mode3()
    test_trim_ok_rows_for_chart()
    test_analyze_by_snr_caps_chart_at_1000()
    test_analyze_by_snr_custom_cap()
    test_ok_frame_attempt_record_prefers_last_pass()
    test_batch_snr_cap_guard()
    print("OK: dataset accuracy / CodeBit BER tests passed")


if __name__ == "__main__":
    main()
