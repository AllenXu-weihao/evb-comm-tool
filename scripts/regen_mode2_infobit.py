#!/usr/bin/env python3
"""Regenerate mode2.csv InfoBit[0..3] from G_decode(Sim Out)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.mode2_g_decode import mode2_decode_infobit


def main() -> None:
    path = ROOT / "data" / "mode2.csv"
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    changed = 0
    for row in rows:
        outs = [float(row[f"Out[{i}]"]) for i in range(8)]
        new_ib = mode2_decode_infobit(outs)
        old_ib = [int(row[f"InfoBit[{i}]"]) for i in range(4)]
        if new_ib != old_ib:
            changed += 1
        for i in range(4):
            row[f"InfoBit[{i}]"] = str(new_ib[i])

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {path.name}: {changed}/{len(rows)} InfoBit rows changed")


if __name__ == "__main__":
    main()
