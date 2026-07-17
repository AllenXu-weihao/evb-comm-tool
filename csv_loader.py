"""CSV 测试文件加载器 — mode1/mode2 单行格式 / 交错双行格式（仿真行 + 实测行）。"""

from __future__ import annotations

import csv
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from analysis.aggregate import (
    has_measured,
    in_value_to_raw,
    mode2_export_measured_infobits,
    sim_row_display_infobits,
)
from analysis.sign_compare import chip_value_to_bit, sim_value_to_bit

if TYPE_CHECKING:
    from analysis.aggregate import CaseRecord

ROW_KIND_SIM = "仿真行"
ROW_KIND_MEASURED = "实测行"
# 旧版三行格式（仅加载兼容）
ROW_KIND_TRUTH = "真实行"
ROW_KIND_REF = "参考行"
ROWS_PER_FRAME_LEGACY_TRIPLE = 3
ROWS_PER_FRAME = 2

STANDARD_FIELDNAMES: list[str] = (
    ["RowKind", "Attempt", "EbNo_dB", "FrameIdx"]
    + [f"In[{i}]" for i in range(12)]
    + [f"Out[{i}]" for i in range(8)]
    + [f"InfoBit[{i}]" for i in range(4)]
    + ["IterNum", "RecvHex"]
)

INFO_BIT_KEYS = [f"InfoBit[{i}]" for i in range(4)]
CODED_BIT_COUNT = 8
CODED_BIT_PREFIXES = ("CodedBit", "CodeBit")

# data/ 目录约定：测试集（源 CSV）与测后数据集（按日期分子目录）
DATA_DIR_NAME = "data"
TESTSET_DIR_NAME = "测试集"
POST_TEST_DIR_NAME = "测后数据集"
_RESULT_TS_RE = re.compile(r"_result_(\d{8})_(\d{6})", re.IGNORECASE)


def project_root() -> Path:
    return Path(__file__).resolve().parent


def data_root() -> Path:
    return project_root() / DATA_DIR_NAME


def testset_dir() -> Path:
    """源测试 CSV 目录：data/测试集/。"""
    d = data_root() / TESTSET_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def post_test_root() -> Path:
    """测后数据集根目录：data/测后数据集/。"""
    d = data_root() / POST_TEST_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def post_test_day_dir(when: datetime | None = None) -> Path:
    """按日期分子目录：data/测后数据集/YYYY-MM-DD/。"""
    day = (when or datetime.now()).strftime("%Y-%m-%d")
    d = post_test_root() / day
    d.mkdir(parents=True, exist_ok=True)
    return d


def detect_coded_bit_prefix(fieldnames: list[str] | None) -> str | None:
    """表头含 CodedBit[0] 或 CodeBit[0] 时返回列名前缀。"""
    if not fieldnames:
        return None
    fn = set(fieldnames)
    for prefix in CODED_BIT_PREFIXES:
        if f"{prefix}[0]" in fn:
            return prefix
    return None


def coded_bit_keys(prefix: str, count: int = CODED_BIT_COUNT) -> list[str]:
    return [f"{prefix}[{i}]" for i in range(count)]


def resolve_export_fieldnames(source_fieldnames: list[str] | None = None) -> list[str]:
    """标准交错列 + 可选 CodedBit/CodeBit[0..7]（插在 Out[7] 与 InfoBit[0] 之间）+ HardwareConverged。"""
    base = list(STANDARD_FIELDNAMES)
    prefix = detect_coded_bit_prefix(source_fieldnames)
    if prefix:
        insert_at = base.index("InfoBit[0]")
        for i, key in enumerate(coded_bit_keys(prefix)):
            base.insert(insert_at + i, key)
    if "HardwareConverged" not in base:
        base.append("HardwareConverged")
    return base


