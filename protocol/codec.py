"""EVB serial protocol frame encoder/decoder."""

from __future__ import annotations

FRAME_HEADER = 0xAA
TRAILER = bytes([0x09, 0xC4, 0x09, 0xC4, 0x09, 0xC4, 0x0F, 0xA0])
TX_FRAME_LEN = 34
RX_FRAME_LEN = 17

TX_VOLTAGE_REF = 4.096
RX_VOLTAGE_SCALE = 5.0 * (-1.25)  # (raw/4096) * 5.0 * (-1.25)


def _clamp12(value: int) -> int:
    return max(0, min(0xFFF, int(value)))


def build_tx_frame(cmd: int, channels: list[int]) -> bytes:
    """Build a 34-byte TX frame from command byte and 12 channel raw values."""
    if len(channels) != 12:
        raise ValueError(f"Expected 12 channels, got {len(channels)}")

    frame = bytearray(TX_FRAME_LEN)
    frame[0] = FRAME_HEADER
    frame[1] = int(cmd) & 0xFF

    for i, raw in enumerate(channels):
        val = _clamp12(raw)
        frame[2 + i * 2] = (val >> 8) & 0xFF
        frame[3 + i * 2] = val & 0xFF

    frame[26:34] = TRAILER
    return bytes(frame)


def parse_rx_frame(data: bytes) -> dict:
    """Parse a 17-byte RX frame into iteration count and 8 output channels."""
    if len(data) < RX_FRAME_LEN:
        raise ValueError(f"RX frame too short: {len(data)} bytes (need {RX_FRAME_LEN})")

    iteration = data[0]
    outputs: list[dict] = []

    for i in range(8):
        raw = ((data[1 + i * 2] << 8) | data[2 + i * 2]) & 0xFFF
        voltage = (raw / 4096.0) * RX_VOLTAGE_SCALE
        outputs.append({"raw": raw, "voltage": voltage})

    return {"iteration": iteration, "outputs": outputs}


def raw_to_tx_voltage(raw: int) -> float:
    """Convert 12-bit TX channel raw value to voltage."""
    return (raw / 4096.0) * TX_VOLTAGE_REF


def format_hex(data: bytes, sep: str = " ") -> str:
    """Format bytes as uppercase hex string."""
    return sep.join(f"{b:02X}" for b in data)


def parse_cmd(value: str | int) -> int:
    """Parse command byte from decimal or hex string."""
    if isinstance(value, int):
        return value & 0xFF
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return int(text, 16) & 0xFF
    return int(text) & 0xFF
