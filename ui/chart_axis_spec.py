"""批量测试可视化分析 — 坐标轴 / 图例 / 柱状图口径（无 matplotlib 依赖）。

改文案或坐标含义时：
1. 先改本文件与 docs/批量测试可视化分析.md
2. 递增 ui/audit_schema.py 中 AUDIT_SCHEMA_VERSION
3. 运行 python scripts/verify_audit_ui.py
"""

from __future__ import annotations

from ui.perf_settings import BATCH_BAR_MIN_MS

# ── 横轴（四图共用）────────────────────────────────────────
# 物理量：Eb/N0 信噪比；单位 dB；每个刻度 = 该 EbN0 下批量已测的 SNR 点
EBNO_XLABEL_RIGHT = "EbN0 [单位 dB]"
EBNO_XLABEL_TICK = "横轴刻度：Eb/N0 信噪比 (dB)"

# 兼容旧名
EBNO_XLABEL = EBNO_XLABEL_RIGHT

# ── BER 折线图 ─────────────────────────────────────────────
BER_LINE_YLABEL = "纵轴：信道 BER\n(10^n 对数刻度)"

# ── BER 柱状图 ─────────────────────────────────────────────
BER_BAR_YLABEL = "纵轴：误码 bit 累计"
BER_BAR_TITLE = "BER 误码 bit 对比"
BER_BAR_SUBTITLE = "蓝柱=理论(仿真)  橙柱=实测(ber表)"
BER_BAR_BASE_FOOTNOTE = "基数 = ok 表总 bit（每 SNR ≤1000 帧 × 通道数）"
BER_BAR_LABEL_THEORY = "理论误码 bit（仿真 Sim Out 硬判）"
BER_BAR_LABEL_MEAS = "实测误码 bit（ber表累加）"

# ── 迭代折线图 ─────────────────────────────────────────────
ITER_LINE_YLABEL = "纵轴：迭代次数\n（芯片实测均值）"

# ── 迭代柱状图 ─────────────────────────────────────────────
ITER_BAR_YLABEL = "纵轴：迭代次数累计"
ITER_BAR_TITLE = "迭代次数对比"
ITER_BAR_SUBTITLE = "蓝柱=理论(仿真)  橙柱=实测(芯片)"
ITER_BAR_BASE_FOOTNOTE = "基数 = ok 表帧数（每 SNR ≤1000；1 仿真 + 1 实测/帧）"
ITER_BAR_LABEL_THEORY = "理论迭代累加（仿真 IterNum）"
ITER_BAR_LABEL_MEAS = "实测迭代累加（芯片 IterNum）"

# ── 页面说明行（两行 × 左右两列，节省纵向空间）────────────────
CHART_AXIS_HINT_R1L = (
    "【横轴·四图相同】EbN0 (dB) = 信噪比；每个刻度对应该 EbN0 下已测批量帧。"
)
CHART_AXIS_HINT_R1R = (
    "【BER 折线·纵轴】信道误码率 BER，10^n 对数刻度（如 10^-2 = 1%）。"
)
CHART_AXIS_HINT_R2L = (
    "【BER 柱·纵轴】误码 bit 累计数；蓝=理论仿真误码，橙=实测 ber 表误码；"
    "横轴刻度下为基数=ok 总 bit（图表裁剪后）。"
)
CHART_AXIS_HINT_R2R = (
    "【迭代柱·纵轴】迭代次数累计；蓝=理论仿真 IterNum 累加，橙=实测芯片 IterNum 累加；"
    "横轴刻度下为基数=ok 帧数（图表裁剪后）。"
)
CHART_AXIS_HINT_REFRESH = (
    f"测试时柱图+折线合并刷新（约每 {BATCH_BAR_MIN_MS}ms 取最新累加值），"
    "全量标注/标准差批量结束后重算。"
)

# 兼容旧用法 / 文档引用
CHART_AXIS_HINT = (
    f"{CHART_AXIS_HINT_R1L}\n{CHART_AXIS_HINT_R1R}\n"
    f"{CHART_AXIS_HINT_R2L}\n{CHART_AXIS_HINT_R2R}\n"
    f"{CHART_AXIS_HINT_REFRESH}"
)

BER_LINE_YSCALE = "log"
BER_LINE_EMPTY_YLIM = (1e-6, 1.0)
BER_LINE_EMPTY_XTICKS = tuple(range(7))
ITER_LINE_EMPTY_YLIM = (0.0, 6.0)
ITER_LINE_EMPTY_XTICKS = tuple(range(7))

# 折线图图例
MEASURED_BER_LABEL_MODE2 = "实测误码率 (ber误码bit ÷ 图表分母bit)"
MEASURED_BER_LABEL_DEFAULT = "实测误码率 (ok 口径，末次收敛 Attempt)"
THEORETICAL_BER_LABEL = "理论误码率 (ok 仿真行: Sim Out 硬判 vs CodeBit)"
MEASURED_ITER_LABEL = "芯片平均迭代（ok 口径）"
THEORETICAL_ITER_LABEL = "理论迭代次数（ok 仿真 IterNum）"

BER_TITLE_MODE2 = "Mode2 CodeBit BER vs SNR (芯片实测 + 理论)"
ITER_TITLE = "迭代次数 vs SNR (芯片实测 + 理论)"
