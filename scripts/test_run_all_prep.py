"""Non-GUI checks for batch prep helpers (7000-row dataset)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.aggregate import case_from_csv_group, clear_all_measured
from csv_loader import load_test_csv, post_test_dataset_path


def test_clear_and_groups() -> None:
    path = ROOT / "data" / "testdata.csv"
    if not path.is_file():
        print("skip: no testdata.csv")
        return

    loaded = load_test_csv(path)
    cases = [case_from_csv_group(g) for g in loaded.cases]
    n = len(cases)
    assert n > 0

    t0 = time.perf_counter()
    clear_all_measured(cases)
    assert loaded.dataset is not None
    loaded.dataset.clear_all_measured()
    groups = [{"mode": 1, "channels": tc.channels} for tc in cases]
    elapsed = time.perf_counter() - t0
    assert len(groups) == n
    assert elapsed < 2.0, f"batch prep too slow: {elapsed:.2f}s"
    out = post_test_dataset_path(path)
    assert out.name.startswith("testdata_result_")
    print(f"ok: {n} groups prep in {elapsed:.3f}s")


if __name__ == "__main__":
    test_clear_and_groups()
