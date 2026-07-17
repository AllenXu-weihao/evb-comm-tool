"""批量测试柱状图实时累加器 — 每帧 O(1) 更新，无需全量 analyze_by_snr。"""

from __future__ import annotations

from dataclasses import dataclass

from analysis.aggregate import (
    CaseRecord,
    FRAMES_PER_SNR,
    count_attempt_error_bits,
    count_sim_reference_error_bits_for_case,
    is_ok_chart_frame,
    ok_frame_attempt_record,
)
from analysis.sign_compare import compare_channels_for_mode


@dataclass
class _SnrBucket:
    error_bits: int = 0
    reference_error_bits: int = 0
    meas_iter_sum: int = 0
    ref_iter_sum: int = 0
    channel_bits: int = 0
    frames: int = 0


@dataclass
class SnrLiveBarRow:
    snr_db: float
    error_bits: int
    reference_error_bits: int
    meas_iter_sum: int
    ref_iter_sum: int
    channel_bits: int
    tested_count: int


class SnrLiveAccumulator:
    """按 ok 图表口径增量维护各 SNR 柱状图数据。"""

    def __init__(self, *, max_per_snr: int | None = None) -> None:
        from analysis.aggregate import FRAMES_PER_SNR

        self._max_per_snr = int(
            max_per_snr if max_per_snr is not None else FRAMES_PER_SNR
        )
        self._by_snr: dict[float, _SnrBucket] = {}
        self._slots: dict[int, tuple[float, int, int, int, int, int]] = {}
        self._snr_rank_without_frame_idx: dict[float, int] = {}

    def set_max_per_snr(self, cap: int) -> None:
        self._max_per_snr = max(1, int(cap))

    def clear(self) -> None:
        self._by_snr.clear()
        self._slots.clear()
        self._snr_rank_without_frame_idx.clear()

    def ok_count_for_snr(self, snr: float) -> int:
        bucket = self._by_snr.get(float(snr))
        return int(bucket.frames) if bucket is not None else 0

    def _subtract(
        self,
        snr: float,
        meas: int,
        ref: int,
        meas_it: int,
        ref_it: int,
        channel_bits: int,
    ) -> None:
        bucket = self._by_snr.get(snr)
        if bucket is None:
            return
        bucket.error_bits -= meas
        bucket.reference_error_bits -= ref
        bucket.meas_iter_sum -= meas_it
        bucket.ref_iter_sum -= ref_it
        bucket.channel_bits -= channel_bits
        bucket.frames -= 1
        if bucket.frames <= 0:
            self._by_snr.pop(snr, None)

    def _chart_eligible(self, tc: CaseRecord) -> bool:
        if tc.snr_db is None:
            return False
        if tc.frame_idx is not None:
            return is_ok_chart_frame(tc, max_per_snr=self._max_per_snr)
        snr = float(tc.snr_db)
        return self._snr_rank_without_frame_idx.get(snr, 0) < self._max_per_snr

    def upsert_case(self, case_index: int, tc: CaseRecord) -> bool:
        """写入/更新单帧 ok 图表贡献；通信失败帧从累加中移除。"""
        from csv_loader import is_comm_error_frame

        if case_index in self._slots:
            old = self._slots.pop(case_index)
            self._subtract(old[0], old[1], old[2], old[3], old[4], old[5])

        if is_comm_error_frame(tc) or tc.snr_db is None:
            return False

        ar = ok_frame_attempt_record(tc)
        if ar is None:
            return False

        if not self._chart_eligible(tc):
            return False

        meas_err = count_attempt_error_bits(tc, ar)
        ref_err, _ = count_sim_reference_error_bits_for_case(tc)
        meas_it = int(ar.iteration_count)
        ref_it = int(tc.iter_ref) if tc.iter_ref is not None else 0
        channel_bits = compare_channels_for_mode(tc.mode)
        snr = float(tc.snr_db)

        bucket = self._by_snr.setdefault(snr, _SnrBucket())
        bucket.error_bits += meas_err
        bucket.reference_error_bits += ref_err
        bucket.meas_iter_sum += meas_it
        bucket.ref_iter_sum += ref_it
        bucket.channel_bits += channel_bits
        bucket.frames += 1
        self._slots[case_index] = (snr, meas_err, ref_err, meas_it, ref_it, channel_bits)
        if tc.frame_idx is None:
            self._snr_rank_without_frame_idx[snr] = (
                self._snr_rank_without_frame_idx.get(snr, 0) + 1
            )
        return True

    @property
    def ok_frame_count(self) -> int:
        return len(self._slots)

    def bar_rows(self) -> list[SnrLiveBarRow]:
        rows = [
            SnrLiveBarRow(
                snr_db=snr,
                error_bits=b.error_bits,
                reference_error_bits=b.reference_error_bits,
                meas_iter_sum=b.meas_iter_sum,
                ref_iter_sum=b.ref_iter_sum,
                channel_bits=b.channel_bits,
                tested_count=b.frames,
            )
            for snr, b in self._by_snr.items()
            if b.frames > 0
        ]
        rows.sort(key=lambda r: r.snr_db)
        return rows
