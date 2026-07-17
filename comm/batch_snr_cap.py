"""批量测试：每 SNR BER 基数满后跳过后续帧（worker 线程内计数）。"""

from __future__ import annotations


class BatchSnrCapGuard:
    """在 serial_worker 批量循环中判定是否跳过当前 SNR 的剩余帧。"""

    __slots__ = ("cap", "enabled", "_ok_count", "_last_completed_snr")

    def __init__(self, *, cap: int, enabled: bool = True) -> None:
        self.cap = max(1, int(cap))
        self.enabled = bool(enabled)
        self._ok_count: dict[float, int] = {}
        self._last_completed_snr: float | None = None

    def reset(self, *, cap: int, enabled: bool) -> None:
        self.cap = max(1, int(cap))
        self.enabled = bool(enabled)
        self._ok_count.clear()
        self._last_completed_snr = None

    def ok_count(self, snr: float) -> int:
        return int(self._ok_count.get(float(snr), 0))

    def is_snr_full(self, snr: float | None) -> bool:
        if not self.enabled or snr is None:
            return False
        return self.ok_count(float(snr)) >= self.cap

    def record_converged_frame(self, snr: float | None) -> bool:
        """记录一帧 ok 口径收敛实测；返回 True 表示该 SNR 刚达到 cap。"""
        if snr is None:
            return False
        key = float(snr)
        n = self.ok_count(key) + 1
        self._ok_count[key] = n
        if self.enabled and n >= self.cap:
            self._last_completed_snr = key
            return True
        return False

    def consume_snr_completed(self) -> float | None:
        snr = self._last_completed_snr
        self._last_completed_snr = None
        return snr