def _pad_rows_to_fieldnames(rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    for row in rows:
        for key in fieldnames:
            row.setdefault(key, "")


def _fill_coded_bits_from_outputs(
    row: dict[str, str],
    outputs: list[float],
    fieldnames: list[str],
    *,
    only_empty: bool = False,
) -> None:
    """CodedBit[i] = Out[i] 硬判：<0→1，≥0→0（与 chip_value_to_bit 一致）。

    only_empty=True 时不覆盖测试集已给定的仿真行 CodeBit。
    """
    prefix = detect_coded_bit_prefix(fieldnames)
    if not prefix:
        return
    for i in range(CODED_BIT_COUNT):
        key = f"{prefix}[{i}]"
        if key not in fieldnames:
            continue
        if only_empty and str(row.get(key, "")).strip() != "":
            continue
        out = outputs[i] if i < len(outputs) else 0.0
        row[key] = str(chip_value_to_bit(out))


def _parse_coded_bits_from_row(row: dict) -> list[int] | None:
    """从仿真行读取测试集给定的 CodeBit[0..7]；缺列或全空则返回 None。"""
    prefix = detect_coded_bit_prefix(list(row.keys()))
    if not prefix:
        return None
    bits: list[int] = []
    any_present = False
    for i in range(CODED_BIT_COUNT):
        key = f"{prefix}[{i}]"
        raw = row.get(key, "")
        if raw is None or str(raw).strip() == "":
            bits.append(0)
            continue
        any_present = True
        bit = _int_cell(row, key, 0)
        bits.append(0 if bit is None else int(bit))
    return bits if any_present else None


def _sim_outputs_from_csv_row(row: dict[str, str]) -> list[float]:
    return [_float_cell(row, f"Out[{i}]") for i in range(8)]


def _float_cell(row: dict, key: str, default: float = 0.0) -> float:
    val = row.get(key, "")
    if val is None or str(val).strip() == "":
        return default
    return float(val)


def _int_cell(row: dict, key: str, default: int | None = None) -> int | None:
    val = row.get(key, "")
    if val is None or str(val).strip() == "":
        return default
    return int(float(val))


def infer_matrix_mode_from_path(path: str | Path) -> int:
    """从文件名推断矩阵模式：mode3/model3→3，mode2→2，否则 1。"""
    stem = Path(path).stem.lower()
    if "mode3" in stem or "model3" in stem or "模式3" in stem:
        return 3
    if "mode2" in stem or "模式2" in stem:
        return 2
    return 1


def _infer_matrix_mode_from_fieldnames(fieldnames: list[str], path_mode: int) -> int:
    """表头仅含 InfoBit[0..1]（无 InfoBit[2]）时视为 mode3。"""
    if path_mode == 3:
        return 3
    fn = set(fieldnames)
    has_ib = [f"InfoBit[{i}]" in fn for i in range(4)]
    if (has_ib[0] or has_ib[1]) and not has_ib[2]:
        return 3
    return path_mode


def _info_bit_count_for_mode(matrix_mode: int) -> int:
    return 2 if matrix_mode == 3 else 4


def _info_bit_keys_for_mode(matrix_mode: int) -> list[str]:
    return [f"InfoBit[{i}]" for i in range(_info_bit_count_for_mode(matrix_mode))]


def _resolve_info_bit_spec(row: dict, matrix_mode: int) -> tuple[int, list[str]]:
    """按 matrix_mode 与行内实际 InfoBit 列决定有效模式与必填列。"""
    if f"InfoBit[2]" not in row and (f"InfoBit[0]" in row or f"InfoBit[1]" in row):
        return 3, _info_bit_keys_for_mode(3)
    mode = matrix_mode
    return mode, _info_bit_keys_for_mode(mode)


def _parse_sim_row(row: dict, row_num: int, *, matrix_mode: int = 1) -> dict:
    """解析仿真行：In[i] 归一化浮点 → 12-bit DAC；Out[i] 为仿真电流。"""
    channels: list[int] = []
    for i in range(12):
        key = f"In[{i}]"
        if key not in row:
            raise ValueError(f"第 {row_num} 行缺少 {key}")
        channels.append(in_value_to_raw(_float_cell(row, key)))

    sim_outputs: list[float] = []
    for i in range(8):
        key = f"Out[{i}]"
        if key not in row:
            raise ValueError(f"第 {row_num} 行缺少 {key}")
        sim_outputs.append(_float_cell(row, key))

    ebno = _float_cell(row, "EbNo_dB")
    frame_idx = _int_cell(row, "FrameIdx", row_num - 1) or (row_num - 1)
    iter_ref = _int_cell(row, "IterNum")

    matrix_mode, info_bit_keys = _resolve_info_bit_spec(row, matrix_mode)
    info_bit_count = len(info_bit_keys)

    info_bits: list[int] | None = None
    expected_info_bits: list[int] | None = None
    if any(key in row for key in info_bit_keys):
        csv_bits: list[int] = []
        for key in info_bit_keys:
            if key not in row:
                raise ValueError(f"第 {row_num} 行缺少 {key}")
            bit = _int_cell(row, key, 0)
            csv_bits.append(0 if bit is None else int(bit))
        if matrix_mode == 2:
            info_bits = csv_bits
            expected_info_bits = list(csv_bits)
        else:
            info_bits = csv_bits
    if matrix_mode == 2 and info_bits is None and len(sim_outputs) >= 8:
        from analysis.mode2_g_decode import mode2_decode_infobit

        info_bits = mode2_decode_infobit(sim_outputs)
    elif info_bits is None and len(sim_outputs) >= info_bit_count:
        info_bits = [sim_value_to_bit(sim_outputs[i]) for i in range(info_bit_count)]

    name = f"Eb{ebno:g}_F{frame_idx}"
    coded_bits = _parse_coded_bits_from_row(row)

    return {
        "group_id": name,
        "name": name,
        "mode": matrix_mode,
        "cmd": 0,
        "channels": channels,
        "sim_outputs": sim_outputs,
        "info_bits": info_bits,
        "expected_info_bits": expected_info_bits,
        "coded_bits": coded_bits,
        "iter_ref": iter_ref,
        "snr_db": ebno,
        "frame_idx": frame_idx,
    }


def _parse_measured_row(row: dict) -> dict:
    """从实测行读取芯片 RX 列（Out[] = I_col，IterNum = 实测迭代，RecvHex）。"""
    measured_outputs: list[float] = []
    has_any = False
    for i in range(8):
        key = f"Out[{i}]"
        val = row.get(key, "")
        if val is None or str(val).strip() == "":
            measured_outputs.append(0.0)
        else:
            measured_outputs.append(_float_cell(row, key))
            has_any = True

    measured_iter = _int_cell(row, "IterNum", 0) or 0
    recv_hex = str(row.get("RecvHex", "") or "").strip()

    if not has_any and not recv_hex and measured_iter <= 0:
        return {}

    return {
        "measured_outputs": measured_outputs if has_any else None,
        "measured_iter": measured_iter if measured_iter > 0 else None,
        "recv_hex": recv_hex,
    }


def _detect_legacy_triple_format(raw_rows: list[dict[str, str]]) -> bool:
    """是否旧版三行/帧（真实/参考/实测）。"""
    if not raw_rows:
        return False
    kinds = {str(r.get("RowKind", "")).strip() for r in raw_rows[:9]}
    if ROW_KIND_TRUTH in kinds or ROW_KIND_REF in kinds:
        return True
    return len(raw_rows) % ROWS_PER_FRAME_LEGACY_TRIPLE == 0 and len(raw_rows) % ROWS_PER_FRAME != 0


def _group_interleaved_frame_rows(
    raw_rows: list[dict[str, str]],
) -> list[tuple[dict[str, str], list[dict[str, str]]]]:
    """按仿真行分帧；其后连续实测行归属该帧（支持每帧 0..N 次 Attempt）。"""
    groups: list[tuple[dict[str, str], list[dict[str, str]]]] = []
    current_sim: dict[str, str] | None = None
    current_meas: list[dict[str, str]] = []
    for row_num, row in enumerate(raw_rows, start=2):
        kind = row.get("RowKind", "").strip()
        if kind in (ROW_KIND_SIM, ROW_KIND_REF):
            if current_sim is not None:
                groups.append((current_sim, current_meas))
            current_sim = row
            current_meas = []
            continue
        if kind == ROW_KIND_MEASURED:
            if current_sim is None:
                raise ValueError(f"第 {row_num} 行为实测行，但前面缺少仿真行")
            current_meas.append(row)
            continue
        if kind:
            raise ValueError(f"第 {row_num} 行 RowKind 无法识别: {kind!r}")
    if current_sim is not None:
        groups.append((current_sim, current_meas))
    return groups


def _normalize_legacy_triple_rows(
    raw_rows: list[dict[str, str]],
    fieldnames: list[str],
) -> list[dict[str, str]]:
    """旧版 21000 行三行/帧 → 14000 行双行/帧（仿真行 + 实测行）。"""
    dual: list[dict[str, str]] = []
    for idx in range(0, len(raw_rows), ROWS_PER_FRAME_LEGACY_TRIPLE):
        truth_row = raw_rows[idx]
        ref_row = raw_rows[idx + 1]
        meas_row = raw_rows[idx + 2]
        sim = {fn: ref_row.get(fn, "") for fn in fieldnames}
        sim["RowKind"] = ROW_KIND_SIM
        sim["Attempt"] = ""
        for key in INFO_BIT_KEYS:
            if truth_row.get(key, "").strip():
                sim[key] = truth_row[key]
        dual.append(sim)
        meas = {fn: meas_row.get(fn, "") for fn in fieldnames}
        meas["RowKind"] = ROW_KIND_MEASURED
        dual.append(meas)
    return dual


def _empty_measured_csv_row(sim_row: dict[str, str], fieldnames: list[str]) -> dict[str, str]:
    """新建空白实测行（保留 EbNo / FrameIdx）。"""
    row = {fn: "" for fn in fieldnames}
    row["RowKind"] = ROW_KIND_MEASURED
    row["Attempt"] = ""
    row["EbNo_dB"] = sim_row.get("EbNo_dB", "")
    row["FrameIdx"] = sim_row.get("FrameIdx", "")
    return row


def _measured_infobits_for_export(
    mode: int,
    currents: list[float],
    chip_bits: list[int] | None,
) -> list[int]:
    """实测行 InfoBit：按规则留空（不参与 BER）。"""
    del mode, currents, chip_bits
    return []


def _attempt_to_csv_row(
    sim_row: dict[str, str],
    fieldnames: list[str],
    attempt_num: int,
    rx_hex: str,
    iteration_count: int,
    currents: list[float],
    chip_bits: list[int],
    *,
    mode: int = 1,
    hardware_converged: bool | None = None,
) -> dict[str, str]:
    """单次尝试 → 实测 CSV 行（InfoBit 留空；CodeBit = 回传硬判）。"""
    row = _empty_measured_csv_row(sim_row, fieldnames)
    row["Attempt"] = str(attempt_num)
    if rx_hex:
        row["RecvHex"] = rx_hex
    if iteration_count > 0:
        row["IterNum"] = str(iteration_count)
    for i, i_col in enumerate(currents[:8]):
        row[f"Out[{i}]"] = _format_out_current(i_col)
    # 实测 InfoBit 留空（不参与 BER）
    for i in range(4):
        key = f"InfoBit[{i}]"
        if key in fieldnames:
            row[key] = ""
    _fill_coded_bits_from_outputs(row, currents, fieldnames)
    if hardware_converged is not None and "HardwareConverged" in fieldnames:
        row["HardwareConverged"] = "Y" if hardware_converged else "N"
    return row


def _format_out_current(value: float) -> str:
    return f"{value:.4f}"


def _format_in_value(raw: int) -> str:
    from protocol.codec import TX_MID_VOLTAGE, raw_to_row_voltage

    in_val = raw_to_row_voltage(int(raw)) - TX_MID_VOLTAGE
    return f"{in_val:.4f}"


def _sim_csv_row_from_case(
    tc: CaseRecord,
    fieldnames: list[str],
    *,
    source_sim: dict[str, str] | None = None,
) -> dict[str, str]:
    """从 CaseRecord 构建仿真 CSV 行（Attempt 恒为空）。"""
    if source_sim:
        sim = {fn: source_sim.get(fn, "") for fn in fieldnames}
    else:
        sim = {fn: "" for fn in fieldnames}
        for i, ch in enumerate(tc.channels[:12]):
            sim[f"In[{i}]"] = _format_in_value(ch)
        sim_outs = list(tc.sim_outputs) if tc.sim_outputs else [0.0] * 8
        for i, v in enumerate(sim_outs[:8]):
            sim[f"Out[{i}]"] = _format_out_current(v)
    if tc.snr_db is not None:
        sim["EbNo_dB"] = f"{tc.snr_db:g}"
    if tc.frame_idx is not None:
        sim["FrameIdx"] = str(tc.frame_idx)
    if tc.iter_ref is not None:
        sim["IterNum"] = str(tc.iter_ref)
    sim["RowKind"] = ROW_KIND_SIM
    sim["Attempt"] = ""
    display_bits = sim_row_display_infobits(tc)
    if display_bits:
        for i, bit in enumerate(display_bits[:4]):
            key = f"InfoBit[{i}]"
            if key in fieldnames:
                sim[key] = str(int(bit))
    sim_outs = list(tc.sim_outputs) if tc.sim_outputs else _sim_outputs_from_csv_row(sim)
    # 优先写回测试集给定的 CodeBit；仅缺列时用 Out 硬判补齐，不覆盖已有值
    if tc.coded_bits is not None:
        prefix = detect_coded_bit_prefix(fieldnames)
        if prefix:
            for i, bit in enumerate(tc.coded_bits[:CODED_BIT_COUNT]):
                key = f"{prefix}[{i}]"
                if key in fieldnames:
                    sim[key] = str(int(bit))
    _fill_coded_bits_from_outputs(sim, sim_outs, fieldnames, only_empty=True)
    return sim


def post_test_dataset_path(source: str | Path) -> Path:
    """测后数据集路径：data/测后数据集/YYYY-MM-DD/{源文件名}_result_时间戳.csv。

    与源测试集分目录存放，按跑测日期分子文件夹，便于按天查找。
    """
    src = Path(source)
    ts = datetime.now()
    day_dir = post_test_day_dir(ts)
    return day_dir / f"{src.stem}_result_{ts.strftime('%Y%m%d_%H%M%S')}.csv"


def migrate_data_layout(*, dry_run: bool = False) -> list[str]:
    """将旧版 data/ 扁平布局迁移到 测试集 / 测后数据集/日期。

    - 源 CSV（非 *_result_*）→ data/测试集/
    - *_result_*.csv 及同名 .xlsx → data/测后数据集/YYYY-MM-DD/（日期取自文件名时间戳）
    返回操作说明列表。
    """
    root = data_root()
    if not root.is_dir():
        return []
    logs: list[str] = []
    ts_dir = testset_dir()
    pt_root = post_test_root()
    skip_names = {TESTSET_DIR_NAME, POST_TEST_DIR_NAME}

    def _day_from_result_name(name: str) -> str | None:
        m = _RESULT_TS_RE.search(name)
        if not m:
            return None
        ymd = m.group(1)
        return f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"

    def _move(src: Path, dest: Path, label: str) -> None:
        if dry_run:
            logs.append(f"MOVE {src.name} → {label}")
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            logs.append(f"SKIP exists {dest.relative_to(root)}")
            return
        shutil.move(str(src), str(dest))
        logs.append(f"MOVED {src.name} → {label}")

    for path in sorted(root.iterdir()):
        if path.name in skip_names or path.name.startswith("."):
            continue
        if path.is_dir():
            continue
        day = _day_from_result_name(path.name)
        if day is not None:
            dest_dir = pt_root / day
            _move(path, dest_dir / path.name, f"测后数据集/{day}/")
            continue
        # 源测试文件：csv / bak；非 result 的 xlsx 样例也进测试集
        suffix = path.suffix.lower()
        if suffix in {".csv", ".bak"} or (
            suffix == ".xlsx" and "_result_" not in path.name.lower()
        ):
            _move(path, ts_dir / path.name, "测试集/")

    return logs


def post_test_excel_paths(post_test_path: str | Path) -> dict[str, Path]:
    """测后 Excel 路径：完整 / ok / ber。"""
    p = Path(post_test_path)
    stem = p.with_suffix("")  # drop .csv
    return {
        "full": Path(f"{stem}.xlsx"),
        "ok": Path(f"{stem}_ok.xlsx"),
        "ber": Path(f"{stem}_ber.xlsx"),
    }


def error_rx_dataset_path(post_test_path: str | Path) -> Path:
    """兼容旧名：指向去通信错误后的 ok Excel。"""
    return post_test_excel_paths(post_test_path)["ok"]


def is_comm_error_frame(tc: "CaseRecord") -> bool:
    """通信错误帧：已测且最终仍未收敛（重发耗尽后仍有 raw < 0x2FF）。

    ok 导出时对此类帧是「整套删除」：仿真行 + Attempt 1..N 全部不要，
    不是只删最后一次失败 Attempt。中间曾失败但最终收敛的帧不算通信错误帧
    （仅删中间未收敛 Attempt，见 build_export_rows）。
    """
    from analysis.aggregate import frame_was_tested, has_measured

    if not frame_was_tested(tc) and not has_measured(tc):
        return False
    return not bool(tc.hardware_converged)


def measured_row_is_nonconverged(row: dict[str, str]) -> bool:
    """实测行是否未收敛（应在 ok/ber 中剔除）。

    判定优先 HardwareConverged=N；若无该列则看任一路 Out 对应 raw < 0x2FF
    （Out≈+2.5 即 raw≈0，是最常见情形）。
    """
    from protocol.codec import column_current_to_raw
    from protocol.validator import RETRY_THRESHOLD

    if str(row.get("RowKind", "")).strip() != ROW_KIND_MEASURED:
        return False
    hc = str(row.get("HardwareConverged", "")).strip().upper()
    if hc == "N":
        return True
    if hc == "Y":
        return False
    for i in range(8):
        raw_s = str(row.get(f"Out[{i}]", "")).strip()
        if not raw_s:
            continue
        try:
            i_col = float(raw_s)
        except ValueError:
            continue
        if column_current_to_raw(i_col) < RETRY_THRESHOLD:
            return True
    return False


def _export_row_snr(row: dict[str, str]) -> float | None:
    raw = str(row.get("EbNo_dB", "")).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _export_row_frame_idx(row: dict[str, str]) -> int:
    raw = str(row.get("FrameIdx", "")).strip()
    if not raw:
        return 0
    try:
        return int(float(raw))
    except ValueError:
        return 0


def trim_ok_rows_for_chart(
    rows: list[dict[str, str]],
    *,
    max_frames_per_snr: int | None = None,
) -> list[dict[str, str]]:
    """图表验算：每个 EbNo_dB 按 FrameIdx 只保留前 N 帧（1 仿真 + 1 实测/帧）。"""
    if max_frames_per_snr is None:
        from ui.chart_settings import get_frames_per_snr

        cap = get_frames_per_snr()
    else:
        cap = int(max_frames_per_snr)
    if cap <= 0 or not rows:
        return []

    by_snr: dict[float, list[tuple[int, dict[str, str], dict[str, str]]]] = {}
    i = 0
    n = len(rows)
    while i < n:
        row = rows[i]
        if str(row.get("RowKind", "")).strip() not in (ROW_KIND_SIM, "仿真行"):
            i += 1
            continue
        sim = row
        snr = _export_row_snr(sim)
        if snr is None:
            i += 1
            continue
        j = i + 1
        if j >= n or str(rows[j].get("RowKind", "")).strip() not in (
            ROW_KIND_MEASURED,
            "实测行",
        ):
            i += 1
            continue
        meas = rows[j]
        by_snr.setdefault(snr, []).append(
            (_export_row_frame_idx(sim), sim, meas)
        )
        i = j + 1

    out: list[dict[str, str]] = []
    for snr in sorted(by_snr):
        group = sorted(by_snr[snr], key=lambda x: x[0])
        for _, sim, meas in group[:cap]:
            out.append(sim)
            out.append(meas)
    return out


def validate_ok_export_rows(rows: list[dict[str, str]]) -> None:
    """断言 ok 表：每帧恰好 1 仿真 + 1 实测。"""
    i = 0
    n = len(rows)
    frame = 0
    while i < n:
        frame += 1
        kind = str(rows[i].get("RowKind", "")).strip()
        if kind not in (ROW_KIND_SIM, "仿真行"):
            raise ValueError(f"ok 第 {frame} 帧应以仿真行开头，实际 RowKind={kind!r}")
        if i + 1 >= n:
            raise ValueError(f"ok 第 {frame} 帧缺少实测行")
        kind2 = str(rows[i + 1].get("RowKind", "")).strip()
        if kind2 not in (ROW_KIND_MEASURED, "实测行"):
            raise ValueError(f"ok 第 {frame} 帧第二行应为实测行，实际 RowKind={kind2!r}")
        if i + 2 < n and str(rows[i + 2].get("RowKind", "")).strip() in (
            ROW_KIND_SIM,
            "仿真行",
        ):
            pass
        elif i + 2 < n and str(rows[i + 2].get("RowKind", "")).strip() in (
            ROW_KIND_MEASURED,
            "实测行",
        ):
            raise ValueError(f"ok 第 {frame} 帧出现多条实测行（应为 1 仿真 + 1 实测）")
        i += 2


def filter_ok_export_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """result → ok：去掉未收敛实测行；若某帧无剩余实测行则连仿真行一并去掉。"""
    out: list[dict[str, str]] = []
    i = 0
    n = len(rows)
    while i < n:
        row = rows[i]
        kind = str(row.get("RowKind", "")).strip()
        if kind != ROW_KIND_SIM:
            # 孤立实测行：仅保留已收敛的
            if kind == ROW_KIND_MEASURED and not measured_row_is_nonconverged(row):
                out.append(row)
            i += 1
            continue
        sim = row
        j = i + 1
        kept_meas: list[dict[str, str]] = []
        while j < n and str(rows[j].get("RowKind", "")).strip() == ROW_KIND_MEASURED:
            if not measured_row_is_nonconverged(rows[j]):
                kept_meas.append(rows[j])
            j += 1
        if kept_meas:
            out.append(sim)
            out.extend(kept_meas)
        i = j
    return out


@dataclass
class TestCsvDataset:
    """testdata.csv 全文件镜像，支持内存更新实测行并导出测试后数据集。"""

    path: Path
    fieldnames: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)
    interleaved: bool = True
    rows_per_frame: int = ROWS_PER_FRAME

    def _stride(self) -> int:
        return ROWS_PER_FRAME

    def ensure_export_fieldnames(self) -> None:
        """补全导出/检查点表头（含 Attempt），避免旧交错 CSV 缺列被 DictWriter 丢弃。"""
        new_fn = resolve_export_fieldnames(self.fieldnames)
        if new_fn == self.fieldnames and "Attempt" in self.fieldnames:
            return
        self.fieldnames = new_fn
        _pad_rows_to_fieldnames(self.rows, new_fn)

    def sim_row_index(self, case_index: int) -> int:
        return case_index * ROWS_PER_FRAME

    def meas_row_index(self, case_index: int) -> int:
        return case_index * ROWS_PER_FRAME + 1

    def _dual_row_sim_source(self, case_index: int) -> dict[str, str] | None:
        """内存双行布局下取仿真行；已展开或非仿真行时返回 None。"""
        si = self.sim_row_index(case_index)
        if si >= len(self.rows):
            return None
        row = self.rows[si]
        kind = str(row.get("RowKind", "")).strip()
        if kind in (ROW_KIND_SIM, ROW_KIND_REF):
            return row
        return None

    def build_export_rows(
        self,
        cases: list[CaseRecord],
        *,
        exclude_comm_errors: bool = False,
    ) -> list[dict[str, str]]:
        """从 CaseRecord 全新构建导出行：每帧 1 仿真行 + 各次实测行。

        exclude_comm_errors=True（② ok 口径）：
          - 最终仍通信失败：整帧删除
          - 每帧严格 1 仿真 + 1 实测（``ok_frame_attempt_record``）：
            优先末次收敛且无误码 Attempt；否则末次收敛（可有误码）
        """
        if not self.interleaved or not cases:
            return [dict(r) for r in self.rows]
        from analysis.aggregate import ok_frame_attempt_record

        new_rows: list[dict[str, str]] = []
        for idx, tc in enumerate(cases):
            if exclude_comm_errors:
                ar = ok_frame_attempt_record(tc)
                if ar is None:
                    continue
                sim = _sim_csv_row_from_case(
                    tc,
                    self.fieldnames,
                    source_sim=self._dual_row_sim_source(idx),
                )
                new_rows.append(sim)
                new_rows.append(
                    _attempt_to_csv_row(
                        sim,
                        self.fieldnames,
                        ar.attempt,
                        ar.rx_hex,
                        ar.iteration_count,
                        ar.actual_currents,
                        ar.chip_bits,
                        mode=tc.mode,
                        hardware_converged=True,
                    )
                )
                continue

            sim = _sim_csv_row_from_case(
                tc,
                self.fieldnames,
                source_sim=self._dual_row_sim_source(idx),
            )
            meas_rows: list[dict[str, str]] = []
            if tc.attempt_records:
                for ar in tc.attempt_records:
                    meas_rows.append(
                        _attempt_to_csv_row(
                            sim,
                            self.fieldnames,
                            ar.attempt,
                            ar.rx_hex,
                            ar.iteration_count,
                            ar.actual_currents,
                            ar.chip_bits,
                            mode=tc.mode,
                            hardware_converged=ar.hardware_converged,
                        )
                    )
            elif has_measured(tc):
                meas_rows.append(
                    _attempt_to_csv_row(
                        sim,
                        self.fieldnames,
                        1,
                        tc.rx_hex,
                        tc.iteration_count,
                        tc.actual_currents,
                        tc.chip_bits,
                        mode=tc.mode,
                        hardware_converged=tc.hardware_converged,
                    )
                )
            new_rows.append(sim)
            new_rows.extend(meas_rows)
        return new_rows

    def build_error_rx_export_rows(self, cases: list[CaseRecord]) -> list[dict[str, str]]:
        """仅导出通信错误帧（最终未收敛）：仿真行 + 全部 Attempt（整帧剔除对照用）。"""
        if not self.interleaved or not cases:
            return []
        new_rows: list[dict[str, str]] = []
        for idx, tc in enumerate(cases):
            if not is_comm_error_frame(tc):
                continue
            sim = _sim_csv_row_from_case(
                tc,
                self.fieldnames,
                source_sim=self._dual_row_sim_source(idx),
            )
            new_rows.append(sim)
            if tc.attempt_records:
                for ar in tc.attempt_records:
                    new_rows.append(
                        _attempt_to_csv_row(
                            sim,
                            self.fieldnames,
                            ar.attempt,
                            ar.rx_hex,
                            ar.iteration_count,
                            ar.actual_currents,
                            ar.chip_bits,
                            mode=tc.mode,
                            hardware_converged=ar.hardware_converged,
                        )
                    )
            elif has_measured(tc):
                new_rows.append(
                    _attempt_to_csv_row(
                        sim,
                        self.fieldnames,
                        1,
                        tc.rx_hex,
                        tc.iteration_count,
                        tc.actual_currents,
                        tc.chip_bits,
                        mode=tc.mode,
                        hardware_converged=tc.hardware_converged,
                    )
                )
        return new_rows

    def rebuild_rows_from_cases(self, cases: list[CaseRecord]) -> None:
        """按用例重建交错行：每帧 1 仿真行 + attempt_records 中各次实测行（测试/兼容用）。"""
        if not self.interleaved or not cases:
            return
        self.rows = self.build_export_rows(cases)

    def update_measured(self, case_index: int, tc: CaseRecord) -> None:
        """将 CaseRecord 写入内存实测行（导出前 rebuild_rows_from_cases）。"""
        if not self.interleaved:
            return
        mi = self.meas_row_index(case_index)
        si = self.sim_row_index(case_index)
        if mi >= len(self.rows) or si >= len(self.rows):
            return
        sim_row = self.rows[si]
        if tc.attempt_records:
            ar = tc.attempt_records[-1]
            row = _attempt_to_csv_row(
                sim_row,
                self.fieldnames,
                ar.attempt,
                ar.rx_hex,
                ar.iteration_count,
                ar.actual_currents,
                ar.chip_bits,
                mode=tc.mode,
                hardware_converged=ar.hardware_converged,
            )
        elif has_measured(tc):
            row = _attempt_to_csv_row(
                sim_row,
                self.fieldnames,
                1,
                tc.rx_hex,
                tc.iteration_count,
                tc.actual_currents,
                tc.chip_bits,
                mode=tc.mode,
                hardware_converged=tc.hardware_converged,
            )
        else:
            row = _empty_measured_csv_row(sim_row, self.fieldnames)
        self.rows[mi] = row

    def clear_measured_row(self, case_index: int) -> None:
        if not self.interleaved:
            return
        si = self.sim_row_index(case_index)
        mi = self.meas_row_index(case_index)
        if si >= len(self.rows) or mi >= len(self.rows):
            return
        self.rows[mi] = _empty_measured_csv_row(self.rows[si], self.fieldnames)

    def update_sim_infobits(self, case_index: int, info_bits: list[int]) -> None:
        """写入仿真行 InfoBit[0..3]（Mode2 CSV 真值列）。"""
        if not self.interleaved:
            return
        si = self.sim_row_index(case_index)
        if si >= len(self.rows):
            return
        row = self.rows[si]
        for i, bit in enumerate(info_bits[:4]):
            key = f"InfoBit[{i}]"
            row[key] = str(int(bit))

    def clear_all_measured(self) -> None:
        """清空全部实测行。"""
        if not self.interleaved:
            return
        n_cases = len(self.rows) // ROWS_PER_FRAME
        keep = frozenset({"RowKind", "EbNo_dB", "FrameIdx"})
        for case_index in range(n_cases):
            si = self.sim_row_index(case_index)
            mi = self.meas_row_index(case_index)
            if si >= len(self.rows) or mi >= len(self.rows):
                continue
            sim_row = self.rows[si]
            for key in list(self.rows[mi]):
                if key in keep:
                    if key == "RowKind":
                        self.rows[mi][key] = ROW_KIND_MEASURED
                    elif key == "EbNo_dB":
                        self.rows[mi][key] = sim_row.get("EbNo_dB", "")
                    elif key == "FrameIdx":
                        self.rows[mi][key] = sim_row.get("FrameIdx", "")
                else:
                    self.rows[mi][key] = ""

    def _write_to(self, path: Path) -> None:
        write_csv_snapshot(path, self.fieldnames, self.rows)

    @staticmethod
    def snapshot_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        """浅拷贝行列表，供后台检查点写入时与主线程解耦。"""
        return [dict(r) for r in rows]

    def save(self) -> None:
        """写回加载时的源文件（一般勿在批量测试中使用）。"""
        self._write_to(self.path)

    def save_as(self, path: str | Path, *, export_rows: list[dict[str, str]] | None = None) -> Path:
        """导出 CSV；export_rows 给定时不改写内存 rows（测后多 Attempt 导出）。"""
        path = Path(path)
        if export_rows is not None:
            write_csv_snapshot(path, self.fieldnames, export_rows)
        else:
            self._write_to(path)
        return path


