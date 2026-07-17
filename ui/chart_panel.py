"""批量测试可视化分析 — BER/迭代折线图、分子分母柱状图与 ok 实测协议样例。"""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("QtAgg")

from analysis.aggregate import AttemptRecord, CaseRecord, SnrPoint, ok_frame_attempts
from analysis.sign_compare import compare_channels_for_mode
from ui.theme import (
    COLOR_BG_PANEL,
    COLOR_BG_TABLE,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)

from ui.chart_axis_spec import (
    BER_BAR_LABEL_MEAS,
    BER_BAR_LABEL_THEORY,
    BER_BAR_BASE_FOOTNOTE,
    BER_BAR_SUBTITLE,
    BER_BAR_TITLE,
    BER_BAR_YLABEL,
    BER_LINE_EMPTY_XTICKS,
    BER_LINE_EMPTY_YLIM,
    BER_LINE_YLABEL,
    BER_TITLE_MODE2,
    CHART_AXIS_HINT_R1L,
    CHART_AXIS_HINT_R1R,
    CHART_AXIS_HINT_R2L,
    CHART_AXIS_HINT_R2R,
    CHART_AXIS_HINT_REFRESH,
    EBNO_XLABEL_RIGHT,
    EBNO_XLABEL_TICK,
    ITER_BAR_LABEL_MEAS,
    ITER_BAR_LABEL_THEORY,
    ITER_BAR_BASE_FOOTNOTE,
    ITER_BAR_SUBTITLE,
    ITER_BAR_TITLE,
    ITER_BAR_YLABEL,
    ITER_LINE_EMPTY_XTICKS,
    ITER_LINE_EMPTY_YLIM,
    ITER_LINE_YLABEL,
    ITER_TITLE,
    MEASURED_BER_LABEL_DEFAULT,
    MEASURED_BER_LABEL_MODE2,
    MEASURED_ITER_LABEL,
    THEORETICAL_BER_LABEL,
    THEORETICAL_ITER_LABEL,
)
_CHART_FIGSIZE = (5, 11.0)
_CHART_CANVAS_MIN_HEIGHT = 640
_LINE_BAR_HEIGHT_RATIOS = (1.9, 1.95)
_LINE_BAR_HSPACE = 0.14

# 顶天立地：副图区尽量铺满，底部窄条放柱图脚注
_CHART_FOOTNOTE_BAND = 0.048
_CHART_TOP_MARGIN = 0.992
_FIG_FOOTNOTE_Y = 0.006
_FIG_FOOTNOTE_GID = "fig_axis_footnote"
_CHART_LINE_TITLE_PAD = 5
_CHART_BAR_TITLE_PAD = 4
_CHART_BAR_XTICK_PAD = 2


