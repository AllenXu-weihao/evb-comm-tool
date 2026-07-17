"""芯片实测 vs 仿真 CodeBit 判定逻辑（Sim-to-Real）。

作者: Xander
日期: 2026-06-30

# 判决规则（仿真 / 芯片统一）：
#   模拟量 >= 0 → bit=0；模拟量 < 0 → bit=1

# BER（全模式）：
#   实测侧 = 回传 Out 硬判（正≥0→0，负→1）
#   参考侧 = 仿真行 CodeBit（测试集给定；缺列时由 Sim Out 同下标硬判）
#   Mode1：实测 Out[0..3] vs 仿真 CodeBit[4..7]；参考 BER = Sim Out[0..3] vs CodeBit[4..7]
#   Mode2：Out/CodeBit[3,5,6,7] 同下标；Mode3：Out/CodeBit[0..1] 同下标
# InfoBit 列保留展示，实测行留空，不参与 BER。
"""

from __future__ import annotations

from protocol.codec import raw_to_column_current

COMPARE_CHANNELS = 4
COMPARE_CHANNELS_MODE3 = 2
DISPLAY_CHANNELS = 8
INFO_BIT_COUNT = 4
# Mode1 BER：实测 Out[0..3] 与仿真 CodeBit[4..7] 交叉比对
MODE1_BER_MEAS_OUT_INDICES = (0, 1, 2, 3)
MODE1_BER_REF_CODED_BIT_INDICES = (4, 5, 6, 7)
# Mode2 BER：Out[3,5,6,7] 与 CodeBit[3,5,6,7] 同下标（4 bit/帧）
MODE2_BER_OUT_INDICES = (3, 5, 6, 7)
# Mode3 BER：Out[0,1] 与 CodeBit[0,1] 同下标（2 bit/帧）
MODE3_BER_OUT_INDICES = (0, 1)


def ber_meas_out_indices_for_mode(mode: int) -> tuple[int, ...]:
    """BER 实测侧：参与硬判的 Out 下标。"""
    m = int(mode)
    if m == 2:
        return MODE2_BER_OUT_INDICES
    if m == 3:
        return MODE3_BER_OUT_INDICES
    return MODE1_BER_MEAS_OUT_INDICES


def ber_ref_coded_bit_indices_for_mode(mode: int) -> tuple[int, ...]:
    """BER 参考侧：仿真行 CodeBit 下标（与实测 Out 按通道配对）。"""
    m = int(mode)
    if m == 2:
        return MODE2_BER_OUT_INDICES
    if m == 3:
        return MODE3_BER_OUT_INDICES
    return MODE1_BER_REF_CODED_BIT_INDICES


def ber_channel_pairs_for_mode(mode: int) -> tuple[tuple[int, int], ...]:
    """BER 通道配对：(实测 Out 下标, 仿真 CodeBit 下标)。"""
    meas = ber_meas_out_indices_for_mode(mode)
    ref = ber_ref_coded_bit_indices_for_mode(mode)
    return tuple(zip(meas, ref))


def ber_out_indices_for_mode(mode: int) -> tuple[int, ...]:
    """参与 BER 的 Out 下标（实测硬判侧；兼容旧名）。"""
    return ber_meas_out_indices_for_mode(mode)


def compare_channels_for_mode(mode: int) -> int:
    """参与 BER 比对的 bit 数：mode3 → 2，mode2 → 4（Out[3,5,6,7]），其余 → 4。"""
    return len(ber_out_indices_for_mode(mode))


def ber_compare_label_for_mode(mode: int) -> str:
    """日志/UI 用：本模式 BER 比对口径（硬判 正≥0→0，负→1）。"""
    m = int(mode)
    meas = ber_meas_out_indices_for_mode(m)
    ref = ber_ref_coded_bit_indices_for_mode(m)
    outs = ",".join(str(i) for i in meas)
    if meas == ref:
        return f"Out/CodeBit[{outs}]（正0负1）"
    cbs = ",".join(str(i) for i in ref)
    return f"实测 Out[{outs}] vs 仿真 CodeBit[{cbs}]（正0负1）"


