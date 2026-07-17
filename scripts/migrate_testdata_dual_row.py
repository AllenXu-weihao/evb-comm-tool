#!/usr/bin/env python3
"""将 data/testdata.csv 从 7000 行仿真数据迁移为 14000 行交错双行格式。

背景
----
旧版 testdata.csv 每行一组仿真用例（EbNo_dB、In[]、Out[] 等），共约 7000 行。
新版采用「仿真行 + 实测行」交错存储：每组用例占 2 行，实测行初始为空，
供 UART 批量测试后由工具回填 RecvHex、InfoBit 等字段。

本脚本为一次性迁移工具，调用 ``csv_loader.migrate_to_interleaved`` 写回磁盘。
流程详见：``scripts/migrate_testdata_dual_row_流程图.md``

用法::

    python scripts/migrate_testdata_dual_row.py
    python scripts/migrate_testdata_dual_row.py --input data/testdata.csv --output data/testdata.csv
    python scripts/migrate_testdata_dual_row.py --no-backup

"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，以便导入 csv_loader
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from csv_loader import ROW_KIND_MEASURED, ROW_KIND_SIM, load_test_csv, migrate_to_interleaved


def main() -> None:
    """解析命令行参数，校验源文件，执行迁移并打印结果摘要。"""
    parser = argparse.ArgumentParser(description="迁移 testdata.csv 为仿真/实测交错双行格式")
    parser.add_argument(
        "--input",
        "-i",
        default=str(ROOT / "data" / "testdata.csv"),
        help="源 CSV（默认 data/testdata.csv）",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="输出 CSV（默认与 --input 相同，就地更新）",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="就地更新时不创建 .bak 备份",
    )
    args = parser.parse_args()

    src = Path(args.input)
    dst = Path(args.output) if args.output else src

    # 1. 校验源文件存在
    if not src.exists():
        print(f"错误: 找不到 {src}", file=sys.stderr)
        sys.exit(1)

    try:
        # 2. 预读源文件，记录迁移前行数（用例组数）
        before = load_test_csv(src)

        # 3. 已是交错格式则跳过，避免重复迁移
        if before.interleaved:
            print(f"已是交错格式: {len(before.cases)} 对（{len(before.cases) * 2} 行）")
            return

        # 4. 执行迁移：展开为仿真行+空白实测行，就地更新时可选 .bak 备份
        out = migrate_to_interleaved(src, dst, backup=not args.no_backup)

        # 5. 重新加载输出文件，打印迁移前后对比
        after = load_test_csv(out)
        print(f"迁移完成: {len(before.cases)} 仿真行 → {len(after.cases)} 对（{len(after.cases) * 2} 行）")
        print(f"输出: {out}")
        if not args.no_backup and out == src:
            print(f"备份: {src.with_suffix(src.suffix + '.bak')}")
        print(f"RowKind: {ROW_KIND_SIM} / {ROW_KIND_MEASURED}")
    except Exception as exc:
        print(f"迁移失败: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
