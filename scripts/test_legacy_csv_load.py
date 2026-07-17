#!/usr/bin/env python3
"""旧版单行 CSV 向后兼容加载 — 内存交错展开回归测试。

Background
----------
早期 testdata.csv 为 **7000 行单行仿真格式**（无 RowKind、无 InfoBit 列）。
GUI 与 BER 分析链路现已统一假设 **14000 行交错双行**（仿真行 + 实测行交替）。
`load_test_csv()` 对旧文件会在内存中调用 `build_interleaved_rows_from_legacy()` 展开，
**不修改磁盘上的源文件**——与 `migrate_to_interleaved()` 就地迁移不同。

This test ensures
-----------------
1. 使用 `data/testdata.csv.bak`（migrate 前的旧版备份）作为 fixture；
2. 加载后 `TestDataLoad.interleaved == False`（源文件格式仍为 legacy 单行）；
3. `cases` 仍为 7000 组（按仿真行解析，与旧版语义一致）；
4. `dataset` 在内存中展开为 14000 行，`RowKind` 严格交替「仿真行 / 实测行」；
5. GUI 表格渲染与 BER 逐对读写实测行时，不因缺少磁盘级迁移而崩溃或错位。

运行：``python scripts/test_legacy_csv_load.py``
若 fixture 不存在则 SKIP（不 fail CI）。

Author: Xander
Date: 2026-06-30
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from csv_loader import load_test_csv


def main() -> None:
    # migrate_to_interleaved 会备份原文件为 testdata.csv.bak，即最贴近生产的 legacy 夹具
    legacy = ROOT / "data" / "testdata.csv.bak"
    if not legacy.exists():
        print(f"SKIP: 未找到 {legacy}")
        return

    loaded = load_test_csv(legacy)

    # 源 CSV 无 RowKind 列 → load 返回值标记为非交错；防止误把磁盘文件当已迁移格式
    assert not loaded.interleaved, "源文件应为旧版单行"

    # cases 仍按 7000 组仿真行解析；业务层（发帧、BER）计数与旧版一致
    assert len(loaded.cases) == 7000, f"期望 7000 组，实际 {len(loaded.cases)}"

    # legacy 路径必须生成内存 dataset；GUI 表格与 update_measured/save_as 依赖此镜像
    assert loaded.dataset is not None, "应生成内存交错数据集"

    # dataset 内部已是交错格式，供表格逐行展示及实测行回填
    assert loaded.dataset.interleaved

    # 7000 组 × 2（仿真 + 空白实测）= 14000 行；磁盘文件仍为 7000 行
    assert len(loaded.dataset.rows) == 14000, (
        f"期望 14000 行，实际 {len(loaded.dataset.rows)}"
    )

    # RowKind 交替不变量：偶数索引仿真、奇数索引实测；BER/GUI 按 (2i, 2i+1) 配对
    assert loaded.dataset.rows[0].get("RowKind") == "仿真行"
    assert loaded.dataset.rows[1].get("RowKind") == "实测行"

    print("OK: 7000 组 → 14000 行（仿真+实测）")


if __name__ == "__main__":
    main()
