"""BER / 图表基数（每 SNR 帧数）与批量自动切 SNR 设置。"""

from __future__ import annotations

import os

DEFAULT_FRAMES_PER_SNR = 1000
MIN_FRAMES_PER_SNR = 100
MAX_FRAMES_PER_SNR = 10000

_frames_per_snr = DEFAULT_FRAMES_PER_SNR
_auto_advance_snr = True


def _env_frames_per_snr() -> int | None:
    raw = os.environ.get("EVB_FRAMES_PER_SNR", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def get_frames_per_snr() -> int:
    return int(_frames_per_snr)


def set_frames_per_snr(n: int) -> int:
    global _frames_per_snr
    _frames_per_snr = max(MIN_FRAMES_PER_SNR, min(MAX_FRAMES_PER_SNR, int(n)))
    return _frames_per_snr


def get_auto_advance_snr() -> bool:
    return bool(_auto_advance_snr)


def set_auto_advance_snr(enabled: bool) -> None:
    global _auto_advance_snr
    _auto_advance_snr = bool(enabled)


def ber_bar_base_footnote(frames: int | None = None) -> str:
    cap = int(frames if frames is not None else get_frames_per_snr())
    return f"基数 = ok 表总 bit（每 SNR ≤{cap} 帧 × 通道数）"


def iter_bar_base_footnote(frames: int | None = None) -> str:
    cap = int(frames if frames is not None else get_frames_per_snr())
    return f"基数 = ok 表帧数（每 SNR ≤{cap}；1 仿真 + 1 实测/帧）"


_env_cap = _env_frames_per_snr()
if _env_cap is not None:
    set_frames_per_snr(_env_cap)
