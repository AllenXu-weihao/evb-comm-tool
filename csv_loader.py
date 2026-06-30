"""CSV test file loader."""

from __future__ import annotations

import csv
from pathlib import Path

from protocol.codec import parse_cmd


def load_test_csv(path: str | Path) -> list[dict]:
    """Load test groups from CSV file.

    Expected columns:
        group_id, cmd, ch1..ch12, [exp_sign1..exp_sign8]
    """
    path = Path(path)
    groups: list[dict] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV 文件为空或缺少表头")

        fieldnames = [fn.strip() for fn in reader.fieldnames]
        has_exp_sign = any(fn.startswith("exp_sign") for fn in fieldnames)

        for row_num, row in enumerate(reader, start=2):
            channels = []
            for i in range(1, 13):
                key = f"ch{i}"
                if key not in row or row[key] is None or str(row[key]).strip() == "":
                    raise ValueError(f"第 {row_num} 行缺少 {key}")
                channels.append(int(row[key]))

            cmd = parse_cmd(row.get("cmd", "0"))

            expected_signs = None
            if has_exp_sign:
                expected_signs = []
                for i in range(1, 9):
                    key = f"exp_sign{i}"
                    val = row.get(key, "")
                    if val is None or str(val).strip() == "":
                        expected_signs.append(0)
                    else:
                        expected_signs.append(int(val))

            groups.append(
                {
                    "group_id": row.get("group_id", str(row_num - 1)),
                    "cmd": cmd,
                    "channels": channels,
                    "expected_signs": expected_signs,
                }
            )

    return groups


def infer_expected_signs_from_channels(channels: list[int]) -> list[int]:
    """Infer expected output signs from first 8 input channels."""
    from analysis.ber import infer_sign_from_raw

    return [infer_sign_from_raw(ch) for ch in channels[:8]]
