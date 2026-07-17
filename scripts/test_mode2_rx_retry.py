"""回传 raw < 0x2FF 重试与样式 Excel 导出单元测试（无需串口）。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.aggregate import CaseRecord, case_from_csv_group, clear_measured, fill_measured, analyze_by_snr
from analysis.report_export import write_styled_dataset_xlsx
from analysis.sign_compare import compute_channel_ber_from_error_bits
from comm.serial_worker import RxAttempt, SendResult
from csv_loader import ROW_KIND_MEASURED, ROW_KIND_SIM, STANDARD_FIELDNAMES, _attempt_to_csv_row, load_test_csv
from protocol.codec import build_tx_frame
from protocol.validator import CONVERGE_CHANNELS, RETRY_THRESHOLD, needs_retry, validate_rx_frame


def _outputs_from_raws(raws: list[int]) -> list[dict]:
    return [{"current": 0.0, "raw": r} for r in raws]


def test_needs_retry_all_channels_2ff() -> None:
    ok = [RETRY_THRESHOLD] * CONVERGE_CHANNELS
    assert not needs_retry(_outputs_from_raws(ok))
    low = ok.copy()
    low[7] = RETRY_THRESHOLD - 1
    assert needs_retry(_outputs_from_raws(low))
    low_ch5 = ok.copy()
    low_ch5[4] = 0x1FF
    assert needs_retry(_outputs_from_raws(low_ch5))
    border = [RETRY_THRESHOLD - 1] + [RETRY_THRESHOLD] * 7
    assert needs_retry(_outputs_from_raws(border))


def test_validate_rx_frame_2ff() -> None:
    # 8 路均 0x300 (>= 0x2FF)
    data = bytes([0x01]) + b"\x03\x00" * 8
    ok, msg = validate_rx_frame(data)
    assert ok and msg == "OK"
    # CH8 = 0x2FE
    bad = bytes([0x01]) + b"\x03\x00" * 7 + bytes([0x02, 0xFE])
    ok2, msg2 = validate_rx_frame(bad)
    assert not ok2
    assert "8" in msg2
    assert "2FF" in msg2


def _parsed(currents: list[float], iteration: int = 1, raw: int = 0x300) -> dict:
    return {
        "iteration": iteration,
        "outputs": [{"current": c, "raw": raw} for c in currents],
    }


def test_fill_measured_multi_attempt() -> None:
    tc = CaseRecord(
        name="f1",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        sim_outputs=[0.1] * 8,
    )
    p1 = _parsed([0.1] * 8, iteration=1, raw=0x100)
    p2 = _parsed([0.1] * 8, iteration=2, raw=0x300)
    result = SendResult(
        success=True,
        converged=True,
        tx_frame=build_tx_frame(tc.channels, 2),
        rx_frame=b"\x01" + b"\x00" * 16,
        parsed=p2,
        retries=1,
        attempts=[
            RxAttempt(rx_frame=b"\x00" + b"\x00" * 16, parsed=p1, converged=False),
            RxAttempt(rx_frame=b"\x01" + b"\x00" * 16, parsed=p2, converged=True),
        ],
    )
    fill_measured(tc, result)
    assert len(tc.attempt_records) == 2
    assert tc.attempt_records[0].attempt == 1
    assert tc.attempt_records[1].attempt == 2
    assert tc.success
    assert tc.error == ""
    assert tc.attempt_records[-1].rx_hex


def test_fill_measured_exhausted() -> None:
    tc = CaseRecord(
        name="f_ex",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        sim_outputs=[0.1] * 8,
    )
    p_last = _parsed([0.1] * 8, iteration=5, raw=0x100)
    result = SendResult(
        success=True,
        converged=False,
        tx_frame=build_tx_frame(tc.channels, 2),
        rx_frame=b"\x04" + b"\x00" * 16,
        parsed=p_last,
        retries=4,
        attempts=[
            RxAttempt(rx_frame=b"\x00" + b"\x00" * 16, parsed=p_last, converged=False),
        ],
    )
    fill_measured(tc, result)
    assert tc.success
    assert "未收敛" in tc.error


def test_attempt_csv_row() -> None:
    sim = {fn: "" for fn in STANDARD_FIELDNAMES}
    sim["RowKind"] = ROW_KIND_SIM
    sim["EbNo_dB"] = "0"
    sim["FrameIdx"] = "1"
    row = _attempt_to_csv_row(
        sim,
        list(STANDARD_FIELDNAMES),
        2,
        "02 FF",
        3,
        [0.1, -0.2, 0.3, 0.4, 0.5, 0.0, 0.0, 0.0],
        [0, 1, 0, 1],
        mode=2,
    )
    assert row["Attempt"] == "2"
    assert row["Out[4]"] == "0.5000"


def test_rebuild_one_attempt_two_rows() -> None:
    """单次尝试：1 仿真行 + 1 实测行（Attempt=1）。"""
    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    tc = CaseRecord(
        name="once",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        sim_outputs=[0.1] * 8,
        snr_db=0.0,
        frame_idx=1,
    )
    p1 = _parsed([0.1] * 8, iteration=1)
    fill_measured(
        tc,
        SendResult(
            success=True,
            converged=True,
            tx_frame=build_tx_frame(tc.channels, 2),
            rx_frame=b"\x00" + b"\x00" * 16,
            parsed=p1,
            attempts=[RxAttempt(rx_frame=b"\x00" + b"\x00" * 16, parsed=p1, converged=True)],
        ),
    )
    assert len(tc.attempt_records) == 1
    loaded.dataset.rebuild_rows_from_cases([tc])
    assert len(loaded.dataset.rows) == 2
    assert loaded.dataset.rows[0]["RowKind"] == ROW_KIND_SIM
    assert loaded.dataset.rows[0]["Attempt"] == ""
    assert loaded.dataset.rows[1]["RowKind"] == ROW_KIND_MEASURED
    assert loaded.dataset.rows[1]["Attempt"] == "1"


def _make_tc_with_attempts(n: int) -> CaseRecord:
    tc = CaseRecord(
        name="retry",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        sim_outputs=[0.1] * 8,
        snr_db=0.0,
        frame_idx=1,
    )
    attempts = []
    for i in range(1, n + 1):
        is_last = i == n
        attempts.append(
            RxAttempt(
                rx_frame=bytes([i - 1]) + b"\x00" * 16,
                parsed=_parsed(
                    [0.1] * 8,
                    iteration=i,
                    raw=0x300 if is_last else 0x100,
                ),
                converged=is_last,
            )
        )
    fill_measured(
        tc,
        SendResult(
            success=True,
            converged=True,
            tx_frame=build_tx_frame(tc.channels, 2),
            rx_frame=attempts[-1].rx_frame,
            parsed=attempts[-1].parsed,
            retries=max(0, n - 1),
            attempts=attempts,
        ),
    )
    return tc


def _assert_export_frame_shape(rows: list[dict[str, str]]) -> None:
    from csv_loader import _group_interleaved_frame_rows

    for sim, meas_list in _group_interleaved_frame_rows(rows):
        assert sim["RowKind"] == ROW_KIND_SIM
        assert sim.get("Attempt", "") == ""
        for meas in meas_list:
            assert meas["RowKind"] == ROW_KIND_MEASURED
            assert str(meas.get("Attempt", "")).strip() != ""


def test_build_export_three_attempts_four_rows() -> None:
    """build_export_rows：3 次重试 → 恰好 4 行（1 仿真 + 3 实测）。"""
    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    tc = _make_tc_with_attempts(3)
    rows = loaded.dataset.build_export_rows([tc])
    assert len(rows) == 4
    assert rows[0]["RowKind"] == ROW_KIND_SIM
    assert rows[0]["Attempt"] == ""
    for i in range(1, 4):
        assert rows[i]["Attempt"] == str(i)
    _assert_export_frame_shape(rows)


def test_double_export_no_duplicate_sim() -> None:
    """连续导出或 rebuild 不产生重复仿真行 / 仿真行带 Attempt。"""
    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    tc = _make_tc_with_attempts(3)
    ds = loaded.dataset
    ds.rows = ds.build_export_rows([tc])
    rows2 = ds.build_export_rows([tc])
    assert len(rows2) == 4
    assert sum(1 for r in rows2 if r["RowKind"] == ROW_KIND_SIM) == 1
    assert rows2[0]["Attempt"] == ""
    _assert_export_frame_shape(rows2)
    ds.rebuild_rows_from_cases([tc])
    ds.rebuild_rows_from_cases([tc])
    assert len(ds.rows) == 4
    assert sum(1 for r in ds.rows if r["RowKind"] == ROW_KIND_SIM) == 1
    _assert_export_frame_shape(ds.rows)


def test_export_from_dual_row_checkpoint() -> None:
    """双行检查点（update_measured）后导出：1 仿真 + N 实测，内存仍为双行/帧。"""
    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    tc = _make_tc_with_attempts(2)
    ds = loaded.dataset
    dual_len = len(ds.rows)
    ds.update_measured(0, tc)
    assert ds.rows[0]["RowKind"] == ROW_KIND_SIM
    assert len(ds.rows) == dual_len
    rows = ds.build_export_rows([tc])
    assert len(rows) == 3
    assert rows[0]["Attempt"] == ""
    assert rows[1]["Attempt"] == "1"
    assert rows[2]["Attempt"] == "2"
    _assert_export_frame_shape(rows)


def test_rebuild_three_attempts_four_rows() -> None:
    """三次尝试：1 仿真行 + 3 实测行（Attempt 1..3）。"""
    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    tc = _make_tc_with_attempts(3)
    assert len(tc.attempt_records) == 3
    loaded.dataset.rebuild_rows_from_cases([tc])
    assert len(loaded.dataset.rows) == 4
    assert loaded.dataset.rows[0]["Attempt"] == ""
    for i in range(1, 4):
        assert loaded.dataset.rows[i]["Attempt"] == str(i)


def test_rebuild_untested_sim_only() -> None:
    """未测帧：仅导出仿真行，不补空白实测行。"""
    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    tc = case_from_csv_group(loaded.cases[0])
    clear_measured(tc)
    loaded.dataset.rebuild_rows_from_cases([tc])
    assert len(loaded.dataset.rows) == 1
    assert loaded.dataset.rows[0]["RowKind"] == ROW_KIND_SIM


def test_rebuild_dual_row_exports_all_attempts() -> None:
    """rebuild_rows_from_cases 导出 Attempt=1..N 全部实测行（测前内存仍为双行/帧）。"""
    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    tc = _make_tc_with_attempts(4)
    assert len(tc.attempt_records) == 4
    loaded.dataset.rebuild_rows_from_cases([tc])
    assert len(loaded.dataset.rows) == 5  # 1 sim + 4 measured
    assert loaded.dataset.rows[0]["RowKind"] == ROW_KIND_SIM
    assert loaded.dataset.rows[0]["Attempt"] == ""
    for i in range(1, 5):
        meas = loaded.dataset.rows[i]
        assert meas["RowKind"] == ROW_KIND_MEASURED
        assert meas["Attempt"] == str(i)


def test_rebuild_dual_row_two_attempts() -> None:
    """双次重试：仿真行 + Attempt 1/2 两行实测。"""
    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    tc = _make_tc_with_attempts(2)
    loaded.dataset.rebuild_rows_from_cases([tc])
    assert len(loaded.dataset.rows) == 3
    assert loaded.dataset.rows[1]["Attempt"] == "1"
    assert loaded.dataset.rows[2]["Attempt"] == "2"


def test_ber_nan_when_no_tested_frames() -> None:
    import math

    assert math.isnan(compute_channel_ber_from_error_bits(0, 0))
    tc = CaseRecord(
        name="untested",
        mode=2,
        channels=[2500] * 12,
        sim_outputs=[0.1] * 8,
        snr_db=1.0,
        frame_idx=1,
    )
    points = analyze_by_snr([tc])
    assert len(points) == 1
    assert points[0].tested_count == 0
    assert math.isnan(points[0].channel_ber)


def test_styled_xlsx() -> None:
    rows = [
        {fn: "" for fn in STANDARD_FIELDNAMES},
        {fn: "" for fn in STANDARD_FIELDNAMES},
    ]
    rows[0].update(
        {
            "RowKind": ROW_KIND_SIM,
            "EbNo_dB": "0",
            "FrameIdx": "1",
            "InfoBit[0]": "0",
            "InfoBit[1]": "1",
        }
    )
    rows[1].update(
        {
            "RowKind": ROW_KIND_MEASURED,
            "Attempt": "2",
            "EbNo_dB": "0",
            "FrameIdx": "1",
            "InfoBit[0]": "1",
            "InfoBit[1]": "1",
            "Out[4]": "0.5000",
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "styled.xlsx"
        write_styled_dataset_xlsx(path, list(STANDARD_FIELDNAMES), rows, matrix_mode=2)
        assert path.stat().st_size > 0
        import openpyxl

        wb = openpyxl.load_workbook(path)
        ws = wb.active
        assert ws["A2"].fill.start_color.rgb.endswith("E3F2FD")


def test_interleaved_load_ensures_attempt_column() -> None:
    """旧交错 CSV 无 Attempt 表头时，加载后应补全列并在实测行写入 Attempt=1。"""
    import csv
    import tempfile

    headers = [
        "RowKind", "EbNo_dB", "FrameIdx",
        *[f"In[{i}]" for i in range(12)],
        *[f"Out[{i}]" for i in range(8)],
        *[f"InfoBit[{i}]" for i in range(4)],
        "IterNum", "RecvHex",
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8-sig", newline="") as f:
        path = Path(f.name)
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        sim = {h: "" for h in headers}
        sim.update(
            {
                "RowKind": ROW_KIND_SIM,
                "EbNo_dB": "0",
                "FrameIdx": "1",
                **{f"In[{i}]": "0" for i in range(12)},
                **{f"Out[{i}]": "0.1" for i in range(8)},
                "InfoBit[0]": "0",
                "InfoBit[1]": "1",
                "InfoBit[2]": "0",
                "InfoBit[3]": "1",
            }
        )
        meas = {h: "" for h in headers}
        meas.update({"RowKind": ROW_KIND_MEASURED, "EbNo_dB": "0", "FrameIdx": "1"})
        w.writerow(sim)
        w.writerow(meas)

    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    assert "Attempt" in loaded.dataset.fieldnames
    tc = case_from_csv_group(loaded.cases[0])
    fill_measured(
        tc,
        SendResult(
            success=True,
            converged=True,
            tx_frame=build_tx_frame(tc.channels, 2),
            rx_frame=b"\x01" + b"\x00" * 16,
            parsed=_parsed([0.1] * 8, iteration=2),
            attempts=[RxAttempt(rx_frame=b"\x01" + b"\x00" * 16, parsed=_parsed([0.1] * 8, iteration=2), converged=True)],
        ),
    )
    loaded.dataset.rebuild_rows_from_cases([tc])
    meas_row = loaded.dataset.rows[1]
    assert meas_row["Attempt"] == "1"
    path.unlink(missing_ok=True)


def test_ber_excludes_non_converged() -> None:
    """raw < 0x2FF 的帧不计入 BER 分子/分母。"""
    import math

    from analysis.aggregate import count_channel_error_bits

    ok = CaseRecord(
        name="ok",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        sim_outputs=[0.1, 0.1, 0.1, 0.1, 0.1, -0.1, -0.1, -0.1],
        snr_db=0.0,
        frame_idx=1,
        success=True,
        hardware_converged=True,
        actual_currents=[0.1, 0.1, 0.1, 0.1, 0.1, -0.1, -0.1, -0.1],
        rx_hex="AA",
        iteration_count=1,
    )
    bad = CaseRecord(
        name="bad",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        sim_outputs=[0.1, 0.1, 0.1, 0.1, 0.1, -0.1, -0.1, -0.1],
        snr_db=0.0,
        frame_idx=2,
        success=True,
        hardware_converged=False,
        actual_currents=[2.5] * 8,
        rx_hex="BB",
        iteration_count=1,
        error="未收敛（已用最后一次回传统计）",
    )
    err, bits, n = count_channel_error_bits([ok, bad])
    assert n == 1
    assert bits == 4
    points = analyze_by_snr([ok, bad])
    assert points[0].tested_count == 1
    assert points[0].converged_count == 1
    assert math.isfinite(points[0].channel_ber)


def test_error_rx_export_rows() -> None:
    """通信错误帧导出：仅最终未收敛整帧；最终收敛帧不进错误表。"""
    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    loaded.dataset.ensure_export_fieldnames()
    tc = CaseRecord(
        name="err",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        sim_outputs=[0.1] * 8,
        snr_db=0.0,
        frame_idx=1,
    )
    p1 = _parsed([2.5] * 8, iteration=1, raw=0x100)
    p2 = _parsed([0.1] * 8, iteration=2, raw=0x300)
    fill_measured(
        tc,
        SendResult(
            success=True,
            converged=True,
            tx_frame=build_tx_frame(tc.channels, 2),
            rx_frame=b"\x01" + b"\x00" * 16,
            parsed=p2,
            retries=1,
            attempts=[
                RxAttempt(rx_frame=b"\x00" + b"\x00" * 16, parsed=p1, converged=False),
                RxAttempt(rx_frame=b"\x01" + b"\x00" * 16, parsed=p2, converged=True),
            ],
        ),
    )
    full = loaded.dataset.build_export_rows([tc])
    assert len(full) == 3  # sim + 2 measured（① 保留中间 Attempt）
    # 最终收敛 → 不是通信错误帧；② ok 去掉中间未收敛 Attempt → 仅 sim+最后一次
    assert loaded.dataset.build_error_rx_export_rows([tc]) == []
    ok_filtered = loaded.dataset.build_export_rows([tc], exclude_comm_errors=True)
    assert len(ok_filtered) == 2
    assert ok_filtered[0]["RowKind"] == "仿真行"
    assert ok_filtered[1]["Attempt"] == "2"
    assert ok_filtered[1].get("HardwareConverged") == "Y"

    # 最终仍失败：5 次 Attempt 全是 Out≈2.5 → ok 必须整套删除（sim+1..5），不是只删第 5 次
    bad = CaseRecord(
        name="bad",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        sim_outputs=[0.1] * 8,
        snr_db=0.0,
        frame_idx=2,
    )
    p_bad = _parsed([2.5] * 8, iteration=5, raw=0x100)
    five_fail = [
        RxAttempt(rx_frame=bytes([i]) + b"\x00" * 16, parsed=p_bad, converged=False)
        for i in range(5)
    ]
    fill_measured(
        bad,
        SendResult(
            success=True,
            converged=False,
            tx_frame=build_tx_frame(bad.channels, 2),
            rx_frame=b"\x04" + b"\x00" * 16,
            parsed=p_bad,
            retries=5,
            attempts=five_fail,
        ),
    )
    full_bad = loaded.dataset.build_export_rows([bad])
    assert len(full_bad) == 6  # result：仿真行 + Attempt1..5 全保留
    err_rows = loaded.dataset.build_error_rx_export_rows([bad])
    assert len(err_rows) == 6  # 通信错误表也是整套
    ok_bad = loaded.dataset.build_export_rows([bad], exclude_comm_errors=True)
    assert ok_bad == [], "最终失败帧：ok 应删除仿真行+全部 Attempt，不是只删第5次"

    with tempfile.TemporaryDirectory() as tmp:
        xlsx = Path(tmp) / "err.xlsx"
        write_styled_dataset_xlsx(
            xlsx, list(loaded.dataset.fieldnames), err_rows, matrix_mode=2, highlight_ber=False
        )
        assert xlsx.stat().st_size > 0


def test_three_excel_export_filters() -> None:
    """三份 Excel 口径：完整 / ok / 仅误码帧（误码通道高亮）。"""
    from analysis.report_export import (
        filter_ber_error_rows,
        measured_ber_stats_by_snr_from_exports,
        write_styled_dataset_xlsx,
    )
    from csv_loader import (
        is_comm_error_frame,
        post_test_excel_paths,
        resolve_export_fieldnames,
        trim_ok_rows_for_chart,
    )

    path = ROOT / "data" / "mode2.csv"
    if not path.is_file():
        return
    loaded = load_test_csv(path)
    assert loaded.dataset is not None
    # 强制带 CodedBit 列（mode2.csv 可能无此列）
    loaded.dataset.fieldnames = resolve_export_fieldnames(["CodedBit[0]"])
    loaded.dataset.ensure_export_fieldnames()
    fn = list(loaded.dataset.fieldnames)
    assert any(c.startswith("CodedBit[") for c in fn)

    # 最终收敛、中间有未收敛 Attempt → ①保留中间行；②只留最终收敛 Attempt
    ok_tc = CaseRecord(
        name="ok",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        coded_bits=[0, 0, 0, 0, 0, 0, 0, 0],  # Mode2 BER 通道全 0
        sim_outputs=[0.1] * 8,
        snr_db=0.0,
        frame_idx=1,
    )
    p1 = _parsed([2.5] * 8, iteration=1, raw=0x100)
    # 收敛但 Out 硬判与仿真 CodeBit 不一致 → 应进 ③
    p2 = _parsed([-0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1], iteration=2, raw=0x300)
    fill_measured(
        ok_tc,
        SendResult(
            success=True,
            converged=True,
            tx_frame=build_tx_frame(ok_tc.channels, 2),
            rx_frame=b"\x01" + b"\x00" * 16,
            parsed=p2,
            retries=1,
            attempts=[
                RxAttempt(rx_frame=b"\x00" + b"\x00" * 16, parsed=p1, converged=False),
                RxAttempt(rx_frame=b"\x01" + b"\x00" * 16, parsed=p2, converged=True),
            ],
        ),
    )
    assert not is_comm_error_frame(ok_tc)

    # 最终仍未收敛 → 通信错误，整套剔除（sim + 全部 Attempt）
    bad_tc = CaseRecord(
        name="bad",
        mode=2,
        channels=[2500] * 12,
        info_bits=[0, 1, 0, 1],
        coded_bits=[0] * 8,
        sim_outputs=[0.1] * 8,
        snr_db=0.0,
        frame_idx=2,
    )
    p_bad = _parsed([2.5] * 8, iteration=5, raw=0x100)
    fill_measured(
        bad_tc,
        SendResult(
            success=True,
            converged=False,
            tx_frame=build_tx_frame(bad_tc.channels, 2),
            rx_frame=b"\x04" + b"\x00" * 16,
            parsed=p_bad,
            retries=5,
            attempts=[
                RxAttempt(
                    rx_frame=bytes([i]) + b"\x00" * 16, parsed=p_bad, converged=False
                )
                for i in range(5)
            ],
        ),
    )
    assert is_comm_error_frame(bad_tc)

    # 无误码收敛帧 → 进②但不进③
    clean_tc = CaseRecord(
        name="clean",
        mode=2,
        channels=[2500] * 12,
        coded_bits=[0] * 8,
        sim_outputs=[0.1] * 8,
        snr_db=1.0,
        frame_idx=3,
    )
    p_clean = _parsed([0.1] * 8, iteration=1, raw=0x300)
    fill_measured(
        clean_tc,
        SendResult(
            success=True,
            converged=True,
            tx_frame=build_tx_frame(clean_tc.channels, 2),
            rx_frame=b"\x02" + b"\x00" * 16,
            parsed=p_clean,
            attempts=[
                RxAttempt(rx_frame=b"\x02" + b"\x00" * 16, parsed=p_clean, converged=True),
            ],
        ),
    )

    full = loaded.dataset.build_export_rows([ok_tc, bad_tc, clean_tc])
    ok_only = loaded.dataset.build_export_rows(
        [ok_tc, bad_tc, clean_tc], exclude_comm_errors=True
    )
    chart_only = trim_ok_rows_for_chart(ok_only)
    ber_only = filter_ber_error_rows(ok_only, fn, matrix_mode=2)
    assert len(full) == 3 + 6 + 2  # ok: sim+2; bad: sim+5; clean: sim+1
    # ② ok：每帧 1 仿真 + 1 实测
    assert len(ok_only) == 4
    assert chart_only == ok_only
    assert all(r.get("FrameIdx") != "2" for r in chart_only)
    # ④ ber：仅 ok 帧有误码的末次 attempt
    assert any(r.get("FrameIdx") == "1" for r in ber_only)
    assert all(r.get("FrameIdx") != "2" for r in ber_only)
    assert all(r.get("FrameIdx") != "3" for r in ber_only)
    # ② 实测行不得再有 Out≈2.5 / HC=N
    for r in ok_only:
        if str(r.get("RowKind", "")).strip() != "实测行":
            continue
        assert str(r.get("HardwareConverged", "")).upper() == "Y"
        for j in range(8):
            v = str(r.get(f"Out[{j}]", "")).strip()
            if not v:
                continue
            assert abs(float(v) - 2.5) > 1e-3, f"ok still has Out=2.5: {r}"
    # ③：仅 ok 帧最终收敛且误码的实测行（中间 2.5 Attempt 已不在 ok 中）
    assert any(r.get("FrameIdx") == "1" for r in ber_only)
    assert all(r.get("FrameIdx") != "2" for r in ber_only)
    assert all(r.get("FrameIdx") != "3" for r in ber_only)
    assert any(str(r.get("RowKind", "")).strip() == "仿真行" for r in ber_only)
    assert any(str(r.get("RowKind", "")).strip() == "实测行" for r in ber_only)
    assert all(
        str(r.get("HardwareConverged", "")).upper() != "N"
        for r in ber_only
        if str(r.get("RowKind", "")).strip() == "实测行"
    )

    with tempfile.TemporaryDirectory() as tmp:
        post = Path(tmp) / "demo_result_20260709.csv"
        paths = post_test_excel_paths(post)
        write_styled_dataset_xlsx(
            paths["full"], fn, full, matrix_mode=2, dataset_style="full"
        )
        write_styled_dataset_xlsx(
            paths["ok"], fn, ok_only, matrix_mode=2, dataset_style="ok"
        )
        write_styled_dataset_xlsx(
            paths["ber"], fn, ber_only, matrix_mode=2, dataset_style="ber"
        )
        for p in paths.values():
            assert p.is_file() and p.stat().st_size > 0

    chart_stats = measured_ber_stats_by_snr_from_exports(chart_only, fn, matrix_mode=2)
    points = analyze_by_snr([ok_tc, bad_tc, clean_tc])
    for p in points:
        snr = p.snr_db
        if snr in chart_stats:
            eb, cb, fc = chart_stats[snr]
            assert p.error_bits == eb
            assert p.channel_bits == cb
            assert p.tested_count == fc

    from analysis.aggregate import (
        count_sim_reference_error_bits,
        count_sim_reference_error_bits_ok,
    )
    from analysis.report_export import reference_ber_stats_by_snr_from_exports

    all_cases = [ok_tc, bad_tc, clean_tc]
    _, _, n_full = count_sim_reference_error_bits(all_cases)
    _, _, n_ok = count_sim_reference_error_bits_ok(all_cases)
    assert n_full == 3
    assert n_ok == 2
    exp_ref = reference_ber_stats_by_snr_from_exports(chart_only, fn, matrix_mode=2)
    for p in points:
        if p.snr_db in exp_ref:
            _, cb, fc = exp_ref[p.snr_db]
            assert p.reference_channel_bits == cb
            assert fc == p.tested_count or p.tested_count == 0

    from analysis.report_export import build_snr_audit_rows

    audit = build_snr_audit_rows(
        points,
        full_rows=full,
        ok_rows=ok_only,
        ber_rows=ber_only,
        fieldnames=fn,
        matrix_mode=2,
    )
    assert audit
    for row in audit:
        if row["chart_frames"] > 0:
            assert row["meas_match"], row
            assert row["frame_audit_ok"], row

    from analysis.report_export import build_iter_audit_rows

    iter_audit = build_iter_audit_rows(points, ok_only)
    assert iter_audit
    for row in iter_audit:
        if row["chart_frames"] > 0:
            assert row["meas_match"], row


def test_filter_ber_error_rows_from_ok_one_to_one() -> None:
    from analysis.report_export import filter_ber_error_rows
    from csv_loader import ROW_KIND_MEASURED, ROW_KIND_SIM, resolve_export_fieldnames

    fn = resolve_export_fieldnames(["CodedBit[0]"])
    sim = {k: "" for k in fn}
    sim.update(
        {
            "RowKind": ROW_KIND_SIM,
            "EbNo_dB": "0",
            "FrameIdx": "1",
            **{f"Out[{i}]": "0.5" for i in range(8)},
            **{f"CodedBit[{i}]": "0" for i in range(8)},
        }
    )
    err = {k: "" for k in fn}
    err.update(
        {
            "RowKind": ROW_KIND_MEASURED,
            "Attempt": "2",
            "HardwareConverged": "Y",
            "EbNo_dB": "0",
            "FrameIdx": "1",
            **{f"Out[{i}]": "-0.5" for i in range(8)},
        }
    )
    good = {k: "" for k in fn}
    good.update(
        {
            "RowKind": ROW_KIND_SIM,
            "EbNo_dB": "1",
            "FrameIdx": "2",
            **{f"Out[{i}]": "0.5" for i in range(8)},
            **{f"CodedBit[{i}]": "0" for i in range(8)},
        }
    )
    good_meas = {k: "" for k in fn}
    good_meas.update(
        {
            "RowKind": ROW_KIND_MEASURED,
            "Attempt": "1",
            "HardwareConverged": "Y",
            "EbNo_dB": "1",
            "FrameIdx": "2",
            **{f"Out[{i}]": "0.5" for i in range(8)},
        }
    )
    filtered = filter_ber_error_rows([sim, err, good, good_meas], fn, matrix_mode=1)
    assert len(filtered) == 2
    assert filtered[0]["FrameIdx"] == "1"


def test_filter_ber_error_rows_keeps_only_last_error_attempt() -> None:
    from analysis.report_export import filter_ber_error_rows
    from csv_loader import ROW_KIND_MEASURED, ROW_KIND_SIM, resolve_export_fieldnames

    fn = resolve_export_fieldnames(["CodedBit[0]"])
    sim = {k: "" for k in fn}
    sim.update(
        {
            "RowKind": ROW_KIND_SIM,
            "EbNo_dB": "0",
            "FrameIdx": "1",
            **{f"Out[{i}]": "0.5" for i in range(8)},
            **{f"CodedBit[{i}]": "0" for i in range(8)},
            "HardwareConverged": "",
        }
    )
    err1 = {k: "" for k in fn}
    err1.update(
        {
            "RowKind": ROW_KIND_MEASURED,
            "Attempt": "2",
            "HardwareConverged": "Y",
            "EbNo_dB": "0",
            "FrameIdx": "1",
            **{f"Out[{i}]": "-0.5" for i in range(8)},
            **{f"CodedBit[{i}]": "1" for i in range(8)},
        }
    )
    err2 = {k: "" for k in fn}
    err2.update(
        {
            "RowKind": ROW_KIND_MEASURED,
            "Attempt": "3",
            "HardwareConverged": "Y",
            "EbNo_dB": "0",
            "FrameIdx": "1",
            **{f"Out[{i}]": "-0.2" for i in range(8)},
            **{f"CodedBit[{i}]": "1" for i in range(8)},
        }
    )
    filtered = filter_ber_error_rows([sim, err2], fn, matrix_mode=1)
    assert len(filtered) == 2
    assert filtered[0]["RowKind"] == ROW_KIND_SIM
    assert filtered[1]["Attempt"] == "3"


def test_filter_ber_error_rows_keeps_only_mismatch() -> None:
    """ok 表 1:1：仅误码帧进入 ber。"""
    from analysis.report_export import filter_ber_error_rows
    from csv_loader import ROW_KIND_MEASURED, ROW_KIND_SIM, resolve_export_fieldnames

    fn = resolve_export_fieldnames(["CodedBit[0]"])
    sim_err = {k: "" for k in fn}
    sim_err.update(
        {
            "RowKind": ROW_KIND_SIM,
            "EbNo_dB": "0",
            "FrameIdx": "1",
            **{f"Out[{i}]": "0.5" for i in range(8)},
            **{f"CodedBit[{i}]": "0" for i in range(8)},
        }
    )
    bad = {k: "" for k in fn}
    bad.update(
        {
            "RowKind": ROW_KIND_MEASURED,
            "Attempt": "2",
            "HardwareConverged": "Y",
            "EbNo_dB": "0",
            "FrameIdx": "1",
            **{f"Out[{i}]": "-0.5" for i in range(8)},
        }
    )
    sim_ok = {k: "" for k in fn}
    sim_ok.update(
        {
            "RowKind": ROW_KIND_SIM,
            "EbNo_dB": "1",
            "FrameIdx": "2",
            **{f"Out[{i}]": "0.5" for i in range(8)},
            **{f"CodedBit[{i}]": "0" for i in range(8)},
        }
    )
    good = {k: "" for k in fn}
    good.update(
        {
            "RowKind": ROW_KIND_MEASURED,
            "Attempt": "1",
            "HardwareConverged": "Y",
            "EbNo_dB": "1",
            "FrameIdx": "2",
            **{f"Out[{i}]": "0.5" for i in range(8)},
        }
    )
    filtered = filter_ber_error_rows(
        [sim_err, bad, sim_ok, good], fn, matrix_mode=1
    )
    assert len(filtered) == 2
    assert filtered[0]["FrameIdx"] == "1"
    assert filtered[1]["Attempt"] == "2"


def main() -> None:
    test_needs_retry_all_channels_2ff()
    test_validate_rx_frame_2ff()
    test_fill_measured_exhausted()
    test_fill_measured_multi_attempt()
    test_ber_excludes_non_converged()
    test_error_rx_export_rows()
    test_three_excel_export_filters()
    test_filter_ber_error_rows_keeps_only_last_error_attempt()
    test_filter_ber_error_rows_keeps_only_mismatch()
    test_rebuild_one_attempt_two_rows()
    test_build_export_three_attempts_four_rows()
    test_double_export_no_duplicate_sim()
    test_export_from_dual_row_checkpoint()
    test_rebuild_three_attempts_four_rows()
    test_rebuild_untested_sim_only()
    test_rebuild_dual_row_exports_all_attempts()
    test_rebuild_dual_row_two_attempts()
    test_ber_nan_when_no_tested_frames()
    test_attempt_csv_row()
    test_interleaved_load_ensures_attempt_column()
    test_styled_xlsx()
    print("OK: rx retry tests passed")
    print(f"  RETRY_THRESHOLD=0x{RETRY_THRESHOLD:03X}")
    print(f"  CONVERGE_CHANNELS={CONVERGE_CHANNELS}")


if __name__ == "__main__":
    main()
