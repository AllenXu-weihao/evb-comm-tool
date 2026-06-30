#!/usr/bin/env python3
"""Generate a 1000-row demo CSV test file."""

from __future__ import annotations

import csv
import random
from pathlib import Path


def generate_row(group_id: int) -> dict:
    cmd = group_id % 256
    channels = []
    exp_signs = []

    pattern = group_id % 8
    for i in range(12):
        if i < 8:
            if pattern == 0:
                raw = random.randint(2500, 4000)
            elif pattern == 1:
                raw = random.randint(100, 1500)
            elif pattern == 2:
                raw = 2048
            elif pattern == 3:
                raw = 3800 if i % 2 == 0 else 200
            else:
                raw = random.randint(500, 3500)
            channels.append(raw)
            if raw > 2100:
                exp_signs.append(-1)
            elif raw < 1900:
                exp_signs.append(1)
            else:
                exp_signs.append(0)
        else:
            channels.append(2500)

    row = {"group_id": group_id, "cmd": f"0x{cmd:02X}"}
    for i, ch in enumerate(channels, 1):
        row[f"ch{i}"] = ch
    for i, sign in enumerate(exp_signs, 1):
        row[f"exp_sign{i}"] = sign
    return row


def main() -> None:
    out = Path(__file__).parent / "sample_test_1000.csv"
    fieldnames = (
        ["group_id", "cmd"]
        + [f"ch{i}" for i in range(1, 13)]
        + [f"exp_sign{i}" for i in range(1, 9)]
    )

    random.seed(42)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for gid in range(1, 1001):
            writer.writerow(generate_row(gid))

    print(f"Generated {out} with 1000 rows")


if __name__ == "__main__":
    main()