def coded_bits_from_outputs(
    outputs: list[float],
    mode: int = 1,
    *,
    out_indices: tuple[int, ...] | None = None,
) -> list[int]:
    """从 Out[] 指定下标硬判得到 bit 序列（负1正0）。"""
    indices = out_indices if out_indices is not None else ber_meas_out_indices_for_mode(mode)
    return [
        chip_value_to_bit(outputs[i]) if i < len(outputs) else 0
        for i in indices
    ]


def mode2_coded_bits_from_outputs(outputs: list[float]) -> list[int]:
    """Mode2 CodeBit：Out[3,5,6,7] 硬判（<0→1，≥0→0）。"""
    return coded_bits_from_outputs(outputs, 2)


def chip_value_to_bit(value: float) -> int:
    """Measured Out (I_col) → bit：模拟量 >= 0 → 0；< 0 → 1。"""
    return 1 if value < 0 else 0


def sim_value_to_bit(value: float) -> int:
    """Sim Out → bit（与 chip_value_to_bit 相同：>= 0 → 0；< 0 → 1）。"""
    return chip_value_to_bit(value)


reference_out_to_bit = chip_value_to_bit


def value_sign(value: float) -> int:
    """提取符号：+1 / -1（仿真 Out 参考展示用）。"""
    return 1 if value >= 0 else -1


def sign_label(sign: int) -> str:
    if sign > 0:
        return "+"
    if sign < 0:
        return "-"
    return "0"


def bit_label(bit: int) -> str:
    return "1" if bit else "0"


def compare_channel(chip_current: float, info_bit: int) -> bool:
    """单通道 bit 比对：chip_value_to_bit(I_col) == 期望 CodeBit。"""
    return chip_value_to_bit(chip_current) == int(info_bit)


def chip_current_from_raw(raw: int) -> float:
    """ADC raw → 列电流。"""
    return raw_to_column_current(raw)


def count_channel_errors(result: dict) -> int:
    """单帧 bit 不匹配数（每通道独立计 1 bit）。"""
    return sum(
        1
        for ch in result.get("channels", [])
        if ch.get("judged") and not ch.get("passed")
    )


def count_channel_matches(result: dict) -> tuple[int, int]:
    """单帧 (匹配通道数, 参与比对通道数)。"""
    judged = [ch for ch in result.get("channels", []) if ch.get("judged")]
    match = sum(1 for ch in judged if ch.get("passed"))
    return match, len(judged)


def compute_channel_ber_from_error_bits(error_bits: int, total_bits: int) -> float:
    """通道 BER = error_bits / total_bits。"""
    if total_bits <= 0:
        return float("nan")
    return error_bits / total_bits


def compute_channel_ber(
    channel_pass: int,
    channel_total: int,
) -> float:
    """通道 bit BER；等价于 (channel_total - channel_pass) / channel_total。"""
    return compute_channel_ber_from_error_bits(channel_total - channel_pass, channel_total)


def compare_frame(
    chip_currents: list[float],
    info_bits: list[int],
    sim_outputs: list[float] | None = None,
    compare_channels: int = COMPARE_CHANNELS,
    mode: int = 1,
) -> dict:
    """比对实测 CodeBit vs 仿真 CodeBit。

    info_bits：期望 CodeBit（长度 = compare_channels_for_mode(mode)）。
    实测 CodeBit = chip_value_to_bit(Out[i])；相同正确，不同计误码。
    InfoBit 不参与。

    Returns:
        dict with keys: passed, match_count, channel_errors, compare_channels, channels
    """
    del compare_channels  # 以 mode 为准
    pairs = ber_channel_pairs_for_mode(mode)
    meas_out_set = {out_i for out_i, _ in pairs}
    out_to_pair = {out_i: j for j, (out_i, _) in enumerate(pairs)}
    n = len(pairs)
    sim = sim_outputs or []
    channels: list[dict] = []
    match_count = 0
    judged_results: list[bool] = []

    for i in range(DISPLAY_CHANNELS):
        chip_i = chip_currents[i] if i < len(chip_currents) else 0.0
        sim_i = sim[i] if i < len(sim) else 0.0
        chip_bit = chip_value_to_bit(chip_i)
        sim_bit = chip_value_to_bit(sim_i) if i < len(sim) else 0
        if i in meas_out_set:
            j = out_to_pair[i]
            _, ref_cb_i = pairs[j]
            ref_fallback = sim_bit if ref_cb_i == i else (
                chip_value_to_bit(sim[ref_cb_i]) if ref_cb_i < len(sim) else sim_bit
            )
            ref_bit = int(info_bits[j]) if j < len(info_bits) else ref_fallback
            judged = bool(info_bits) or ref_cb_i < len(sim)
            ok = chip_bit == ref_bit if judged else None
            info_i = ref_bit
        else:
            judged = False
            ok = None
            info_i = 0
        if ok:
            match_count += 1
        if judged and ok is not None:
            judged_results.append(ok)

        channels.append(
            {
                "channel": i + 1,
                "chip_current": chip_i,
                "sim_out": sim_i,
                "chip_bit": chip_bit,
                "raw_chip_bit": chip_bit,
                "info_bit": info_i,
                "sim_bit": sim_bit,
                "chip_sign": value_sign(chip_i),
                "sim_sign": value_sign(sim_i),
                "passed": ok,
                "judged": judged,
            }
        )

    channel_errors = sum(1 for ok in judged_results if not ok)
    return {
        "passed": all(judged_results) if judged_results else False,
        "match_count": match_count,
        "channel_errors": channel_errors,
        "compare_channels": n,
        "total_channels": n,
        "channels": channels,
    }


