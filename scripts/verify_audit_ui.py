"""批量测试可视化分析面板结构自检（改 audit_schema / chart_axis_spec 后请运行）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.audit_schema import AUDIT_SCHEMA_VERSION
from ui.chart_axis_spec import (
    BER_LINE_YLABEL,
    EBNO_XLABEL,
    ITER_BAR_YLABEL,
    ITER_LINE_YLABEL,
)


def main() -> None:
    chart_src = (ROOT / "ui" / "chart_panel.py").read_text(encoding="utf-8")
    required = (
        "ax_ber_bar",
        "ax_iter_bar",
        "update_ok_hex_sample",
        "_setup_ber_line_axes",
        "_setup_iter_line_axes",
        "BER_LINE_YLABEL",
        "ITER_LINE_YLABEL",
        "EBNO_XLABEL",
        "ITER_BAR_YLABEL",
        "chart_axis_spec",
    )
    missing = [token for token in required if token not in chart_src]
    assert not missing, (
        f"ChartPanel 缺少预期结构: {missing}，当前 schema v{AUDIT_SCHEMA_VERSION}"
    )
    banned = ("BER-SNR 验算", "update_snr_audit", "update_iter_audit")
    found = [token for token in banned if token in chart_src]
    assert not found, (
        f"ChartPanel 仍含已移除验算表: {found}，当前 schema v{AUDIT_SCHEMA_VERSION}"
    )
    assert AUDIT_SCHEMA_VERSION >= 8
    print(
        f"verify_audit_ui OK · panel v{AUDIT_SCHEMA_VERSION} · "
        f"axes={EBNO_XLABEL!r}"
    )


if __name__ == "__main__":
    main()
