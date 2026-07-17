"""用例记录与按 SNR 聚合统计（实测 CodeBit vs 仿真 CodeBit）。

BER（全模式，仅硬件收敛帧 raw≥0x2FF）：
  实测 CodeBit = 回传 Out 硬判（负1正0）
  仿真 CodeBit = 测试集给定（优先）；缺列时由 Sim Out 硬判
  相同 = 正确；不同 = 误码
  Mode1: 实测 Out[0..3] vs 仿真 CodeBit[4..7]；参考 = Sim Out[0..3] vs CodeBit[4..7]
  Mode2: [3,5,6,7] 同下标；Mode3: [0..1] 同下标

InfoBit：列保留；实测行导出留空；不参与 BER。
测后导出不得改写仿真行 CodeBit（测试集给定值）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from analysis.sign_compare import (
    MODE2_BER_OUT_INDICES,
    ber_meas_out_indices_for_mode,
    ber_ref_coded_bit_indices_for_mode,
    chip_value_to_bit,
    coded_bits_from_outputs,
    compare_channels_for_mode,
    compare_frame,
    compute_channel_ber_from_error_bits,
    mode2_coded_bits_from_outputs,
    sim_value_to_bit,
)
from comm.serial_worker import RxAttempt, SendResult
from protocol.codec import format_hex, in_value_to_row_voltage, row_voltage_to_raw


@dataclass
class AttemptRecord:
    """单次 RX 尝试的实测记录（含重发过程中的未收敛帧）。"""

    attempt: int
    rx_hex: str
    iteration_count: int
    actual_currents: list[float]
    actual_raws: list[int]
    chip_bits: list[int]
    channel_results: list[dict]
    match_count: int
    channel_errors: int
    passed: bool
    hardware_converged: bool


@dataclass
class CaseRecord:
    """单条测试用例及运行结果。"""

    name: str
    mode: int
    channels: list[int]
    cmd: int = 0
    sim_outputs: list[float] | None = None  # MATLAB 仿真 Out[0..7]（参考，不参与判定）
    info_bits: list[int] | None = None  # 加载时仿真行 InfoBit（列保留；BER 不用）
    expected_info_bits: list[int] | None = None  # Mode2：MATLAB CSV 真值副本（导出仿真行优先用此）
    coded_bits: list[int] | None = None  # 测试集仿真行 CodeBit[0..7]（给定则保留；BER 参考）
    iter_ref: int | None = None  # 测试集参考迭代次数
    snr_db: float | None = None
    frame_idx: int | None = None
    iteration_count: int = 0  # 芯片实测迭代次数（RX byte0 + 1）
    actual_currents: list[float] = field(default_factory=list)  # RX 列电流 I_col
    chip_bits: list[int] = field(default_factory=list)  # BER 用硬判 bit（与 CodeBit 同口径）
    actual_raws: list[int] = field(default_factory=list)
    channel_results: list[dict] = field(default_factory=list)
    tx_hex: str = ""
    rx_hex: str = ""
    match_count: int = 0
    channel_errors: int = 0  # CodeBit 不匹配数（单帧）
    passed: bool | None = None  # 全匹配，信息性；BER 用 channel_errors 聚合
    hardware_converged: bool = False
    retries: int = 0
    low_value_retries: int = 0
    success: bool = False
    error: str = ""
    attempt_records: list[AttemptRecord] = field(default_factory=list)


FRAMES_PER_SNR = 1000  # 图表 BER 基数：每 SNR 仅保留 FrameIdx 1..N 的帧对


@dataclass
class SnrPoint:
    snr_db: float
    channel_ber: float  # 实测 BER = error_bits / channel_bits（仅硬件收敛帧）
    error_bits: int  # 实测 Σ 各收敛帧 bit 不匹配数
    channel_bits: int  # Σ 收敛帧比对通道数（Mode1/2: 4×N，Mode3: 2×N）
    tested_count: int  # 图表帧数（每 SNR 至多 FRAMES_PER_SNR）
    frame_error_rate: float  # 信息性：未全匹配帧 / 收敛已测帧
    avg_iterations: float
    std_iterations: float
    case_count: int  # 该 SNR 下已加载帧数
    converged_count: int  # 硬件收敛帧数
    reference_ber: float | None = None  # 参考 BER = Sim Out 硬判 vs 指定 CodeBit
    reference_error_bits: int = 0
    reference_channel_bits: int = 0
    avg_ref_iterations: float | None = None  # 仿真行 IterNum 按 SNR 均值
    std_ref_iterations: float | None = None
    meas_iter_sum: int = 0  # 图表口径实测行 IterNum 累加
    ref_iter_sum: int = 0  # 图表口径仿真行 IterNum 累加


def sim_coded_bits_for_ber(tc: CaseRecord) -> list[int] | None:
    """BER 参考侧：仿真行 CodeBit（给定优先；缺列时 Sim Out 同下标硬判）。"""
    ref_idx = ber_ref_coded_bit_indices_for_mode(tc.mode)
    if tc.coded_bits is not None and len(tc.coded_bits) >= max(ref_idx) + 1:
        return [int(tc.coded_bits[i]) for i in ref_idx]
    sim = tc.sim_outputs or []
    if sim and len(sim) >= max(ref_idx) + 1:
        return [chip_value_to_bit(sim[i]) for i in ref_idx]
    return None


def meas_coded_bits_for_ber(tc: CaseRecord) -> list[int] | None:
    """BER 左端：实测 Out 硬判 CodeBit（负1正0）。"""
    currents = tc.actual_currents or []
    if not currents:
        return None
    return coded_bits_from_outputs(currents, tc.mode)


def mode2_reference_infobits(tc: CaseRecord) -> list[int] | None:
    """Mode2 Sim CodeBit（BER 参考）。"""
    return sim_coded_bits_for_ber(tc) if int(tc.mode) == 2 else None


def mode2_truth_infobits(tc: CaseRecord) -> list[int] | None:
    """Mode2 仿真行真值 = CSV InfoBit 列（expected_info_bits 优先；列保留，BER 不用）。"""
    if tc.expected_info_bits is not None:
        return list(tc.expected_info_bits)
    if tc.info_bits is not None:
        return list(tc.info_bits)
    return None


def mode2_measured_infobits(tc: CaseRecord) -> list[int] | None:
    """Mode2 实测 CodeBit（BER 左端）。"""
    return meas_coded_bits_for_ber(tc) if int(tc.mode) == 2 else None


def mode2_truth_infobits_for_export(tc: CaseRecord) -> list[int] | None:
    """Mode2 真实行 InfoBit = CSV 真值（加载时 info_bits）。"""
    return mode2_truth_infobits(tc)


def sim_row_display_infobits(tc: CaseRecord) -> list[int] | None:
    """仿真行 InfoBit 展示：Mode2 = CSV 真值；Mode1/3 = tc.info_bits。"""
    if int(tc.mode) == 2:
        return mode2_truth_infobits(tc)
    return tc.info_bits


def mode2_export_measured_infobits(currents: list[float]) -> list[int]:
    """已废弃：实测行 InfoBit 导出留空，不参与 BER。保留函数以免旧脚本导入失败。"""
    return []


def comparison_info_bits(tc: CaseRecord) -> list[int] | None:
    """BER 比对用期望 CodeBit（仿真行给定 CodeBit 或 Sim Out 硬判）。"""
    return sim_coded_bits_for_ber(tc)


def in_value_to_raw(in_val: float) -> int:
    """testdata In[i] 归一化浮点 → 12-bit DAC 码（经行电压公式）。"""
    return row_voltage_to_raw(in_value_to_row_voltage(in_val))


def attempt_from_rx(
    parsed: dict,
    rx_frame: bytes,
    attempt: int,
    converged: bool,
    info_bits: list[int] | None,
    *,
    mode: int = 1,
    sim_outputs: list[float] | None = None,
) -> AttemptRecord:
    """由单次 RX 解析结果构建 AttemptRecord 并执行 bit 比对。"""
    compare_n = compare_channels_for_mode(mode)
    currents = [o["current"] for o in parsed["outputs"]]
    raws = [o["raw"] for o in parsed["outputs"]]
    ar = AttemptRecord(
        attempt=attempt,
        rx_hex=format_hex(rx_frame),
        iteration_count=parsed["iteration"],
        actual_currents=currents,
        actual_raws=raws,
        chip_bits=[],
        channel_results=[],
        match_count=0,
        channel_errors=0,
        passed=False,
        hardware_converged=converged,
    )
    if info_bits or (int(mode) == 2 and sim_outputs):
        result = compare_frame(
            currents,
            info_bits or [],
            sim_outputs=sim_outputs,
            compare_channels=compare_n,
            mode=mode,
        )
        ar.channel_results = result["channels"]
        ar.chip_bits = [ch["chip_bit"] for ch in result["channels"] if ch.get("judged")]
        ar.match_count = result["match_count"]
        ar.channel_errors = result.get("channel_errors", compare_n - result["match_count"])
        ar.passed = result["passed"]
    else:
        ar.chip_bits = [chip_value_to_bit(c) for c in currents[:compare_n]]
    return ar


def apply_bit_compare(tc: CaseRecord) -> dict | None:
    """对已有实测列电流执行 CodeBit 比对，写入 match_count / channel_errors / passed。"""
    if not tc.actual_currents:
        tc.match_count = 0
        tc.channel_errors = 0
        tc.passed = None
        tc.channel_results = []
        tc.chip_bits = []
        return None
    ref_bits = sim_coded_bits_for_ber(tc)
    if not ref_bits:
        tc.match_count = 0
        tc.channel_errors = 0
        tc.passed = None
        tc.channel_results = []
        tc.chip_bits = []
        return None

    compare_n = compare_channels_for_mode(tc.mode)
    result = compare_frame(
        tc.actual_currents,
        ref_bits,
        sim_outputs=tc.sim_outputs,
        compare_channels=compare_n,
        mode=tc.mode,
    )
    tc.channel_results = result["channels"]
    tc.chip_bits = [ch["chip_bit"] for ch in result["channels"] if ch.get("judged")]
    tc.match_count = result["match_count"]
    tc.channel_errors = result.get("channel_errors", compare_n - result["match_count"])
    tc.passed = result["passed"]
    return result


# 兼容旧名
apply_sim_compare = apply_bit_compare


def converged_cases(cases: list[CaseRecord]) -> list[CaseRecord]:
    """仅保留硬件收敛帧（信息性计数；BER/迭代聚合用 tested_cases_with_rx）。"""
    return [
        tc
        for tc in cases
        if tc.hardware_converged
        and tc.success
        and tc.actual_currents
        and tc.iteration_count > 0
    ]


def tested_cases_with_rx(cases: list[CaseRecord]) -> list[CaseRecord]:
    """已测且含有效 RX 的帧（含未收敛；重试过程中的中间 RX 不计）。"""
    return [
        tc
        for tc in cases
        if frame_was_tested(tc)
        and tc.actual_currents
        and tc.iteration_count > 0
    ]


def compute_frame_error_rate(cases: list[CaseRecord]) -> float:
    """信息性帧错误率：未 4/4 全匹配的帧数 / 硬件收敛已测帧数（raw < 0x2FF 不计入）。"""
    total = 0
    errors = 0
    for tc in cases:
        if not tc.hardware_converged or tc.passed is None:
            continue
        total += 1
        if not tc.passed:
            errors += 1
    return errors / total if total > 0 else 0.0


def frame_was_tested(tc: CaseRecord) -> bool:
    """该帧是否已执行过串口收发（含未收敛）。"""
    return bool(tc.error or tc.retries > 0 or tc.rx_hex or tc.actual_currents or tc.iteration_count > 0)


def ber_eligible_cases(cases: list[CaseRecord]) -> list[CaseRecord]:
    """参与 BER 统计的帧：已测且硬件收敛（CH1–8 raw 均 ≥ 0x2FF）。"""
    return [
        tc
        for tc in cases
        if frame_was_tested(tc) and tc.hardware_converged and tc.actual_currents
    ]


def count_measured_error_bits(tc: CaseRecord) -> int:
    """单帧实测 error bits：实测 CodeBit vs 仿真 CodeBit。

    raw < 0x2FF（未硬件收敛）的帧不计入误码，返回 0。
    """
    if not frame_was_tested(tc) or not tc.hardware_converged:
        return 0
    sim_bits = sim_coded_bits_for_ber(tc)
    meas_bits = meas_coded_bits_for_ber(tc)
    if not sim_bits or not meas_bits:
        return 0
    n = min(len(sim_bits), len(meas_bits))
    return sum(int(meas_bits[j]) != int(sim_bits[j]) for j in range(n))


def last_converged_attempt_record(tc: CaseRecord) -> AttemptRecord | None:
    """该帧最后一次通信收敛（raw≥0x2FF）的 Attempt。"""
    for ar in reversed(tc.attempt_records):
        if ar.hardware_converged:
            return ar
    if tc.hardware_converged and tc.actual_currents and frame_was_tested(tc):
        return AttemptRecord(
            attempt=1,
            rx_hex=tc.rx_hex,
            iteration_count=tc.iteration_count,
            actual_currents=list(tc.actual_currents),
            actual_raws=list(tc.actual_raws),
            chip_bits=list(tc.chip_bits),
            channel_results=list(tc.channel_results),
            match_count=tc.match_count,
            channel_errors=tc.channel_errors,
            passed=bool(tc.passed),
            hardware_converged=True,
        )
    return None


def attempt_record_is_ber_pass(tc: CaseRecord, ar: AttemptRecord) -> bool:
    """收敛 Attempt 相对仿真 CodeBit 是否无误码。"""
    if not ar.hardware_converged:
        return False
    return count_attempt_error_bits(tc, ar) == 0


def ok_frame_attempt_record(tc: CaseRecord) -> AttemptRecord | None:
    """ok 口径：每帧保留 1 条实测 Attempt。

    1. 整帧通信失败（``is_comm_error_frame``）→ None（整帧不进 ok）
    2. 优先 **末次「收敛且无误码」** Attempt
    3. 否则 **末次收敛** Attempt（可有误码）
    """
    from csv_loader import is_comm_error_frame

    if is_comm_error_frame(tc):
        return None

    last_pass: AttemptRecord | None = None
    last_converged: AttemptRecord | None = None
    for ar in tc.attempt_records:
        if not ar.hardware_converged:
            continue
        last_converged = ar
        if attempt_record_is_ber_pass(tc, ar):
            last_pass = ar

    if last_pass is not None:
        return last_pass
    if last_converged is not None:
        return last_converged
    return last_converged_attempt_record(tc)


def _ok_pair_sort_key(item: tuple[CaseRecord, AttemptRecord]) -> tuple[int | float, str]:
    tc, _ = item
    fi = tc.frame_idx if tc.frame_idx is not None else 0
    return (fi, tc.name)


def is_ok_chart_frame(
    tc: CaseRecord,
    *,
    max_per_snr: int = FRAMES_PER_SNR,
) -> bool:
    """单帧是否计入图表子集（FrameIdx 1..max_per_snr；缺 FrameIdx 时不排除）。"""
    if tc.frame_idx is None:
        return True
    return int(tc.frame_idx) <= int(max_per_snr)


def ok_chart_frame_attempts(
    cases: list[CaseRecord] | None = None,
    *,
    pairs: list[tuple[CaseRecord, AttemptRecord]] | None = None,
    max_per_snr: int = FRAMES_PER_SNR,
) -> list[tuple[CaseRecord, AttemptRecord]]:
    """图表用 ok 子集：每 SNR 按 FrameIdx 取前 max_per_snr 帧（1 仿真 + 1 实测/帧）。"""
    if pairs is None:
        if cases is None:
            return []
        pairs = ok_frame_attempts(cases)
    by_snr: dict[float, list[tuple[CaseRecord, AttemptRecord]]] = {}
    for tc, ar in pairs:
        if tc.snr_db is None:
            continue
        by_snr.setdefault(float(tc.snr_db), []).append((tc, ar))
    out: list[tuple[CaseRecord, AttemptRecord]] = []
    for snr in sorted(by_snr):
        group = sorted(by_snr[snr], key=_ok_pair_sort_key)
        out.extend(group[:max_per_snr])
    return out


def ok_frame_attempts(cases: list[CaseRecord]) -> list[tuple[CaseRecord, AttemptRecord]]:
    """ok 口径：跳过通信失败帧；每帧 1 条 Attempt（``ok_frame_attempt_record``）。"""
    out: list[tuple[CaseRecord, AttemptRecord]] = []
    for tc in cases:
        ar = ok_frame_attempt_record(tc)
        if ar is not None:
            out.append((tc, ar))
    return out


def count_attempt_error_bits(tc: CaseRecord, ar: AttemptRecord) -> int:
    """单次收敛 Attempt 相对仿真 CodeBit 的误码 bit 数。"""
    if not ar.hardware_converged:
        return 0
    ref = sim_coded_bits_for_ber(tc)
    meas = coded_bits_from_outputs(ar.actual_currents, tc.mode)
    if not ref or not meas:
        return 0
    n = min(len(ref), len(meas))
    return sum(int(meas[j]) != int(ref[j]) for j in range(n))


def count_channel_error_bits_from_ok_pairs(
    pairs: list[tuple[CaseRecord, AttemptRecord]],
) -> tuple[int, int, int]:
    """实测 BER：给定 ok (case, attempt) 列表。"""
    error_bits = sum(count_attempt_error_bits(tc, ar) for tc, ar in pairs)
    channel_bits = sum(compare_channels_for_mode(tc.mode) for tc, _ in pairs)
    return error_bits, channel_bits, len(pairs)


def count_channel_error_bits_ok(cases: list[CaseRecord]) -> tuple[int, int, int]:
    """实测 BER（ok 全量口径）。"""
    return count_channel_error_bits_from_ok_pairs(ok_frame_attempts(cases))


def count_channel_error_bits_ok_chart(cases: list[CaseRecord]) -> tuple[int, int, int]:
    """实测 BER（图表口径：每 SNR 前 FRAMES_PER_SNR 帧）。"""
    return count_channel_error_bits_from_ok_pairs(ok_chart_frame_attempts(cases=cases))


def count_channel_error_bits(cases: list[CaseRecord]) -> tuple[int, int, int]:
    """实测 BER（ok 口径）。"""
    return count_channel_error_bits_ok(cases)


def compute_channel_ber_from_cases(cases: list[CaseRecord]) -> float:
    """BER = error_bits / channel_bits（仅收敛帧）。"""
    error_bits, channel_bits, _ = count_channel_error_bits(cases)
    return compute_channel_ber_from_error_bits(error_bits, channel_bits)


def count_sim_reference_error_bits(cases: list[CaseRecord]) -> tuple[int, int, int]:
    """参考 BER：仿真行 Sim Out 硬判(正0负1) vs 仿真行指定 CodeBit。

    二者可无因果一一对应；仅统计具备 Sim Out 与 CodeBit 的帧。
    返回 (error_bits, channel_bits, n_frames)。
    """
    error_bits = 0
    channel_bits = 0
    n_ref = 0
    for tc in cases:
        err, bits = count_sim_reference_error_bits_for_case(tc)
        if bits <= 0:
            continue
        error_bits += err
        channel_bits += bits
        n_ref += 1
    return error_bits, channel_bits, n_ref


def count_sim_reference_error_bits_ok(
    cases: list[CaseRecord],
) -> tuple[int, int, int]:
    """参考 BER（ok 全量口径）。"""
    pairs = ok_frame_attempts(cases)
    return count_sim_reference_error_bits([tc for tc, _ in pairs])


def count_sim_reference_error_bits_ok_chart(
    cases: list[CaseRecord],
) -> tuple[int, int, int]:
    """参考 BER（图表口径：每 SNR 前 FRAMES_PER_SNR 帧）。"""
    pairs = ok_chart_frame_attempts(cases=cases)
    return count_sim_reference_error_bits([tc for tc, _ in pairs])


def count_sim_reference_error_bits_for_case(tc: CaseRecord) -> tuple[int, int]:
    """单帧参考误码：Sim Out 硬判（实测侧下标）vs 指定 CodeBit（参考侧下标）。"""
    ref_bits = sim_coded_bits_for_ber(tc)
    if not tc.sim_outputs or ref_bits is None:
        return 0, 0
    meas_idx = ber_meas_out_indices_for_mode(tc.mode)
    sim = tc.sim_outputs
    if len(sim) < max(meas_idx) + 1:
        return 0, 0
    out_bits = coded_bits_from_outputs(sim, tc.mode, out_indices=meas_idx)
    n = min(len(out_bits), len(ref_bits))
    err = sum(int(out_bits[j]) != int(ref_bits[j]) for j in range(n))
    return err, n


def compute_iteration_stats(cases: list[CaseRecord]) -> tuple[float, float]:
    """已测帧迭代次数：均值、标准差（RX byte0+1，含未收敛）。"""
    iters = [tc.iteration_count for tc in cases if tc.iteration_count > 0]
    if not iters:
        return 0.0, 0.0
    avg = sum(iters) / len(iters)
    var = sum((i - avg) ** 2 for i in iters) / len(iters)
    return avg, math.sqrt(var)


def compute_ref_iteration_stats(
    cases: list[CaseRecord],
) -> tuple[float | None, float | None]:
    """仿真行参考迭代：该 SNR 下各帧 IterNum（iter_ref）的均值、标准差。"""
    refs = [int(tc.iter_ref) for tc in cases if tc.iter_ref is not None]
    if not refs:
        return None, None
    avg = sum(refs) / len(refs)
    var = sum((i - avg) ** 2 for i in refs) / len(refs)
    return avg, math.sqrt(var)


def compute_ok_iteration_averages_from_pairs(
    pairs: list[tuple[CaseRecord, AttemptRecord]],
) -> tuple[float, float, float | None, float | None, int, int]:
    """ok 口径平均迭代（给定配对列表）。"""
    fc = len(pairs)
    if fc == 0:
        return 0.0, 0.0, None, None, 0, 0
    meas_iters = [ar.iteration_count for _, ar in pairs]
    ref_iters = [int(tc.iter_ref) if tc.iter_ref is not None else 0 for tc, _ in pairs]
    meas_avg = sum(meas_iters) / fc
    ref_avg = sum(ref_iters) / fc
    meas_var = sum((i - meas_avg) ** 2 for i in meas_iters) / fc
    ref_var = sum((i - ref_avg) ** 2 for i in ref_iters) / fc
    return (
        meas_avg,
        math.sqrt(meas_var),
        ref_avg,
        math.sqrt(ref_var),
        sum(meas_iters),
        sum(ref_iters),
    )


def compute_ok_iteration_averages(
    cases: list[CaseRecord],
) -> tuple[float, float, float | None, float | None, int, int]:
    """ok 全量口径平均迭代。"""
    return compute_ok_iteration_averages_from_pairs(ok_frame_attempts(cases))


def compute_ok_iteration_averages_chart(
    cases: list[CaseRecord],
) -> tuple[float, float, float | None, float | None, int, int]:
    """图表口径平均迭代（每 SNR 前 FRAMES_PER_SNR 帧）。"""
    return compute_ok_iteration_averages_from_pairs(ok_chart_frame_attempts(cases=cases))


def analyze_by_snr(
    cases: list[CaseRecord],
    *,
    max_per_snr: int | None = None,
) -> list[SnrPoint]:
    """按 SNR 聚合图表数据：ok 每 SNR 仅前 max_per_snr 帧（参考/实测 BER、迭代均值）。"""
    cap = int(max_per_snr if max_per_snr is not None else FRAMES_PER_SNR)
    groups: dict[float, list[CaseRecord]] = {}
    for tc in cases:
        if tc.snr_db is None:
            continue
        groups.setdefault(tc.snr_db, []).append(tc)

    points: list[SnrPoint] = []
    for snr in sorted(groups.keys()):
        group = groups[snr]
        chart_pairs = ok_chart_frame_attempts(cases=group, max_per_snr=cap)
        avg_iter, std_iter, avg_ref_iter, std_ref_iter, meas_iter_sum, ref_iter_sum = (
            compute_ok_iteration_averages_from_pairs(chart_pairs)
        )
        error_bits, channel_bits, tested_count = count_channel_error_bits_from_ok_pairs(
            chart_pairs
        )
        ref_error_bits, ref_channel_bits, _ = count_sim_reference_error_bits(
            [tc for tc, _ in chart_pairs]
        )
        ref_ber = (
            compute_channel_ber_from_error_bits(ref_error_bits, ref_channel_bits)
            if ref_channel_bits > 0
            else None
        )
        judged = [
            tc
            for tc, _ in chart_pairs
            if tc.hardware_converged and frame_was_tested(tc) and tc.passed is not None
        ]
        converged = converged_cases(group)
        points.append(
            SnrPoint(
                snr_db=snr,
                channel_ber=compute_channel_ber_from_error_bits(error_bits, channel_bits),
                error_bits=error_bits,
                channel_bits=channel_bits,
                tested_count=tested_count,
                frame_error_rate=compute_frame_error_rate(judged) if judged else 0.0,
                avg_iterations=avg_iter,
                std_iterations=std_iter,
                case_count=len(group),
                converged_count=len(converged),
                reference_ber=ref_ber,
                reference_error_bits=ref_error_bits,
                reference_channel_bits=ref_channel_bits,
                avg_ref_iterations=avg_ref_iter,
                std_ref_iterations=std_ref_iter,
                meas_iter_sum=meas_iter_sum,
                ref_iter_sum=ref_iter_sum,
            )
        )
    return points


def case_from_csv_group(group: dict) -> CaseRecord:
    """从 csv_loader 返回的 dict 构建 CaseRecord（含 CSV 实测行预填）。"""
    snr = group.get("snr_db")
    tc = CaseRecord(
        name=str(group.get("group_id", group.get("name", ""))),
        mode=int(group.get("mode", 1)),
        cmd=int(group.get("cmd", 0)),
        channels=group["channels"],
        sim_outputs=group.get("sim_outputs"),
        info_bits=group.get("info_bits"),
        expected_info_bits=group.get("expected_info_bits"),
        coded_bits=group.get("coded_bits"),
        iter_ref=group.get("iter_ref"),
        snr_db=float(snr) if snr is not None else None,
        frame_idx=group.get("frame_idx"),
    )
    measured_outputs = group.get("measured_outputs")
    measured_iter = group.get("measured_iter")
    recv_hex = group.get("recv_hex") or ""
    if measured_outputs or recv_hex or measured_iter:
        if measured_outputs:
            tc.actual_currents = list(measured_outputs)
        if measured_iter:
            tc.iteration_count = int(measured_iter)
        if recv_hex:
            tc.rx_hex = recv_hex
        if tc.actual_currents or tc.rx_hex:
            tc.hardware_converged = True
            tc.success = True
            apply_bit_compare(tc)
    return tc


def has_measured(tc: CaseRecord) -> bool:
    """实测行是否已有芯片 RX 数据。"""
    return bool(tc.rx_hex or tc.actual_currents or tc.iteration_count > 0)


def clear_measured(tc: CaseRecord) -> None:
    """清空实测行（批量/重测前调用；CSV 仿真数据不变）。"""
    tc.rx_hex = ""
    tc.iteration_count = 0
    tc.actual_currents = []
    tc.chip_bits = []
    tc.actual_raws = []
    tc.channel_results = []
    tc.match_count = 0
    tc.channel_errors = 0
    tc.passed = None
    tc.hardware_converged = False
    tc.success = False
    tc.error = ""
    tc.retries = 0
    tc.low_value_retries = 0
    tc.attempt_records = []


def _apply_attempt_to_case(tc: CaseRecord, ar: AttemptRecord) -> None:
    """将单次尝试写入 CaseRecord 主字段（用于最后一次 / BER）。"""
    tc.rx_hex = ar.rx_hex
    tc.iteration_count = ar.iteration_count
    tc.actual_raws = list(ar.actual_raws)
    tc.actual_currents = list(ar.actual_currents)
    tc.chip_bits = list(ar.chip_bits)
    tc.channel_results = list(ar.channel_results)
    tc.match_count = ar.match_count
    tc.channel_errors = ar.channel_errors
    tc.passed = ar.passed
    tc.hardware_converged = ar.hardware_converged


def fill_measured(tc: CaseRecord, result: SendResult, *, tx_hex: str = "") -> None:
    """将串口 RX 写入实测行并执行 InfoBit 比对。"""
    tc.retries = result.retries
    tc.low_value_retries = result.low_value_retries
    tc.attempt_records = []
    if tx_hex:
        tc.tx_hex = tx_hex
    elif result.tx_frame:
        tc.tx_hex = format_hex(result.tx_frame)

    if result.attempts:
        for i, att in enumerate(result.attempts, start=1):
            tc.attempt_records.append(
                attempt_from_rx(
                    att.parsed, att.rx_frame, i, att.converged,
                    comparison_info_bits(tc), mode=tc.mode,
                    sim_outputs=tc.sim_outputs,
                )
            )

    if result.success and result.parsed and result.rx_frame:
        if not tc.attempt_records:
            tc.attempt_records.append(
                attempt_from_rx(
                    result.parsed,
                    result.rx_frame,
                    1,
                    result.converged,
                    comparison_info_bits(tc),
                    mode=tc.mode,
                    sim_outputs=tc.sim_outputs,
                )
            )
        final_pass_ar = None
        for ar in tc.attempt_records:
            if ar.hardware_converged and ar.passed:
                final_pass_ar = ar
        if final_pass_ar is not None:
            _apply_attempt_to_case(tc, final_pass_ar)
        else:
            _apply_attempt_to_case(tc, tc.attempt_records[-1])
        tc.success = True
        if result.converged and final_pass_ar is not None:
            tc.error = ""
        elif result.converged:
            tc.error = "已收敛但仍有误码（已用最后一次收敛回传统计）"
        else:
            tc.error = "未收敛（已用最后一次回传统计）"
    else:
        tc.hardware_converged = False
        tc.success = False
        tc.passed = None
        tc.match_count = 0
        tc.channel_errors = 0
        tc.channel_results = []
        tc.chip_bits = []
        tc.error = result.error or "收发失败"


def clear_all_measured(cases: list[CaseRecord]) -> None:
    """批量测试开始前清空全部实测行。"""
    for tc in cases:
        clear_measured(tc)


def recompute_measured_bit_compare(cases: list[CaseRecord]) -> int:
    """Mode2：对已测帧重跑 Out[3,5,6,7] CodeBit vs Sim 比对。"""
    count = 0
    for tc in cases:
        if not frame_was_tested(tc) or not tc.actual_currents:
            continue
        apply_bit_compare(tc)
        count += 1
    return count
