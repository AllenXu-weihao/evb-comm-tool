"""剪贴板 mode1 / testdata 行解析 — 单帧测试粘贴用。"""

from __future__ import annotations

from dataclasses import dataclass

from analysis.aggregate import in_value_to_raw
from analysis.sign_compare import sim_value_to_bit


@dataclass
class PasteRowResult:
    """解析后的单行 testdata / mode1 字段。"""

    channels: list[int]  # 12 路 DAC raw
    sim_outputs: list[float] | None  # 8 路仿真电流；仅 12 In 时为 None
    info_bits: list[int] | None = None  # InfoBit[0..3]；缺失时为 None
    snr_db: float | None = None
    frame_idx: int | None = None
    iter_ref: int | None = None


def _strip_bom(text: str) -> str:
    return text.lstrip("\ufeff")


def _split_fields(line: str) -> list[str]:
    """按 Tab 或逗号分列（Excel 复制多为 Tab）。"""
    line = line.strip()
    if "\t" in line:
        parts = line.split("\t")
    else:
        parts = line.split(",")
    return [p.strip() for p in parts if p.strip() != ""]


def _is_header_line(line: str) -> bool:
    lower = line.lower()
    return "ebno" in lower or "in[0]" in lower or lower.startswith("frameidx")


def _parse_numbers(fields: list[str]) -> list[float]:
    nums: list[float] = []
    for f in fields:
        try:
            nums.append(float(f))
        except ValueError as exc:
            raise ValueError(f"无法解析数值: {f!r}") from exc
    return nums


def _info_bit_count(matrix_mode: int) -> int:
    return 2 if matrix_mode == 3 else 4


def parse_pasted_testdata(text: str, *, matrix_mode: int = 1) -> PasteRowResult:
    """解析剪贴板中的 mode1 / mode3 / testdata 行。

    支持格式：
    - 12 值：仅 In[0..11]
    - 20 值：In[0..11] + Out[0..7]
    - 22 值：EbNo_dB, FrameIdx, In[0..11], Out[0..7]
    - 23 值：上述 + IterNum
    - 25 值（mode3）：上述 + InfoBit[0..1] + IterNum
    - 27 值（mode1）：上述 + InfoBit[0..3] + IterNum
    - 25+ / 27+ 值：跳过多余前缀列，取末尾 25 或 27 个数值列
    """
    text = _strip_bom(text).strip()
    if not text:
        raise ValueError("剪贴板为空")

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    line = lines[0]
    if _is_header_line(line):
        if len(lines) < 2:
            raise ValueError("仅有表头，缺少数据行")
        line = lines[1]

    fields = _split_fields(line)
    if fields and fields[0] in ("仿真行", "实测行"):
        fields = fields[1:]
    if len(fields) < 12:
        raise ValueError(f"至少需要 12 个 In 值，当前仅 {len(fields)} 列")

    nums = _parse_numbers(fields)
    n = len(nums)
    ib_count = _info_bit_count(matrix_mode)

    snr_db: float | None = None
    frame_idx: int | None = None
    iter_ref: int | None = None
    info_bits: list[int] | None = None

    if n == 12:
        in_vals = nums
        out_vals: list[float] | None = None
    elif n == 20:
        in_vals = nums[:12]
        out_vals = nums[12:20]
    elif n == 22:
        snr_db = nums[0]
        frame_idx = int(nums[1])
        in_vals = nums[2:14]
        out_vals = nums[14:22]
    elif n == 23:
        snr_db = nums[0]
        frame_idx = int(nums[1])
        in_vals = nums[2:14]
        out_vals = nums[14:22]
        iter_ref = int(nums[22])
    elif ib_count == 2 and n == 25:
        snr_db = nums[0]
        frame_idx = int(nums[1])
        in_vals = nums[2:14]
        out_vals = nums[14:22]
        info_bits = [int(nums[22 + i]) for i in range(2)]
        iter_ref = int(nums[24])
    elif n == 27:
        snr_db = nums[0]
        frame_idx = int(nums[1])
        in_vals = nums[2:14]
        out_vals = nums[14:22]
        info_bits = [int(nums[22 + i]) for i in range(4)]
        iter_ref = int(nums[26])
    elif ib_count == 2 and n > 25:
        tail = nums[-25:]
        snr_db = tail[0]
        frame_idx = int(tail[1])
        in_vals = tail[2:14]
        out_vals = tail[14:22]
        info_bits = [int(tail[22 + i]) for i in range(2)]
        iter_ref = int(tail[24])
    elif n > 27:
        tail = nums[-27:]
        snr_db = tail[0]
        frame_idx = int(tail[1])
        in_vals = tail[2:14]
        out_vals = tail[14:22]
        info_bits = [int(tail[22 + i]) for i in range(4)]
        iter_ref = int(tail[26])
    else:
        raise ValueError(
            f"无法识别粘贴格式（{n} 列）。"
            f"需要 12（仅 In）、20（In+Out）、22/23 或 "
            f"{25 if ib_count == 2 else 27}（含 InfoBit）列"
        )

    if len(in_vals) != 12:
        raise ValueError(f"In 通道应为 12 路，当前 {len(in_vals)}")
    if out_vals is not None and len(out_vals) != 8:
        raise ValueError(f"Out 通道应为 8 路，当前 {len(out_vals)}")
    if info_bits is not None and len(info_bits) != ib_count:
        raise ValueError(f"InfoBit 应为 {ib_count} 路，当前 {len(info_bits)}")

    if info_bits is None and out_vals is not None:
        info_bits = [sim_value_to_bit(out_vals[i]) for i in range(ib_count)]

    channels = [in_value_to_raw(v) for v in in_vals]
    return PasteRowResult(
        channels=channels,
        sim_outputs=out_vals,
        info_bits=info_bits,
        snr_db=snr_db,
        frame_idx=frame_idx,
        iter_ref=iter_ref,
    )
