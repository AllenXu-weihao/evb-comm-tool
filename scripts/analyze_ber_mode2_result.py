#!/usr/bin/env python3
"""Diagnose BER for mode2 result CSV."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.aggregate import (
    analyze_by_snr,
    apply_bit_compare,
    case_from_csv_group,
    count_channel_error_bits,
    count_sim_reference_error_bits,
)
from analysis.mode2_g_decode import mode2_decode_infobit
from analysis.sign_compare import compare_frame
from csv_loader import load_test_csv


def main() -> None:
    data_dir = ROOT / "data"
    result_files = sorted(data_dir.glob("mode2(1)_result_*.csv"))
    result_path = None
    for candidate in reversed(result_files):
        try:
            load_test_csv(candidate)
            result_path = candidate
            break
        except ValueError:
            continue
    if result_path is None:
        result_path = data_dir / "mode2(1)_result_20260702_154142.csv"
    source_path = data_dir / "mode2(1).csv"
    print(f"Analyzing: {result_path.name}")

    try:
        loaded = load_test_csv(result_path)
    except ValueError as exc:
        print(f"WARN: {result_path.name} invalid dual-row format ({exc}); partial parse fallback")
        loaded = load_test_csv(source_path)
        with result_path.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        filled = 0
        cases = [case_from_csv_group(g) for g in loaded.cases]
        for i in range(0, len(rows) - 1, 2):
            sim, meas = rows[i], rows[i + 1]
            if sim.get("RowKind") != "仿真行" or meas.get("RowKind") != "实测行":
                continue
            if not meas.get("Out[0]", "").strip():
                continue
            idx = int(float(sim["FrameIdx"])) - 1
            if idx < 0 or idx >= len(cases):
                continue
            outs = [float(meas[f"Out[{j}]"]) for j in range(8)]
            tc = cases[idx]
            tc.actual_currents = outs
            tc.iteration_count = int(float(meas.get("IterNum") or 1))
            tc.rx_hex = meas.get("RecvHex") or "00"
            apply_bit_compare(tc)
            filled += 1
        print(f"Partial inject: {filled} measured frames")
    else:
        cases = [case_from_csv_group(g) for g in loaded.cases]
    print(f"Loaded {len(cases)} cases, matrix_mode={loaded.matrix_mode}")

    tc = cases[0]
    print("\n=== Frame 1 ===")
    print("info_bits (sim row / Phase1):", tc.info_bits)
    print("expected_info_bits (MATLAB CSV):", tc.expected_info_bits)
    g_sim = mode2_decode_infobit(tc.sim_outputs or [])
    print("G_decode(sim Out):", g_sim)
    print("sim Out[0..3]:", tc.sim_outputs[:4])
    print("measured Out[0..3]:", tc.actual_currents[:4] if tc.actual_currents else None)
    if tc.actual_currents:
        g_meas = mode2_decode_infobit(tc.actual_currents)
        print("G_decode(measured):", g_meas)
        print("channel_errors:", tc.channel_errors, "passed:", tc.passed)
        r = compare_frame(
            tc.actual_currents, g_sim, tc.sim_outputs, mode=2,
        )
        for ch in r["channels"][:4]:
            print(
                f"  IB{ch['channel']}: G_meas={ch['chip_bit']} "
                f"G_sim={ch['info_bit']} ok={ch['passed']}"
            )

    src = load_test_csv(source_path)
    matlab_mismatch = 0
    total = 0
    for g in src.cases:
        if g.get("info_bits") and g.get("sim_outputs"):
            g_bits = mode2_decode_infobit(g["sim_outputs"])
            for i in range(4):
                total += 1
                if g_bits[i] != g["info_bits"][i]:
                    matlab_mismatch += 1
    print(
        f"\nSource mode2(1): MATLAB InfoBit vs G_decode(sim Out) mismatches: "
        f"{matlab_mismatch}/{total} ({100 * matlab_mismatch / total:.1f}%)"
    )

    err, ch_bits, n_tested = count_channel_error_bits(cases)
    ref_err, ref_bits, _ = count_sim_reference_error_bits(cases)
    print(f"\nMeasured BER: {err}/{ch_bits} = {err / ch_bits:.4f} (N_tested={n_tested})")
    print(f"Reference BER: {ref_err}/{ref_bits} = {ref_err / ref_bits:.4f}")

    points = analyze_by_snr(cases)
    print("\nBy SNR (first 5 and last 3):")
    for p in points[:5]:
        print(
            f"  EbNo={p.snr_db:g} dB: meas={p.channel_ber:.4f} "
            f"({p.error_bits}/{p.channel_bits}), ref={p.reference_ber:.4f}, "
            f"tested={p.tested_count}"
        )
    print("  ...")
    for p in points[-3:]:
        print(
            f"  EbNo={p.snr_db:g} dB: meas={p.channel_ber:.4f} "
            f"({p.error_bits}/{p.channel_bits}), ref={p.reference_ber:.4f}, "
            f"tested={p.tested_count}"
        )

    print("\n=== Manual CSV scan (G_decode measured vs G_decode sim) ===")
    manual_err = 0
    manual_bits = 0
    frames_with_meas = 0
    with result_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for i in range(0, len(rows), 2):
        sim, meas = rows[i], rows[i + 1]
        if meas.get("RowKind") != "实测行" or not meas.get("Out[0]", "").strip():
            continue
        frames_with_meas += 1
        sim_outs = [float(sim[f"Out[{j}]"]) for j in range(8)]
        meas_outs = [float(meas[f"Out[{j}]"]) for j in range(8)]
        expect = mode2_decode_infobit(sim_outs)
        decoded = mode2_decode_infobit(meas_outs)
        for j in range(4):
            manual_bits += 1
            if decoded[j] != expect[j]:
                manual_err += 1
    print(
        f"Manual: {manual_err}/{manual_bits} = {manual_err / manual_bits:.4f} "
        f"over {frames_with_meas} frames"
    )

    sim_inf_mismatch = 0
    for i in range(0, len(rows), 2):
        sim = rows[i]
        sim_outs = [float(sim[f"Out[{j}]"]) for j in range(8)]
        g_bits = mode2_decode_infobit(sim_outs)
        for j in range(4):
            ib = int(float(sim[f"InfoBit[{j}]"]))
            if g_bits[j] != ib:
                sim_inf_mismatch += 1
    print(
        f"Sim rows InfoBit vs G_decode(sim Out) mismatches in result: "
        f"{sim_inf_mismatch}/{len(rows) // 2 * 4}"
    )


if __name__ == "__main__":
    main()