def write_csv_snapshot(
    path: Path | str,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


@dataclass
class TestDataLoad:
    """load_test_csv 返回值：用例列表 + 可选文件镜像。"""

    cases: list[dict]
    dataset: TestCsvDataset | None = None
    interleaved: bool = False
    matrix_mode: int = 1


def build_interleaved_rows_from_legacy(
    sim_rows: list[dict[str, str]],
    old_fieldnames: list[str],
    *,
    matrix_mode: int = 1,
) -> tuple[list[str], list[dict[str, str]], int]:
    """将单行仿真 CSV 展开为交错双行（仿真行 + 空白实测行），仅内存。

    测试集已给定的 CodeBit/CodedBit 必须保留；仅缺列时用 Out 硬判补齐。
    （旧逻辑 only_empty=False 会在展开时用 Out 硬判覆盖给定值，导致监测误报/BER 参考错乱。）
    """
    del matrix_mode  # 展开不依赖模式；保留参数兼容调用方
    fieldnames = resolve_export_fieldnames(old_fieldnames)
    out_rows: list[dict[str, str]] = []
    for sim in sim_rows:
        sim_out = {fn: "" for fn in fieldnames}
        sim_out["Attempt"] = ""
        for key in old_fieldnames:
            if key in sim_out:
                sim_out[key] = sim.get(key, "")
        sim_out["RowKind"] = ROW_KIND_SIM
        sim_outs = _sim_outputs_from_csv_row(sim_out)
        # 关键：不得覆盖测试集给定 CodeBit
        _fill_coded_bits_from_outputs(
            sim_out, sim_outs, fieldnames, only_empty=True
        )
        out_rows.append(sim_out)
        out_rows.append(_empty_measured_csv_row(sim_out, fieldnames))
    return fieldnames, out_rows, ROWS_PER_FRAME


def load_test_csv(path: str | Path) -> TestDataLoad:
    """从 testdata.csv / mode1.csv 加载测试用例。

    支持格式：
    - **单行**（如 7000/21000/27000 行）：EbNo_dB, In[], Out[], 可选 CodedBit[0..7], InfoBit[0..3], IterNum
    - **交错双行**（14000 行）：RowKind 仿真行/实测行（Mode1/2/3）
    - **旧版三行**（21000 行）：加载时自动规范为双行
    """
    path = Path(path)
    path_mode = infer_matrix_mode_from_path(path)
    cases: list[dict] = []
    raw_rows: list[dict[str, str]] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV 文件为空或缺少表头")

        fieldnames = [fn.strip() for fn in reader.fieldnames]
        matrix_mode = _infer_matrix_mode_from_fieldnames(fieldnames, path_mode)
        if "EbNo_dB" not in fieldnames or "In[0]" not in fieldnames or "Out[0]" not in fieldnames:
            raise ValueError(
                "不支持的 CSV 格式；请使用 mode1.csv / mode2.csv（EbNo_dB, In[0..11], "
                "Out[0..7], 可选 InfoBit[0..3], IterNum）或交错双行 testdata.csv"
            )

        interleaved = "RowKind" in fieldnames

        for row in reader:
            normalized = {k.strip(): (v if v is not None else "") for k, v in row.items()}
            raw_rows.append(normalized)

        interleaved = "RowKind" in fieldnames
        legacy_triple = interleaved and _detect_legacy_triple_format(raw_rows)

        if interleaved and legacy_triple:
            if len(raw_rows) % ROWS_PER_FRAME_LEGACY_TRIPLE != 0:
                raise ValueError(
                    f"旧版三行格式行数应为 {ROWS_PER_FRAME_LEGACY_TRIPLE} 的倍数，"
                    f"当前 {len(raw_rows)} 行"
                )
            for triple_idx in range(0, len(raw_rows), ROWS_PER_FRAME_LEGACY_TRIPLE):
                truth_row = raw_rows[triple_idx]
                ref_row = raw_rows[triple_idx + 1]
                meas_row = raw_rows[triple_idx + 2]
                row_num = triple_idx + 2
                ref_kind = ref_row.get("RowKind", "").strip()
                meas_kind = meas_row.get("RowKind", "").strip()
                if ref_kind and ref_kind not in (ROW_KIND_REF, ROW_KIND_SIM):
                    raise ValueError(f"第 {row_num + 1} 行应为 {ROW_KIND_SIM!r}，实际 {ref_kind!r}")
                if meas_kind and meas_kind != ROW_KIND_MEASURED:
                    raise ValueError(f"第 {row_num + 2} 行应为 {ROW_KIND_MEASURED!r}，实际 {meas_kind!r}")
                group = _parse_sim_row(ref_row, row_num + 1, matrix_mode=matrix_mode)
                if any(truth_row.get(key, "").strip() for key in INFO_BIT_KEYS):
                    truth_bits: list[int] = []
                    for key in INFO_BIT_KEYS:
                        bit = _int_cell(truth_row, key, 0)
                        truth_bits.append(0 if bit is None else int(bit))
                    group["info_bits"] = truth_bits
                    if matrix_mode == 2:
                        group["expected_info_bits"] = list(truth_bits)
                group.update(_parse_measured_row(meas_row))
                cases.append(group)
            raw_rows = _normalize_legacy_triple_rows(raw_rows, fieldnames)
        elif interleaved:
            for frame_idx, (sim_row, meas_rows) in enumerate(
                _group_interleaved_frame_rows(raw_rows), start=1
            ):
                row_num = frame_idx * 2
                sim_kind = sim_row.get("RowKind", "").strip()
                if sim_kind and sim_kind not in (ROW_KIND_SIM, ROW_KIND_REF):
                    raise ValueError(f"第 {row_num} 行应为 {ROW_KIND_SIM!r}，实际 {sim_kind!r}")
                group = _parse_sim_row(sim_row, row_num, matrix_mode=matrix_mode)
                if meas_rows:
                    for meas_row in meas_rows:
                        meas_kind = meas_row.get("RowKind", "").strip()
                        if meas_kind and meas_kind != ROW_KIND_MEASURED:
                            raise ValueError(
                                f"帧 {group.get('frame_idx', frame_idx)} 含非实测行: {meas_kind!r}"
                            )
                    group.update(_parse_measured_row(meas_rows[-1]))
                cases.append(group)
        else:
            for row_num, normalized in enumerate(raw_rows, start=2):
                group = _parse_sim_row(normalized, row_num, matrix_mode=matrix_mode)
                cases.append(group)

    dataset: TestCsvDataset | None = None
    if interleaved:
        dataset = TestCsvDataset(
            path=path,
            fieldnames=fieldnames,
            rows=raw_rows,
            interleaved=True,
            rows_per_frame=ROWS_PER_FRAME,
        )
        dataset.ensure_export_fieldnames()
    elif raw_rows:
        expanded_fieldnames, expanded_rows, rpf = build_interleaved_rows_from_legacy(
            raw_rows, fieldnames, matrix_mode=matrix_mode
        )
        dataset = TestCsvDataset(
            path=path,
            fieldnames=expanded_fieldnames,
            rows=expanded_rows,
            interleaved=True,
            rows_per_frame=rpf,
        )

    return TestDataLoad(
        cases=cases,
        dataset=dataset,
        interleaved=interleaved,
        matrix_mode=matrix_mode,
    )


def migrate_to_interleaved(
    src: str | Path,
    dst: str | Path | None = None,
    *,
    backup: bool = True,
) -> Path:
    """将 7000 行仿真 CSV 迁移为 14000 行交错格式（仿真行 + 空白实测行）。"""
    src = Path(src)
    out = Path(dst) if dst else src

    loaded = load_test_csv(src)
    if loaded.interleaved:
        raise ValueError(f"{src} 已是交错双行格式，无需迁移")

    if not loaded.cases:
        raise ValueError(f"{src} 无数据行")

    if loaded.dataset is None:
        raise ValueError(f"{src} 无法构建交错数据集")

    fieldnames = loaded.dataset.fieldnames
    out_rows = loaded.dataset.rows

    if backup and out == src:
        bak = src.with_suffix(src.suffix + ".bak")
        shutil.copy2(src, bak)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)

    return out
