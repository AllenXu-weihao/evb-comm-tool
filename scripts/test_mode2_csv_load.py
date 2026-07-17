#!/usr/bin/env python3

"""Mode2 CSV 加载回归测试 — matrix_mode=2、CodedBit BER、InfoBit 导出。



InfoBit 来源（loader 内约定，Mode2 双行/帧）：

  **仿真行** — CSV 测试集自带 InfoBit（列保留，BER 不用）

  **实测行** — G_decode(实测 Out[0..7]) 导出



实测 BER = Out[3,5,6,7] 硬判 CodeBit(实测) vs CodeBit(Sim)；无参考 BER。

"""



from __future__ import annotations



import csv

import sys

from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))



from analysis.aggregate import (

    apply_bit_compare,

    case_from_csv_group,

    count_measured_error_bits,

    count_sim_reference_error_bits,

    mode2_measured_infobits,

    mode2_reference_infobits,

    mode2_truth_infobits,

    recompute_measured_bit_compare,

)

from analysis.mode2_g_decode import (

    MODE2_G_MATRIX,

    hardout_from_analogs,

    mode2_decode_infobit,

    mode2_decode_u,

    mode2_hardout0,

    mode2_hardout1,

    mode2_hardout2,

)

from analysis.sign_compare import chip_value_to_bit, mode2_coded_bits_from_outputs

from csv_loader import (

    ROW_KIND_MEASURED,

    ROW_KIND_SIM,

    ROWS_PER_FRAME,

    TestCsvDataset,

    _measured_infobits_for_export,

    infer_matrix_mode_from_path,

    load_test_csv,

)

from protocol.codec import build_tx_frame, resolve_tx_matrix_mode





def test_mode2_dual_row_export() -> None:

    """Mode2 导出：未测帧仅仿真行；已测帧按 attempt 展开。"""

    path = ROOT / "data" / "mode2.csv"

    if not path.is_file():

        return

    loaded = load_test_csv(path)

    assert loaded.dataset is not None

    assert loaded.dataset.rows_per_frame == ROWS_PER_FRAME

    cases = [case_from_csv_group(g) for g in loaded.cases[:3]]

    loaded.dataset.rebuild_rows_from_cases(cases)

    rows = loaded.dataset.rows

    assert len(rows) == 3

    for frame in range(3):

        sim = rows[frame]

        assert sim["RowKind"] == ROW_KIND_SIM

        tc = cases[frame]

        truth_ib = mode2_truth_infobits(tc)

        assert truth_ib is not None

        for i in range(4):

            assert int(sim[f"InfoBit[{i}]"]) == truth_ib[i]





def test_mode2_dual_row_after_measure() -> None:

    """已测帧：仿真行 CSV InfoBit；实测行 G_decode(实测 Out) 导出。"""

    path = ROOT / "data" / "mode2.csv"

    if not path.is_file():

        return

    loaded = load_test_csv(path)

    tc = case_from_csv_group(loaded.cases[0])

    tc.actual_currents = [-0.7446, 0.7007, 0.6506, -0.7214, -0.4126, 0.2881, 2.5, -0.4871]

    tc.iteration_count = 5

    tc.rx_hex = "00" * 17

    assert loaded.dataset is not None

    loaded.dataset.rebuild_rows_from_cases([tc])

    sim = loaded.dataset.rows[0]

    meas = loaded.dataset.rows[1]

    expected_truth = mode2_truth_infobits(tc)

    expected_meas_ib = mode2_decode_infobit(tc.actual_currents)

    assert expected_truth is not None

    for i in range(4):

        assert int(sim[f"InfoBit[{i}]"]) == expected_truth[i]

        assert int(meas[f"InfoBit[{i}]"]) == expected_meas_ib[i]

    assert mode2_measured_infobits(tc) == mode2_coded_bits_from_outputs(tc.actual_currents)