def configure_matplotlib() -> None:
    """Apply matplotlib rcParams once — ASCII minus on axes, dark theme colors."""
    from ui.perf_settings import CHART_DPI

    matplotlib.rcParams.update(
        {
            "font.sans-serif": ["SimHei", "Microsoft YaHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "figure.dpi": CHART_DPI,
            "figure.facecolor": COLOR_BG_PANEL,
            "axes.facecolor": COLOR_BG_TABLE,
            "axes.edgecolor": "#888888",
            "axes.labelcolor": COLOR_TEXT_PRIMARY,
            "text.color": COLOR_TEXT_PRIMARY,
            "xtick.color": COLOR_TEXT_PRIMARY,
            "ytick.color": COLOR_TEXT_PRIMARY,
            "grid.color": "#555555",
            "axes.formatter.use_mathtext": True,
            "mathtext.fontset": "dejavusans",
        }
    )


configure_matplotlib()

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.audit_schema import AUDIT_SCHEMA_VERSION
from ui.chart_settings import (
    MAX_FRAMES_PER_SNR,
    MIN_FRAMES_PER_SNR,
    ber_bar_base_footnote,
    get_auto_advance_snr,
    get_frames_per_snr,
    iter_bar_base_footnote,
)


def _clear_figure_footnotes(fig: Figure) -> None:
    for txt in list(fig.texts):
        if txt.get_gid() == _FIG_FOOTNOTE_GID:
            txt.remove()


def _apply_bar_footnotes(ax, *, base_footnote: str = "") -> None:
    """柱图脚注贴 figure 底边，不占 axes 下方空白。"""
    fig = ax.figure
    ax.set_xlabel("")
    _clear_figure_footnotes(fig)
    foot_kw = dict(
        transform=fig.transFigure,
        fontsize=7,
        color=COLOR_TEXT_SECONDARY,
        gid=_FIG_FOOTNOTE_GID,
        va="bottom",
        clip_on=False,
    )
    fig.text(0.07, _FIG_FOOTNOTE_Y, EBNO_XLABEL_TICK, ha="left", **foot_kw)
    if base_footnote:
        fig.text(0.50, _FIG_FOOTNOTE_Y, base_footnote, ha="center", **foot_kw)
    fig.text(0.995, _FIG_FOOTNOTE_Y, EBNO_XLABEL_RIGHT, ha="right", **foot_kw)


def _apply_ebno_xlabel(ax, *, extra_footnote: str = "", tick_note: bool = True) -> None:
    """折线图横轴：右端单位，尽量贴底。"""
    ax.set_xlabel(EBNO_XLABEL_RIGHT, loc="right", fontsize=8, labelpad=1)
    if tick_note:
        ax.text(
            0.0,
            -0.22,
            EBNO_XLABEL_TICK,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=7,
            color=COLOR_TEXT_SECONDARY,
        )
    if extra_footnote:
        ax.text(
            0.5,
            -0.42,
            extra_footnote,
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=7,
            color=COLOR_TEXT_SECONDARY,
        )


def _snr_xtick_labels(snrs: list[float], base_values: list[int] | None) -> list[str]:
    del base_values  # 基数口径见柱图底部脚注同一行
    return [f"{s:g}" for s in snrs]


def _apply_snr_xticks(ax, snr_ticks: tuple[int, ...]) -> None:
    ax.set_xticks(list(snr_ticks))
    ax.set_xticklabels([str(t) for t in snr_ticks])
    ax.set_xlim(snr_ticks[0] - 0.5, snr_ticks[-1] + 0.5)


def _setup_ber_line_axes(ax, *, empty: bool) -> None:
    if empty:
        ax.set_ylim(*BER_LINE_EMPTY_YLIM)
        _configure_ber_log_axis(ax, ymin=BER_LINE_EMPTY_YLIM[0], ymax=BER_LINE_EMPTY_YLIM[1])
    else:
        _configure_ber_log_axis(ax)
    ax.set_ylabel(BER_LINE_YLABEL)
    _apply_ebno_xlabel(ax, tick_note=False)
    ax.grid(True, linestyle="--", alpha=0.6)
    if empty:
        _apply_snr_xticks(ax, BER_LINE_EMPTY_XTICKS)


def _setup_iter_line_axes(ax, *, empty: bool) -> None:
    ax.set_ylabel(ITER_LINE_YLABEL)
    _apply_ebno_xlabel(ax, tick_note=False)
    ax.grid(True, linestyle="--", alpha=0.6)
    if empty:
        ax.set_ylim(*ITER_LINE_EMPTY_YLIM)
        _apply_snr_xticks(ax, ITER_LINE_EMPTY_XTICKS)


def _format_ber_power10(raw: float) -> str:
    """Format BER as powers of 10 (mathtext) for chart annotations."""
    if not math.isfinite(raw) or raw <= 0:
        return r"$<10^{-4}$"
    if raw < 1e-4:
        return r"$<10^{-4}$"
    exp = int(math.floor(math.log10(raw)))
    coeff = raw / (10.0 ** exp)
    if abs(coeff - 1.0) < 0.12:
        return rf"$10^{{{exp}}}$"
    return rf"${coeff:.1f}\times10^{{{exp}}}$"


def _power10_tick_label(exp: int) -> str:
    """纵轴刻度：mathtext 渲染 10^n，避免 Unicode 上标在 SimHei 下乱码。"""
    return rf"$10^{{{exp}}}$"


def _ber_log_ticks(ymin: float, ymax: float) -> tuple[list[float], list[str]]:
    ticks: list[float] = []
    labels: list[str] = []
    for exp in range(-6, 1):
        value = 10.0 ** exp
        if value >= ymin * 0.65 and value <= ymax * 1.6:
            ticks.append(value)
            labels.append(_power10_tick_label(exp))
    if not ticks:
        ticks = [ymin, ymax]
        labels = [_format_ber_power10(ymin).strip("$"), _format_ber_power10(ymax).strip("$")]
    return ticks, labels


def _configure_ber_log_axis(ax, *, ymin: float | None = None, ymax: float | None = None) -> None:
    ax.set_yscale("log")
    if ymin is not None and ymax is not None and ymin < ymax:
        ticks, labels = _ber_log_ticks(ymin, ymax)
        ax.set_yticks(ticks)
        ax.set_yticklabels(labels, fontsize=8)
    else:
        ticks, labels = _ber_log_ticks(*BER_LINE_EMPTY_YLIM)
        ax.set_yticks(ticks)
        ax.set_yticklabels(labels, fontsize=8)
    ax.yaxis.set_minor_formatter(FuncFormatter(lambda _v, _p: ""))


def _apply_line_snr_xticks(ax, snrs: list[float]) -> None:
    """折线图横轴：刻度为实测 Eb/N0 (dB) 整数值。"""
    if not snrs:
        return
    unique = sorted({float(s) for s in snrs})
    ax.set_xticks(unique)
    ax.set_xticklabels([f"{s:g}" for s in unique])
    pad = 0.4 if len(unique) == 1 else 0.5
    ax.set_xlim(unique[0] - pad, unique[-1] + pad)

def _annotate_series_points(
    ax,
    xs: list[float],
    ys: list[float],
    labels: list[str],
    *,
    color: str,
    y_offset: int,
    fontsize: int = 7,
) -> None:
    """Label every SNR point; vertical offset separates series, x stagger reduces overlap."""
    if not xs:
        return
    if len(xs) > 20:
        return
    bbox_kw = dict(
        boxstyle="round,pad=0.15",
        facecolor=COLOR_BG_TABLE,
        edgecolor="none",
        alpha=0.6,
    )
    va = "bottom" if y_offset > 0 else "top"
    for i, (x, y, label) in enumerate(zip(xs, ys, labels)):
        x_off = 10 if i % 2 == 0 else -10
        ax.annotate(
            label,
            (x, y),
            textcoords="offset points",
            xytext=(x_off, y_offset),
            fontsize=fontsize,
            ha="center",
            va=va,
            color=color,
            clip_on=False,
            bbox=bbox_kw,
        )
        ax.texts[-1].set_gid("line_val")


def _annotate_compared_series_points(
    ax,
    snrs: list[float],
    ys_a: list[float],
    labels_a: list[str],
    color_a: str,
    ys_b: dict[float, float],
    labels_b: dict[float, str],
    color_b: str,
    *,
    offset: int = 10,
    fontsize: int = 7,
) -> None:
    """同 SNR 双序列标注：数值较大者标签在上方，较小者在下方。"""
    if not snrs or len(snrs) > 20:
        return
    bbox_kw = dict(
        boxstyle="round,pad=0.15",
        facecolor=COLOR_BG_TABLE,
        edgecolor="none",
        alpha=0.6,
    )
    for i, (snr, ya, la) in enumerate(zip(snrs, ys_a, labels_a)):
        x_off = 10 if i % 2 == 0 else -10
        yb = ys_b.get(snr)
        lb = labels_b.get(snr)
        if yb is not None and lb is not None and math.isfinite(yb):
            if ya >= yb:
                off_a, off_b = offset, -offset
            else:
                off_a, off_b = -offset, offset
            for y, label, color, off in (
                (ya, la, color_a, off_a),
                (yb, lb, color_b, off_b),
            ):
                va = "bottom" if off > 0 else "top"
                ax.annotate(
                    label,
                    (snr, y),
                    textcoords="offset points",
                    xytext=(x_off, off),
                    fontsize=fontsize,
                    ha="center",
                    va=va,
                    color=color,
                    clip_on=False,
                    bbox=bbox_kw,
                )
                ax.texts[-1].set_gid("line_val")
        else:
            ax.annotate(
                la,
                (snr, ya),
                textcoords="offset points",
                xytext=(x_off, offset),
                fontsize=fontsize,
                ha="center",
                va="bottom",
                color=color_a,
                clip_on=False,
                bbox=bbox_kw,
            )
            ax.texts[-1].set_gid("line_val")


def _format_int_bar(value: int) -> str:
    return str(int(value))


def _add_dual_bar_value_labels(
    ax,
    bars_a,
    bars_b,
    values_a: list[int],
    values_b: list[int],
) -> tuple[list, list]:
    """在每根柱顶标注累计数值；返回文本对象供 live 就地更新。"""
    peak = max(max(values_a, default=0), max(values_b, default=0), 1)
    pad = max(peak * 0.02, 0.4)
    texts_a: list = []
    texts_b: list = []
    for bar, val in zip(bars_a, values_a):
        y = max(float(val), 0.0)
        txt = ax.text(
            bar.get_x() + bar.get_width() / 2,
            y + (pad if y > 0 else 0.2),
            _format_int_bar(val),
            ha="center",
            va="bottom",
            fontsize=6,
            color="#5dade2",
            clip_on=False,
        )
        txt.set_gid("bar_val_a")
        texts_a.append(txt)
    for bar, val in zip(bars_b, values_b):
        y = max(float(val), 0.0)
        txt = ax.text(
            bar.get_x() + bar.get_width() / 2,
            y + (pad if y > 0 else 0.2),
            _format_int_bar(val),
            ha="center",
            va="bottom",
            fontsize=6,
            color="#f0b27a",
            clip_on=False,
        )
        txt.set_gid("bar_val_b")
        texts_b.append(txt)
    return texts_a, texts_b


def _patch_bar_value_labels(
    state: dict,
    values_a: list[int],
    values_b: list[int],
) -> None:
    peak = max(max(values_a, default=0), max(values_b, default=0), 1)
    pad = max(peak * 0.02, 0.4)
    for bar, val, txt in zip(
        state.get("bars_a", []),
        values_a,
        state.get("val_texts_a", []),
    ):
        y = max(float(val), 0.0)
        txt.set_position((bar.get_x() + bar.get_width() / 2, y + (pad if y > 0 else 0.2)))
        txt.set_text(_format_int_bar(val))
    for bar, val, txt in zip(
        state.get("bars_b", []),
        values_b,
        state.get("val_texts_b", []),
    ):
        y = max(float(val), 0.0)
        txt.set_position((bar.get_x() + bar.get_width() / 2, y + (pad if y > 0 else 0.2)))
        txt.set_text(_format_int_bar(val))


def _remove_gid_texts(ax, gid: str) -> None:
    for txt in list(ax.texts):
        if txt.get_gid() == gid:
            txt.remove()


def _fit_chart(fig: Figure) -> None:
    """顶天立地铺满 canvas；底部窄条留给 figure 脚注。"""
    fig.tight_layout(
        rect=[0.07, _CHART_FOOTNOTE_BAND, 0.995, _CHART_TOP_MARGIN],
        pad=0.06,
        h_pad=0.10,
    )
    fig.subplots_adjust(
        top=_CHART_TOP_MARGIN,
        bottom=_CHART_FOOTNOTE_BAND,
        hspace=_LINE_BAR_HSPACE,
    )


def _set_line_chart_title(ax, title: str) -> None:
    ax.set_title(title, pad=_CHART_LINE_TITLE_PAD, fontsize=9)


def _format_bar_chart_title(title: str, subtitle: str) -> str:
    """柱图标题与图例说明同一行，节省纵向空间。"""
    subtitle = subtitle.strip()
    if not subtitle:
        return title
    return f"{title}  ·  {subtitle}"


def _draw_dual_bar_chart(
    ax,
    snrs: list[float],
    values_a: list[int],
    values_b: list[int],
    *,
    label_a: str,
    label_b: str,
    title: str,
    subtitle: str,
    empty_hint: str,
    ylabel: str,
    empty_xticks: tuple[int, ...] = BER_LINE_EMPTY_XTICKS,
    base_values: list[int] | None = None,
    base_footnote: str = "",
) -> None:
    ax.clear()
    if not snrs:
        ax.set_title(
            _format_bar_chart_title(title, subtitle),
            fontsize=9,
            pad=_CHART_BAR_TITLE_PAD,
        )
        ax.set_ylabel(ylabel, fontsize=8)
        ax.text(
            0.5,
            0.5,
            empty_hint,
            ha="center",
            va="center",
            transform=ax.transAxes,
            color=COLOR_TEXT_SECONDARY,
            fontsize=9,
        )
        _apply_snr_xticks(ax, empty_xticks)
        _apply_bar_footnotes(ax, base_footnote=base_footnote)
        ax.grid(True, axis="y", linestyle="--", alpha=0.35)
        return

    x = list(range(len(snrs)))
    width = 0.36
    bars_a = ax.bar(
        [xi - width / 2 for xi in x],
        values_a,
        width=width,
        label=label_a,
        color="#3498db",
        alpha=0.88,
    )
    bars_b = ax.bar(
        [xi + width / 2 for xi in x],
        values_b,
        width=width,
        label=label_b,
        color="#e67e22",
        alpha=0.88,
    )
    val_texts_a, val_texts_b = _add_dual_bar_value_labels(
        ax, list(bars_a), list(bars_b), values_a, values_b
    )
    ax._bar_val_texts = (val_texts_a, val_texts_b)  # type: ignore[attr-defined]
    ax.set_xticks(x)
    ax.set_xticklabels(_snr_xtick_labels(snrs, base_values), fontsize=7)
    ax.set_title(
        _format_bar_chart_title(title, subtitle),
        fontsize=9,
        pad=_CHART_BAR_TITLE_PAD,
    )
    ax.set_ylabel(ylabel, fontsize=8)
    ax.tick_params(axis="x", pad=_CHART_BAR_XTICK_PAD)
    ax.grid(True, axis="y", linestyle="--", alpha=0.4)
    _rescale_bar_axis(ax, values_a, values_b, with_value_labels=True)
    _apply_bar_footnotes(ax, base_footnote=base_footnote)


def _rescale_bar_axis(
    ax,
    values_a: list[int],
    values_b: list[int],
    *,
    with_value_labels: bool = True,
) -> None:
    peak = max(max(values_a, default=0), max(values_b, default=0), 1)
    headroom = 1.14 if with_value_labels else 1.08
    ax.set_ylim(0, peak * headroom)


def _patch_dual_bars(
    ax,
    state: dict | None,
    snrs: list[float],
    values_a: list[int],
    values_b: list[int],
    base_values: list[int] | None,
) -> tuple[dict, bool]:
    """就地更新柱高；SNR 结构不变时避免 ax.clear。返回 (state, structure_changed)。"""
    snr_key = tuple(snrs)
    if (
        state
        and state.get("snr_key") == snr_key
        and state.get("bars_a")
        and state.get("bars_b")
    ):
        for bar, height in zip(state["bars_a"], values_a):
            bar.set_height(height)
            bar.set_y(0)
        for bar, height in zip(state["bars_b"], values_b):
            bar.set_height(height)
            bar.set_y(0)
        if base_values is not None:
            labels = _snr_xtick_labels(snrs, base_values)
            sig = tuple(labels)
            if state.get("xtick_sig") != sig:
                ax.set_xticklabels(labels, fontsize=7)
                state["xtick_sig"] = sig
        if state.get("val_texts_a") and state.get("val_texts_b"):
            _patch_bar_value_labels(state, values_a, values_b)
        _rescale_bar_axis(ax, values_a, values_b, with_value_labels=True)
        return state, False
    return state or {}, True


def _capture_dual_bar_state(
    ax,
    snrs: list[float],
) -> dict:
    containers = list(ax.containers)
    bars_a = list(containers[-2]) if len(containers) >= 2 else []
    bars_b = list(containers[-1]) if len(containers) >= 1 else []
    val_texts = getattr(ax, "_bar_val_texts", None)
    if val_texts:
        val_texts_a, val_texts_b = val_texts
    else:
        val_texts_a = [t for t in ax.texts if t.get_gid() == "bar_val_a"]
        val_texts_b = [t for t in ax.texts if t.get_gid() == "bar_val_b"]
    return {
        "snr_key": tuple(snrs),
        "bars_a": bars_a,
        "bars_b": bars_b,
        "val_texts_a": val_texts_a,
        "val_texts_b": val_texts_b,
    }


class ChartPanel(QWidget):
    """BER-SNR / 迭代次数-SNR 折线图、分子分母柱状图与 ok 实测协议样例。"""

    audit_schema_version = AUDIT_SCHEMA_VERSION
    frames_per_snr_changed = pyqtSignal(int)
    auto_advance_snr_changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._cases: list[CaseRecord] = []
        self._ok_sample_pairs: list[tuple[CaseRecord, AttemptRecord]] = []
        self._live_snr_key: tuple[float, ...] | None = None
        self._ber_bar_state: dict | None = None
        self._iter_bar_state: dict | None = None
        self._live_line_artists: dict | None = None
        self._live_ber_line_annots: list = []
        self._live_iter_line_annots: list = []
        self._ber_bar_footnote = ber_bar_base_footnote()
        self._iter_bar_footnote = iter_bar_base_footnote()
        self._build_ui()

    def _build_ui(self) -> None:
        from ui.perf_settings import CHART_DPI

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        btn_row = QHBoxLayout()
        self.btn_mode2_compute_ber = QPushButton("计算 BER / 刷新图表 (Mode2)")
        self.btn_mode2_compute_ber.setToolTip(
            "Mode2：实测 BER = Out[3,5,6,7] 硬判 CodeBit(实测 vs Sim)；"
            "理论 BER = Sim Out 硬判 vs 指定 CodeBit"
        )
        self.btn_refresh = QPushButton("刷新图表")
        self.btn_export = QPushButton("导出图表")
        btn_row.addWidget(self.btn_mode2_compute_ber)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addWidget(self.btn_export)
        btn_row.addSpacing(12)
        btn_row.addWidget(QLabel("BER基数/ SNR:"))
        self._frames_per_snr_spin = QSpinBox()
        self._frames_per_snr_spin.setRange(MIN_FRAMES_PER_SNR, MAX_FRAMES_PER_SNR)
        self._frames_per_snr_spin.setValue(get_frames_per_snr())
        self._frames_per_snr_spin.valueChanged.connect(self.frames_per_snr_changed.emit)
        btn_row.addWidget(self._frames_per_snr_spin)
        self._chk_auto_advance_snr = QCheckBox("达基数自动下一 SNR")
        self._chk_auto_advance_snr.setChecked(get_auto_advance_snr())
        self._chk_auto_advance_snr.toggled.connect(self.auto_advance_snr_changed.emit)
        btn_row.addWidget(self._chk_auto_advance_snr)
        btn_row.addStretch()
        self._set_mode2_workflow_visible(False)
        layout.addLayout(btn_row)

        self.lbl_chart_hint = self._build_chart_hint_block()
        layout.addWidget(self.lbl_chart_hint)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(8)
        ber_group = QGroupBox("BER（上：误码率折线  下：误码 bit 柱）")
        ber_layout = QVBoxLayout(ber_group)
        ber_layout.setContentsMargins(2, 2, 2, 0)
        ber_layout.setSpacing(0)
        self.fig_ber = Figure(figsize=_CHART_FIGSIZE, dpi=CHART_DPI)
        gs_ber = self.fig_ber.add_gridspec(
            2, 1,
            height_ratios=list(_LINE_BAR_HEIGHT_RATIOS),
            hspace=_LINE_BAR_HSPACE,
        )
        self.ax_ber = self.fig_ber.add_subplot(gs_ber[0])
        self.ax_ber_bar = self.fig_ber.add_subplot(gs_ber[1])
        self.canvas_ber = FigureCanvas(self.fig_ber)
        self.canvas_ber.setMinimumHeight(_CHART_CANVAS_MIN_HEIGHT)
        self.canvas_ber.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        ber_layout.addWidget(self.canvas_ber)
        charts_row.addWidget(ber_group)

        iter_group = QGroupBox("迭代（上：均值折线  下：累加/帧数柱）")
        iter_layout = QVBoxLayout(iter_group)
        iter_layout.setContentsMargins(2, 2, 2, 0)
        iter_layout.setSpacing(0)
        self.fig_iter = Figure(figsize=_CHART_FIGSIZE, dpi=CHART_DPI)
        gs_iter = self.fig_iter.add_gridspec(
            2, 1,
            height_ratios=list(_LINE_BAR_HEIGHT_RATIOS),
            hspace=_LINE_BAR_HSPACE,
        )
        self.ax_iter = self.fig_iter.add_subplot(gs_iter[0])
        self.ax_iter_bar = self.fig_iter.add_subplot(gs_iter[1])
        self.canvas_iter = FigureCanvas(self.fig_iter)
        self.canvas_iter.setMinimumHeight(_CHART_CANVAS_MIN_HEIGHT)
        self.canvas_iter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        iter_layout.addWidget(self.canvas_iter)
        charts_row.addWidget(iter_group)
        layout.addLayout(charts_row, stretch=1)

        hex_group = QGroupBox("批量测试 · 发送 / 接收（ok 实测样例，AA 协议解析）")
        hex_layout = QVBoxLayout(hex_group)
        hex_layout.setSpacing(4)
        hex_layout.setContentsMargins(6, 6, 6, 4)
        sample_row = QHBoxLayout()
        sample_row.addWidget(QLabel("ok 实测帧："))
        self.ok_sample_combo = QComboBox()
        self.ok_sample_combo.setMinimumWidth(220)
        self.ok_sample_combo.currentIndexChanged.connect(self._on_ok_sample_changed)
        sample_row.addWidget(self.ok_sample_combo, stretch=1)
        hex_layout.addLayout(sample_row)

        hex_row = QHBoxLayout()
        hex_row.setSpacing(8)
        tx_box = QGroupBox("发送")
        tx_lay = QVBoxLayout(tx_box)
        tx_lay.setSpacing(2)
        tx_lay.setContentsMargins(4, 4, 4, 4)
        self.tx_hex_line = QLineEdit()
        self.tx_hex_line.setReadOnly(True)
        self.tx_hex_line.setPlaceholderText("TX hex…")
        tx_lay.addWidget(self.tx_hex_line)
        self.decode_tx_sample = QTextEdit()
        self.decode_tx_sample.setReadOnly(True)
        self.decode_tx_sample.setMaximumHeight(56)
        self.decode_tx_sample.setPlaceholderText("AA 协议字段…")
        tx_lay.addWidget(self.decode_tx_sample)
        hex_row.addWidget(tx_box, stretch=1)

        rx_box = QGroupBox("接收")
        rx_lay = QVBoxLayout(rx_box)
        rx_lay.setSpacing(2)
        rx_lay.setContentsMargins(4, 4, 4, 4)
        self.rx_hex_line = QLineEdit()
        self.rx_hex_line.setReadOnly(True)
        self.rx_hex_line.setPlaceholderText("RX hex…")
        rx_lay.addWidget(self.rx_hex_line)
        self.decode_rx_sample = QTextEdit()
        self.decode_rx_sample.setReadOnly(True)
        self.decode_rx_sample.setMaximumHeight(56)
        self.decode_rx_sample.setPlaceholderText("AA 协议字段…")
        rx_lay.addWidget(self.decode_rx_sample)
        hex_row.addWidget(rx_box, stretch=1)
        hex_layout.addLayout(hex_row)
        layout.addWidget(hex_group, stretch=0)

    def _build_chart_hint_block(self) -> QWidget:
        """两行说明：每行左右两列，第二行右侧含刷新/实时状态。"""
        hint_style = (
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; padding: 0 2px;"
        )
        block = QWidget()
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(2)

        def _hint_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(hint_style)
            lbl.setAlignment(
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
            )
            return lbl

        row1 = QHBoxLayout()
        row1.setSpacing(24)
        row1.addWidget(_hint_label(CHART_AXIS_HINT_R1L), stretch=1)
        row1.addWidget(_hint_label(CHART_AXIS_HINT_R1R), stretch=1)
        block_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(24)
        row2.addWidget(_hint_label(CHART_AXIS_HINT_R2L), stretch=1)
        self.lbl_chart_hint_live = _hint_label(self._format_chart_hint_live(""))
        row2.addWidget(self.lbl_chart_hint_live, stretch=1)
        block_layout.addLayout(row2)
        return block

    @staticmethod
    def _format_chart_hint_live(extra: str) -> str:
        base = f"{CHART_AXIS_HINT_R2R} · {CHART_AXIS_HINT_REFRESH}"
        return f"{base}  |  {extra}" if extra else base

        self._clear_ok_sample()
        self.update_charts([], matrix_mode=1)

    def _set_mode2_workflow_visible(self, visible: bool) -> None:
        self.btn_mode2_compute_ber.setVisible(visible)
        self.btn_refresh.setVisible(not visible)

    def set_mode2_workflow(self, enabled: bool) -> None:
        self._set_mode2_workflow_visible(enabled)

    def set_cases(self, cases: list[CaseRecord], *, refresh_table: bool = True) -> None:
        del refresh_table
        self._cases = [c for c in cases if c.tx_hex or c.actual_currents]

    def update_ok_hex_sample(self, cases: list[CaseRecord]) -> None:
        """从 ok 口径实测帧中选一条，按 AA 协议解析 TX/RX。"""
        self._ok_sample_pairs = ok_frame_attempts(cases)
        self.ok_sample_combo.blockSignals(True)
        self.ok_sample_combo.clear()
        for tc, ar in self._ok_sample_pairs:
            snr = "—" if tc.snr_db is None else f"{tc.snr_db:g}"
            fi = "—" if tc.frame_idx is None else str(tc.frame_idx)
            self.ok_sample_combo.addItem(
                f"EbNo={snr}  FrameIdx={fi}  Attempt={ar.attempt}"
            )
        self.ok_sample_combo.blockSignals(False)
        if self._ok_sample_pairs:
            self.ok_sample_combo.setCurrentIndex(0)
            self._show_ok_sample(0)
        else:
            self._clear_ok_sample()

    def _on_ok_sample_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._ok_sample_pairs):
            self._clear_ok_sample()
            return
        self._show_ok_sample(index)

    def _clear_ok_sample(self) -> None:
        self.tx_hex_line.clear()
        self.rx_hex_line.clear()
        self.decode_tx_sample.clear()
        self.decode_rx_sample.clear()

    def _show_ok_sample(self, index: int) -> None:
        from protocol.codec import (
            RX_FRAME_LEN,
            TX_FRAME_LEN,
            build_tx_frame,
            format_hex,
            format_rx_decode,
            format_tx_decode,
            resolve_tx_matrix_mode,
        )

        tc, ar = self._ok_sample_pairs[index]
        tx_hex = (tc.tx_hex or "").strip()
        if not tx_hex and tc.channels:
            mode = resolve_tx_matrix_mode(tc.mode, tc.mode)
            tx_hex = format_hex(build_tx_frame(tc.channels, mode))
        rx_hex = (ar.rx_hex or tc.rx_hex or "").strip()

        if tx_hex:
            self.tx_hex_line.setText(tx_hex)
            try:
                tx_bytes = bytes.fromhex(tx_hex.replace(" ", ""))
                if len(tx_bytes) == TX_FRAME_LEN:
                    self.decode_tx_sample.setPlainText(format_tx_decode(tx_bytes))
                else:
                    self.decode_tx_sample.setPlainText(
                        f"TX 长度异常: {len(tx_bytes)}B（期望 {TX_FRAME_LEN}B）"
                    )
            except ValueError as exc:
                self.decode_tx_sample.setPlainText(f"TX 解析失败: {exc}")
        else:
            self.tx_hex_line.clear()
            self.decode_tx_sample.setPlainText("（无发送 hex）")

        if rx_hex:
            self.rx_hex_line.setText(rx_hex)
            try:
                rx_bytes = bytes.fromhex(rx_hex.replace(" ", ""))
                if len(rx_bytes) == RX_FRAME_LEN:
                    self.decode_rx_sample.setPlainText(format_rx_decode(rx_bytes))
                else:
                    self.decode_rx_sample.setPlainText(
                        f"RX 长度异常: {len(rx_bytes)}B（期望 {RX_FRAME_LEN}B）"
                    )
            except ValueError as exc:
                self.decode_rx_sample.setPlainText(f"RX 解析失败: {exc}")
        else:
            self.rx_hex_line.clear()
            self.decode_rx_sample.setPlainText("（无接收 hex）")

    def _reset_live_chart_state(self) -> None:
        self._live_snr_key = None
        self._ber_bar_state = None
        self._iter_bar_state = None
        self._live_line_artists = None
        self._live_ber_line_annots = []
        self._live_iter_line_annots = []
        self._live_ber_ylim: tuple[float, float] | None = None
        self._live_iter_ylim: float | None = None

    def _clear_line_point_annots(self, ax, store: list) -> None:
        for artist in store:
            try:
                artist.remove()
            except Exception:
                pass
        store.clear()
        _remove_gid_texts(ax, "line_val")

    def _refresh_live_ber_line_annots(
        self,
        snrs: list[float],
        meas_bers: list[float],
        ref_bers: list[float],
    ) -> None:
        self._clear_line_point_annots(self.ax_ber, self._live_ber_line_annots)
        if not snrs:
            return
        meas_labels = [_format_ber_power10(y) for y in meas_bers]
        ref_by_snr = {float(s): float(y) for s, y in zip(snrs, ref_bers)}
        ref_lbl_by_snr = {
            float(s): _format_ber_power10(y) for s, y in zip(snrs, ref_bers)
        }
        _annotate_compared_series_points(
            self.ax_ber,
            snrs,
            meas_bers,
            meas_labels,
            "#e67e22",
            ref_by_snr,
            ref_lbl_by_snr,
            "#2980b9",
        )
        self._live_ber_line_annots = [
            t for t in self.ax_ber.texts if t.get_gid() == "line_val"
        ]

    def _refresh_live_iter_line_annots(
        self,
        snrs: list[float],
        meas_iters: list[float],
        ref_iters: list[float],
    ) -> None:
        self._clear_line_point_annots(self.ax_iter, self._live_iter_line_annots)
        if not snrs:
            return
        meas_labels = [f"{y:.2f}" for y in meas_iters]
        ref_by_snr = {float(s): float(y) for s, y in zip(snrs, ref_iters)}
        ref_lbl_by_snr = {float(s): f"{y:.2f}" for s, y in zip(snrs, ref_iters)}
        _annotate_compared_series_points(
            self.ax_iter,
            snrs,
            meas_iters,
            meas_labels,
            "#e67e22",
            ref_by_snr,
            ref_lbl_by_snr,
            "#2980b9",
        )
        self._live_iter_line_annots = [
            t for t in self.ax_iter.texts if t.get_gid() == "line_val"
        ]

    def _refresh_dual_bars_live(
        self,
        ax,
        state_attr: str,
        plotted,
        *,
        values_a: list[int],
        values_b: list[int],
        base_values: list[int] | None,
        label_a: str,
        label_b: str,
        title: str,
        subtitle: str,
        ylabel: str,
        empty_hint: str,
        base_footnote: str = "",
    ) -> bool:
        """刷新单根柱图；返回 True 表示 SNR 结构变化（需要 tight_layout）。"""
        snrs = [p.snr_db for p in plotted]
        state = getattr(self, state_attr)
        if not snrs:
            setattr(self, state_attr, None)
            _draw_dual_bar_chart(
                ax,
                [],
                [],
                [],
                label_a=label_a,
                label_b=label_b,
                title=title,
                subtitle=subtitle,
                empty_hint=empty_hint,
                ylabel=ylabel,
                base_footnote=base_footnote,
            )
            return True

        state, need_full = _patch_dual_bars(
            ax, state, snrs, values_a, values_b, base_values
        )
        if need_full:
            _draw_dual_bar_chart(
                ax,
                snrs,
                values_a,
                values_b,
                label_a=label_a,
                label_b=label_b,
                title=title,
                subtitle=subtitle,
                empty_hint=empty_hint,
                ylabel=ylabel,
                base_values=base_values,
                base_footnote=base_footnote,
            )
            state = _capture_dual_bar_state(ax, snrs)
        setattr(self, state_attr, state)
        return need_full

    def _update_ber_bars(self, plotted, *, matrix_mode: int, live: bool = False) -> bool:
        del matrix_mode
        theory_bits = [int(getattr(p, "reference_error_bits", 0)) for p in plotted]
        meas_bits = [int(getattr(p, "error_bits", 0)) for p in plotted]
        base_bits = [int(getattr(p, "channel_bits", 0)) for p in plotted]
        if live:
            return self._refresh_dual_bars_live(
                self.ax_ber_bar,
                "_ber_bar_state",
                plotted,
                values_a=theory_bits,
                values_b=meas_bits,
                base_values=base_bits if plotted else None,
                label_a=BER_BAR_LABEL_THEORY,
                label_b=BER_BAR_LABEL_MEAS,
                title=BER_BAR_TITLE,
                subtitle=BER_BAR_SUBTITLE,
                ylabel=BER_BAR_YLABEL,
                empty_hint="暂无 SNR 柱状数据",
                base_footnote=self._ber_bar_footnote,
            )
        _draw_dual_bar_chart(
            self.ax_ber_bar,
            [p.snr_db for p in plotted],
            theory_bits,
            meas_bits,
            label_a=BER_BAR_LABEL_THEORY,
            label_b=BER_BAR_LABEL_MEAS,
            title=BER_BAR_TITLE,
            subtitle=BER_BAR_SUBTITLE,
            ylabel=BER_BAR_YLABEL,
            empty_hint="暂无 SNR 柱状数据",
            base_values=base_bits if plotted else None,
            base_footnote=self._ber_bar_footnote,
        )
        return True

    def _update_iter_bars(self, plotted, *, live: bool = False) -> bool:
        theory_iters = [int(getattr(p, "ref_iter_sum", 0)) for p in plotted]
        meas_iters = [int(getattr(p, "meas_iter_sum", 0)) for p in plotted]
        base_frames = [int(getattr(p, "tested_count", 0)) for p in plotted]
        if live:
            return self._refresh_dual_bars_live(
                self.ax_iter_bar,
                "_iter_bar_state",
                plotted,
                values_a=theory_iters,
                values_b=meas_iters,
                base_values=base_frames if plotted else None,
                label_a=ITER_BAR_LABEL_THEORY,
                label_b=ITER_BAR_LABEL_MEAS,
                title=ITER_BAR_TITLE,
                subtitle=ITER_BAR_SUBTITLE,
                ylabel=ITER_BAR_YLABEL,
                empty_hint="暂无迭代柱状数据",
                base_footnote=self._iter_bar_footnote,
            )
        _draw_dual_bar_chart(
            self.ax_iter_bar,
            [p.snr_db for p in plotted],
            theory_iters,
            meas_iters,
            label_a=ITER_BAR_LABEL_THEORY,
            label_b=ITER_BAR_LABEL_MEAS,
            title=ITER_BAR_TITLE,
            subtitle=ITER_BAR_SUBTITLE,
            ylabel=ITER_BAR_YLABEL,
            empty_hint="暂无迭代柱状数据",
            base_values=base_frames if plotted else None,
            base_footnote=self._iter_bar_footnote,
        )
        return True

    def _update_live_lines(
        self, rows, *, matrix_mode: int, annotate: bool = True
    ) -> bool:
        """轻量折线增量：批量 live 也刷新点数值标注。"""
        if not rows:
            return False

        mode2 = int(matrix_mode) == 2
        snrs = [r.snr_db for r in rows]
        snr_key = tuple(snrs)
        meas_bers = [
            max(r.error_bits / r.channel_bits, 1e-6) if r.channel_bits else 1e-6
            for r in rows
        ]
        ref_bers = [
            max(r.reference_error_bits / r.channel_bits, 1e-6) if r.channel_bits else 1e-6
            for r in rows
        ]
        meas_iters = [
            r.meas_iter_sum / r.tested_count if r.tested_count else 0.0
            for r in rows
        ]
        ref_iters = [
            r.ref_iter_sum / r.tested_count if r.tested_count else 0.0
            for r in rows
        ]

        if snr_key == self._live_snr_key and self._live_line_artists:
            artists = self._live_line_artists
            artists["meas_ber"].set_data(snrs, meas_bers)
            artists["ref_ber"].set_data(snrs, ref_bers)
            artists["meas_iter"].set_data(snrs, meas_iters)
            artists["ref_iter"].set_data(snrs, ref_iters)
            ber_min = min(meas_bers + ref_bers)
            ber_max = max(meas_bers + ref_bers)
            ymin = max(ber_min * 0.8, 1e-6)
            ymax = min(ber_max * 1.2, 1.0)
            if ymin >= ymax:
                ymax = min(ymax * 10, 1.0)
            new_ber_ylim = (ymin, ymax)
            if new_ber_ylim != self._live_ber_ylim:
                self.ax_ber.set_ylim(ymin, ymax)
                _configure_ber_log_axis(self.ax_ber, ymin=ymin, ymax=ymax)
                self._live_ber_ylim = new_ber_ylim
            iter_max = max(max(meas_iters, default=0), max(ref_iters, default=0), 1.0)
            new_iter_top = iter_max * 1.22
            if self._live_iter_ylim != new_iter_top:
                self.ax_iter.set_ylim(0, new_iter_top)
                self._live_iter_ylim = new_iter_top
            if annotate:
                self._refresh_live_ber_line_annots(snrs, meas_bers, ref_bers)
                self._refresh_live_iter_line_annots(snrs, meas_iters, ref_iters)
            return False

        self.ax_ber.clear()
        self.ax_iter.clear()
        self.ax_ber.set_yscale("log")
        self.ax_ber.set_ylabel(BER_LINE_YLABEL)
        meas_label = (
            MEASURED_BER_LABEL_MODE2 if mode2 else MEASURED_BER_LABEL_DEFAULT
        )
        (meas_ber_line,) = self.ax_ber.plot(
            snrs,
            meas_bers,
            "s-",
            color="#e67e22",
            linewidth=2,
            markersize=6,
            label=meas_label,
        )
        (ref_ber_line,) = self.ax_ber.plot(
            snrs,
            ref_bers,
            "o--",
            color="#2980b9",
            linewidth=2,
            markersize=5,
            label=THEORETICAL_BER_LABEL,
        )
        ber_title = BER_TITLE_MODE2 if mode2 else "通道 BER vs SNR"
        _set_line_chart_title(self.ax_ber, ber_title)
        ber_min = min(meas_bers + ref_bers)
        ber_max = max(meas_bers + ref_bers)
        ymin = max(ber_min * 0.8, 1e-6)
        ymax = min(ber_max * 1.2, 1.0)
        if ymin >= ymax:
            ymax = min(ymax * 10, 1.0)
        self.ax_ber.set_ylim(ymin, ymax)
        _configure_ber_log_axis(self.ax_ber, ymin=ymin, ymax=ymax)
        _apply_line_snr_xticks(self.ax_ber, snrs)
        _apply_ebno_xlabel(self.ax_ber, tick_note=False)
        self.ax_ber.grid(True, linestyle="--", alpha=0.6)

        (meas_iter_line,) = self.ax_iter.plot(
            snrs,
            meas_iters,
            "o-",
            color="#e67e22",
            linewidth=2,
            markersize=6,
            label=MEASURED_ITER_LABEL,
        )
        (ref_iter_line,) = self.ax_iter.plot(
            snrs,
            ref_iters,
            "s--",
            color="#2980b9",
            linewidth=2,
            markersize=5,
            label=THEORETICAL_ITER_LABEL,
        )
        self.ax_iter.set_ylabel(ITER_LINE_YLABEL)
        _apply_line_snr_xticks(self.ax_iter, snrs)
        _apply_ebno_xlabel(self.ax_iter, tick_note=False)
        _set_line_chart_title(self.ax_iter, ITER_TITLE)
        self.ax_iter.grid(True, linestyle="--", alpha=0.6)
        iter_max = max(max(meas_iters, default=0), max(ref_iters, default=0), 1.0)
        self.ax_iter.set_ylim(0, iter_max * 1.22)

        self._live_ber_ylim = (ymin, ymax)
        self._live_iter_ylim = iter_max * 1.22
        self._live_snr_key = snr_key
        self._live_line_artists = {
            "meas_ber": meas_ber_line,
            "ref_ber": ref_ber_line,
            "meas_iter": meas_iter_line,
            "ref_iter": ref_iter_line,
        }
        if annotate:
            self._refresh_live_ber_line_annots(snrs, meas_bers, ref_bers)
            self._refresh_live_iter_line_annots(snrs, meas_iters, ref_iters)
        return True

    def set_frames_per_snr_value(self, value: int) -> None:
        self._frames_per_snr_spin.blockSignals(True)
        self._frames_per_snr_spin.setValue(int(value))
        self._frames_per_snr_spin.blockSignals(False)

    def set_auto_advance_snr_checked(self, checked: bool) -> None:
        self._chk_auto_advance_snr.blockSignals(True)
        self._chk_auto_advance_snr.setChecked(bool(checked))
        self._chk_auto_advance_snr.blockSignals(False)

    def set_ber_cap_controls_enabled(self, enabled: bool) -> None:
        self._frames_per_snr_spin.setEnabled(enabled)
        self._chk_auto_advance_snr.setEnabled(enabled)

    def set_frames_per_snr_footnotes(self, cap: int) -> None:
        self._ber_bar_footnote = ber_bar_base_footnote(cap)
        self._iter_bar_footnote = iter_bar_base_footnote(cap)

    def set_live_status(self, extra: str) -> None:
        """批量测试中柱状图实时状态（附在说明行末尾）。"""
        self.lbl_chart_hint_live.setText(self._format_chart_hint_live(extra))

    def update_bars_live(self, rows, *, matrix_mode: int) -> None:
        """批量测试中轻量刷新：柱图就地更新 + 折线 set_data（不走 ChartAggWorker）。"""
        layout_dirty = self._update_live_lines(
            rows, matrix_mode=matrix_mode, annotate=True
        )
        layout_dirty |= self._update_ber_bars(rows, matrix_mode=matrix_mode, live=True)
        layout_dirty |= self._update_iter_bars(rows, live=True)
        if layout_dirty:
            _fit_chart(self.fig_ber)
            _fit_chart(self.fig_iter)
        self.canvas_ber.draw_idle()
        self.canvas_iter.draw_idle()

    def update_charts(self, points: list[SnrPoint], *, matrix_mode: int = 1) -> None:
        self._reset_live_chart_state()
        self.ax_ber.clear()
        self.ax_iter.clear()
        compare_n = compare_channels_for_mode(matrix_mode)
        ch_label = f"CH1–{compare_n}"
        mode2 = int(matrix_mode) == 2

        if not points:
            hint = "请先「运行全部」完成批量测试，再点「刷新图表」"
            if mode2:
                self.ax_ber.set_title(
                    "Mode2 CodeBit BER vs SNR\n"
                    f"Out[3,5,6,7] 硬判：芯片实测 vs 理论\n（{hint}）"
                )
            else:
                self.ax_ber.set_title(f"通道 BER vs SNR\n（{hint}）")
            _setup_ber_line_axes(self.ax_ber, empty=True)
            self.ax_iter.set_title(f"{ITER_TITLE}\n（{hint}）")
            _setup_iter_line_axes(self.ax_iter, empty=True)
            self._update_ber_bars([], matrix_mode=matrix_mode)
            self._update_iter_bars([])
            _fit_chart(self.fig_ber)
            _fit_chart(self.fig_iter)
            self.canvas_ber.draw_idle()
            self.canvas_iter.draw_idle()
            return

        plotted = [
            p for p in points
            if p.tested_count > 0 and math.isfinite(p.channel_ber)
        ]
        if not plotted:
            if mode2:
                self.ax_ber.set_title(
                    "Mode2 CodeBit BER vs SNR\n"
                    "Out[3,5,6,7] 硬判：芯片实测 vs 理论（尚无已测 SNR 点）"
                )
            else:
                self.ax_ber.set_title("通道 BER vs SNR (尚无已测 SNR 点)")
            _setup_ber_line_axes(self.ax_ber, empty=True)
            self.ax_iter.set_title(f"{ITER_TITLE} (尚无已测 SNR 点)")
            _setup_iter_line_axes(self.ax_iter, empty=True)
            self._update_ber_bars([], matrix_mode=matrix_mode)
            self._update_iter_bars([])
            _fit_chart(self.fig_ber)
            _fit_chart(self.fig_iter)
            self.canvas_ber.draw_idle()
            self.canvas_iter.draw_idle()
            return

        snrs = [p.snr_db for p in plotted]
        meas_bers = [max(p.channel_ber, 1e-6) for p in plotted]
        ref_bers = [
            max(p.reference_ber, 1e-6)
            if p.reference_ber is not None and math.isfinite(p.reference_ber)
            else None
            for p in plotted
        ]
        avgs = [p.avg_iterations for p in plotted]
        stds = [p.std_iterations for p in plotted]

        self.ax_ber.set_yscale("log")
        self.ax_ber.set_ylabel(BER_LINE_YLABEL)
        meas_label = (
            MEASURED_BER_LABEL_MODE2 if mode2 else MEASURED_BER_LABEL_DEFAULT
        )
        self.ax_ber.plot(
            snrs, meas_bers, "s-",
            color="#e67e22", linewidth=2, markersize=6, label=meas_label,
        )
        has_ref = any(r is not None for r in ref_bers)
        if has_ref:
            ref_snrs = [s for s, r in zip(snrs, ref_bers) if r is not None]
            ref_vals = [r for r in ref_bers if r is not None]
            self.ax_ber.plot(
                ref_snrs, ref_vals, "o--",
                color="#2980b9", linewidth=2, markersize=5, label=THEORETICAL_BER_LABEL,
            )
        ber_title = BER_TITLE_MODE2 if mode2 else f"{ch_label} 符号 BER vs SNR"
        _set_line_chart_title(self.ax_ber, ber_title)
        all_bers = list(meas_bers)
        if has_ref:
            all_bers.extend(r for r in ref_bers if r is not None)
        ber_min = min(all_bers)
        ber_max = max(all_bers)
        ymin = max(ber_min * 0.8, 1e-6)
        ymax = min(ber_max * 1.2, 1.0)
        if ymin >= ymax:
            ymax = min(ymax * 10, 1.0)
        self.ax_ber.set_ylim(ymin, ymax)
        self.ax_ber.set_yscale("log")
        _configure_ber_log_axis(self.ax_ber, ymin=ymin, ymax=ymax)
        _apply_line_snr_xticks(self.ax_ber, snrs)
        _apply_ebno_xlabel(self.ax_ber, tick_note=False)
        self.ax_ber.grid(True, linestyle="--", alpha=0.6)
        meas_labels = [_format_ber_power10(raw) for raw in (p.channel_ber for p in plotted)]
        if has_ref:
            ref_by_snr = {
                snr: ber
                for snr, ber in zip(snrs, ref_bers)
                if ber is not None
            }
            ref_lbl_by_snr = {
                snr: _format_ber_power10(raw)
                for snr, raw in zip(snrs, (p.reference_ber for p in plotted))
                if raw is not None and math.isfinite(raw)
            }
            _annotate_compared_series_points(
                self.ax_ber,
                snrs,
                meas_bers,
                meas_labels,
                "#e67e22",
                ref_by_snr,
                ref_lbl_by_snr,
                "#2980b9",
            )
        else:
            _annotate_series_points(
                self.ax_ber, snrs, meas_bers, meas_labels,
                color="#e67e22", y_offset=10,
            )

        self.ax_iter.errorbar(
            snrs,
            avgs,
            yerr=stds,
            fmt="o-",
            color="#e67e22",
            linewidth=2,
            markersize=6,
            capsize=4,
            capthick=1.5,
            label=MEASURED_ITER_LABEL,
        )
        ref_pairs = [
            (p.snr_db, p.avg_ref_iterations, p.std_ref_iterations or 0.0)
            for p in plotted
            if p.avg_ref_iterations is not None and math.isfinite(p.avg_ref_iterations)
        ]
        if ref_pairs:
            ref_snrs, ref_avgs, ref_stds = zip(*ref_pairs)
            self.ax_iter.errorbar(
                list(ref_snrs),
                list(ref_avgs),
                yerr=list(ref_stds),
                fmt="s--",
                color="#2980b9",
                linewidth=2,
                markersize=5,
                capsize=3,
                capthick=1.2,
                label=THEORETICAL_ITER_LABEL,
            )
        self.ax_iter.set_ylabel(ITER_LINE_YLABEL)
        _apply_line_snr_xticks(self.ax_iter, snrs)
        _apply_ebno_xlabel(self.ax_iter, tick_note=False)
        _set_line_chart_title(self.ax_iter, ITER_TITLE)
        self.ax_iter.grid(True, linestyle="--", alpha=0.6)
        iter_max = max(max(avgs, default=0), 1.0)
        if ref_pairs:
            iter_max = max(iter_max, max(ref_avgs))
        self.ax_iter.set_ylim(0, iter_max * 1.22)
        iter_labels = [f"{avg:.2f}" for avg in avgs]
        if ref_pairs:
            ref_by_snr = {float(s): float(v) for s, v in zip(ref_snrs, ref_avgs)}
            ref_lbl_by_snr = {
                float(s): f"{v:.2f}" for s, v in zip(ref_snrs, ref_avgs)
            }
            _annotate_compared_series_points(
                self.ax_iter,
                snrs,
                avgs,
                iter_labels,
                "#e67e22",
                ref_by_snr,
                ref_lbl_by_snr,
                "#2980b9",
            )
        else:
            _annotate_series_points(
                self.ax_iter, snrs, avgs, iter_labels,
                color="#e67e22", y_offset=8,
            )

        self._update_ber_bars(plotted, matrix_mode=matrix_mode)
        self._update_iter_bars(plotted)

        _fit_chart(self.fig_ber)
        _fit_chart(self.fig_iter)
        self.canvas_ber.draw_idle()
        self.canvas_iter.draw_idle()

    def export_charts(self, path: str) -> None:
        self.fig_ber.savefig(f"{path}_ber.png", dpi=150, bbox_inches="tight")
        self.fig_iter.savefig(f"{path}_iter.png", dpi=150, bbox_inches="tight")