# 兼容旧名
compare_frame_mode2 = compare_frame


class SimToRealTracker:
    """批量测试时累计帧级 / 通道级通过率（CodeBit 比对）。"""

    def __init__(self, num_channels: int = COMPARE_CHANNELS) -> None:
        self.num_channels = num_channels
        self.frame_total = 0
        self.frame_pass = 0
        self.channel_total = 0
        self.channel_pass = 0
        self.channel_errors = 0
        self.per_channel_total = [0] * num_channels
        self.per_channel_pass = [0] * num_channels
        self.retry_count = 0
        self.low_value_retries = 0

    def reset(self) -> None:
        self.frame_total = 0
        self.frame_pass = 0
        self.channel_total = 0
        self.channel_pass = 0
        self.channel_errors = 0
        self.per_channel_total = [0] * self.num_channels
        self.per_channel_pass = [0] * self.num_channels
        self.retry_count = 0
        self.low_value_retries = 0

    def record(
        self,
        info_bits: list[int] | None,
        chip_currents: list[float],
        sim_outputs: list[float] | None = None,
        had_retry: bool = False,
        low_value_retry: bool = False,
        mode: int = 1,
    ) -> dict | None:
        """记录一帧 CodeBit 比对结果；无期望 bit 时返回 None。"""
        if had_retry:
            self.retry_count += 1
        if low_value_retry:
            self.low_value_retries += 1

        if not info_bits:
            return None

        result = compare_frame(
            chip_currents,
            info_bits,
            sim_outputs=sim_outputs,
            compare_channels=self.num_channels,
            mode=mode,
        )
        self.frame_total += 1
        if result["passed"]:
            self.frame_pass += 1

        self.channel_errors += result.get("channel_errors", count_channel_errors(result))

        for i, ch in enumerate(result["channels"][: self.num_channels]):
            if not ch.get("judged", True):
                continue
            self.channel_total += 1
            if i < len(self.per_channel_total):
                self.per_channel_total[i] += 1
            if ch["passed"]:
                self.channel_pass += 1
                if i < len(self.per_channel_pass):
                    self.per_channel_pass[i] += 1

        return result

    @property
    def frame_error_rate(self) -> float | None:
        if self.frame_total == 0:
            return None
        return (self.frame_total - self.frame_pass) / self.frame_total

    @property
    def frame_pass_rate(self) -> float | None:
        if self.frame_total == 0:
            return None
        return self.frame_pass / self.frame_total

    @property
    def channel_ber(self) -> float | None:
        """通道 BER = channel_errors / channel_total。"""
        if self.channel_total == 0:
            return None
        return self.channel_errors / self.channel_total

    def summary(self) -> dict:
        return {
            "frame_total": self.frame_total,
            "frame_pass": self.frame_pass,
            "frame_error_rate": self.frame_error_rate,
            "channel_total": self.channel_total,
            "channel_pass": self.channel_pass,
            "channel_errors": self.channel_errors,
            "channel_ber": self.channel_ber,
            "retry_count": self.retry_count,
            "low_value_retries": self.low_value_retries,
        }
