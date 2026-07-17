"""性能基准脚本：模拟 GUI 后台 Worker 线程的 CSV 加载路径（非功能测试）。

本脚本用于测量 CsvLoadWorker 所走的两段耗时，帮助评估界面是否会卡顿。
不验证业务正确性，只输出各阶段秒数。

Author: Xander
Date: 2026-06-30
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.aggregate import case_from_csv_group
from csv_loader import load_test_csv


def main() -> None:
    path = ROOT / "data" / "testdata.csv"
    if not path.is_file():
        print(f"Missing {path}")
        sys.exit(1)

    # ── Phase 1：IO + 数据结构（load_test_csv）────────────────────────────
    # 1) CSV 文件读取
    # 2) 构建 Dataset（行级原始表）
    # 3) 识别 interleaved 双行格式并分组为 cases
    t0 = time.perf_counter()
    loaded = load_test_csv(path)
    t1 = time.perf_counter()
    n = len(loaded.cases)
    print(f"load_test_csv: {n} groups in {t1 - t0:.2f}s (interleaved={loaded.interleaved})")
    if loaded.dataset:
        print(f"  dataset rows: {len(loaded.dataset.rows)}")

    # ── Phase 2：CPU 密集（case_from_csv_group）──────────────────────────
    # CaseRecord 构造：字符串转数值、业务对象分配；通常是性能热点
    t2 = time.perf_counter()
    cases = [case_from_csv_group(g) for g in loaded.cases]
    t3 = time.perf_counter()
    print(f"case_from_csv_group x{n}: {t3 - t2:.2f}s")

    # ── 汇总：GUI 设计参考 ───────────────────────────────────────────────
    # 判定「界面不冻结」：两段合计应在可接受范围内，且必须在 CsvLoadWorker
    # 后台线程执行，主线程仅等待 finished 信号更新 UI。
    print(f"total: {t3 - t0:.2f}s — UI should stay responsive (background thread)")


if __name__ == "__main__":
    main()
