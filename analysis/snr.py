"""SNR and signal stability metrics."""

from __future__ import annotations

import math
from collections import deque


class SNRTracker:
    """Track per-channel SNR or stability metrics over a rolling window."""

    def __init__(self, num_channels: int = 8, window: int = 100) -> None:
        self.num_channels = num_channels
        self.window = window
        self._history: list[deque[float]] = [
            deque(maxlen=window) for _ in range(num_channels)
        ]
        self._reference: list[float | None] = [None] * num_channels
        self._snr_db: list[float | None] = [None] * num_channels
        self._stability: list[float | None] = [None] * num_channels

    def reset(self) -> None:
        self._history = [deque(maxlen=self.window) for _ in range(self.num_channels)]
        self._reference = [None] * self.num_channels
        self._snr_db = [None] * self.num_channels
        self._stability = [None] * self.num_channels

    def set_reference(self, reference_voltages: list[float] | None) -> None:
        if reference_voltages is None:
            self._reference = [None] * self.num_channels
        else:
            self._reference = list(reference_voltages[: self.num_channels])
            while len(self._reference) < self.num_channels:
                self._reference.append(None)

    def update(self, voltages: list[float]) -> None:
        for i, v in enumerate(voltages[: self.num_channels]):
            self._history[i].append(v)
            self._compute_channel(i)

    def _compute_channel(self, i: int) -> None:
        hist = list(self._history[i])
        if len(hist) < 2:
            self._snr_db[i] = None
            self._stability[i] = None
            return

        mean = sum(hist) / len(hist)
        variance = sum((x - mean) ** 2 for x in hist) / (len(hist) - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0

        # Stability: inverse of coefficient of variation (higher = more stable)
        if abs(mean) > 0.01:
            self._stability[i] = abs(mean) / std if std > 0 else float("inf")
        else:
            self._stability[i] = 1.0 / std if std > 0 else float("inf")

        ref = self._reference[i]
        if ref is not None:
            signal_power = ref ** 2
            noise_power = variance
            if noise_power > 0 and signal_power > 0:
                self._snr_db[i] = 10.0 * math.log10(signal_power / noise_power)
            elif noise_power == 0:
                self._snr_db[i] = float("inf")
            else:
                self._snr_db[i] = None
        else:
            # Without reference: SNR-like metric from mean/std
            if std > 0 and abs(mean) > 0.01:
                self._snr_db[i] = 20.0 * math.log10(abs(mean) / std)
            else:
                self._snr_db[i] = None

    @property
    def snr_db(self) -> list[float | None]:
        return list(self._snr_db)

    @property
    def stability(self) -> list[float | None]:
        return list(self._stability)

    def display_values(self) -> list[float]:
        """Return values suitable for bar chart (SNR or stability)."""
        result = []
        for snr, stab in zip(self._snr_db, self._stability):
            if snr is not None and math.isfinite(snr):
                result.append(min(snr, 60.0))
            elif stab is not None and math.isfinite(stab):
                result.append(min(stab, 60.0))
            else:
                result.append(0.0)
        return result

    def has_reference(self) -> bool:
        return any(r is not None for r in self._reference)
