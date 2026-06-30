"""RX frame validation and retry logic."""

from __future__ import annotations

RETRY_THRESHOLD = 0x1FF  # 511


def needs_retry(outputs: list[dict], threshold: int = RETRY_THRESHOLD) -> bool:
    """Return True if any output raw value is below threshold."""
    return any(o["raw"] < threshold for o in outputs)


def validate_rx_frame(
    data: bytes,
    expected_len: int = 17,
    threshold: int = RETRY_THRESHOLD,
) -> tuple[bool, str]:
    """Validate RX frame length and channel values."""
    if len(data) < expected_len:
        return False, f"帧长度不足: {len(data)}/{expected_len}"

    low_channels = []
    for i in range(8):
        raw = ((data[1 + i * 2] << 8) | data[2 + i * 2]) & 0xFFF
        if raw < threshold:
            low_channels.append(i + 1)

    if low_channels:
        return False, f"通道 {low_channels} 原始值 < 0x{threshold:03X}"

    return True, "OK"
