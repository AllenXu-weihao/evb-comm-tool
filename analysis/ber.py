"""Sign-based bit error rate (BER) analysis."""

from __future__ import annotations

SIGN_POSITIVE = 1
SIGN_NEGATIVE = -1
SIGN_ZERO = 0


def voltage_sign(voltage: float, deadband: float = 0.05) -> int:
    """Classify voltage as +1, -1, or 0."""
    if voltage > deadband:
        return SIGN_POSITIVE
    if voltage < -deadband:
        return SIGN_NEGATIVE
    return SIGN_ZERO


def infer_sign_from_raw(raw: int, midpoint: int = 2048) -> int:
    """Infer expected sign from 12-bit input raw value."""
    if raw > midpoint:
        return SIGN_POSITIVE
    if raw < midpoint:
        return SIGN_NEGATIVE
    return SIGN_ZERO


def signs_match(expected: int, measured: int) -> bool:
    """Compare expected and measured signs."""
    return expected == measured


class SignBERTracker:
    """Track sign-based BER across 8 output channels."""

    def __init__(self, num_channels: int = 8) -> None:
        self.num_channels = num_channels
        self.total = 0
        self.correct = 0
        self.per_channel_total = [0] * num_channels
        self.per_channel_correct = [0] * num_channels
        self.frame_total = 0
        self.frame_errors = 0
        self.retry_count = 0
        self.low_value_retries = 0

    def reset(self) -> None:
        self.total = 0
        self.correct = 0
        self.per_channel_total = [0] * self.num_channels
        self.per_channel_correct = [0] * self.num_channels
        self.frame_total = 0
        self.frame_errors = 0
        self.retry_count = 0
        self.low_value_retries = 0

    def record(
        self,
        expected_signs: list[int] | None,
        measured_voltages: list[float],
        had_retry: bool = False,
        low_value_retry: bool = False,
    ) -> dict:
        """Record one frame's sign comparison results."""
        self.frame_total += 1
        if had_retry:
            self.retry_count += 1
        if low_value_retry:
            self.low_value_retries += 1

        frame_correct = True
        channel_results: list[dict] = []

        for i, voltage in enumerate(measured_voltages[: self.num_channels]):
            measured_sign = voltage_sign(voltage)
            if expected_signs is not None and i < len(expected_signs):
                expected = expected_signs[i]
                match = signs_match(expected, measured_sign)
            else:
                expected = None
                match = None

            if expected is not None:
                self.total += 1
                self.per_channel_total[i] += 1
                if match:
                    self.correct += 1
                    self.per_channel_correct[i] += 1
                else:
                    frame_correct = False
            else:
                match = None

            channel_results.append(
                {
                    "channel": i + 1,
                    "expected": expected,
                    "measured_sign": measured_sign,
                    "voltage": voltage,
                    "correct": match,
                }
            )

        if expected_signs is not None and not frame_correct:
            self.frame_errors += 1

        return {
            "frame_correct": frame_correct if expected_signs else None,
            "channels": channel_results,
        }

    @property
    def ber(self) -> float | None:
        if self.total == 0:
            return None
        return (self.total - self.correct) / self.total

    @property
    def success_rate(self) -> float | None:
        if self.total == 0:
            return None
        return self.correct / self.total

    @property
    def frame_error_rate(self) -> float | None:
        if self.frame_total == 0:
            return None
        return self.frame_errors / self.frame_total

    def per_channel_ber(self) -> list[float | None]:
        result = []
        for t, c in zip(self.per_channel_total, self.per_channel_correct):
            if t == 0:
                result.append(None)
            else:
                result.append((t - c) / t)
        return result

    def summary(self) -> dict:
        return {
            "total_bits": self.total,
            "correct_bits": self.correct,
            "ber": self.ber,
            "success_rate": self.success_rate,
            "frame_total": self.frame_total,
            "frame_errors": self.frame_errors,
            "frame_error_rate": self.frame_error_rate,
            "retry_count": self.retry_count,
            "low_value_retries": self.low_value_retries,
            "per_channel_ber": self.per_channel_ber(),
        }