def test_mode2_g_decode_unit() -> None:

    zeros = [0.0] * 8

    assert hardout_from_analogs(zeros) == [0] * 8

    assert mode2_decode_u(zeros) == [0] * 8

    assert mode2_decode_infobit(zeros) == [0, 0, 0, 0]



    one_neg = [-1.0] + [1.0] * 7

    assert hardout_from_analogs(one_neg) == [1] + [0] * 7

    assert mode2_decode_infobit(one_neg) == [0, 0, 0, 0]



    analogs = [-1.0, 1.0, -1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

    hard = hardout_from_analogs(analogs)

    assert hard == [1, 0, 1, 0, 0, 0, 0, 0]

    hardout1 = mode2_hardout1(hard, MODE2_G_MATRIX)

    for col in range(8):

        expected = sum(hard[row] * MODE2_G_MATRIX[row][col] for row in range(8))

        assert hardout1[col] == expected, f"hardout1[{col}] mismatch"

    u = mode2_decode_u(analogs, MODE2_G_MATRIX)

    assert u == [s % 2 for s in hardout1]

    assert mode2_decode_infobit(analogs) == [0, 0, 0, 0]

    assert mode2_decode_infobit(analogs) == [u[3], u[5], u[6], u[7]]





def test_user_example_sim_out() -> None:

    out = [-0.7401, 0.7895, 0.7895, -0.7895, -0.6531, 0.6531, 0.4506, -0.6531]

    assert hardout_from_analogs(out) == [1, 0, 0, 1, 1, 0, 0, 1]

    assert mode2_decode_infobit(out) == [0, 1, 1, 1]





def test_mode2_g_column_examples() -> None:

    hardout0 = [1, 0, 0, 1, 1, 0, 0, 1]

    hardout1 = mode2_hardout1(hardout0, MODE2_G_MATRIX)

    assert hardout1[3] == hardout0[3] + hardout0[7]

    assert hardout1[5] == hardout0[5] + hardout0[7]

    assert hardout1[6] == hardout0[6] + hardout0[7]

    assert hardout1[7] == hardout0[7]

    hardout2 = mode2_hardout2(hardout1)

    assert [hardout2[3], hardout2[5], hardout2[6], hardout2[7]] == [0, 1, 1, 1]

    analogs = [1.0 if b == 0 else -1.0 for b in hardout0]

    assert mode2_hardout0(analogs) == hardout0

    assert mode2_decode_infobit(analogs) == [0, 1, 1, 1]





def test_measured_infobit_export() -> None:

    currents = [-1.0, 1.0, -1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

    g_bits = mode2_decode_infobit(currents)

    assert _measured_infobits_for_export(2, currents, None) == g_bits

    assert _measured_infobits_for_export(1, [0.2, -0.2, 0.3, -0.1], None) == [0, 1, 0, 1]





def test_frame1000_measured_codedbit_ber() -> None:

    measured = [-0.7446, 0.7007, 0.6506, -0.7214, -0.4126, 0.2881, 2.5000, -0.4871]

    tc = case_from_csv_group({

        "group_id": "frame1000",

        "mode": 2,

        "channels": [0] * 12,

        "sim_outputs": measured,

        "info_bits": mode2_decode_infobit(measured),

        "expected_info_bits": mode2_decode_infobit(measured),

    })

    tc.actual_currents = list(measured)

    tc.iteration_count = 5

    tc.rx_hex = "00" * 17

    assert count_measured_error_bits(tc) == 0

    apply_bit_compare(tc)

    assert tc.channel_errors == 0





def test_mode2_codedbit_ber_vs_sim() -> None:

    sim = [-1.0, 1.0, -1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

    tc = case_from_csv_group({

        "group_id": "t",

        "mode": 2,

        "channels": [0] * 12,

        "sim_outputs": sim,

        "info_bits": [0, 0, 0, 0],

    })

    tc.actual_currents = [-1.0, 1.0, 1.0, -1.0, 1.0, 1.0, 1.0, 1.0]

    tc.iteration_count = 5

    sim_bits = mode2_coded_bits_from_outputs(sim)

    meas_bits = mode2_coded_bits_from_outputs(tc.actual_currents)

    assert count_measured_error_bits(tc) == sum(

        int(meas_bits[j]) != int(sim_bits[j]) for j in range(4)

    )





def test_mode2_screenshot_sim_vs_meas() -> None:

    sim = [-0.7895, -0.7895, 0.7895, 0.7895, 1, 1, -1, -1]

    measured = [-0.7495, 0.6909, 0.6812, -0.6824, -0.6006, 0.7178, -0.0256, 1.6077]

    tc = case_from_csv_group({

        "group_id": "screenshot",

        "mode": 2,

        "channels": [0] * 12,

        "sim_outputs": sim,

        "info_bits": mode2_decode_infobit(sim),

        "expected_info_bits": mode2_decode_infobit(sim),

    })

    tc.actual_currents = measured

    tc.iteration_count = 5

    tc.rx_hex = "00" * 17

    assert mode2_coded_bits_from_outputs(measured) == [1, 0, 1, 0]

    assert mode2_coded_bits_from_outputs(sim) == [0, 0, 1, 1]

    assert mode2_reference_infobits(tc) == [0, 0, 1, 1]

    assert mode2_measured_infobits(tc) == [1, 0, 1, 0]

    path = ROOT / "data" / "mode2.csv"

    if not path.is_file():

        return

    loaded = load_test_csv(path)

    assert loaded.dataset is not None

    loaded.dataset.update_measured(0, tc)

    meas = loaded.dataset.rows[1]

    for i in range(4):

        assert int(meas[f"InfoBit[{i}]"]) == mode2_decode_infobit(measured)[i]





def main() -> None:

    test_mode2_dual_row_export()

    print("OK: Mode2 dual-row export (14000 rows / 7000 frames)")

    test_mode2_dual_row_after_measure()

    print("OK: sim=CSV InfoBit, measured export=G_decode, BER=CodeBit")



    test_mode2_g_decode_unit()

    print("OK: mode2 G decode unit tests")



    test_user_example_sim_out()

    print("OK: user example sim Out → InfoBit [0,1,1,1]")



    test_mode2_g_column_examples()

    print("OK: hardout2[3,5,6,7] → InfoBit[0..3] mapping verified")



    test_measured_infobit_export()

    print("OK: measured InfoBit export still uses G_decode for Mode2")



    test_frame1000_measured_codedbit_ber()

    print("OK: frame1000 CodeBit(measured)==CodeBit(sim) → 0 BER errors")



    test_mode2_codedbit_ber_vs_sim()

    print("OK: Mode2 CodeBit BER vs Sim Out[3,5,6,7]")



    test_mode2_screenshot_sim_vs_meas()

    print("OK: screenshot CodeBit meas=[1,0,1,0] vs sim=[0,0,1,1]")



    path = ROOT / "data" / "mode2.csv"

    if not path.is_file():

        print(f"SKIP: {path} not found")

        return



    assert infer_matrix_mode_from_path(path) == 2

    assert infer_matrix_mode_from_path("mode1.csv") == 1



    with path.open(newline="", encoding="utf-8") as f:

        raw_rows = list(csv.DictReader(f))

    assert all(f"InfoBit[{i}]" in raw_rows[0] for i in range(4))



    loaded = load_test_csv(path)

    assert loaded.matrix_mode == 2

    assert len(loaded.cases) == 7000

    assert loaded.dataset is not None

    assert loaded.dataset.rows_per_frame == ROWS_PER_FRAME

    assert len(loaded.dataset.rows) == 7000 * ROWS_PER_FRAME



    first = loaded.cases[0]

    assert first["mode"] == 2

    assert first["info_bits"] is not None

    expected_ib = mode2_decode_infobit(first["sim_outputs"])

    assert first["info_bits"] == expected_ib

    csv_ib = [int(raw_rows[0][f"InfoBit[{i}]"]) for i in range(4)]

    assert first["info_bits"] == csv_ib



    g_mismatch = 0

    for raw, group in zip(raw_rows, loaded.cases):

        g_bits = mode2_decode_infobit(group["sim_outputs"])

        csv_bits = [int(raw[f"InfoBit[{i}]"]) for i in range(4)]

        assert group["info_bits"] == g_bits

        if csv_bits != g_bits:

            g_mismatch += 1

    assert g_mismatch == 0



    tc = case_from_csv_group(first)

    assert tc.mode == 2

    frame = build_tx_frame(tc.channels, resolve_tx_matrix_mode(0, 2))

    ch1_high = frame[1]

    assert (ch1_high >> 4) & 0x0F == 2

    for ch_idx in range(1, 12):

        high = frame[1 + ch_idx * 2]

        assert (high >> 4) & 0x0F == 0



    print("OK: mode2.csv → matrix_mode=2, InfoBit columns = G_decode(Sim Out)")



    tc_all = [case_from_csv_group(g) for g in loaded.cases[:50]]

    ref_err, ref_bits, n_ref = count_sim_reference_error_bits(tc_all)
    assert n_ref == len(tc_all)
    assert ref_bits == len(tc_all) * 4
    print(f"OK: mode2 reference BER uses Out[3,5,6,7] vs specified CodeBit ({n_ref} frames)")



    path_with_ib = ROOT / "data" / "mode2(1).csv"

    if path_with_ib.is_file():

        loaded_ib = load_test_csv(path_with_ib)

        first_ib = loaded_ib.cases[0]

        csv_ib = first_ib["info_bits"]

        matlab_ib = first_ib.get("expected_info_bits")

        assert csv_ib is not None

        assert matlab_ib == [1, 1, 0, 1]



        tc_ib_all = [case_from_csv_group(g) for g in loaded_ib.cases[:50]]

        for tc in tc_ib_all:

            tc.actual_currents = list(tc.sim_outputs or [0.0] * 8)

            tc.iteration_count = 5

            tc.rx_hex = "00" * 17



        n = recompute_measured_bit_compare(tc_ib_all)

        assert n == 50

        total_meas_err = sum(count_measured_error_bits(tc) for tc in tc_ib_all)

        assert total_meas_err == 0

        print(f"OK: aligned sim=measured → meas BER=0/{50 * 4}")



        tc_diff = tc_ib_all[0]

        tc_diff.actual_currents = [

            -0.7446, 0.7007, 0.6506, -0.7214, -0.4126, 0.2881, 2.5000, -0.4871,

        ]

        apply_bit_compare(tc_diff)

        sim_bits = mode2_coded_bits_from_outputs(tc_diff.sim_outputs or [])

        meas_bits = mode2_coded_bits_from_outputs(tc_diff.actual_currents)

        exp_err = sum(int(meas_bits[j]) != int(sim_bits[j]) for j in range(4))

        assert tc_diff.channel_errors == exp_err

        print(f"OK: CodeBit(measured) vs CodeBit(sim) → errors={tc_diff.channel_errors}/4")





if __name__ == "__main__":

    main()

