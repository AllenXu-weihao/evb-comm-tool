"""Verify RX column-current formula against testdata CSV."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.sign_compare import chip_value_to_bit
from protocol.codec import raw_to_column_current, parse_rx_frame


def parse_hex_recv(hex_str: str) -> list[int]:
    data = bytes.fromhex(hex_str.replace(" ", ""))
    parsed = parse_rx_frame(data)
    return [o["raw"] for o in parsed["outputs"]]


def formula_requirements_doc(raw: int) -> float:
    """需求书 §2.5 公式：I_col = (raw/4096×5)×(−1.25) — raw>0 时恒为负。"""
    return (raw / 4096.0) * 5.0 * (-1.25)


def sign(v: float) -> int:
    return 1 if v >= 0 else -1


def main() -> None:
    # 中点对称式：raw=2048 → I_col=0
    ic_mid = raw_to_column_current(2048)
    print(f"Midpoint check: raw=2048 → I_col={ic_mid:+.4f} (expected 0.0)")
    assert abs(ic_mid) < 0.001, f"unexpected I_col at raw=2048: {ic_mid}"

    # chip_value_to_bit：负→1，零或正→0（实测与参考 BER 共用）
    assert chip_value_to_bit(-0.5) == 1
    assert chip_value_to_bit(0.5) == 0
    assert chip_value_to_bit(0.0) == 0
    from analysis.sign_compare import sim_value_to_bit
    assert sim_value_to_bit(-0.5) == 1
    assert sim_value_to_bit(0.5) == 0
    assert sim_value_to_bit(0.0) == 0
    print("ok: chip_value_to_bit / sim_value_to_bit (negative→1, zero/positive→0)")

    path = ROOT / "data" / "testdata.csv"
    if not path.exists():
        path = ROOT / "data" / "testdata_interleaved.csv"
    if not path.exists():
        print("skip: no testdata CSV for sign scan")
        return

    req_pos = req_neg = codec_pos = codec_neg = 0
    codec_match = codec_total = 0

    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        prev_sim = None
        for row in reader:
            kind = row.get("RowKind", "").strip()
            if kind == "仿真行":
                prev_sim = [_float(row, f"Out[{i}]") for i in range(8)]
            elif kind == "实测行" and prev_sim:
                hex_str = (row.get("RecvHex") or "").strip()
                if not hex_str:
                    continue
                raws = parse_hex_recv(hex_str)
                for i in range(4):
                    raw = raws[i]
                    sim = prev_sim[i]
                    req = formula_requirements_doc(raw)
                    ic = raw_to_column_current(raw)
                    if req >= 0:
                        req_pos += 1
                    else:
                        req_neg += 1
                    if ic >= 0:
                        codec_pos += 1
                    else:
                        codec_neg += 1
                    codec_total += 1
                    if sign(ic) == sign(sim):
                        codec_match += 1
                prev_sim = None

    print("Requirements-doc formula sign distribution:", req_pos, "+", req_neg, "-")
    print("codec raw_to_column_current:", codec_pos, "+", codec_neg, "-")
    rate = codec_match / codec_total if codec_total else 0
    print(f"Sign match rate vs sim Out: {codec_match}/{codec_total} = {rate:.1%}")


def _float(row: dict, key: str) -> float:
    v = row.get(key, "")
    return float(v) if v not in (None, "") else 0.0


if __name__ == "__main__":
    main()
