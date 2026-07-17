"""Diagnose Out=2.5 Attempt=1 frames in a post-test CSV."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "data" / "mode2_79_result_20260709_164856.csv"
out = ROOT / "scripts" / "_diag_attempt_out.txt"

rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
lines: list[str] = [f"nrows={len(rows)}"]


def outs_of(r: dict) -> list[float | None]:
    vals: list[float | None] = []
    for j in range(8):
        x = r.get(f"Out[{j}]", "")
        try:
            vals.append(float(x) if str(x).strip() != "" else None)
        except ValueError:
            vals.append(None)
    return vals


def has_25(vals: list[float | None]) -> bool:
    return any(v is not None and abs(v - 2.5) < 1e-4 for v in vals)


hits = 0
for i, r in enumerate(rows):
    if str(r.get("RowKind", "")).strip() != "实测行":
        continue
    oo = outs_of(r)
    if not has_25(oo):
        continue
    hits += 1
    if hits <= 25:
        lines.append(
            f"i={i} F={r.get('FrameIdx')} Att={r.get('Attempt')} "
            f"HC={r.get('HardwareConverged')} Out={oo}"
        )
lines.append(f"hits={hits}")

byf: dict[tuple, list] = defaultdict(list)
for r in rows:
    byf[(r.get("EbNo_dB"), r.get("FrameIdx"))].append(r)

n = 0
att1_only_fail = 0
att1_then_ok = 0
for r in rows:
    if str(r.get("RowKind", "")).strip() != "实测行":
        continue
    if str(r.get("Attempt", "")).strip() != "1":
        continue
    if not has_25(outs_of(r)):
        continue
    key = (r.get("EbNo_dB"), r.get("FrameIdx"))
    group = byf[key]
    meas = [g for g in group if str(g.get("RowKind", "")).strip() == "实测行"]
    last_hc = meas[-1].get("HardwareConverged") if meas else None
    n_att = len(meas)
    if n_att == 1 and str(last_hc).upper() == "N":
        att1_only_fail += 1
    if n_att >= 2 and str(last_hc).upper() == "Y":
        att1_then_ok += 1
    if n < 10:
        lines.append(f"FRAME {key} n_meas={n_att} last_HC={last_hc}")
        for g in group:
            oo = outs_of(g)
            lines.append(
                f"  {g.get('RowKind')} Att={g.get('Attempt')} "
                f"HC={g.get('HardwareConverged')} Out0={oo[0]} has25={has_25(oo)}"
            )
        n += 1

lines.append(f"Att1_with_2.5_and_only_one_meas_HC_N={att1_only_fail}")
lines.append(f"Att1_with_2.5_but_later_converged={att1_then_ok}")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", out)
