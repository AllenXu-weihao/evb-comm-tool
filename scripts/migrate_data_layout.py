"""一次性：将 data/ 扁平文件迁到 测试集 / 测后数据集/日期。

用法（项目根目录）:
  .\\.venv\\Scripts\\python.exe scripts\\migrate_data_layout.py
  .\\.venv\\Scripts\\python.exe scripts\\migrate_data_layout.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csv_loader import migrate_data_layout  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate data/ into 测试集 + 测后数据集/日期")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要移动的文件，不真正移动")
    args = ap.parse_args()
    logs = migrate_data_layout(dry_run=args.dry_run)
    if not logs:
        print("无需迁移（data/ 已是新布局，或目录为空）")
        return 0
    for line in logs:
        print(line)
    print(f"\n共 {len(logs)} 条操作" + ("（dry-run）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
